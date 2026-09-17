"""Unit tests for `assistant.report` (STEP2_PLAN.md §4 task 11, §6).

Uses a fixed jsonl fixture — no live dcode/model call needed (§6: "고정 jsonl
픽스처로 출력 검증"). Covers DC3 (timeline + total duration), DC4 (failure +
context), DC7 (retry count), DC8 (hierarchical trace view).
"""

from __future__ import annotations

import json
from pathlib import Path

from assistant.report import _collect_metrics, cmd_fail, cmd_list, cmd_show, cmd_stats

RUN_ID = "20260101-000000-testrun1"

FIXTURE_EVENTS = [
    {
        "ts": "2026-01-01T00:00:00.000+09:00",
        "run_id": RUN_ID,
        "seq": 1,
        "type": "run_start",
        "data": {"user_input": "read a.py, then missing.txt", "thread_id": "t1", "cwd": "/repo"},
    },
    {"ts": "...", "run_id": RUN_ID, "seq": 2, "type": "model_start", "name": "m1", "attempt": 1},
    {
        "ts": "...",
        "run_id": RUN_ID,
        "seq": 3,
        "type": "model_error",
        "name": "m1",
        "status": "error",
        "attempt": 1,
        "dur_ms": 100.0,
        "error": "TimeoutError: transient failure",
    },
    {"ts": "...", "run_id": RUN_ID, "seq": 4, "type": "model_start", "name": "m1", "attempt": 2},
    {
        "ts": "...",
        "run_id": RUN_ID,
        "seq": 5,
        "type": "model_end",
        "name": "m1",
        "status": "success",
        "attempt": 2,
        "dur_ms": 200.0,
        "data": {"input_tokens": 100, "output_tokens": 10, "requested_tools": ["read_file"]},
    },
    {
        "ts": "...",
        "run_id": RUN_ID,
        "seq": 6,
        "type": "tool_start",
        "name": "read_file",
        "data": {"args": {"file_path": "a.py"}},
    },
    {
        "ts": "...",
        "run_id": RUN_ID,
        "seq": 7,
        "type": "tool_end",
        "name": "read_file",
        "status": "success",
        "dur_ms": 5.0,
        "data": {"result_len": 42},
    },
    {
        "ts": "...",
        "run_id": RUN_ID,
        "seq": 8,
        "type": "tool_start",
        "name": "read_file",
        "data": {"args": {"file_path": "missing.txt"}},
    },
    {
        "ts": "...",
        "run_id": RUN_ID,
        "seq": 9,
        "type": "tool_end",
        "name": "read_file",
        "status": "error",
        "dur_ms": 3.0,
        "error": "FileNotFoundError: missing.txt",
    },
    {
        "ts": "...",
        "run_id": RUN_ID,
        "seq": 10,
        "type": "run_end",
        "status": "ok",
        "dur_ms": 500.0,
        "data": {"event_count": 9, "error_count": 2},
    },
]


def _write_fixture(runs_dir: Path, run_id: str = RUN_ID, events: list[dict] | None = None) -> None:
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    lines = [json.dumps(e) for e in (events if events is not None else FIXTURE_EVENTS)]
    (run_dir / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- _collect_metrics (DC7's data source) ---------------------------------


def test_collect_metrics_counts_calls_tools_retries_tokens_and_errors() -> None:
    metrics = _collect_metrics(FIXTURE_EVENTS)
    assert metrics["model_calls"] == 2  # two model_start events (attempt 1 and 2)
    assert metrics["tool_calls"] == 2
    assert metrics["retries"] == 1  # exactly one model_start with attempt >= 2
    assert metrics["errors"] == 2  # one model_error + one failed tool_end
    assert metrics["total_dur_ms"] == 500.0
    assert metrics["input_tokens"] == 100
    assert metrics["output_tokens"] == 10


def test_collect_metrics_reports_none_duration_for_unterminated_run() -> None:
    """T4-u/T8: a run with no run_end is "미종료", not a crash."""
    metrics = _collect_metrics(FIXTURE_EVENTS[:-1])  # drop run_end
    assert metrics["total_dur_ms"] is None


# --- show: DC3 (timeline + total duration) + DC8 (hierarchical trace) ----


def test_cmd_show_renders_trace_and_metrics_footer(tmp_path: Path, capsys) -> None:
    _write_fixture(tmp_path)
    exit_code = cmd_show(RUN_ID, tmp_path)
    out = capsys.readouterr().out

    assert exit_code == 0
    assert f"run {RUN_ID}" in out
    assert "실패 2" in out
    assert "model_call #1" in out
    assert "attempt=2" in out  # the retried call, not the first attempt
    assert "tool  read_file" in out
    assert "ERROR" in out
    assert "missing.txt" in out
    assert "지표" in out
    assert "재시도 1회" in out
    assert "토큰 in 100 / out 10" in out


def test_cmd_show_missing_run_returns_error(tmp_path: Path, capsys) -> None:
    exit_code = cmd_show("no-such-run", tmp_path)
    assert exit_code == 1
    assert "no-such-run" in capsys.readouterr().out


# --- fail: DC4 (failures with preceding context, T6) ---------------------


def test_cmd_fail_shows_each_failure_with_context(tmp_path: Path, capsys) -> None:
    _write_fixture(tmp_path)
    exit_code = cmd_fail(RUN_ID, tmp_path)
    out = capsys.readouterr().out

    assert exit_code == 0
    # Both failures get their own block.
    assert "seq=3 model_error" in out
    assert "seq=9 tool_end" in out
    assert "TimeoutError: transient failure" in out
    assert "FileNotFoundError: missing.txt" in out
    # The successful tool call (seq 6-7) is context for the seq=9 failure,
    # not a failure block of its own.
    assert "seq=6 model_error" not in out


def test_cmd_fail_context_window_is_bounded(tmp_path: Path, capsys) -> None:
    """T6: only the *preceding* 3 events accompany a failure, not the whole run."""
    _write_fixture(tmp_path)
    cmd_fail(RUN_ID, tmp_path)
    out = capsys.readouterr().out
    second_block = out.split("--- seq=9")[1]
    # The 3 events immediately before seq=9 are seq 6,7,8; anything earlier
    # (seq=5 and before) belongs to the first failure's own context, not this one.
    assert "seq=6" in second_block
    assert "seq=5" not in second_block


def test_cmd_fail_no_failures(tmp_path: Path, capsys) -> None:
    clean_events = [e for e in FIXTURE_EVENTS if e.get("status") != "error"]
    _write_fixture(tmp_path, run_id="clean-run", events=clean_events)
    exit_code = cmd_fail("clean-run", tmp_path)
    assert exit_code == 0
    assert "실패한 이벤트 없음" in capsys.readouterr().out


def test_cmd_fail_catches_a_model_error_with_no_tool_failure(tmp_path: Path, capsys) -> None:
    """검토 R-A regression: a run whose only failure is `model_error` (no
    `tool_end status=error`) must still be found by `fail`/`_collect_metrics`
    — this is exactly the "provider died / rate-limited" case, and it was
    silently invisible before `MODEL_ERROR` carried `status="error"`.
    """
    events = [
        FIXTURE_EVENTS[0],  # run_start
        {"ts": "...", "run_id": "model-fail-run", "seq": 2, "type": "model_start", "name": "m1", "attempt": 1},
        {
            "ts": "...",
            "run_id": "model-fail-run",
            "seq": 3,
            "type": "model_error",
            "name": "m1",
            "status": "error",
            "attempt": 1,
            "dur_ms": 50.0,
            "error": "RateLimitError: 429",
        },
        {
            "ts": "...",
            "run_id": "model-fail-run",
            "seq": 4,
            "type": "run_end",
            "status": "ok",
            "dur_ms": 60.0,
            "data": {"event_count": 3, "error_count": 1},
        },
    ]
    _write_fixture(tmp_path, run_id="model-fail-run", events=events)

    metrics = _collect_metrics(events)
    assert metrics["errors"] == 1

    exit_code = cmd_fail("model-fail-run", tmp_path)
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "실패한 이벤트 없음" not in out
    assert "seq=3 model_error" in out
    assert "RateLimitError: 429" in out


# --- stats: thin wrapper around the same metrics as show's footer (D7) ---


def test_cmd_stats_matches_shows_metrics_footer(tmp_path: Path, capsys) -> None:
    _write_fixture(tmp_path)
    cmd_stats(RUN_ID, tmp_path)
    stats_out = capsys.readouterr().out.strip()

    cmd_show(RUN_ID, tmp_path)
    show_out = capsys.readouterr().out.strip()
    show_footer = show_out.splitlines()[-1]

    assert stats_out == show_footer


# --- list ------------------------------------------------------------


def test_cmd_list_shows_all_runs_newest_first(tmp_path: Path, capsys) -> None:
    _write_fixture(tmp_path, run_id="20260101-000000-first")
    _write_fixture(tmp_path, run_id="20260102-000000-second")
    cmd_list(tmp_path)
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if "-000000-" in line]
    assert len(lines) == 2
    assert lines[0].startswith("20260102-000000-second")
    assert lines[1].startswith("20260101-000000-first")


def test_cmd_list_empty_runs_dir(tmp_path: Path, capsys) -> None:
    exit_code = cmd_list(tmp_path / "missing")
    assert exit_code == 0
    assert "no runs yet" in capsys.readouterr().out
