"""Unit tests for `assistant.memory` — search, propose/verify (§6 V1-V6).

Tool-level integration (the `search_memory`/`propose_improvement`/
`verify_improvement` wrappers, and `create_plan`'s `memory_refs`
enforcement) lives in `test_plan_gate.py` alongside the rest of
`PlanGateMiddleware.tools` — this file tests `assistant.memory`'s plain
functions directly, with no middleware involved.
"""

from __future__ import annotations

import pytest
from assistant.events import GATE_BLOCK, TOOL_END, EventWriter

from assistant import memory


def _seed_agents_md(tmp_path, *rules: tuple[str, str]) -> None:
    path = tmp_path / ".deepagents" / "AGENTS.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"- **[{rid}]** {text}" for rid, text in rules)
    path.write_text(f"# 규칙\n\n{body}\n", encoding="utf-8")


def _seed_gate_blocks(
    tmp_path, reason: str, count: int, *, thread_id: str = "t1"
) -> None:
    ev = EventWriter(runs_dir=tmp_path / "runs")
    ev.start_run(thread_id=thread_id)
    for _ in range(count):
        ev.record(
            GATE_BLOCK, thread_id=thread_id, name="execute", data={"reason": reason}
        )
    ev.flush()


class TestKnownRefIds:
    def test_empty_project_has_no_refs(self, tmp_path):
        assert memory.known_ref_ids(tmp_path) == set()

    def test_rule_tags_from_agents_md(self, tmp_path):
        _seed_agents_md(tmp_path, ("R1", "PEP8을 따른다"), ("R2", "타입힌트를 붙인다"))
        assert memory.known_ref_ids(tmp_path) == {"R1", "R2"}

    def test_untagged_lines_are_ignored(self, tmp_path):
        path = tmp_path / ".deepagents" / "AGENTS.md"
        path.parent.mkdir(parents=True)
        path.write_text("# 규칙\n\n- 태그 없는 일반 문장입니다.\n", encoding="utf-8")
        assert memory.known_ref_ids(tmp_path) == set()


class TestInvalidRefs:
    def test_v1_style_empty_list_has_no_invalid_entries(self, tmp_path):
        """A no-op sanity check, not the MC3 rejection itself.

        `invalid_refs([])` has nothing to flag — an empty `memory_refs` is
        rejected by the caller before this ever runs (see
        `test_plan_gate.py`'s `test_mc3_...` test for that check).
        """
        _seed_agents_md(tmp_path, ("R1", "규칙"))
        assert memory.invalid_refs([], tmp_path) == []

    def test_v2_unknown_id_is_invalid(self, tmp_path):
        _seed_agents_md(tmp_path, ("R1", "규칙"))
        assert memory.invalid_refs(["R1", "R99"], tmp_path) == ["R99"]

    def test_known_id_is_valid(self, tmp_path):
        _seed_agents_md(tmp_path, ("R1", "규칙"))
        assert memory.invalid_refs(["R1"], tmp_path) == []


class TestSearch:
    def test_matches_rule_line_case_insensitively(self, tmp_path):
        _seed_agents_md(tmp_path, ("R1", "PEP8을 따른다"))
        hits = memory.search("pep8", tmp_path)
        assert hits == [("R1", "AGENTS.md", "- **[R1]** PEP8을 따른다")]

    def test_no_match_returns_empty(self, tmp_path):
        _seed_agents_md(tmp_path, ("R1", "PEP8을 따른다"))
        assert memory.search("존재하지않는말", tmp_path) == []

    def test_format_no_hits_still_explains_why(self, tmp_path):
        text = memory.format_search_results("아무거나", [])
        assert "검색 결과가 없습니다" in text

    def test_format_hits_names_the_citable_id(self, tmp_path):
        text = memory.format_search_results("q", [("R1", "AGENTS.md", "line")])
        assert "[R1]" in text


class TestProposeImprovement:
    def test_v4_tcb_target_rejected(self, tmp_path):
        with pytest.raises(memory.MemoryError, match="TCB"):
            memory.propose_improvement(
                "tests/test_plan_gate.py",
                "충분히 긴 사유 문장입니다",
                "충분히 긴 제안 문장입니다",
                tmp_path,
            )

    def test_disallowed_non_tcb_target_rejected(self, tmp_path):
        with pytest.raises(memory.MemoryError, match="허용된 개선 대상"):
            memory.propose_improvement(
                "README.md",
                "충분히 긴 사유 문장입니다",
                "충분히 긴 제안 문장입니다",
                tmp_path,
            )

    def test_placeholder_proposed_text_rejected(self, tmp_path):
        _seed_gate_blocks(tmp_path, "충분히 긴 사유 문장입니다", 3)
        with pytest.raises(memory.MemoryError):
            memory.propose_improvement(
                ".deepagents/AGENTS.md",
                "충분히 긴 사유 문장입니다",
                "TODO",
                tmp_path,
            )

    def test_v3_below_threshold_rejected(self, tmp_path):
        _seed_gate_blocks(tmp_path, "충분히 긴 사유 문장입니다", 2)
        with pytest.raises(memory.MemoryError, match="2회"):
            memory.propose_improvement(
                ".deepagents/AGENTS.md",
                "충분히 긴 사유 문장입니다",
                "[R9] 충분히 긴 제안 문장입니다",
                tmp_path,
            )

    def test_v3_at_threshold_succeeds(self, tmp_path):
        _seed_gate_blocks(tmp_path, "충분히 긴 사유 문장입니다", 3)
        candidate_id = memory.propose_improvement(
            ".deepagents/AGENTS.md",
            "충분히 긴 사유 문장입니다",
            "[R9] 충분히 긴 제안 문장입니다",
            tmp_path,
        )
        assert candidate_id == "L1"
        lessons = (tmp_path / ".deepagents" / "memories" / "lessons.md").read_text(
            encoding="utf-8"
        )
        assert "## [후보] [L1]" in lessons
        assert "- 상태: pending" in lessons

    def test_tool_end_error_also_counts_toward_threshold(self, tmp_path):
        ev = EventWriter(runs_dir=tmp_path / "runs")
        ev.start_run(thread_id="t1")
        for _ in range(3):
            ev.record(
                TOOL_END,
                thread_id="t1",
                name="read_file",
                status="error",
                error="파일을 찾을 수 없는 사유입니다",
            )
        ev.flush()
        candidate_id = memory.propose_improvement(
            ".deepagents/memories/",
            "파일을 찾을 수 없는 사유입니다",
            "[R9] 없는 파일을 다시 확인하도록 안내를 추가합니다",
            tmp_path,
        )
        assert candidate_id == "L1"

    def test_candidate_ids_increment(self, tmp_path):
        _seed_gate_blocks(tmp_path, "충분히 긴 사유 문장입니다", 3)
        first = memory.propose_improvement(
            ".deepagents/AGENTS.md",
            "충분히 긴 사유 문장입니다",
            "[R9] 첫 번째 제안 문장입니다",
            tmp_path,
        )
        second = memory.propose_improvement(
            ".deepagents/AGENTS.md",
            "충분히 긴 사유 문장입니다",
            "[R10] 두 번째 제안 문장입니다",
            tmp_path,
        )
        assert (first, second) == ("L1", "L2")


class TestVerifyImprovement:
    def test_missing_candidate_raises(self, tmp_path):
        with pytest.raises(memory.MemoryError):
            memory.verify_improvement("L1", tmp_path)

    def test_v5_records_before_and_after(self, tmp_path):
        _seed_agents_md(tmp_path, ("R1", "기존 규칙"))
        _seed_gate_blocks(tmp_path, "충분히 긴 사유 문장입니다", 3)
        candidate_id = memory.propose_improvement(
            ".deepagents/AGENTS.md",
            "충분히 긴 사유 문장입니다",
            "[R9] 새로 추가되는 규칙 문장입니다",
            tmp_path,
        )
        result = memory.verify_improvement(candidate_id, tmp_path)
        assert result["before"] == 2  # R1 + the candidate's own L1 tag
        assert result["after"] == 3  # + freshly cited R9
        assert result["improved"] is True

    def test_v6_no_fresh_tag_is_not_improved(self, tmp_path):
        _seed_gate_blocks(tmp_path, "충분히 긴 사유 문장입니다", 3)
        candidate_id = memory.propose_improvement(
            ".deepagents/AGENTS.md",
            "충분히 긴 사유 문장입니다",
            "새 태그 없이 그냥 강조만 하는 제안 문장입니다",
            tmp_path,
        )
        result = memory.verify_improvement(candidate_id, tmp_path)
        assert result["improved"] is False
        assert result["before"] == result["after"]

    def test_skills_target_before_after(self, tmp_path):
        skill_dir = tmp_path / ".deepagents" / "skills" / "plan-first"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "# plan-first\n\n기존 절차\n", encoding="utf-8"
        )
        _seed_gate_blocks(tmp_path, "충분히 긴 사유 문장입니다", 3)
        candidate_id = memory.propose_improvement(
            ".deepagents/skills/plan-first/SKILL.md",
            "충분히 긴 사유 문장입니다",
            "계획 전에 search_memory를 반드시 호출한다",
            tmp_path,
        )
        result = memory.verify_improvement(candidate_id, tmp_path)
        before_after_improved = (result["before"], result["after"], result["improved"])
        assert before_after_improved == (0, 1, True)

    def test_skills_target_already_present_is_not_improved(self, tmp_path):
        skill_dir = tmp_path / ".deepagents" / "skills" / "plan-first"
        skill_dir.mkdir(parents=True)
        proposed = "계획 전에 search_memory를 반드시 호출한다"
        (skill_dir / "SKILL.md").write_text(
            f"# plan-first\n\n{proposed}\n", encoding="utf-8"
        )
        _seed_gate_blocks(tmp_path, "충분히 긴 사유 문장입니다", 3)
        candidate_id = memory.propose_improvement(
            ".deepagents/skills/plan-first/SKILL.md",
            "충분히 긴 사유 문장입니다",
            proposed,
            tmp_path,
        )
        result = memory.verify_improvement(candidate_id, tmp_path)
        before_after_improved = (result["before"], result["after"], result["improved"])
        assert before_after_improved == (1, 1, False)


class TestUpdateCandidateStatus:
    def test_status_line_rewritten_on_success(self, tmp_path):
        _seed_gate_blocks(tmp_path, "충분히 긴 사유 문장입니다", 3)
        candidate_id = memory.propose_improvement(
            ".deepagents/AGENTS.md",
            "충분히 긴 사유 문장입니다",
            "[R9] 새 규칙 문장입니다",
            tmp_path,
        )
        memory.update_candidate_status(
            candidate_id, tmp_path, verified=True, before=1, after=2
        )
        lessons = (tmp_path / ".deepagents" / "memories" / "lessons.md").read_text(
            encoding="utf-8"
        )
        assert "- 상태: verified (before=1, after=2)" in lessons

    def test_status_line_rewritten_on_rejection(self, tmp_path):
        _seed_gate_blocks(tmp_path, "충분히 긴 사유 문장입니다", 3)
        candidate_id = memory.propose_improvement(
            ".deepagents/AGENTS.md",
            "충분히 긴 사유 문장입니다",
            "새 태그 없는 제안 문장입니다",
            tmp_path,
        )
        memory.update_candidate_status(
            candidate_id, tmp_path, verified=False, before=1, after=1
        )
        lessons = (tmp_path / ".deepagents" / "memories" / "lessons.md").read_text(
            encoding="utf-8"
        )
        assert "- 상태: rejected" in lessons
