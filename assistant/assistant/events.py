"""Event schema and JSONL writer for the observability middleware.

Design constraints (see `docs/plan/STEP2_PLAN.md` §5):

- D5: never write to stdout/stderr — only to `runs/<run_id>/events.jsonl`.
  Diagnostics go through the `logging` module only.
- D6: redact secrets and cap field size before anything is persisted.
- D7: one JSON object per line; reserved event types for later steps are
  declared here (as strings only) so `report.py` does not need to change
  when Step 3/4 start emitting them.

`EventWriter.record()` never touches the filesystem itself (D9): it only
enqueues, so it has nothing to raise. The background writer thread it starts
does the actual I/O and swallows its own failures (logged at debug level) —
see the `EventWriter` docstring for why the write path had to move off the
caller's thread.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import queue
import re
import secrets
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

# --- Event types (D7) --------------------------------------------------

RUN_START = "run_start"
MODEL_START = "model_start"
MODEL_END = "model_end"
MODEL_ERROR = "model_error"
TOOL_START = "tool_start"
TOOL_END = "tool_end"
RUN_END = "run_end"

# Reserved for Step 3 (plan gate) and Step 4 (memory / self-improvement).
# Declared now so `report.py` does not need to change when they start firing.
GATE_BLOCK = "gate_block"
MEMORY_HIT = "memory_hit"
IMPROVE_START = "improve_start"
IMPROVE_END = "improve_end"

# --- Redaction (D6) ------------------------------------------------------

_SENSITIVE_KEY_RE = re.compile(r"key|token(?!s)|secret|password", re.IGNORECASE)
"""`token(?!s)` excludes plural metric fields like `input_tokens`/`output_tokens`
(D7's own token-count requirement, §1 4-3) while still catching `token`,
`api_token`, `auth_token`, etc."""
_HASH_ONLY_KEYS = frozenset({"content", "command"})
_MAX_STR_LEN = 200


def _truncate_str(value: str) -> str:
    """Cap a string at `_MAX_STR_LEN` chars, noting how much was cut."""
    if len(value) <= _MAX_STR_LEN:
        return value
    cut = len(value) - _MAX_STR_LEN
    return f"{value[:_MAX_STR_LEN]}…(+{cut} chars)"


def _hash_summary(value: str) -> dict[str, Any]:
    """Replace a large field's text with its length and a short hash."""
    digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()
    return {"len": len(value), "sha256_8": digest[:8]}


def _redact_value(key: str | None, value: Any) -> Any:  # noqa: ANN401
    if key is not None and _SENSITIVE_KEY_RE.search(key):
        return "***"
    if key in _HASH_ONLY_KEYS and isinstance(value, str):
        return _hash_summary(value)
    if isinstance(value, str):
        return _truncate_str(value)
    if isinstance(value, dict):
        return {k: _redact_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(None, item) for item in value]
    return value


def redact(data: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive keys and cap oversized fields before persisting.

    Args:
        data: Arbitrary event payload (e.g. tool call args).

    Returns:
        A new dict safe to write to `events.jsonl`.
    """
    return {k: _redact_value(k, v) for k, v in data.items()}


# --- run_id (D1) ----------------------------------------------------------


def _new_run_id(thread_id: str | None) -> str:
    """Build a run id from the current time and thread id.

    Falls back to a random suffix when `thread_id` is unavailable, so a
    missing thread id never blocks logging (see STEP2_PLAN.md §7 risk table).
    """
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = (thread_id or "")[:8] or secrets.token_hex(4)
    return f"{stamp}-{suffix}"


def _now_iso() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


# --- Writer -----------------------------------------------------------


_WORKER_IDLE_TIMEOUT_SECONDS = 0.5
"""How long the writer thread waits for the next event before exiting.

Not a daemon thread: a headless one-shot run (`dcode -n`) was observed to
exit the whole process within microseconds of the last hook call, killing a
daemon thread before it ever got scheduled — `runs/` was never even created.
A plain (non-daemon) thread makes Python's interpreter-shutdown join() wait
for it, but only a *bounded* wait: without this idle timeout the thread would
block on `queue.get()` forever and hang every exit, since nothing signals
"no more events are coming" for a single-run writer. In measured practice
one `record()` call reaches disk in well under 50ms, so this bound is a
safety margin, not the expected case.
"""


class EventWriter:
    """Appends one JSON object per line to `runs/<run_id>/events.jsonl`.

    One instance corresponds to one run (one user turn). `record()` only
    enqueues (pure in-memory work, no I/O) — a dedicated background thread
    does the actual `mkdir`/write.

    D9 (`docs/plan/STEP2_PLAN.md` §5): dcode's server runs hooks on its
    asyncio event loop thread and raises if that thread makes a *synchronous*
    blocking call (`os.mkdir`, confirmed by a real headless run — see S11).
    Plain file `write()` is explicitly exempted by that same guard, but
    `mkdir()` is not, so directory creation cannot happen on the calling
    thread. Moving all I/O to one dedicated thread sidesteps this
    entirely and, as a side effect, removing the earlier per-call lock:
    a single consumer thread already serializes writes.
    """

    def __init__(self, runs_dir: Path, thread_id: str | None = None) -> None:
        """Start the run's writer thread.

        Args:
            runs_dir: Root log directory (repo `runs/`).
            thread_id: Conversation thread id, when available.

        Note:
            Never raises for a bad `runs_dir` (e.g. read-only) — that failure
            surfaces inside the background thread instead, which logs it at
            debug level and drops events for this run. `record()` stays a
            cheap, non-blocking enqueue either way (D4/D5/D9).
        """
        self.run_id = _new_run_id(thread_id)
        self.run_dir = runs_dir / self.run_id
        self.path = self.run_dir / "events.jsonl"
        self._seq = 0
        self._seq_lock = threading.Lock()
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._worker = threading.Thread(
            target=self._run_worker,
            name=f"event-writer-{self.run_id}",
            daemon=False,
        )
        self._worker.start()

    def _run_worker(self) -> None:
        """Background loop: create the run dir once, then drain the queue.

        Runs off the event loop thread, so the blocking calls here are safe.
        A failure (e.g. read-only `runs/`) is logged once and the queue is
        drained without writing, so `record()` callers never block on a full
        queue. Every dequeued item (written, dropped, or a sentinel) is
        marked done so `flush()` can use `Queue.join()`. Exits after
        `_WORKER_IDLE_TIMEOUT_SECONDS` of silence — see that constant.
        """
        try:
            self.run_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.debug("EventWriter: could not create run directory", exc_info=True)
            self._drain_without_writing()
            return

        while True:
            try:
                entry = self._queue.get(timeout=_WORKER_IDLE_TIMEOUT_SECONDS)
            except queue.Empty:
                return  # idle: this run's writer has nothing left to do
            try:
                if entry is None:  # shutdown sentinel
                    return
                try:
                    line = json.dumps(entry, ensure_ascii=False)
                    with self.path.open("a", encoding="utf-8") as f:
                        f.write(line + "\n")
                except OSError:
                    logger.debug("EventWriter: dropped one event line", exc_info=True)
            finally:
                self._queue.task_done()

    def _drain_without_writing(self) -> None:
        while True:
            try:
                entry = self._queue.get(timeout=_WORKER_IDLE_TIMEOUT_SECONDS)
            except queue.Empty:
                return
            try:
                if entry is None:
                    return
            finally:
                self._queue.task_done()

    def flush(self) -> None:
        """Block until every event enqueued so far has been written or dropped.

        A test/verification helper. Production callers don't need it — D9
        treats a short persistence delay after the last event as acceptable.
        """
        self._queue.join()

    def record(
        self,
        event_type: str,
        *,
        name: str | None = None,
        status: str | None = None,
        dur_ms: float | None = None,
        error: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Enqueue one event line; the background thread writes it.

        Args:
            event_type: One of the constants above.
            name: Tool or model name, when applicable.
            status: e.g. `"ok"` / `"error"` / `"interrupted"`.
            dur_ms: Duration in milliseconds, when applicable.
            error: Error message (truncated like any other string field).
            data: Extra structured payload; redacted before writing.

        This method itself never touches the filesystem, so it has nothing
        to raise for the caller to swallow (contrast with the pre-D9 design).
        """
        entry: dict[str, Any] = {"ts": _now_iso(), "run_id": self.run_id, "type": event_type}
        if name is not None:
            entry["name"] = name
        if status is not None:
            entry["status"] = status
        if dur_ms is not None:
            entry["dur_ms"] = dur_ms
        if error is not None:
            entry["error"] = _truncate_str(error)
        if data is not None:
            entry["data"] = redact(data)

        with self._seq_lock:
            self._seq += 1
            entry["seq"] = self._seq
        self._queue.put(entry)


# --- Reader (shared by report.py) --------------------------------------


def iter_events(path: Path) -> Iterator[dict[str, Any]]:
    """Yield parsed events from a jsonl file, skipping unparseable lines.

    A run interrupted mid-write (e.g. Ctrl+C) can leave a truncated last
    line; skipping it rather than raising keeps `report.py` crash-free (T4-u).

    Args:
        path: Path to an `events.jsonl` file. Missing files yield nothing.

    Yields:
        One dict per valid event line, in file order.
    """
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
