"""Unit tests for `assistant.observability.EventLoggerMiddleware`.

Not listed as its own row in STEP2_PLAN.md §4 (the table only lists
`tests/test_events.py` and `tests/test_report.py`), but §6 requires T3-u
(fail-open on a logging failure) as a unit test, and observability.py
(task 7) is what that test targets. Added here rather than skipped.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from assistant.events import EventWriter, iter_events
from assistant.observability import EventLoggerMiddleware


class _FakeToolMessage:
    def __init__(self, status: str = "success", content: str = "ok") -> None:
        self.status = status
        self.content = content


def _tool_request(name: str = "read_file", args: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(tool_call={"name": name, "args": args or {}, "id": "call-1"})


def _model_request(model_name: str = "test-model") -> SimpleNamespace:
    return SimpleNamespace(model=SimpleNamespace(model=model_name))


def _events(writer: EventWriter) -> list[dict]:
    """Flush the writer's background thread, then read what it wrote.

    D9 made `EventWriter` write on a background thread, so a test must wait
    for the queue to drain before reading the file — otherwise it races the
    writer thread and reads a partial (or missing) file.
    """
    writer.flush()
    return list(iter_events(writer.path))


# --- run boundary --------------------------------------------------------


def test_before_after_agent_write_run_start_and_end(tmp_path: Path) -> None:
    mw = EventLoggerMiddleware(runs_dir=tmp_path)
    state = {"messages": [HumanMessage(content="read the readme")]}
    mw.before_agent(state, runtime=None)
    writer = mw._writer  # noqa: SLF001 - test needs the writer before after_agent clears it
    mw.after_agent(state, runtime=None)

    events = _events(writer)
    types = [e["type"] for e in events]
    assert types == ["run_start", "run_end"]
    assert events[0]["data"]["user_input"] == "read the readme"
    assert events[1]["status"] == "ok"
    assert "dur_ms" in events[1]


def test_before_agent_closes_previous_run_as_interrupted(tmp_path: Path) -> None:
    mw = EventLoggerMiddleware(runs_dir=tmp_path)
    state = {"messages": []}
    mw.before_agent(state, runtime=None)
    first_writer = mw._writer  # noqa: SLF001

    mw.before_agent(state, runtime=None)  # no after_agent in between (HITL interrupt)

    events = _events(first_writer)
    assert events[-1]["type"] == "run_end"
    assert events[-1]["status"] == "interrupted"


# --- tool calls ------------------------------------------------------


def test_wrap_tool_call_records_start_and_end(tmp_path: Path) -> None:
    mw = EventLoggerMiddleware(runs_dir=tmp_path)
    mw.before_agent({"messages": []}, runtime=None)

    request = _tool_request("read_file", {"file_path": "README.md"})
    result = mw.wrap_tool_call(request, lambda _req: _FakeToolMessage(content="file contents"))

    assert isinstance(result, _FakeToolMessage)
    events = _events(mw._writer)  # noqa: SLF001
    tool_events = [e for e in events if e["type"] in ("tool_start", "tool_end")]
    assert [e["type"] for e in tool_events] == ["tool_start", "tool_end"]
    assert tool_events[1]["status"] == "success"
    assert tool_events[1]["data"]["result_len"] == len("file contents")


def test_wrap_tool_call_records_error_and_reraises(tmp_path: Path) -> None:
    mw = EventLoggerMiddleware(runs_dir=tmp_path)
    mw.before_agent({"messages": []}, runtime=None)

    def _boom(_req: object) -> None:
        raise FileNotFoundError("no such file: missing.txt")

    with pytest.raises(FileNotFoundError):
        mw.wrap_tool_call(_tool_request("read_file", {"file_path": "missing.txt"}), _boom)

    events = _events(mw._writer)  # noqa: SLF001
    tool_end = next(e for e in events if e["type"] == "tool_end")
    assert tool_end["status"] == "error"
    assert "missing.txt" in tool_end["error"]


@pytest.mark.asyncio
async def test_awrap_tool_call_records_start_and_end(tmp_path: Path) -> None:
    mw = EventLoggerMiddleware(runs_dir=tmp_path)
    mw.before_agent({"messages": []}, runtime=None)

    async def _handler(_req: object) -> _FakeToolMessage:
        return _FakeToolMessage(content="ok")

    await mw.awrap_tool_call(_tool_request(), _handler)
    events = _events(mw._writer)  # noqa: SLF001
    assert [e["type"] for e in events if e["type"].startswith("tool_")] == [
        "tool_start",
        "tool_end",
    ]


# --- model calls -----------------------------------------------------


def test_wrap_model_call_records_tokens_and_requested_tools(tmp_path: Path) -> None:
    mw = EventLoggerMiddleware(runs_dir=tmp_path)
    mw.before_agent({"messages": []}, runtime=None)

    ai_message = AIMessage(
        content="ok",
        tool_calls=[{"name": "read_file", "args": {}, "id": "1"}],
        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    )
    response = SimpleNamespace(result=[ai_message])
    mw.wrap_model_call(_model_request(), lambda _req: response)

    events = _events(mw._writer)  # noqa: SLF001
    model_end = next(e for e in events if e["type"] == "model_end")
    assert model_end["data"]["input_tokens"] == 10
    assert model_end["data"]["output_tokens"] == 5
    assert model_end["data"]["requested_tools"] == ["read_file"]


def test_wrap_model_call_records_error_and_reraises(tmp_path: Path) -> None:
    mw = EventLoggerMiddleware(runs_dir=tmp_path)
    mw.before_agent({"messages": []}, runtime=None)

    def _boom(_req: object) -> None:
        raise TimeoutError("model call timed out")

    with pytest.raises(TimeoutError):
        mw.wrap_model_call(_model_request(), _boom)

    events = _events(mw._writer)  # noqa: SLF001
    assert events[-1]["type"] == "model_error"
    assert "timed out" in events[-1]["error"]


# --- T3-u: logging failures never break the wrapped call -----------------


def test_logging_failure_is_swallowed_tool_call_still_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mw = EventLoggerMiddleware(runs_dir=tmp_path)
    mw.before_agent({"messages": []}, runtime=None)

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(EventWriter, "record", _raise)

    result = mw.wrap_tool_call(_tool_request(), lambda _req: _FakeToolMessage(content="ok"))
    assert isinstance(result, _FakeToolMessage)  # handler's result still returned


def test_logging_failure_is_swallowed_run_boundary_still_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Generic construction failure (any reason) must not reach before/after_agent."""
    monkeypatch.setattr(
        EventWriter,
        "__init__",
        lambda self, *a, **kw: (_ for _ in ()).throw(RuntimeError("could not start writer")),
    )
    mw = EventLoggerMiddleware(runs_dir=tmp_path)
    mw.before_agent({"messages": []}, runtime=None)  # must not raise
    mw.after_agent({"messages": []}, runtime=None)  # must not raise either


# --- D9: unwritable runs/ must not crash or hang the caller ---------------


def test_unwritable_runs_dir_does_not_crash_or_hang(tmp_path: Path) -> None:
    """Regression for S11: `mkdir` now happens on the background thread, so an
    unwritable `runs/` must be absorbed there (T9/DC5), not on the caller.
    """
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(mode=0o500)  # read-only: the run subdirectory can't be created
    try:
        mw = EventLoggerMiddleware(runs_dir=runs_dir)
        mw.before_agent({"messages": []}, runtime=None)  # must not raise or hang
        writer = mw._writer  # noqa: SLF001

        result = mw.wrap_tool_call(_tool_request(), lambda _req: _FakeToolMessage(content="ok"))
        assert isinstance(result, _FakeToolMessage)

        mw.after_agent({"messages": []}, runtime=None)  # must not raise or hang
        writer.flush()  # must return even though nothing could be written
        assert not writer.path.exists()
    finally:
        runs_dir.chmod(0o700)  # allow pytest to clean up tmp_path
