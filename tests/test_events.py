"""Unit tests for `assistant.events` (STEP2_PLAN.md §6: T1, T1b, T2, T4-u)."""

from __future__ import annotations

import asyncio
import concurrent.futures as cf
import hashlib
from pathlib import Path

from assistant.events import (
    RUN_START,
    TOOL_END,
    EventWriter,
    iter_events,
    redact,
)


def _events(ev: EventWriter, run_id: str) -> list[dict]:
    ev.flush()
    return list(iter_events(ev._runs_dir / run_id / "events.jsonl"))  # noqa: SLF001


# --- T1: concurrent writes all parse as valid JSON ----------------------


def test_concurrent_writes_all_valid_and_sequenced(tmp_path: Path) -> None:
    ev = EventWriter(tmp_path)
    run_id = ev.start_run(thread_id="thread123")

    def write_one(i: int) -> None:
        ev.record(RUN_START, thread_id="thread123", name=f"evt-{i}")

    with cf.ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(write_one, range(100)))

    parsed = _events(ev, run_id)
    assert len(parsed) == 100
    assert sorted(event["seq"] for event in parsed) == list(range(1, 101))


# --- T1b: two runs opened concurrently never cross-contaminate (검토 I3) ---


def test_concurrent_runs_do_not_mix_events(tmp_path: Path) -> None:
    ev = EventWriter(tmp_path)

    async def run_one(label: str, count: int) -> str:
        run_id = ev.start_run(thread_id=label)
        for i in range(count):
            ev.record(RUN_START, thread_id=label, name=f"{label}-{i}")
            await asyncio.sleep(0)  # yield, so the two tasks genuinely interleave
        ev.close_run(status="ok", thread_id=label)
        return run_id

    async def main() -> tuple[str, str]:
        return await asyncio.gather(run_one("alpha", 20), run_one("bravo", 20))

    run_id_a, run_id_b = asyncio.run(main())
    assert run_id_a != run_id_b

    ev.flush()
    events_a = list(iter_events(ev._runs_dir / run_id_a / "events.jsonl"))  # noqa: SLF001
    events_b = list(iter_events(ev._runs_dir / run_id_b / "events.jsonl"))  # noqa: SLF001

    names_a = {e["name"] for e in events_a if "name" in e}
    names_b = {e["name"] for e in events_b if "name" in e}
    assert all(name.startswith("alpha-") for name in names_a)
    assert all(name.startswith("bravo-") for name in names_b)
    assert names_a.isdisjoint(names_b)


def test_record_without_open_run_is_a_noop(tmp_path: Path) -> None:
    ev = EventWriter(tmp_path)
    ev.record(RUN_START, name="nothing-open")  # must not raise
    ev.flush()
    assert not any((tmp_path).rglob("events.jsonl"))


def test_record_with_wrong_thread_id_is_a_noop(tmp_path: Path) -> None:
    """A `record()` for a `thread_id` that never called `start_run` must not
    fall back to some *other* open run — that would be exactly the
    cross-attribution bug thread-id-keying exists to prevent (검토 I3)."""
    ev = EventWriter(tmp_path)
    run_id = ev.start_run(thread_id="real-run")
    ev.record(RUN_START, thread_id="someone-elses-thread", name="should-not-land-here")
    events = _events(ev, run_id)
    assert events == []


# --- T2: redaction / truncation rules (D6, C4) -------------------------------


def test_redact_truncates_long_strings() -> None:
    long_value = "x" * 300
    result = redact({"note": long_value})
    assert result["note"] == f"{'x' * 200}…(+100 chars)"


def test_redact_error_status_gets_1000_char_cap() -> None:
    long_value = "x" * 1300
    result = redact({"note": long_value}, limit=1000)
    assert result["note"] == f"{'x' * 1000}…(+300 chars)"


def test_redact_keeps_short_strings_untouched() -> None:
    result = redact({"note": "short"})
    assert result["note"] == "short"


def test_redact_masks_sensitive_keys() -> None:
    data = {"api_key": "sk-1234567890", "PASSWORD": "hunter2", "secret_token": "abc"}
    result = redact(data)
    assert result["api_key"] == "***"
    assert result["PASSWORD"] == "***"
    assert result["secret_token"] == "***"


def test_redact_masks_sensitive_keys_even_under_error_limit() -> None:
    """D6 exception: key masking is unconditional, regardless of the cap (C4)."""
    result = redact({"api_key": "x" * 2000}, limit=1000)
    assert result["api_key"] == "***"


def test_redact_does_not_mask_plural_token_count_fields() -> None:
    """Regression: D6's `token` rule must not catch D7's own `*_tokens` metrics."""
    data = {"input_tokens": 10, "output_tokens": 5, "auth_token": "should-be-masked"}
    result = redact(data)
    assert result["input_tokens"] == 10
    assert result["output_tokens"] == 5
    assert result["auth_token"] == "***"


def test_redact_hashes_content_and_command_fields() -> None:
    text = "print('hello world')" * 5
    result = redact({"content": text, "command": "rm -rf /", "other": "kept"})

    assert result["content"] == {
        "len": len(text),
        "sha256_8": hashlib.sha256(text.encode()).hexdigest()[:8],
    }
    assert result["command"]["len"] == len("rm -rf /")
    assert result["other"] == "kept"


def test_redact_recurses_into_nested_dicts_and_lists() -> None:
    data = {"args": {"api_key": "secret", "items": ["a" * 300, "b"]}}
    result = redact(data)
    assert result["args"]["api_key"] == "***"
    assert result["args"]["items"][0] == f"{'a' * 200}…(+100 chars)"
    assert result["args"]["items"][1] == "b"


# --- run_id (D1) ----------------------------------------------------------


def test_run_id_uses_thread_id_prefix(tmp_path: Path) -> None:
    ev = EventWriter(tmp_path)
    run_id = ev.start_run(thread_id="abcdefghijk")
    assert run_id.rsplit("-", 1)[-1] == "abcdefgh"


def test_run_id_falls_back_to_random_suffix_without_thread_id(tmp_path: Path) -> None:
    ev = EventWriter(tmp_path)
    run_id = ev.start_run(thread_id=None)
    assert len(run_id.rsplit("-", 1)[-1]) == 8


# --- record() writes the documented schema (D7) --------------------------


def test_record_writes_expected_fields(tmp_path: Path) -> None:
    ev = EventWriter(tmp_path)
    run_id = ev.start_run(thread_id="t1")
    ev.record(
        TOOL_END, thread_id="t1", name="read_file", status="ok", dur_ms=12.5, data={"file_path": "a.py"}
    )
    (event,) = _events(ev, run_id)

    assert event["type"] == TOOL_END
    assert event["name"] == "read_file"
    assert event["status"] == "ok"
    assert event["dur_ms"] == 12.5
    assert event["data"] == {"file_path": "a.py"}
    assert event["seq"] == 1
    assert event["run_id"] == run_id
    assert "ts" in event


def test_close_run_records_counters_and_clears_run(tmp_path: Path) -> None:
    ev = EventWriter(tmp_path)
    run_id = ev.start_run(thread_id="t1")
    ev.record(TOOL_END, thread_id="t1", name="read_file", status="ok")
    ev.record(TOOL_END, thread_id="t1", name="write_file", status="error")
    ev.close_run(status="ok", thread_id="t1")

    assert ev.current_run_id(thread_id="t1") is None
    events = _events(ev, run_id)
    run_end = events[-1]
    assert run_end["type"] == "run_end"
    assert run_end["data"] == {"event_count": 2, "error_count": 1}


# --- T4-u: iter_events never raises on missing/malformed data ------------


def test_iter_events_skips_malformed_trailing_line(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(
        '{"type": "run_start", "seq": 1}\n{"type": "tool_start", "seq": 2', encoding="utf-8"
    )
    events = list(iter_events(path))
    assert len(events) == 1
    assert events[0]["type"] == "run_start"


def test_iter_events_missing_file_yields_nothing(tmp_path: Path) -> None:
    assert list(iter_events(tmp_path / "missing.jsonl")) == []
