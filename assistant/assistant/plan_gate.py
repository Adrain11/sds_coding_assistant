"""Plan-gate middleware + CLI (Step 3 — see `docs/plan/STEP3_PLAN.md`).

**D1 — blocked by default.** Without an approved plan, `write_file`,
`edit_file`, `delete`, and `task` are rejected before `handler()` ever runs
(S17's pattern: return an error `ToolMessage` instead of calling `handler`).
`execute` (the shell) is rejected unconditionally, approved plan or not —
see D4 below.

**D3 — plan tools are middleware-provided, not filesystem-written.** Writing
a plan file with `write_file` would need `write_file` to already be open,
which is exactly what having no plan closes off. `PlanGateMiddleware`
exposes `create_plan`/`review_plan`/`revise_plan`/`get_plan_status` as
`self.tools` instead (the same pattern `AskUserMiddleware.tools[0]` uses —
confirmed present in this dcode build, `agent.py:3131`).

**D4 — no `approve` tool.** Approval only happens out-of-band, from
`python -m assistant.plan_gate approve <plan_id>`, run by a human in a
terminal the agent cannot reach (`execute` is blocked in every state). This
is what makes "the agent approves its own plan" structurally impossible,
not just discouraged — see the module-level design note under
`_announce_approved_if_new` for how `plan_approved` still ends up in the
*agent's own* run timeline despite `approve` running in a different process.

**D6 — fail-closed.** `_validate_tool_call` catches every exception from its
own scope-checking logic and turns it into a block, never a pass-through.
Contrast `assistant/observability.py`'s `_safe()`, which fails *open* — the
logger is an observer, this gate is a judge (8일차 22p).

**D7 — TCB.** `_TCB_PATH_PREFIXES` blocks writes/edits/deletes to the gate's
own code, the logger, the tests, and vendored `libs/` regardless of any
plan's `target_files` — a plan cannot authorize disabling the plan gate.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import AgentMiddleware, TracePolicy, omit_payload
from langchain_core.messages import ToolMessage as LCToolMessage
from langchain_core.tools import tool

from assistant.events import GATE_BLOCK, PLAN_APPROVED, PLAN_CREATED, PLAN_REVIEWED
from assistant.observability import thread_id_from_config
from assistant.plans import APPROVED, DRAFT, Plan, PlanError, PlanStore

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langchain_core.messages import ToolMessage
    from langgraph.prebuilt.tool_node import ToolCallRequest
    from langgraph.types import Command

    from assistant.events import EventWriter

logger = logging.getLogger(__name__)

# --- D1: tool classification --------------------------------------------

_GATED_WITH_SCOPE = frozenset({"write_file", "edit_file", "delete"})
"""Blocked without an approved plan; once approved, only inside `target_files`."""

_GATED_NO_SCOPE = frozenset({"task"})
"""Blocked without an approved plan with `allow_subagent: true` (검토 R2)."""

_ALWAYS_BLOCKED = frozenset({"execute"})
"""Never unblocked, approved plan or not (D4/검토 R4 — see module docstring)."""

_GATED_TOOLS = _GATED_WITH_SCOPE | _GATED_NO_SCOPE | _ALWAYS_BLOCKED

# --- D7: TCB — always blocked for write_file/edit_file/delete, even inside
# an approved plan's target_files (검토 R1 extends this to `delete` too). ---

_TCB_PATH_PREFIXES = (
    "assistant/assistant/plan_gate.py",
    "assistant/assistant/plans.py",
    "assistant/assistant/events.py",
    "assistant/assistant/observability.py",
    "tests/",
    ".deepagents/plans/",
    "libs/",
)


def _relative_to_project(path: str, project_root: Path) -> str:
    """Best-effort project-relative, forward-slashed form of `path`.

    Used only for TCB/scope string comparison — never for filesystem access,
    so a path outside `project_root` (which `.relative_to` rejects) falls
    back to its resolved absolute form instead of raising.
    """
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = project_root / candidate
    resolved = candidate.resolve()
    try:
        return resolved.relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _is_tcb_path(path: str, project_root: Path) -> bool:
    rel = _relative_to_project(path, project_root)
    return any(rel == prefix.rstrip("/") or rel.startswith(prefix) for prefix in _TCB_PATH_PREFIXES)


def _path_in_scope(path: str, target_files: list[str], project_root: Path) -> bool:
    rel = _relative_to_project(path, project_root)
    return any(rel == _relative_to_project(t, project_root) for t in target_files)


# --- reviewer model (D3's `review_plan`) --------------------------------


def _default_reviewer(plan: Plan) -> str:
    """Call a model to critique a draft plan; any failure propagates (fail-closed).

    Kept as a free function (not a method) so tests can monkeypatch it, or a
    caller can inject a different one via `PlanGateMiddleware(reviewer=...)`
    — mirrors this repo's constructor-injection convention for `EventWriter`
    (`docs/plan/STEP2_PLAN.md` §5 D2b/검토 I2).

    Uses `models.default` (dcode's own configured model) unless the
    `REVIEW_MODEL` env var names a different one — a cheaper/faster model
    keeps `review_plan` from doubling the cost of every plan (§7 risk).
    """
    from deepagents_code.config import create_model  # only this module imports dcode internals

    model_spec = os.environ.get("REVIEW_MODEL") or None
    result = create_model(model_spec, bind_preserved_thinking=False)
    prompt = (
        "당신은 소프트웨어 개발 계획을 검토하는 리뷰어입니다. 아래 계획을 비판적으로 검토하고, "
        "빠진 것 · 모호한 것 · 리스크를 3~5줄로 지적하세요. 특별한 문제가 없다면 그렇게 말하세요.\n\n"
        f"제목: {plan.title}\n"
        f"요구사항: {plan.requirements}\n"
        f"범위: {plan.scope}\n"
        f"완료조건: {plan.done_criteria}\n"
        f"대상 파일: {', '.join(plan.target_files)}\n"
        f"작업 순서: {'; '.join(plan.steps)}\n"
        f"테스트 방법: {plan.test_plan}\n"
    )
    response = result.model.invoke(prompt)
    content = getattr(response, "content", None)
    return content if isinstance(content, str) else str(content)


def _safe_record(ev: EventWriter, event_type: str, thread_id: str | None, *, name: str, data: dict[str, Any]) -> None:
    """Fail-open event logging (mirrors `observability._safe` — a failed log
    write must never itself become the reason a plan/gate action fails)."""
    try:
        ev.record(event_type, thread_id=thread_id, name=name, data=data)
    except Exception:  # noqa: BLE001
        logger.debug("assistant.plan_gate: swallowed logging failure", exc_info=True)


class PlanGateMiddleware(AgentMiddleware):
    """Blocks write/execute/delete/task tools without an approved plan (D1).

    Installed directly after `EventLoggerMiddleware` in `agent_middleware`
    (`docs/plan/STEP3_PLAN.md` §4 item 5) — being logged *by* the outer
    logger, not before it, is what lets a blocked call still show up in
    `report.py` as a `gate_block` (2-4's evidence needs the block itself on
    the record, not just its absence).
    """

    trace_policy = TracePolicy(process_inputs=omit_payload)

    def __init__(
        self,
        event_writer: EventWriter,
        *,
        project_root: Path | None = None,
        reviewer: Callable[[Plan], str] | None = None,
    ) -> None:
        super().__init__()
        self._ev = event_writer
        if project_root is None:
            from assistant.events import resolve_project_dir

            project_root = resolve_project_dir()
        self._project_root = project_root
        # `PlanStore.__init__` does one `mkdir(parents=True, exist_ok=True)`
        # here, at agent-construction time — the same place and pattern
        # dcode's own `ensure_project_skills_dir`/`ensure_user_skills_dir`
        # already use (`agent.py` skill-source assembly, same call site as
        # `EventWriter()`). If that were unsafe on this thread, dcode's own
        # skill wiring would already be broken; nothing here runs it again
        # per tool call (D9 — no `mkdir` in the request path).
        self._store = PlanStore(project_root)
        self._reviewer = reviewer if reviewer is not None else _default_reviewer
        self._gate_log = self._project_root / ".deepagents" / "plans" / "gate.log"
        self._announced_approved: set[tuple[str | None, str]] = set()
        self.tools = self._build_tools()

    # --- D3: plan tools --------------------------------------------------

    def _build_tools(self) -> list[Any]:
        store = self._store

        @tool
        def create_plan(
            title: str,
            requirements: str,
            scope: str,
            done_criteria: str,
            target_files: list[str],
            steps: list[str],
            test_plan: str,
            allow_subagent: bool = False,
        ) -> str:
            """Create a new development plan in `draft` status.

            All fields are required and must be concrete (a placeholder like
            "TODO" or a single-character answer is rejected) — this is how
            2-1/2-2 (requirements/scope/done-criteria, target files/steps/
            test plan) are enforced structurally rather than by instruction.

            Args:
                title: Short plan title.
                requirements: What must be true when this plan is done.
                scope: What this plan does and does not cover.
                done_criteria: How completion will be judged.
                target_files: Exact file paths this plan may change once
                    approved. Writes/edits/deletes outside this list are
                    blocked even after approval.
                steps: Ordered implementation steps.
                test_plan: How the change will be tested or verified.
                allow_subagent: Whether this plan may delegate work to a
                    subagent (`task`). Defaults to False (blocked).

            Returns:
                The new plan's id and the next step (`review_plan`), or a
                rejection message naming the invalid field.
            """
            try:
                plan = store.create(
                    title=title,
                    requirements=requirements,
                    scope=scope,
                    done_criteria=done_criteria,
                    target_files=target_files,
                    steps=steps,
                    test_plan=test_plan,
                    allow_subagent=allow_subagent,
                )
            except PlanError as exc:
                return f"계획 생성 거부됨: {exc}"
            _safe_record(
                self._ev,
                PLAN_CREATED,
                thread_id_from_config(),
                name=plan.title,
                data={"plan_id": plan.plan_id, "target_files": plan.target_files},
            )
            return (
                f"계획 생성됨 (plan_id={plan.plan_id}, 상태=draft).\n"
                f'다음: review_plan(plan_id="{plan.plan_id}")로 리뷰를 받으세요.'
            )

        @tool
        def review_plan(plan_id: str) -> str:
            """Get an AI critique of a draft plan; advances it to `reviewed`.

            Args:
                plan_id: The plan to review. Must currently be `draft`.

            Returns:
                The reviewer's critique on success. On any failure (wrong
                state, or the reviewer model call itself failing) the plan
                stays `draft` and a message explains why (D6 — fail-closed:
                a broken review never silently counts as a passed one).
            """
            try:
                plan = store.get(plan_id)
            except PlanError as exc:
                return f"리뷰 실패: {exc}"
            if plan.status != DRAFT:
                return f"리뷰 거부됨: draft 상태의 계획만 리뷰할 수 있습니다 (현재 상태: {plan.status})"
            try:
                note = self._reviewer(plan)
            except Exception as exc:  # noqa: BLE001 - fail-closed, see docstring
                logger.warning("assistant.plan_gate: reviewer model call failed", exc_info=True)
                return (
                    f"리뷰 실패 (모델 호출 오류: {type(exc).__name__}: {exc}). "
                    "계획은 draft 상태로 유지됩니다. 다시 시도하거나 사람에게 알리세요."
                )
            store.review(plan_id, note)
            _safe_record(
                self._ev,
                PLAN_REVIEWED,
                thread_id_from_config(),
                name=plan.title,
                data={"plan_id": plan.plan_id, "note": note},
            )
            return (
                f"리뷰 완료 (상태=reviewed):\n{note}\n\n"
                f"승인은 사람이 다음 명령으로 합니다:\n"
                f"python -m assistant.plan_gate approve {plan_id}"
            )

        @tool
        def revise_plan(
            plan_id: str,
            title: str | None = None,
            requirements: str | None = None,
            scope: str | None = None,
            done_criteria: str | None = None,
            target_files: list[str] | None = None,
            steps: list[str] | None = None,
            test_plan: str | None = None,
            allow_subagent: bool | None = None,
        ) -> str:
            """Revise a plan, applying the reviewer's feedback; returns it to `draft`.

            Args:
                plan_id: The plan to revise.
                title: New title, or omit to leave unchanged.
                requirements: New requirements, or omit to leave unchanged.
                scope: New scope, or omit to leave unchanged.
                done_criteria: New completion criteria, or omit to leave unchanged.
                target_files: New target file list, or omit to leave unchanged.
                steps: New step list, or omit to leave unchanged.
                test_plan: New test plan, or omit to leave unchanged.
                allow_subagent: New subagent-delegation flag, or omit to leave unchanged.

            Returns:
                Confirmation, or a rejection if the plan is already `approved`
                (an approved plan cannot be widened by editing it in place).
            """
            updates = {
                "title": title,
                "requirements": requirements,
                "scope": scope,
                "done_criteria": done_criteria,
                "target_files": target_files,
                "steps": steps,
                "test_plan": test_plan,
                "allow_subagent": allow_subagent,
            }
            try:
                store.revise(plan_id, **updates)
            except PlanError as exc:
                return f"수정 거부됨: {exc}"
            return f"계획 수정됨 (plan_id={plan_id}, 상태=draft). review_plan으로 다시 리뷰받으세요."

        @tool
        def get_plan_status(plan_id: str) -> str:
            """Get a plan's current status, target files, and review note.

            Args:
                plan_id: The plan to inspect.
            """
            try:
                plan = store.get(plan_id)
            except PlanError as exc:
                return f"조회 실패: {exc}"
            lines = [
                f"plan_id={plan.plan_id} 상태={plan.status}",
                f"target_files={plan.target_files}",
                f"allow_subagent={plan.allow_subagent}",
            ]
            if plan.review_note:
                lines.append(f"review_note={plan.review_note}")
            return "\n".join(lines)

        return [create_plan, review_plan, revise_plan, get_plan_status]

    # --- D1/D6: the gate itself -------------------------------------------

    def _approved_plans(self) -> list[Plan]:
        plans: list[Plan] = []
        for plan_id in self._store.list_ids():
            try:
                plan = self._store.get(plan_id)
            except PlanError:
                # D6: a corrupted plan file simply does not count as an
                # approval — fails closed without crashing the gate.
                continue
            if plan.status == APPROVED:
                plans.append(plan)
        return plans

    def _announce_approved_if_new(self, plan: Plan) -> None:
        """Emit `plan_approved` into the *current run's* timeline (EC9).

        `approve` itself runs in a separate CLI process (D4) that has no
        handle on the live run the agent process is writing to, so it
        cannot record this event directly. Instead, the agent process
        records it itself, the first time it notices (by re-reading the
        plan file) that this plan is approved — naturally landing right
        before the write/edit/delete it just authorized, which is exactly
        the `plan_approved` → `code_changed` order EC9 asks for.

        Keyed by `(thread_id, plan_id)`, not just `plan_id`: this
        middleware instance is long-lived across an entire server process,
        and a second, later run in the same process must still get its own
        `plan_approved` entry in *its* `events.jsonl`.
        """
        thread_id = thread_id_from_config()
        key = (thread_id, plan.plan_id)
        if key in self._announced_approved:
            return
        self._announced_approved.add(key)
        _safe_record(
            self._ev,
            PLAN_APPROVED,
            thread_id,
            name=plan.title,
            data={"plan_id": plan.plan_id, "target_files": plan.target_files},
        )

    def _check(self, name: str, args: dict[str, Any]) -> str | None:
        """Return a block reason, or `None` to let the call through."""
        if name in _ALWAYS_BLOCKED:
            return "execute(셸)는 승인 후에도 항상 차단됩니다 — 셸이 열리면 사람만 할 수 있는 승인을 에이전트가 대신할 수 있게 됩니다 (D4)."

        if name in _GATED_NO_SCOPE:  # "task"
            approved = self._approved_plans()
            for plan in approved:
                if plan.allow_subagent:
                    self._announce_approved_if_new(plan)
                    return None
            if approved:
                return "서브에이전트(task) 위임은 allow_subagent=true로 승인된 계획이 있어야 합니다 (현재 승인된 계획에는 없음)."
            return "승인된 계획이 없어 서브에이전트(task)를 막습니다."

        if name in _GATED_WITH_SCOPE:  # write_file / edit_file / delete
            path = args.get("file_path")
            if not isinstance(path, str) or not path:
                return "file_path 인자를 확인할 수 없어 차단합니다 (fail-closed)."
            if _is_tcb_path(path, self._project_root):
                return f"'{path}'는 게이트·로거·테스트·원본 코드(TCB)라 승인된 계획 안에 있어도 고치거나 지울 수 없습니다."

            approved = self._approved_plans()
            matching = [p for p in approved if _path_in_scope(path, p.target_files, self._project_root)]
            if matching:
                for plan in matching:
                    self._announce_approved_if_new(plan)
                return None
            if approved:
                for plan in approved:
                    self._store.revert_to_draft(plan.plan_id, reason=f"'{path}' 수정 시도가 target_files 범위 밖")
                return (
                    f"'{path}'는 승인된 계획의 target_files 범위 밖입니다. "
                    "계획이 draft로 되돌아갔습니다 — 재검토(review_plan)와 재승인이 필요합니다."
                )
            return "승인된 계획이 없습니다."

        return None  # not a gated tool name

    def _validate_tool_call(self, request: ToolCallRequest) -> ToolMessage | None:
        name = request.tool_call.get("name", "")
        if name not in _GATED_TOOLS:
            return None
        args = request.tool_call.get("args") or {}
        try:
            reason = self._check(name, args)
        except Exception as exc:  # noqa: BLE001 - D6: any internal error blocks, never passes
            logger.warning("assistant.plan_gate: gate check raised; blocking (fail-closed)", exc_info=True)
            reason = f"게이트 내부 오류로 차단됨(fail-closed): {type(exc).__name__}: {exc}"
        if reason is None:
            return None
        return self._block(request, name, reason)

    def _block(self, request: ToolCallRequest, name: str, reason: str) -> ToolMessage:
        try:
            self._append_gate_log(name, reason)
        except Exception:  # noqa: BLE001
            logger.debug("assistant.plan_gate: gate.log write failed", exc_info=True)
        _safe_record(
            self._ev,
            GATE_BLOCK,
            thread_id_from_config(),
            name=name,
            data={"status": "error", "reason": reason, "args": request.tool_call.get("args", {})},
        )
        message = (
            f"계획 게이트: {name}이(가) 차단되었습니다.\n"
            f"사유: {reason}\n"
            "다음: create_plan(...)으로 계획을 만들고 review_plan(...)으로 리뷰를 받으세요.\n"
            "      승인은 사람이 다음 명령으로 합니다:\n"
            "      python -m assistant.plan_gate approve <plan_id>"
        )
        return LCToolMessage(content=message, name=name, tool_call_id=request.tool_call["id"], status="error")

    def _append_gate_log(self, name: str, reason: str) -> None:
        """Audit line independent of `EventWriter` (D6 — 검토's "차단 사건은
        로거가 죽어도 남아야 한다"). No `mkdir` here (D9): the directory was
        already created once in `PlanStore.__init__`."""
        line = f"{_dt.datetime.now().isoformat(timespec='seconds')} BLOCK {name}: {reason}\n"
        with self._gate_log.open("a", encoding="utf-8") as f:
            f.write(line)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        if (rejection := self._validate_tool_call(request)) is not None:
            return rejection
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        if (rejection := self._validate_tool_call(request)) is not None:
            return rejection
        return await handler(request)


# --- CLI (D4 — the only place a plan can be approved) -------------------


def _print_plan(plan: Plan) -> None:
    print(f"plan_id: {plan.plan_id}")
    print(f"상태: {plan.status}")
    print(f"제목: {plan.title}")
    print(f"요구사항: {plan.requirements}")
    print(f"범위: {plan.scope}")
    print(f"완료조건: {plan.done_criteria}")
    print(f"대상 파일: {plan.target_files}")
    print(f"작업 순서: {plan.steps}")
    print(f"테스트 방법: {plan.test_plan}")
    print(f"서브에이전트 허용: {plan.allow_subagent}")
    if plan.review_note:
        print(f"리뷰 노트: {plan.review_note}")


def cmd_list(store: PlanStore) -> int:
    ids = store.list_ids()
    if not ids:
        print("(no plans yet)")
        return 0
    for plan_id in ids:
        try:
            plan = store.get(plan_id)
        except PlanError as exc:
            print(f"{plan_id}  <손상됨: {exc}>")
            continue
        print(f"{plan.plan_id}  {plan.status:<10} {plan.title}")
    return 0


def cmd_show(store: PlanStore, plan_id: str) -> int:
    try:
        plan = store.get(plan_id)
    except PlanError as exc:
        print(f"오류: {exc}")
        return 1
    _print_plan(plan)
    return 0


def cmd_approve(store: PlanStore, plan_id: str) -> int:
    try:
        plan = store.approve(plan_id)
    except PlanError as exc:
        print(f"승인 거부됨: {exc}")
        return 1
    print(f"계획 {plan.plan_id} 승인됨 (상태={plan.status}).")
    print(f"대상 파일: {plan.target_files}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m assistant.plan_gate")
    parser.add_argument(
        "--project-root", type=Path, default=None, help="Defaults to the project root"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List all plans and their status")
    show_parser = sub.add_parser("show", help="Show one plan's full content")
    show_parser.add_argument("plan_id")
    approve_parser = sub.add_parser("approve", help="Approve a reviewed plan (human only — D4)")
    approve_parser.add_argument("plan_id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.project_root is not None:
        project_root = args.project_root
    else:
        from assistant.events import resolve_project_dir

        project_root = resolve_project_dir()
    store = PlanStore(project_root)

    if args.command == "list":
        return cmd_list(store)
    if args.command == "show":
        return cmd_show(store, args.plan_id)
    if args.command == "approve":
        return cmd_approve(store, args.plan_id)
    return 1  # argparse's required=True makes this unreachable


if __name__ == "__main__":
    sys.exit(main())
