"""Unit tests for `assistant.observability` (STEP2_PLAN.md §6: T3-u, T11-u).

Not listed as its own row in STEP2_PLAN.md §4 (the table only lists
`tests/test_events.py` and `tests/test_report.py`), but §6 requires T3-u
(fail-open on a logging failure) and T11-u (DC7's primary evidence for
retry-attempt logging) as unit tests, and observability.py (task 7/8) is
what both target. Added here rather than skipped.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from assistant.events import EventWriter, iter_events
from assistant.observability import EventLoggerInnerMiddleware, EventLoggerMiddleware
from langchain_core.messages import AIMessage, HumanMessage


class _FakeToolMessage:
    def __init__(self, status: str = "success", content: str = "ok") -> None:
        self.status = status
        self.content = content


def _tool_request(name: str = "read_file", args: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(tool_call={"name": name, "args": args or {}, "id": "call-1"})


def _model_request(model_name: str = "test-model") -> SimpleNamespace:
    return SimpleNamespace(model=SimpleNamespace(model=model_name))


def _events(ev: EventWriter, run_id: str) -> list[dict]:
    ev.flush()
    return list(iter_events(ev._runs_dir / run_id / "events.jsonl"))  # noqa: SLF001


# --- run boundary (outer middleware) --------------------------------------


def test_before_after_agent_write_run_start_and_end(tmp_path: Path) -> None:
    ev = EventWriter(tmp_path)
    mw = EventLoggerMiddleware(ev)
    state = {"messages": [HumanMessage(content="read the readme")]}
    mw.before_agent(state, runtime=None)
    run_id = ev.current_run_id()
    mw.after_agent(state, runtime=None)

    events = _events(ev, run_id)
    assert [e["type"] for e in events] == ["run_start", "run_end"]
    assert events[0]["data"]["user_input"] == "read the readme"
    assert events[1]["status"] == "ok"
    assert "dur_ms" in events[1]


def test_before_agent_closes_previous_run_as_interrupted(tmp_path: Path) -> None:
    ev = EventWriter(tmp_path)
    mw = EventLoggerMiddleware(ev)
    state = {"messages": []}
    mw.before_agent(state, runtime=None)
    first_run_id = ev.current_run_id()

    mw.before_agent(state, runtime=None)  # no after_agent in between (HITL interrupt)

    events = _events(ev, first_run_id)
    assert events[-1]["type"] == "run_end"
    assert events[-1]["status"] == "interrupted"


# --- tool calls (outer middleware) ------------------------------------------


def test_wrap_tool_call_records_start_end_and_code_changed(tmp_path: Path) -> None:
    ev = EventWriter(tmp_path)
    mw = EventLoggerMiddleware(ev)
    mw.before_agent({"messages": []}, runtime=None)
    run_id = ev.current_run_id()

    request = _tool_request("write_file", {"file_path": "a.py"})
    result = mw.wrap_tool_call(
        request, lambda _req: _FakeToolMessage(content="wrote 3 lines")
    )

    assert isinstance(result, _FakeToolMessage)
    events = [e for e in _events(ev, run_id) if e["type"] != "run_start"]
    assert [e["type"] for e in events] == ["tool_start", "tool_end", "code_changed"]
    assert events[1]["status"] == "success"
    assert events[2]["name"] == "write_file"


def test_wrap_tool_call_read_only_tool_has_no_code_changed(tmp_path: Path) -> None:
    ev = EventWriter(tmp_path)
    mw = EventLoggerMiddleware(ev)
    mw.before_agent({"messages": []}, runtime=None)
    run_id = ev.current_run_id()

    mw.wrap_tool_call(
        _tool_request("read_file"), lambda _req: _FakeToolMessage(content="x")
    )
    events = [e for e in _events(ev, run_id) if e["type"] != "run_start"]
    assert [e["type"] for e in events] == ["tool_start", "tool_end"]


def test_wrap_tool_call_captures_error_content_without_raising(tmp_path: Path) -> None:
    """A tool that fails by *returning* status="error" still needs an error field.

    No exception involved — e.g. read_file on a missing path — but the
    result must still carry a human-readable `error` field. A real TUI run
    showed `tool_end status=error` with no `error` text at all — only
    `result_len` — because `_tool_call_result_summary` never looked at
    `content` for the reason.
    """
    ev = EventWriter(tmp_path)
    mw = EventLoggerMiddleware(ev)
    mw.before_agent({"messages": []}, runtime=None)
    run_id = ev.current_run_id()

    result = mw.wrap_tool_call(
        _tool_request("read_file", {"file_path": "missing.txt"}),
        lambda _req: _FakeToolMessage(
            status="error", content="Error: file not found: missing.txt"
        ),
    )

    assert isinstance(
        result, _FakeToolMessage
    )  # not raised — this is the ToolMessage path
    events = [e for e in _events(ev, run_id) if e["type"] == "tool_end"]
    assert events[0]["status"] == "error"
    assert events[0]["error"] == "Error: file not found: missing.txt"


def test_wrap_tool_call_records_error_and_reraises(tmp_path: Path) -> None:
    ev = EventWriter(tmp_path)
    mw = EventLoggerMiddleware(ev)
    mw.before_agent({"messages": []}, runtime=None)
    run_id = ev.current_run_id()

    def _boom(_req: object) -> None:
        raise FileNotFoundError("no such file: missing.txt")

    with pytest.raises(FileNotFoundError):
        mw.wrap_tool_call(
            _tool_request("read_file", {"file_path": "missing.txt"}), _boom
        )

    events = _events(ev, run_id)
    tool_end = next(e for e in events if e["type"] == "tool_end")
    assert tool_end["status"] == "error"
    assert "missing.txt" in tool_end["error"]


@pytest.mark.asyncio
async def test_awrap_tool_call_records_start_and_end(tmp_path: Path) -> None:
    ev = EventWriter(tmp_path)
    mw = EventLoggerMiddleware(ev)
    mw.before_agent({"messages": []}, runtime=None)
    run_id = ev.current_run_id()

    async def _handler(_req: object) -> _FakeToolMessage:
        return _FakeToolMessage(content="ok")

    await mw.awrap_tool_call(_tool_request(), _handler)
    events = [e for e in _events(ev, run_id) if e["type"] != "run_start"]
    assert [e["type"] for e in events] == ["tool_start", "tool_end"]


# --- model calls (inner middleware) -----------------------------------


def test_inner_wrap_model_call_records_tokens_and_requested_tools(
    tmp_path: Path,
) -> None:
    ev = EventWriter(tmp_path)
    outer = EventLoggerMiddleware(ev)
    inner = EventLoggerInnerMiddleware(ev)
    outer.before_agent({"messages": []}, runtime=None)
    run_id = ev.current_run_id()

    ai_message = AIMessage(
        content="ok",
        tool_calls=[{"name": "read_file", "args": {}, "id": "1"}],
        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    )
    response = SimpleNamespace(result=[ai_message])
    inner.wrap_model_call(_model_request(), lambda _req: response)

    events = _events(ev, run_id)
    model_end = next(e for e in events if e["type"] == "model_end")
    assert model_end["attempt"] == 1
    assert model_end["data"]["input_tokens"] == 10
    assert model_end["data"]["output_tokens"] == 5
    assert model_end["data"]["requested_tools"] == ["read_file"]


def test_inner_wrap_model_call_records_error_and_reraises(tmp_path: Path) -> None:
    ev = EventWriter(tmp_path)
    outer = EventLoggerMiddleware(ev)
    inner = EventLoggerInnerMiddleware(ev)
    outer.before_agent({"messages": []}, runtime=None)
    run_id = ev.current_run_id()

    def _boom(_req: object) -> None:
        raise TimeoutError("model call timed out")

    with pytest.raises(TimeoutError):
        inner.wrap_model_call(_model_request(), _boom)

    events = _events(ev, run_id)
    assert events[-1]["type"] == "model_error"
    assert events[-1]["status"] == "error"  # 검토 R-A: report fail keys on this
    assert events[-1]["attempt"] == 1
    assert "timed out" in events[-1]["error"]


# --- T11-u: DC7's primary evidence — attempt-level retry logging ---------


def test_retry_logging_produces_one_pair_per_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A retried model call must log one `model_start`/`model_end` pair per attempt.

    `CodeModelRetryMiddleware` stacked *outside* `EventLoggerInnerMiddleware`
    must produce 3 such pairs for a call that fails twice with a retryable
    error before succeeding — this is DC7's primary evidence (검토 I1:
    401/404 are not retryable, so a TUI reproduction via a bad model
    name/key does not work; a real `httpx` transient error does, and this
    test simulates exactly that class).
    """
    from deepagents_code import model_retry

    monkeypatch.setattr(model_retry.time, "sleep", lambda *_a, **_kw: None)

    ev = EventWriter(tmp_path)
    outer = EventLoggerMiddleware(ev)
    inner = EventLoggerInnerMiddleware(ev)
    outer.before_agent({"messages": []}, runtime=None)
    run_id = ev.current_run_id()

    retry_mw = model_retry.CodeModelRetryMiddleware(max_retries=2)
    request = _model_request()
    calls = {"count": 0}

    def flaky_handler(_req: object) -> SimpleNamespace:
        calls["count"] += 1
        if calls["count"] < 3:
            raise TimeoutError("transient network failure")
        return SimpleNamespace(result=[AIMessage(content="ok")])

    def chained_handler(req: object) -> SimpleNamespace:
        return inner.wrap_model_call(req, flaky_handler)

    result = retry_mw.wrap_model_call(request, chained_handler)

    assert result.result[0].content == "ok"
    assert calls["count"] == 3

    events = _events(ev, run_id)
    starts = [e for e in events if e["type"] == "model_start"]
    ends = [e for e in events if e["type"] == "model_end"]
    errors = [e for e in events if e["type"] == "model_error"]
    assert [e["attempt"] for e in starts] == [1, 2, 3]
    assert [e["attempt"] for e in errors] == [1, 2]
    assert [e["attempt"] for e in ends] == [3]


# --- T3-u: logging failures never break the wrapped call -----------------


def test_logging_failure_is_swallowed_tool_call_still_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ev = EventWriter(tmp_path)
    mw = EventLoggerMiddleware(ev)
    mw.before_agent({"messages": []}, runtime=None)

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(EventWriter, "record", _raise)

    result = mw.wrap_tool_call(
        _tool_request(), lambda _req: _FakeToolMessage(content="ok")
    )
    assert isinstance(result, _FakeToolMessage)  # handler's result still returned


def test_logging_failure_is_swallowed_run_boundary_still_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A construction/record failure of any kind must not reach before/after_agent."""
    ev = EventWriter(tmp_path)
    mw = EventLoggerMiddleware(ev)

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("writer is broken")

    monkeypatch.setattr(EventWriter, "start_run", _raise)
    mw.before_agent({"messages": []}, runtime=None)  # must not raise
    mw.after_agent({"messages": []}, runtime=None)  # must not raise either


# --- D9: unwritable runs/ must not crash or hang the caller ---------------


def test_unwritable_runs_dir_does_not_crash_or_hang(tmp_path: Path) -> None:
    """An unwritable `runs/` must be absorbed on the background thread.

    Regression for S11: `mkdir` happens there, so this must never surface
    to the caller (T9/DC5).
    """
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(mode=0o500)  # read-only: the run subdirectory can't be created
    try:
        ev = EventWriter(runs_dir)
        mw = EventLoggerMiddleware(ev)
        mw.before_agent({"messages": []}, runtime=None)  # must not raise or hang
        run_id = ev.current_run_id()

        result = mw.wrap_tool_call(
            _tool_request(), lambda _req: _FakeToolMessage(content="ok")
        )
        assert isinstance(result, _FakeToolMessage)

        mw.after_agent({"messages": []}, runtime=None)  # must not raise or hang
        ev.flush()  # must return even though nothing could be written
        assert not (runs_dir / run_id / "events.jsonl").exists()
    finally:
        runs_dir.chmod(0o700)  # allow pytest to clean up tmp_path
