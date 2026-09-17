"""Event schema and JSONL writer for the observability middleware.

Design constraints (see `docs/plan/STEP2_PLAN.md` §5):

- D5: never write to stdout/stderr — only to `runs/<run_id>/events.jsonl`.
  Diagnostics go through the `logging` module only.
- D6: redact secrets and cap field size before anything is persisted.
- D7: one JSON object per line; reserved event types for later steps are
  declared here (as strings only) so `report.py` does not need to change
  when Step 3/4 start emitting them.

This module does not swallow errors itself (no fail-open here). Whether a
write failure should be silently ignored is the caller's decision — see
`assistant/observability.py` (D4).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import secrets
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

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

_SENSITIVE_KEY_RE = re.compile(r"key|token|secret|password", re.IGNORECASE)
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


class EventWriter:
    """Appends one JSON object per line to `runs/<run_id>/events.jsonl`.

    One instance corresponds to one run (one user turn). Concurrent calls to
    `record()` from parallel tool calls are safe: a lock serializes sequence
    numbering and the file append.
    """

    def __init__(self, runs_dir: Path, thread_id: str | None = None) -> None:
        """Create the run directory and open a writer for it.

        Args:
            runs_dir: Root log directory (repo `runs/`).
            thread_id: Conversation thread id, when available.

        Raises:
            OSError: If `runs_dir` cannot be created (e.g. read-only). The
                caller decides whether to swallow this (D4).
        """
        self.run_id = _new_run_id(thread_id)
        self.run_dir = runs_dir / self.run_id
        self.path = self.run_dir / "events.jsonl"
        self._lock = threading.Lock()
        self._seq = 0
        self.run_dir.mkdir(parents=True, exist_ok=True)

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
        """Append one event line.

        Args:
            event_type: One of the constants above.
            name: Tool or model name, when applicable.
            status: e.g. `"ok"` / `"error"` / `"interrupted"`.
            dur_ms: Duration in milliseconds, when applicable.
            error: Error message (truncated like any other string field).
            data: Extra structured payload; redacted before writing.

        Raises:
            OSError: If the append write fails. Not swallowed here — see
                the module docstring.
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

        with self._lock:
            self._seq += 1
            entry["seq"] = self._seq
            line = json.dumps(entry, ensure_ascii=False)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")


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
