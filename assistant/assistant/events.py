"""Event schema and JSONL writer shared by both observability middleware.

Design constraints (see `docs/plan/STEP2_PLAN.md` §5):

- D1 (+ 검토 I3): runs are looked up by `thread_id`, explicitly passed on
  every call — not by a plain attribute, and (despite the original design)
  not by a `contextvars.ContextVar` either. `EventWriter` is long-lived and
  shared (D2b/I2) between the outer `EventLoggerMiddleware` (run boundary,
  tool calls) and the inner `EventLoggerInnerMiddleware` (per-attempt model
  calls). A plain unkeyed attribute would let two concurrent conversations
  cross-attribute events; a `ContextVar` was tried first but, confirmed by a
  real headless run, does not survive between `before_agent` and a later
  `wrap_tool_call`/`after_agent` — dcode's server gives each hook its own
  task/context rather than one continuously threaded through the turn. See
  the `EventWriter` docstring for the full story.
- D5: never write to stdout/stderr — only to `runs/<run_id>/events.jsonl`.
  Diagnostics go through the `logging` module only.
- D6 (+ 검토 C4): redact secrets and cap field size before anything is
  persisted. `status="error"` events get a 1000-char cap instead of 200 —
  4-4 requires the failure's own detail to survive, and key masking to
  `***` always applies regardless of the cap.
- D7: one JSON object per line; reserved event types for later steps are
  declared here (as strings only) so `report.py` does not need to change
  when Step 3/4/5 start emitting them. `code_changed`/`run_result` are
  populated now (derived from `tool_end`/`run_end`) per the official
  4-1 rubric wording (계획·리뷰·**코드 변경**·테스트·**최종 결과**).
- D9 (실측, not in the original plan text): dcode's server
  (`langgraph_runtime_inmem`) raises if the event-loop thread makes a
  *synchronous* blocking call — confirmed with a real headless run
  (`BlockingError: Blocking call to os.mkdir`). Plain file `write()` is
  explicitly exempted by that same guard, but `mkdir()` is not. All actual
  I/O therefore happens on one dedicated background thread; `record()`
  itself only enqueues and never touches the filesystem.
"""

from __future__ import annotations

import atexit
import datetime as _dt
import hashlib
import json
import logging
import queue
import re
import secrets
import threading
import time
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

# Populated starting this step (derived from tool_end/run_end; §5 D7 addendum).
CODE_CHANGED = "code_changed"
RUN_RESULT = "run_result"

# Reserved for later steps. Declared now as string constants only, so
# `report.py` does not need to change when they start firing for real.
GATE_BLOCK = "gate_block"  # Step 3
PLAN_CREATED = "plan_created"  # Step 3
PLAN_REVIEWED = "plan_reviewed"  # Step 3
PLAN_APPROVED = "plan_approved"  # Step 3
MEMORY_HIT = "memory_hit"  # Step 4
IMPROVE_START = "improve_start"  # Step 4
IMPROVE_END = "improve_end"  # Step 4
TEST_RUN = "test_run"  # Step 5

# --- Redaction (D6 + C4) ---------------------------------------------------

_SENSITIVE_KEY_RE = re.compile(r"key|token(?!s)|secret|password", re.IGNORECASE)
"""`token(?!s)` excludes plural metric fields like `input_tokens`/`output_tokens`
(D7's own token-count requirement, §1 4-3) while still catching `token`,
`api_token`, `auth_token`, etc."""

_HASH_ONLY_KEYS = frozenset({"content", "command"})
_MAX_STR_LEN = 200
_MAX_ERROR_STR_LEN = 1000
"""C4: `status="error"` events get a higher cap — 4-4 requires the failure's
own detail (e.g. a long path or command tail) to survive, not just its
first 200 chars."""


def _truncate_str(value: str, limit: int = _MAX_STR_LEN) -> str:
    """Cap a string at `limit` chars, noting how much was cut."""
    if len(value) <= limit:
        return value
    cut = len(value) - limit
    return f"{value[:limit]}…(+{cut} chars)"


def _hash_summary(value: str) -> dict[str, Any]:
    """Replace a large field's text with its length and a short hash."""
    digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()
    return {"len": len(value), "sha256_8": digest[:8]}


def _redact_value(key: str | None, value: Any, limit: int) -> Any:  # noqa: ANN401
    if key is not None and _SENSITIVE_KEY_RE.search(key):
        return "***"  # unconditional — not subject to `limit` (D6 exception note)
    if key in _HASH_ONLY_KEYS and isinstance(value, str):
        return _hash_summary(value)
    if isinstance(value, str):
        return _truncate_str(value, limit)
    if isinstance(value, dict):
        return {k: _redact_value(k, v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(None, item, limit) for item in value]
    return value


def redact(data: dict[str, Any], *, limit: int = _MAX_STR_LEN) -> dict[str, Any]:
    """Redact sensitive keys and cap oversized fields before persisting.

    Args:
        data: Arbitrary event payload (e.g. tool call args).
        limit: Per-string cap. Callers pass `_MAX_ERROR_STR_LEN` for
            `status="error"` events (C4).

    Returns:
        A new dict safe to write to `events.jsonl`.
    """
    return {k: _redact_value(k, v, limit) for k, v in data.items()}


# --- run_id ----------------------------------------------------------------


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


# --- current-run tracking (D1 + 검토 I3) -----------------------------------


class _RunState:
    """Mutable per-run bookkeeping held by the `ContextVar`, not by the writer."""

    __slots__ = ("error_count", "event_count", "lock", "run_id", "seq", "started_at")

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.seq = 0
        self.lock = threading.Lock()
        self.started_at = time.monotonic()
        self.event_count = 0
        self.error_count = 0


_DEFAULT_KEY = "_default"
"""Fallback run-lookup key when no `thread_id` is available at all (§7 risk:
base `before_agent` has no config). A single ambient run still works for a
one-conversation-at-a-time session; it just can't tell two such sessions
apart, which is no worse than before this fix."""


def resolve_project_dir() -> Path:
    """Resolve the *project* root — not the server's own `cwd()`.

    S11 addendum (실측): dcode's server process runs with its own `cwd()` in
    a private temp sandbox (`/tmp/deepagents_server_<id>/`) — confirmed by a
    real headless run, where a plain `Path.cwd()` default silently wrote
    every event under that temp directory instead of the repository (F2's
    "project root = the invocation directory" is about *dcode's own*
    project-root resolution, which is a separate mechanism from the raw
    OS-level `cwd()` of the server process, and is also unaffected by S11:
    reading already-set `os.environ` entries is not a syscall). Also used
    for `run_start`'s `cwd` field (`assistant/observability.py`) — a plain
    `Path.cwd()` there was losing the whole event (Blockbuster) as well as
    reporting the wrong directory.

    `get_server_project_context()` reads the client's actual invocation
    directory back out of the environment dcode's own server transport sets
    up — the same mechanism `agent.py` itself falls back to (see
    `_format_execute_description`).
    """
    try:
        from deepagents_code.project_utils import get_server_project_context

        ctx = get_server_project_context()
        if ctx is not None:
            return ctx.project_root or ctx.user_cwd
    except Exception:  # noqa: BLE001 - best-effort; fall through to cwd()
        pass
    return Path.cwd()


# --- Writer -----------------------------------------------------------


class EventWriter:
    """Shared, long-lived event sink for one agent instance.

    Constructor-injected into both `EventLoggerMiddleware` (outer: run
    boundary, tool calls) and `EventLoggerInnerMiddleware` (inner: per-attempt
    model calls) — see D2b/검토 I2. Not a module-level singleton: that would
    make test isolation impossible (T3-u deliberately breaks a writer) and
    would mix state across subagents/parallel runs.

    Runs are looked up by `thread_id`, passed explicitly by the caller on
    every call (D1 + 검토 I3) — **not** tracked via a `contextvars.ContextVar`.
    A `ContextVar` was the original design (isolates concurrent sibling
    tasks cleanly), but a real headless run showed it does not survive
    between separate hook calls on the same turn: `before_agent` sets it,
    and by the time `awrap_tool_call`/`after_agent` run, `ContextVar.get()`
    is back to the default. dcode's server evidently gives each hook its own
    task/context copied from a common ancestor rather than a continuously
    threaded one, so a value set in one hook is invisible to the next.
    `thread_id` (from `RunnableConfig`), by contrast, was confirmed present
    and identical across `before_agent`/`wrap_tool_call`/`after_agent` in
    that same run, so it is a reliable, hook-independent lookup key.
    """

    def __init__(self, runs_dir: Path | None = None) -> None:
        """Start the shared background writer thread.

        Args:
            runs_dir: Root log directory. Defaults to the *project* root's
                `./runs` — see `_default_runs_dir()`, not a plain `Path.cwd()`.
        """
        self._runs_dir = (
            runs_dir if runs_dir is not None else resolve_project_dir() / "runs"
        )
        self._queue: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue()
        self._known_dirs: set[str] = set()
        self._runs_lock = threading.Lock()
        self._runs: dict[str, _RunState] = {}
        self._attempts_lock = threading.Lock()
        self._attempts: dict[str, int] = {}
        self._worker = threading.Thread(
            target=self._run_worker, name="event-writer", daemon=True
        )
        self._worker.start()
        atexit.register(self.flush)
        """검토 P2: `after_agent`'s own `flush()` only covers a normal turn
        end. A process that dies mid-turn (Ctrl+C, forced TUI exit, or an
        interrupt that kills the process before the next turn's
        `before_agent` closes it as `interrupted`) never reaches that call.
        `atexit` is the backstop for exactly that case."""

    # --- attempt tracking (D2b, 검토 P3) -----------------------------------

    def next_attempt(self, thread_id: str | None = None) -> int:
        """1-based attempt count for this thread's in-flight model call.

        Keyed by `thread_id`, not `id(request)` (검토 P3): identity-keying
        leaked and risked `id()` reuse for a call that exhausts its retries
        without ever calling `reset_attempts` (a stale entry could then be
        inherited by an unrelated later `ModelRequest` reusing that address).
        `thread_id` cannot be reused this way, and a stale count left behind
        by a permanent failure is bounded by the next turn's `before_agent`
        calling `reset_attempts` unconditionally.
        """
        key = thread_id or _DEFAULT_KEY
        with self._attempts_lock:
            attempt = self._attempts.get(key, 0) + 1
            self._attempts[key] = attempt
        return attempt

    def reset_attempts(self, thread_id: str | None = None) -> None:
        """Clear this thread's attempt counter.

        Call on success, and on every `before_agent` as a turn-boundary
        backstop for a call that exhausted its retries without succeeding.
        """
        key = thread_id or _DEFAULT_KEY
        with self._attempts_lock:
            self._attempts.pop(key, None)

    # --- run lifecycle ----------------------------------------------------

    def start_run(self, thread_id: str | None = None) -> str:
        """Open a new run, keyed by `thread_id` (or the shared fallback key).

        Returns:
            The new run id.
        """
        run_id = _new_run_id(thread_id)
        key = thread_id or _DEFAULT_KEY
        with self._runs_lock:
            self._runs[key] = _RunState(run_id)
        return run_id

    def current_run_id(self, thread_id: str | None = None) -> str | None:
        """The run id `record()` would attribute events to for this `thread_id`."""
        key = thread_id or _DEFAULT_KEY
        with self._runs_lock:
            state = self._runs.get(key)
        return state.run_id if state is not None else None

    def close_run(
        self,
        *,
        status: str,
        extra: dict[str, Any] | None = None,
        thread_id: str | None = None,
    ) -> None:
        """Record `run_end` for this run, then forget it.

        Args:
            status: e.g. `"ok"` or `"interrupted"` (HITL interrupt, §7 risk).
            extra: Additional `run_end` data fields (merged with the run's
                own event/error counters).
            thread_id: Same key `start_run`/`record` were called with.
        """
        key = thread_id or _DEFAULT_KEY
        with self._runs_lock:
            state = self._runs.pop(key, None)
        if state is None:
            return
        dur_ms = (time.monotonic() - state.started_at) * 1000
        data = {"event_count": state.event_count, "error_count": state.error_count}
        if extra:
            data.update(extra)
        self._record_for(state, RUN_END, status=status, dur_ms=dur_ms, data=data)

    # --- recording ----------------------------------------------------

    def record(
        self,
        event_type: str,
        *,
        thread_id: str | None = None,
        name: str | None = None,
        status: str | None = None,
        dur_ms: float | None = None,
        attempt: int | None = None,
        error: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Enqueue one event line for this run; a no-op with no matching run.

        Args:
            event_type: One of the constants above.
            thread_id: Same key passed to `start_run` for this run.
            name: Tool or model name, when applicable.
            status: e.g. `"success"` / `"error"` / `"interrupted"`.
            dur_ms: Duration in milliseconds, when applicable.
            attempt: 1-based retry attempt number (D2b), when applicable.
            error: Error message (capped like any string field — C4 raises
                the cap for `status="error"`).
            data: Extra structured payload; redacted before writing.

        This method never touches the filesystem, so it has nothing to raise
        for a caller to swallow (contrast with the pre-D9 design).
        """
        key = thread_id or _DEFAULT_KEY
        with self._runs_lock:
            state = self._runs.get(key)
        if state is None:
            return  # no open run to attribute this to (fail-open)
        self._record_for(
            state,
            event_type,
            name=name,
            status=status,
            dur_ms=dur_ms,
            attempt=attempt,
            error=error,
            data=data,
        )

    def _record_for(
        self,
        state: _RunState,
        event_type: str,
        *,
        name: str | None = None,
        status: str | None = None,
        dur_ms: float | None = None,
        attempt: int | None = None,
        error: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        limit = _MAX_ERROR_STR_LEN if status == "error" else _MAX_STR_LEN
        entry: dict[str, Any] = {
            "ts": _now_iso(),
            "run_id": state.run_id,
            "type": event_type,
        }
        if name is not None:
            entry["name"] = name
        if status is not None:
            entry["status"] = status
        if dur_ms is not None:
            entry["dur_ms"] = dur_ms
        if attempt is not None:
            entry["attempt"] = attempt
        if error is not None:
            entry["error"] = _truncate_str(error, limit)
        if data is not None:
            entry["data"] = redact(data, limit=limit)

        with state.lock:
            state.seq += 1
            entry["seq"] = state.seq
        state.event_count += 1
        if status == "error":
            state.error_count += 1
        self._queue.put((state.run_id, entry))

    def flush(self) -> None:
        """Block until every event enqueued so far has been written or dropped.

        Safe to call from the event-loop thread: it blocks on
        `threading.Lock.acquire`, which dcode's Blockbuster guard explicitly
        exempts (D9). Called from `after_agent` so a run's events are durable
        before the hook returns, regardless of how soon the process exits
        afterward (observed: a one-shot headless run can exit within
        microseconds of the last hook call).
        """
        self._queue.join()

    # --- background I/O (D9) -----------------------------------------------

    def _run_worker(self) -> None:
        """Drain the queue forever, off the event-loop thread.

        A per-run directory failure (e.g. read-only `runs/`) is logged once
        per run and that run's events are dropped — `record()` callers never
        block either way.
        """
        while True:
            item = self._queue.get()
            try:
                if item is None:  # shutdown sentinel (not used in practice)
                    return
                run_id, entry = item
                try:
                    run_dir = self._runs_dir / run_id
                    if run_id not in self._known_dirs:
                        run_dir.mkdir(parents=True, exist_ok=True)
                        self._known_dirs.add(run_id)
                    line = json.dumps(entry, ensure_ascii=False)
                    with (run_dir / "events.jsonl").open("a", encoding="utf-8") as f:
                        f.write(line + "\n")
                except OSError:
                    logger.debug("EventWriter: dropped one event line", exc_info=True)
            finally:
                self._queue.task_done()


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
