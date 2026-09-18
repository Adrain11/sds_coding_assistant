"""Unit tests for `assistant.plans` — the plan state machine.

`STEP3_PLAN.md` §6's illegal-transition tests (U5) live here; the
tool-call/gate-blocking tests (U1-U13) live in `test_plan_gate.py`.
"""

from __future__ import annotations

import json

import pytest
from assistant.plans import APPROVED, DRAFT, REVIEWED, Plan, PlanError, PlanStore

_VALID = {
    "title": "이벤트 로거에 재시도 지표 추가",
    "requirements": "재시도 횟수를 report show에서 볼 수 있어야 한다",
    "scope": "assistant/observability.py의 모델 콜 경로만. report.py 렌더링 제외",
    "done_criteria": "report show 출력에 재시도 N회가 보인다",
    "target_files": ["assistant/assistant/observability.py"],
    "steps": ["attempt 카운터 추가", "단위 테스트 작성"],
    "test_plan": "pytest tests/test_observability.py 통과",
    "memory_refs": ["R1"],
}


def _create(store: PlanStore, **overrides: object) -> Plan:
    kwargs = {**_VALID, **overrides}
    return store.create(**kwargs)


class TestCreate:
    def test_creates_in_draft(self, tmp_path):
        store = PlanStore(tmp_path)
        plan = _create(store)
        assert plan.status == DRAFT
        assert (tmp_path / ".deepagents" / "plans" / f"{plan.plan_id}.json").exists()

    def test_rejects_blank_required_field(self, tmp_path):
        store = PlanStore(tmp_path)
        with pytest.raises(PlanError):
            _create(store, requirements="   ")

    def test_rejects_placeholder_field(self, tmp_path):
        store = PlanStore(tmp_path)
        with pytest.raises(PlanError):
            _create(store, scope="TODO")

    def test_rejects_too_short_field(self, tmp_path):
        store = PlanStore(tmp_path)
        with pytest.raises(PlanError):
            _create(store, done_criteria="ok")

    def test_rejects_empty_target_files(self, tmp_path):
        store = PlanStore(tmp_path)
        with pytest.raises(PlanError):
            _create(store, target_files=[])

    def test_rejects_empty_steps(self, tmp_path):
        store = PlanStore(tmp_path)
        with pytest.raises(PlanError):
            _create(store, steps=[])

    def test_rejects_empty_memory_refs(self, tmp_path):
        """MC3 — a plan with no cited memory is rejected (Step 4 M1)."""
        store = PlanStore(tmp_path)
        with pytest.raises(PlanError):
            _create(store, memory_refs=[])

    def test_defaults_allow_subagent_false(self, tmp_path):
        store = PlanStore(tmp_path)
        plan = _create(store)
        assert plan.allow_subagent is False


class TestStateMachine:
    def test_review_requires_draft(self, tmp_path):
        store = PlanStore(tmp_path)
        plan = _create(store)
        store.review(plan.plan_id, "note")
        # Already reviewed — reviewing again must be rejected (U5-adjacent).
        with pytest.raises(PlanError):
            store.review(plan.plan_id, "note again")

    def test_approve_requires_reviewed(self, tmp_path):
        """U5: draft -> approve must be rejected, state unchanged."""
        store = PlanStore(tmp_path)
        plan = _create(store)
        with pytest.raises(PlanError):
            store.approve(plan.plan_id)
        assert store.get(plan.plan_id).status == DRAFT

    def test_full_happy_path(self, tmp_path):
        store = PlanStore(tmp_path)
        plan = _create(store)
        store.review(plan.plan_id, "괜찮아 보입니다")
        approved = store.approve(plan.plan_id)
        assert approved.status == APPROVED

    def test_revise_returns_to_draft(self, tmp_path):
        store = PlanStore(tmp_path)
        plan = _create(store)
        store.review(plan.plan_id, "note")
        revised = store.revise(plan.plan_id, title="새로운 제목으로 충분히 길게")
        assert revised.status == DRAFT
        assert revised.title == "새로운 제목으로 충분히 길게"

    def test_revise_rejects_approved_plan(self, tmp_path):
        store = PlanStore(tmp_path)
        plan = _create(store)
        store.review(plan.plan_id, "note")
        store.approve(plan.plan_id)
        with pytest.raises(PlanError):
            store.revise(plan.plan_id, title="더 이상 못 바꿉니다 안돼요")
        assert store.get(plan.plan_id).status == APPROVED

    def test_revert_to_draft_after_scope_violation(self, tmp_path):
        """EC7: an approved plan reverts to draft with a review_note."""
        store = PlanStore(tmp_path)
        plan = _create(store)
        store.review(plan.plan_id, "note")
        store.approve(plan.plan_id)
        reverted = store.revert_to_draft(plan.plan_id, reason="다른 파일을 건드리려 함")
        assert reverted.status == DRAFT
        assert "범위 위반" in reverted.review_note


class TestPersistence:
    def test_get_missing_plan_raises(self, tmp_path):
        store = PlanStore(tmp_path)
        with pytest.raises(PlanError):
            store.get("does-not-exist")

    def test_corrupted_json_raises_planerror(self, tmp_path):
        """U8: a broken plan file must fail closed.

        It must raise, never crash silently as an approval.
        """
        store = PlanStore(tmp_path)
        plan = _create(store)
        path = tmp_path / ".deepagents" / "plans" / f"{plan.plan_id}.json"
        path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(PlanError):
            store.get(plan.plan_id)

    def test_list_ids_excludes_tmp_files(self, tmp_path):
        store = PlanStore(tmp_path)
        _create(store)
        _create(store, title="두 번째 계획입니다 충분히 길게")
        ids = store.list_ids()
        assert len(ids) == 2
        assert all(not pid.endswith(".tmp") for pid in ids)

    def test_two_stores_same_root_see_each_others_writes(self, tmp_path):
        """A write from one `PlanStore` instance must be visible from another.

        The agent process and the CLI process are separate `PlanStore`
        instances pointed at the same directory — approval in one must be
        visible to the other (D4).
        """
        writer = PlanStore(tmp_path)
        plan = _create(writer)
        writer.review(plan.plan_id, "note")

        reader = PlanStore(tmp_path)
        assert reader.get(plan.plan_id).status == REVIEWED
        reader.approve(plan.plan_id)
        assert writer.get(plan.plan_id).status == APPROVED

    def test_saved_file_is_valid_json(self, tmp_path):
        store = PlanStore(tmp_path)
        plan = _create(store)
        path = tmp_path / ".deepagents" / "plans" / f"{plan.plan_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["plan_id"] == plan.plan_id
        assert data["status"] == DRAFT
