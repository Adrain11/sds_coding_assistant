"""Unit tests for `assistant.events` (STEP2_PLAN.md §6: T1, T2, T4-u)."""

from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
from pathlib import Path

from assistant.events import (
    RUN_START,
    TOOL_END,
    EventWriter,
    iter_events,
    redact,
)


# --- T1: concurrent writes all parse as valid JSON ----------------------


def test_concurrent_writes_all_valid_and_sequenced(tmp_path: Path) -> None:
    writer = EventWriter(tmp_path, thread_id="thread123")

    def write_one(i: int) -> None:
        writer.record(RUN_START, name=f"evt-{i}")

    with cf.ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(write_one, range(100)))

    lines = writer.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 100

    parsed = [json.loads(line) for line in lines]
    assert sorted(event["seq"] for event in parsed) == list(range(1, 101))


# --- T2: redaction / truncation rules (D6) -------------------------------


def test_redact_truncates_long_strings() -> None:
    long_value = "x" * 300
    result = redact({"note": long_value})
    assert result["note"] == f"{'x' * 200}…(+100 chars)"


def test_redact_keeps_short_strings_untouched() -> None:
    result = redact({"note": "short"})
    assert result["note"] == "short"


def test_redact_masks_sensitive_keys() -> None:
    data = {"api_key": "sk-1234567890", "PASSWORD": "hunter2", "secret_token": "abc"}
    result = redact(data)
    assert result["api_key"] == "***"
    assert result["PASSWORD"] == "***"
    assert result["secret_token"] == "***"


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
    writer = EventWriter(tmp_path, thread_id="abcdefghijk")
    assert writer.run_id.rsplit("-", 1)[-1] == "abcdefgh"


def test_run_id_falls_back_to_random_suffix_without_thread_id(tmp_path: Path) -> None:
    writer = EventWriter(tmp_path, thread_id=None)
    suffix = writer.run_id.rsplit("-", 1)[-1]
    assert len(suffix) == 8


# --- record() writes the documented schema (D7) --------------------------


def test_record_writes_expected_fields(tmp_path: Path) -> None:
    writer = EventWriter(tmp_path, thread_id="t1")
    writer.record(
        TOOL_END, name="read_file", status="ok", dur_ms=12.5, data={"file_path": "a.py"}
    )
    (line,) = writer.path.read_text(encoding="utf-8").splitlines()
    event = json.loads(line)

    assert event["type"] == TOOL_END
    assert event["name"] == "read_file"
    assert event["status"] == "ok"
    assert event["dur_ms"] == 12.5
    assert event["data"] == {"file_path": "a.py"}
    assert event["seq"] == 1
    assert event["run_id"] == writer.run_id
    assert "ts" in event


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
