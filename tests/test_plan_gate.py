"""Unit tests for `assistant.plan_gate` — the blocking gate (§6 U1-U13).

8일차 43p's warning drives the shape of these tests: passing output is not
enough evidence that a blocked call was actually blocked. Every "blocked"
case here asserts the mock `handler` was called **zero** times, not just
that the returned message looks like a rejection.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage

from assistant.events import EventWriter
from assistant.plan_gate import PlanGateMiddleware
from assistant.plans import PlanStore

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _request(name: str, args: dict | None = None, call_id: str = "call_1"):
    from langgraph.prebuilt.tool_node import ToolCallRequest

    return ToolCallRequest(
        tool_call={"name": name, "args": args or {}, "id": call_id},
        tool=None,
        state=None,
        runtime=None,
    )


def _ok_handler():
    return MagicMock(return_value=ToolMessage(content="ok", name="x", tool_call_id="call_1"))


def _fake_reviewer(plan):
    return f"검토 의견: {plan.title} 계획은 괜찮아 보입니다."


@pytest.fixture
def gate(tmp_path):
    ev = EventWriter(runs_dir=tmp_path / "runs")
    mw = PlanGateMiddleware(ev, project_root=tmp_path, reviewer=_fake_reviewer)
    yield mw
    ev.flush()


def _approve_plan(gate: PlanGateMiddleware, target_files: list[str], *, allow_subagent: bool = False) -> str:
    """Drive a plan through create -> review -> approve via the store the
    gate itself uses, so the gate's next `_approved_plans()` scan sees it."""
    store: PlanStore = gate._store  # noqa: SLF001 - test-only reach-in
    plan = store.create(
        title="테스트 계획입니다 충분히 길게",
        requirements="요구사항도 충분히 길게 적습니다",
        scope="범위도 충분히 길게 적습니다",
        done_criteria="완료조건도 충분히 길게 적습니다",
        target_files=target_files,
        steps=["첫 단계", "둘째 단계"],
        test_plan="pytest로 확인합니다 충분히 길게",
        allow_subagent=allow_subagent,
    )
    store.review(plan.plan_id, "note")
    store.approve(plan.plan_id)
    return plan.plan_id


class TestNoApprovedPlan:
    def test_u1_write_file_blocked(self, gate):
        handler = _ok_handler()
        result = gate.wrap_tool_call(_request("write_file", {"file_path": "hello.py"}), handler)
        handler.assert_not_called()
        assert result.status == "error"

    def test_u2_execute_blocked(self, gate):
        handler = _ok_handler()
        result = gate.wrap_tool_call(_request("execute", {"command": "touch hello.py"}), handler)
        handler.assert_not_called()
        assert result.status == "error"

    def test_u11_delete_blocked(self, gate):
        handler = _ok_handler()
        result = gate.wrap_tool_call(_request("delete", {"file_path": "hello.py"}), handler)
        handler.assert_not_called()
        assert result.status == "error"

    def test_u12_task_blocked(self, gate):
        handler = _ok_handler()
        result = gate.wrap_tool_call(_request("task", {"description": "make a file"}), handler)
        handler.assert_not_called()
        assert result.status == "error"

    def test_read_tools_pass_through(self, gate):
        """Read tools are never gated — sanity check the allowlist-by-name design."""
        handler = _ok_handler()
        gate.wrap_tool_call(_request("read_file", {"file_path": "README.md"}), handler)
        handler.assert_called_once()


class TestApprovedInScope:
    def test_u3_write_inside_target_files_allowed(self, gate, tmp_path):
        _approve_plan(gate, target_files=["hello.py"])
        handler = _ok_handler()
        gate.wrap_tool_call(_request("write_file", {"file_path": str(tmp_path / "hello.py")}), handler)
        handler.assert_called_once()

    def test_u12_task_allowed_with_allow_subagent(self, gate):
        _approve_plan(gate, target_files=["hello.py"], allow_subagent=True)
        handler = _ok_handler()
        gate.wrap_tool_call(_request("task", {"description": "make a file"}), handler)
        handler.assert_called_once()

    def test_u13_execute_still_blocked_after_approval(self, gate):
        """D4/검토 R4: shell never opens, approved plan or not."""
        _approve_plan(gate, target_files=["hello.py"])
        handler = _ok_handler()
        result = gate.wrap_tool_call(_request("execute", {"command": "echo hi"}), handler)
        handler.assert_not_called()
        assert result.status == "error"


class TestApprovedOutOfScope:
    def test_u4_write_outside_target_files_blocked_and_reverted(self, gate, tmp_path):
        plan_id = _approve_plan(gate, target_files=["hello.py"])
        handler = _ok_handler()
        result = gate.wrap_tool_call(
            _request("write_file", {"file_path": str(tmp_path / "other.py")}), handler
        )
        handler.assert_not_called()
        assert result.status == "error"
        assert gate._store.get(plan_id).status == "draft"  # noqa: SLF001


class TestTCB:
    @pytest.mark.parametrize("tool_name", ["write_file", "edit_file", "delete"])
    def test_u7_tcb_blocked_even_when_in_scope(self, gate, tmp_path, tool_name):
        tcb_path = str(tmp_path / "assistant" / "assistant" / "plan_gate.py")
        _approve_plan(gate, target_files=[tcb_path])
        handler = _ok_handler()
        result = gate.wrap_tool_call(_request(tool_name, {"file_path": tcb_path}), handler)
        handler.assert_not_called()
        assert result.status == "error"

    def test_u7b_tcb_delete_blocked_without_plan(self, gate, tmp_path):
        tcb_path = str(tmp_path / "tests" / "test_plan_gate.py")
        handler = _ok_handler()
        result = gate.wrap_tool_call(_request("delete", {"file_path": tcb_path}), handler)
        handler.assert_not_called()
        assert result.status == "error"

    def test_libs_is_tcb(self, gate, tmp_path):
        libs_path = str(tmp_path / "libs" / "code" / "deepagents_code" / "agent.py")
        _approve_plan(gate, target_files=[libs_path])
        handler = _ok_handler()
        result = gate.wrap_tool_call(_request("edit_file", {"file_path": libs_path}), handler)
        handler.assert_not_called()
        assert result.status == "error"


class TestFailClosed:
    def test_u8_corrupted_plan_file_does_not_grant_approval(self, gate, tmp_path):
        plan_id = _approve_plan(gate, target_files=["hello.py"])
        plan_path = tmp_path / ".deepagents" / "plans" / f"{plan_id}.json"
        plan_path.write_text("{not valid json", encoding="utf-8")
        handler = _ok_handler()
        result = gate.wrap_tool_call(_request("write_file", {"file_path": str(tmp_path / "hello.py")}), handler)
        handler.assert_not_called()
        assert result.status == "error"

    def test_u9_block_happens_even_if_event_writer_raises(self, gate, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError("writer is broken")

        monkeypatch.setattr(gate._ev, "record", _boom)  # noqa: SLF001
        handler = _ok_handler()
        result = gate.wrap_tool_call(_request("write_file", {"file_path": "hello.py"}), handler)
        handler.assert_not_called()
        assert result.status == "error"

    def test_gate_check_exception_blocks_rather_than_passes(self, gate, monkeypatch):
        """D6: an unexpected error inside the scope check must still block."""

        def _boom(*args, **kwargs):
            raise RuntimeError("unexpected")

        monkeypatch.setattr(gate, "_approved_plans", _boom)
        handler = _ok_handler()
        result = gate.wrap_tool_call(_request("write_file", {"file_path": "hello.py"}), handler)
        handler.assert_not_called()
        assert result.status == "error"
        assert "fail-closed" in result.content


class TestAsyncParity:
    def test_u10_awrap_matches_sync_blocking(self, gate):
        async def handler(_request):
            return ToolMessage(content="ok", name="x", tool_call_id="call_1")

        handler = MagicMock(side_effect=handler)
        result = asyncio.run(
            gate.awrap_tool_call(_request("write_file", {"file_path": "hello.py"}), handler)
        )
        handler.assert_not_called()
        assert result.status == "error"

    def test_u10_awrap_allows_in_scope(self, gate, tmp_path):
        _approve_plan(gate, target_files=["hello.py"])

        async def handler(_request):
            return ToolMessage(content="ok", name="x", tool_call_id="call_1")

        handler = MagicMock(side_effect=handler)
        asyncio.run(
            gate.awrap_tool_call(
                _request("write_file", {"file_path": str(tmp_path / "hello.py")}), handler
            )
        )
        handler.assert_called_once()


class TestPlanToolsExposed:
    def test_tools_list_has_four_plan_tools(self, gate):
        names = {t.name for t in gate.tools}
        assert names == {"create_plan", "review_plan", "revise_plan", "get_plan_status"}

    def test_u6_create_plan_tool_rejects_blank_field(self, gate):
        create_plan = next(t for t in gate.tools if t.name == "create_plan")
        result = create_plan.invoke(
            {
                "title": "제목입니다 충분히 길게",
                "requirements": "  ",  # blank — EC4/U6
                "scope": "범위입니다 충분히 길게",
                "done_criteria": "완료조건입니다 충분히 길게",
                "target_files": ["a.py"],
                "steps": ["첫 단계"],
                "test_plan": "테스트 방법입니다 충분히 길게",
            }
        )
        assert "거부됨" in result

    def test_review_plan_reaches_reviewed_via_fake_reviewer(self, gate):
        create_plan = next(t for t in gate.tools if t.name == "create_plan")
        review_plan = next(t for t in gate.tools if t.name == "review_plan")
        msg = create_plan.invoke(
            {
                "title": "제목입니다 충분히 길게",
                "requirements": "요구사항입니다 충분히 길게",
                "scope": "범위입니다 충분히 길게",
                "done_criteria": "완료조건입니다 충분히 길게",
                "target_files": ["a.py"],
                "steps": ["첫 단계"],
                "test_plan": "테스트 방법입니다 충분히 길게",
            }
        )
        plan_id = msg.split("plan_id=")[1].split(",")[0]
        result = review_plan.invoke({"plan_id": plan_id})
        assert "리뷰 완료" in result
        assert gate._store.get(plan_id).status == "reviewed"  # noqa: SLF001

    def test_review_plan_stays_draft_when_reviewer_fails(self, gate):
        def _broken_reviewer(plan):
            raise RuntimeError("no credentials")

        gate._reviewer = _broken_reviewer  # noqa: SLF001
        create_plan = next(t for t in gate.tools if t.name == "create_plan")
        review_plan = next(t for t in gate.tools if t.name == "review_plan")
        msg = create_plan.invoke(
            {
                "title": "제목입니다 충분히 길게",
                "requirements": "요구사항입니다 충분히 길게",
                "scope": "범위입니다 충분히 길게",
                "done_criteria": "완료조건입니다 충분히 길게",
                "target_files": ["a.py"],
                "steps": ["첫 단계"],
                "test_plan": "테스트 방법입니다 충분히 길게",
            }
        )
        plan_id = msg.split("plan_id=")[1].split(",")[0]
        result = review_plan.invoke({"plan_id": plan_id})
        assert "리뷰 실패" in result
        assert gate._store.get(plan_id).status == "draft"  # noqa: SLF001


class TestGateBlockLogged:
    def test_block_writes_gate_log_line(self, gate):
        handler = _ok_handler()
        gate.wrap_tool_call(_request("write_file", {"file_path": "hello.py"}), handler)
        log_text = gate._gate_log.read_text(encoding="utf-8")  # noqa: SLF001
        assert "BLOCK write_file" in log_text

    def test_block_recorded_as_gate_block_event(self, gate, tmp_path):
        from assistant.observability import EventLoggerMiddleware

        outer = EventLoggerMiddleware(gate._ev)  # noqa: SLF001
        outer.before_agent(state={"messages": []}, runtime=None)
        handler = _ok_handler()
        gate.wrap_tool_call(_request("write_file", {"file_path": "hello.py"}), handler)
        outer.after_agent(state={"messages": []}, runtime=None)
        gate._ev.flush()  # noqa: SLF001

        run_dirs = list((tmp_path / "runs").iterdir())
        assert len(run_dirs) == 1
        events_text = (run_dirs[0] / "events.jsonl").read_text(encoding="utf-8")
        assert "gate_block" in events_text
