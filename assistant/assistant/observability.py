"""Event-logging middleware wired into dcode's agent (Step 2).

`EventLoggerMiddleware` is the only piece of `assistant/` that dcode's own
graph calls directly. It implements all 6 hooks required by D3
(`docs/plan/STEP2_PLAN.md` §5): `before_agent`, `wrap_model_call` +
`awrap_model_call`, `wrap_tool_call` + `awrap_tool_call`, and `after_agent`.

Fail-open (D4): every call into `EventWriter` is wrapped by `_safe()`, which
swallows any exception and logs it at debug level. A failure to write a log
line must never interrupt the wrapped model/tool/agent call — the logger is
an observer, not a gate.

Never write to stdout/stderr (D5) — this middleware runs inside the TUI.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    TracePolicy,
    omit_payload,
)

from assistant.events import (
    MODEL_END,
    MODEL_ERROR,
    MODEL_START,
    RUN_END,
    RUN_START,
    TOOL_END,
    TOOL_START,
    EventWriter,
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

logger = logging.getLogger(__name__)


def _thread_id_from_config() -> str | None:
    """Best-effort thread id lookup (§7 risk: base `before_agent` has no config).

    Returns:
        The ambient thread id, or `None` if it cannot be determined — the
        caller falls back to a random run-id suffix rather than failing.
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
    """
    status = getattr(result, "status", "success")
    content = getattr(result, "content", None)
    summary: dict[str, Any] = {"status": status}
    if content is not None:
        summary["result_len"] = len(content) if isinstance(content, str) else len(str(content))
    return summary


class EventLoggerMiddleware(AgentMiddleware):
    """Appends a JSONL trail of one run's model/tool activity to `runs/`.

    Installed **first** in `agent_middleware` (D2) so it sees tool calls that
    inner middleware (e.g. the Step 3 plan gate) blocks. One instance tracks
    at most one open run at a time, matching dcode's single active
    conversation turn per agent instance.
    """

    trace_policy = TracePolicy(process_inputs=omit_payload)
    """Never trace this middleware's own hook inputs — the redacted log file
    is the intended audit trail, not the LangSmith span payload."""

    def __init__(self, runs_dir: Path | None = None) -> None:
        """Create the middleware.

        Args:
            runs_dir: Where to write `<run_id>/events.jsonl` under. Defaults
                to `./runs` (the CLI runs from the repo root — see F2 in
                `docs/plan/STEP2_PLAN.md`).
        """
        super().__init__()
        self._runs_dir = runs_dir if runs_dir is not None else Path.cwd() / "runs"
        self._writer: EventWriter | None = None
        self._run_started_at: float = 0.0
        self._event_count = 0
        self._error_count = 0

    # --- fail-open plumbing (D4) -----------------------------------------

    def _safe(self, action: Callable[[], None]) -> None:
        try:
            action()
        except Exception:  # noqa: BLE001 - logging must never break the agent
            logger.debug("EventLoggerMiddleware: swallowed logging failure", exc_info=True)

    def _record(self, event_type: str, **kwargs: Any) -> None:  # noqa: ANN401
        """Record with already-safe-to-evaluate kwargs (no I/O, unlikely to raise)."""
        self._record_lazy(event_type, lambda: kwargs)

    def _record_lazy(self, event_type: str, build: Callable[[], dict[str, Any]]) -> None:
        """Record with a kwargs builder evaluated *inside* the fail-open guard.

        Use this whenever building the payload does more than reference
        already-known values — e.g. reading `state`, calling `Path.cwd()`, or
        inspecting a handler's result. Evaluating those eagerly as plain call
        arguments would run them *outside* `_safe()`'s try/except, defeating
        D4 (this was a real bug: `Path.cwd()`/`state` inspection in
        `before_agent` could raise and escape uncaught before D9's fix).
        """
        writer = self._writer
        if writer is None:
            return

        def _write() -> None:
            kwargs = build()
            writer.record(event_type, **kwargs)
            self._event_count += 1
            if kwargs.get("status") == "error":
                self._error_count += 1

        self._safe(_write)

    # --- run boundary: before_agent / after_agent ------------------------

    def before_agent(self, state: AgentState[Any], runtime: Runtime[Any]) -> dict[str, Any] | None:
        """Start a new run, closing a previous one left open by an interrupt."""
        if self._writer is not None:
            # §7 risk: after_agent does not fire across a HITL interrupt.
            self._record(RUN_END, status="interrupted", data={"reason": "next_run_started"})

        thread_id = _thread_id_from_config()

        def _start() -> None:
            self._writer = EventWriter(self._runs_dir, thread_id=thread_id)
            self._run_started_at = time.monotonic()
            self._event_count = 0
            self._error_count = 0

        self._safe(_start)
        self._record_lazy(
            RUN_START,
            lambda: {
                "data": {
                    "user_input": _last_human_text(state),
                    "thread_id": thread_id,
                    "cwd": str(Path.cwd()),
                }
            },
        )
        return None

    def after_agent(self, state: AgentState[Any], runtime: Runtime[Any]) -> dict[str, Any] | None:  # noqa: ARG002
        """Close the run started by `before_agent`."""
        dur_ms = (time.monotonic() - self._run_started_at) * 1000
        writer = self._writer
        self._record(
            RUN_END,
            status="ok",
            dur_ms=dur_ms,
            data={"event_count": self._event_count, "error_count": self._error_count},
        )
        # A headless one-shot run (`dcode -n`) was observed to exit the whole
        # process within microseconds of after_agent returning — before the
        # writer thread ever got scheduled — losing every event for the run.
        # `Queue.join()` blocks on `threading.Lock.acquire`, which dcode's
        # Blockbuster guard explicitly exempts (S11), so this is safe to call
        # from the event loop thread. Bounded by D9's worker idle timeout.
        if writer is not None:
            self._safe(writer.flush)
        self._writer = None
        return None

    # --- model calls -------------------------------------------------------

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        """Time and log one model call (sync graph path)."""
        self._record(MODEL_START, name=_model_name(request))
        start = time.monotonic()
        try:
            response = handler(request)
        except Exception as exc:
            self._record(
                MODEL_ERROR,
                name=_model_name(request),
                dur_ms=(time.monotonic() - start) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        self._log_model_end(request, response, start)
        return response

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        """Time and log one model call (async graph path — S4: the common one)."""
        self._record(MODEL_START, name=_model_name(request))
        start = time.monotonic()
        try:
            response = await handler(request)
        except Exception as exc:
            self._record(
                MODEL_ERROR,
                name=_model_name(request),
                dur_ms=(time.monotonic() - start) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        self._log_model_end(request, response, start)
        return response

    def _log_model_end(
        self, request: ModelRequest[Any], response: ModelResponse[Any], start: float
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
                "dur_ms": (time.monotonic() - start) * 1000,
                "data": {
                    "input_tokens": usage.get("input_tokens") if usage else None,
                    "output_tokens": usage.get("output_tokens") if usage else None,
                    "requested_tools": tool_names,
                },
            }

        self._record_lazy(MODEL_END, _build)

    # --- tool calls -----------------------------------------------------

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        """Time and log one tool call (sync graph path)."""
        name = request.tool_call.get("name", "unknown")
        self._record(TOOL_START, name=name, data={"args": request.tool_call.get("args", {})})
        start = time.monotonic()
        try:
            result = handler(request)
        except Exception as exc:
            self._record(
                TOOL_END,
                name=name,
                status="error",
                dur_ms=(time.monotonic() - start) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        self._log_tool_end(name, result, start)
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Time and log one tool call (async graph path — S4: the common one)."""
        name = request.tool_call.get("name", "unknown")
        self._record(TOOL_START, name=name, data={"args": request.tool_call.get("args", {})})
        start = time.monotonic()
        try:
            result = await handler(request)
        except Exception as exc:
            self._record(
                TOOL_END,
                name=name,
                status="error",
                dur_ms=(time.monotonic() - start) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        self._log_tool_end(name, result, start)
        return result

    def _log_tool_end(self, name: str, result: object, start: float) -> None:
        def _build() -> dict[str, Any]:
            summary = _tool_call_result_summary(result)
            return {
                "name": name,
                "status": summary["status"],
                "dur_ms": (time.monotonic() - start) * 1000,
                "data": {"result_len": summary.get("result_len")},
            }

        self._record_lazy(TOOL_END, _build)
