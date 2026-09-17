"""Event-logging middleware wired into dcode's agent (Step 2).

Two middleware classes share one `EventWriter` (constructor injection — D2b,
검토 I2):

- `EventLoggerMiddleware` — outer (`agent_middleware` front, D2). Owns the
  run boundary (`before_agent`/`after_agent`) and tool calls. Being outer
  means it also sees tool calls an inner middleware (e.g. Step 3's plan
  gate) blocks.
- `EventLoggerInnerMiddleware` — inner (`agent_middleware` end, D2b). Logs
  model calls *inside* `CodeModelRetryMiddleware`'s retry loop, so each
  retry attempt gets its own `model_start`/`model_end`/`model_error` instead
  of the outer middleware seeing one pair for the whole retried call (검토
  R2 — 4-3 requires a retry count, which the outer position cannot see).

Both resolve `thread_id` independently at the top of every hook and pass it
to every `EventWriter` call, so the two middleware (and repeated calls
within one) always agree on which run an event belongs to — see the
`EventWriter` docstring in `assistant/events.py` for why this replaced the
original `contextvars.ContextVar` design.

Fail-open (D4): every call into `EventWriter` is wrapped by `_safe()`, which
swallows any exception and logs it at debug level. A failure to write a log
line must never interrupt the wrapped model/tool/agent call — the logger is
an observer, not a gate.

Never write to stdout/stderr (D5) — this middleware runs inside the TUI.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    TracePolicy,
    omit_payload,
)

from assistant.events import (
    CODE_CHANGED,
    MODEL_END,
    MODEL_ERROR,
    MODEL_START,
    RUN_START,
    TOOL_END,
    TOOL_START,
    resolve_project_dir,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langchain.agents.middleware.types import (
        AgentState,
        ModelRequest,
        ModelResponse,
    )
    from langchain_core.messages import ToolMessage
    from langgraph.prebuilt.tool_node import ToolCallRequest
    from langgraph.runtime import Runtime
    from langgraph.types import Command

    from assistant.events import EventWriter

logger = logging.getLogger(__name__)

_WRITE_TOOL_NAMES = frozenset({"write_file", "edit_file", "execute"})
"""Tools whose successful `tool_end` also gets a derived `code_changed`
event (D7 addendum: the official 4-1 wording names "코드 변경" explicitly)."""


def _safe(action: Callable[[], None]) -> None:
    """Fail-open (D4): run `action`, swallow and log any exception."""
    try:
        action()
    except Exception:  # noqa: BLE001 - logging must never break the agent
        logger.debug("assistant.observability: swallowed logging failure", exc_info=True)


def thread_id_from_config() -> str | None:
    """Best-effort thread id lookup (§7 risk: base `before_agent` has no config).

    Confirmed present and identical across `before_agent`/`wrap_tool_call`/
    `after_agent` in a real headless run — see `EventWriter`'s docstring for
    why this, not a `ContextVar`, is the run-lookup key.
    """
    try:
        from langgraph.config import get_config

        configurable = get_config().get("configurable") or {}
        thread_id = configurable.get("thread_id")
        return thread_id if isinstance(thread_id, str) and thread_id else None
    except Exception:  # noqa: BLE001 - best-effort only, see D4
        return None


def _last_human_text(state: AgentState[Any]) -> str | None:
    """Return the most recent human message's text, if any."""
    from langchain_core.messages import HumanMessage

    messages = state.get("messages") or []
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            content = message.content
            return content if isinstance(content, str) else str(content)
    return None


def _model_name(request: ModelRequest[Any]) -> str | None:
    return getattr(request.model, "model", None) or type(request.model).__name__


def _response_ai_message(response: ModelResponse[Any]) -> Any | None:  # noqa: ANN401
    from langchain_core.messages import AIMessage

    for message in reversed(response.result):
        if isinstance(message, AIMessage):
            return message
    return None


def _tool_call_result_summary(result: object) -> dict[str, Any]:
    """Best-effort status/length summary for a tool call's return value.

    `handler()` for `wrap_tool_call` returns a `ToolMessage` or a `Command`
    (S3) — only the former carries a `status`/`content`.

    Most tool failures (e.g. `read_file` on a missing path) never raise —
    the tool returns a `ToolMessage(status="error", content="...")`
    instead, which is the success path as far as `wrap_tool_call` is
    concerned. A real TUI run showed this landing as `status="error"` with
    no `error` text at all (only `result_len`) — `report fail`/`show` could
    point at the failure but not say why. `content` *is* the reason in this
    case, so surface it the same way the `except` branch's `error=` does.
    """
    status = getattr(result, "status", "success")
    content = getattr(result, "content", None)
    summary: dict[str, Any] = {"status": status}
    if content is not None:
        content_str = content if isinstance(content, str) else str(content)
        summary["result_len"] = len(content_str)
        if status == "error":
            summary["error"] = content_str
    return summary


class EventLoggerMiddleware(AgentMiddleware):
    """Outer logger: run boundary and tool calls (D2).

    Installed **first** in `agent_middleware` so it sees tool calls that
    inner middleware (e.g. the Step 3 plan gate) blocks.
    """

    trace_policy = TracePolicy(process_inputs=omit_payload)
    """Never trace this middleware's own hook inputs — the redacted log file
    is the intended audit trail, not the LangSmith span payload."""

    def __init__(self, event_writer: EventWriter) -> None:
        """Args: event_writer: Shared writer, constructor-injected (D2b/I2)."""
        super().__init__()
        self._ev = event_writer

    # --- run boundary -------------------------------------------------

    def before_agent(self, state: AgentState[Any], runtime: Runtime[Any]) -> dict[str, Any] | None:
        """Start a new run, closing a previous one left open by an interrupt."""
        thread_id = thread_id_from_config()

        if self._ev.current_run_id(thread_id) is not None:
            # §7 risk: after_agent does not fire across a HITL interrupt.
            _safe(
                lambda: self._ev.close_run(
                    status="interrupted", extra={"reason": "next_run_started"}, thread_id=thread_id
                )
            )

        # 검토 P3 backstop: a model call that exhausted its retries without
        # succeeding never resets EventLoggerInnerMiddleware's attempt count
        # for this thread — the next turn always starts clean regardless.
        _safe(lambda: self._ev.reset_attempts(thread_id))

        _safe(lambda: self._ev.start_run(thread_id=thread_id))
        _safe(
            lambda: self._ev.record(
                RUN_START,
                thread_id=thread_id,
                data={
                    "user_input": _last_human_text(state),
                    "thread_id": thread_id,
                    "cwd": str(resolve_project_dir()),
                },
            )
        )
        return None

    def after_agent(self, state: AgentState[Any], runtime: Runtime[Any]) -> dict[str, Any] | None:  # noqa: ARG002
        """Close the run started by `before_agent`."""
        thread_id = thread_id_from_config()
        _safe(lambda: self._ev.close_run(status="ok", thread_id=thread_id))
        _safe(self._ev.flush)
        return None

    # --- tool calls -----------------------------------------------------

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        """Time and log one tool call (sync graph path)."""
        thread_id = thread_id_from_config()
        name = request.tool_call.get("name", "unknown")
        _safe(
            lambda: self._ev.record(
                TOOL_START, thread_id=thread_id, name=name, data={"args": request.tool_call.get("args", {})}
            )
        )
        start = time.monotonic()
        try:
            result = handler(request)
        except Exception as exc:
            _safe(
                lambda: self._ev.record(
                    TOOL_END,
                    thread_id=thread_id,
                    name=name,
                    status="error",
                    dur_ms=(time.monotonic() - start) * 1000,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            raise
        self._log_tool_end(thread_id, name, result, start)
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Time and log one tool call (async graph path — S4: the common one)."""
        thread_id = thread_id_from_config()
        name = request.tool_call.get("name", "unknown")
        _safe(
            lambda: self._ev.record(
                TOOL_START, thread_id=thread_id, name=name, data={"args": request.tool_call.get("args", {})}
            )
        )
        start = time.monotonic()
        try:
            result = await handler(request)
        except Exception as exc:
            _safe(
                lambda: self._ev.record(
                    TOOL_END,
                    thread_id=thread_id,
                    name=name,
                    status="error",
                    dur_ms=(time.monotonic() - start) * 1000,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            raise
        self._log_tool_end(thread_id, name, result, start)
        return result

    def _log_tool_end(self, thread_id: str | None, name: str, result: object, start: float) -> None:
        def _build() -> dict[str, Any]:
            summary = _tool_call_result_summary(result)
            return {
                "name": name,
                "status": summary["status"],
                "dur_ms": (time.monotonic() - start) * 1000,
                "error": summary.get("error"),
                "data": {"result_len": summary.get("result_len")},
            }

        def _write() -> None:
            kwargs = _build()
            self._ev.record(TOOL_END, thread_id=thread_id, **kwargs)
            if name in _WRITE_TOOL_NAMES and kwargs["status"] == "success":
                self._ev.record(CODE_CHANGED, thread_id=thread_id, name=name, data=kwargs["data"])

        _safe(_write)


class EventLoggerInnerMiddleware(AgentMiddleware):
    """Inner logger: per-attempt model calls (D2b, 검토 R2).

    Installed **last** in `agent_middleware`, i.e. inside
    `CodeModelRetryMiddleware`'s retry loop, so a retried model call produces
    one `model_start`/`model_end` (or `model_error`) pair *per attempt* with
    an `attempt` field — the outer middleware, being outside the retry loop,
    would only ever see the whole retried call as a single pair with no way
    to recover a retry count (4-3 requires one).
    """

    trace_policy = TracePolicy(process_inputs=omit_payload)

    def __init__(self, event_writer: EventWriter) -> None:
        """Args: event_writer: Same shared writer as `EventLoggerMiddleware`."""
        super().__init__()
        self._ev = event_writer

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        """Time and log one model-call *attempt* (sync graph path)."""
        thread_id = thread_id_from_config()
        attempt = self._ev.next_attempt(thread_id)
        _safe(
            lambda: self._ev.record(
                MODEL_START, thread_id=thread_id, name=_model_name(request), attempt=attempt
            )
        )
        start = time.monotonic()
        try:
            response = handler(request)
        except Exception as exc:
            _safe(
                lambda: self._ev.record(
                    MODEL_ERROR,
                    thread_id=thread_id,
                    status="error",
                    name=_model_name(request),
                    attempt=attempt,
                    dur_ms=(time.monotonic() - start) * 1000,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            raise
        self._ev.reset_attempts(thread_id)
        self._log_model_end(thread_id, request, response, start, attempt)
        return response

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        """Time and log one model-call *attempt* (async graph path — S4)."""
        thread_id = thread_id_from_config()
        attempt = self._ev.next_attempt(thread_id)
        _safe(
            lambda: self._ev.record(
                MODEL_START, thread_id=thread_id, name=_model_name(request), attempt=attempt
            )
        )
        start = time.monotonic()
        try:
            response = await handler(request)
        except Exception as exc:
            _safe(
                lambda: self._ev.record(
                    MODEL_ERROR,
                    thread_id=thread_id,
                    status="error",
                    name=_model_name(request),
                    attempt=attempt,
                    dur_ms=(time.monotonic() - start) * 1000,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            raise
        self._ev.reset_attempts(thread_id)
        self._log_model_end(thread_id, request, response, start, attempt)
        return response

    def _log_model_end(
        self,
        thread_id: str | None,
        request: ModelRequest[Any],
        response: ModelResponse[Any],
        start: float,
        attempt: int,
    ) -> None:
        def _build() -> dict[str, Any]:
            ai_message = _response_ai_message(response)
            usage = (
                getattr(ai_message, "usage_metadata", None) if ai_message is not None else None
            )
            tool_names = (
                [call.get("name") for call in ai_message.tool_calls]
                if ai_message is not None and getattr(ai_message, "tool_calls", None)
                else []
            )
            return {
                "name": _model_name(request),
                "status": "success",
                "attempt": attempt,
                "dur_ms": (time.monotonic() - start) * 1000,
                "data": {
                    "input_tokens": usage.get("input_tokens") if usage else None,
                    "output_tokens": usage.get("output_tokens") if usage else None,
                    "requested_tools": tool_names,
                },
            }

        _safe(lambda: self._ev.record(MODEL_END, thread_id=thread_id, **_build()))
