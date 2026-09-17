"""Plan storage and state machine (Step 3 — plan gate, see `docs/plan/STEP3_PLAN.md` §5).

`Plan`/`PlanStore` hold no tool-calling or middleware logic — that is
`assistant/plan_gate.py`'s job. This module is the data layer both the
in-agent middleware and the human-run CLI (`python -m assistant.plan_gate`)
read and write, so it must not import anything from `deepagents_code` or
`langchain` — it has to work identically in both processes.

State machine (D5)::

       create_plan            review_plan           approve (CLI, D4)
    none ─────────→ draft ──────────────→ reviewed ─────────────→ approved
                      ↑                       │                       │
                      └───── revise_plan ─────┘                       │
                      ↑                                               │
                      └──────── out-of-scope attempt (plan_gate.py) ──┘

`revise_plan` and the out-of-scope revert both land on `draft`, so either
path requires another `review_plan` call before `approve` will accept it
again (2-3, 2-4 — "범위 변경 시 재검토").

Plans are stored one JSON file per plan under
`<project_root>/.deepagents/plans/<plan_id>.json` — a plain directory, not
`EventWriter`'s queued/background design, because plan reads/writes are rare
(a handful per session) and must be immediately consistent for the CLI
(`approve` has to see a `review_plan` that just happened in the agent
process, and vice versa) rather than eventually-consistent.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DRAFT = "draft"
REVIEWED = "reviewed"
APPROVED = "approved"

_MIN_FIELD_LEN = 10
"""EC4/U6: a schema-satisfying but empty/placeholder string (e.g. `"."`) must
still be rejected — the required-argument schema alone cannot catch that."""

_PLACEHOLDER_RE = re.compile(r"^(todo|tbd|n/a|na|-|\.+)$", re.IGNORECASE)

_REQUIRED_TEXT_FIELDS = ("title", "requirements", "scope", "done_criteria", "test_plan")


class PlanError(Exception):
    """Raised for invalid plan content or an illegal state transition.

    Callers (the tools in `plan_gate.py`, and the CLI's `main()`) catch this
    and turn it into a message string — it is never allowed to propagate as
    an unhandled exception into the model or the terminal.
    """


def _validate_text(name: str, value: object) -> str:
    if not isinstance(value, str):
        msg = f"{name}은(는) 문자열이어야 합니다 (받은 타입: {type(value).__name__})"
        raise PlanError(msg)
    stripped = value.strip()
    if len(stripped) < _MIN_FIELD_LEN or _PLACEHOLDER_RE.match(stripped):
        msg = (
            f"{name}은(는) 최소 {_MIN_FIELD_LEN}자 이상의 구체적인 내용이어야 합니다 "
            f"(받은 값: {value!r})"
        )
        raise PlanError(msg)
    return value


def _validate_str_list(name: str, value: object) -> list[str]:
    if not isinstance(value, list) or not value:
        msg = f"{name}은(는) 비어 있지 않은 문자열 목록이어야 합니다 (받은 값: {value!r})"
        raise PlanError(msg)
    cleaned: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            msg = f"{name}의 각 항목은 비어 있지 않은 문자열이어야 합니다 (받은 값: {value!r})"
            raise PlanError(msg)
        cleaned.append(item)
    return cleaned


@dataclass
class Plan:
    """One plan's full content and current state-machine status."""

    plan_id: str
    title: str
    requirements: str
    scope: str
    done_criteria: str
    target_files: list[str]
    steps: list[str]
    test_plan: str
    allow_subagent: bool = False
    status: str = DRAFT
    review_note: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Plan:
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}  # type: ignore[attr-defined]
        return cls(**known)


class PlanStore:
    """File-backed plan storage under `<project_root>/.deepagents/plans/`.

    One process-local lock serializes read-modify-write sequences (`review`,
    `revise`, `approve`, `revert_to_draft`) within *this* process. It does
    not protect against the agent process and the CLI process racing each
    other on the same plan file — considered acceptable: a human runs
    `approve` once, deliberately, well after the agent's last write: see
    `docs/plan/STEP3_PLAN.md` §5 D4.
    """

    def __init__(self, project_root: Path) -> None:
        self._dir = project_root / ".deepagents" / "plans"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, plan_id: str) -> Path:
        return self._dir / f"{plan_id}.json"

    def create(
        self,
        *,
        title: str,
        requirements: str,
        scope: str,
        done_criteria: str,
        target_files: list[str],
        steps: list[str],
        test_plan: str,
        allow_subagent: bool = False,
    ) -> Plan:
        """Validate and persist a new plan in `draft` (EC4/U6)."""
        values = {
            "title": title,
            "requirements": requirements,
            "scope": scope,
            "done_criteria": done_criteria,
            "test_plan": test_plan,
        }
        for name in _REQUIRED_TEXT_FIELDS:
            _validate_text(name, values[name])
        target_files = _validate_str_list("target_files", target_files)
        steps = _validate_str_list("steps", steps)

        plan_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        plan = Plan(
            plan_id=plan_id,
            title=title,
            requirements=requirements,
            scope=scope,
            done_criteria=done_criteria,
            target_files=target_files,
            steps=steps,
            test_plan=test_plan,
            allow_subagent=bool(allow_subagent),
            status=DRAFT,
        )
        with self._lock:
            self._save(plan)
        return plan

    def get(self, plan_id: str) -> Plan:
        """Load one plan by id.

        Raises:
            PlanError: The plan does not exist, or its file is not valid
                JSON (D6 — a caller that needs fail-closed behavior treats
                any `PlanError` here as "no such approved plan").
        """
        path = self._path(plan_id)
        if not path.exists():
            msg = f"계획을 찾을 수 없음: {plan_id}"
            raise PlanError(msg)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            msg = f"계획 파일이 손상됨: {plan_id}"
            raise PlanError(msg) from exc
        try:
            return Plan.from_dict(data)
        except TypeError as exc:
            msg = f"계획 파일 형식이 올바르지 않음: {plan_id}"
            raise PlanError(msg) from exc

    def _save(self, plan: Plan) -> None:
        """Write `plan` atomically (tmp file + rename)."""
        plan.updated_at = time.time()
        path = self._path(plan.plan_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def list_ids(self) -> list[str]:
        """All known plan ids, oldest first (ids are timestamp-prefixed)."""
        return sorted(p.stem for p in self._dir.glob("*.json"))

    def review(self, plan_id: str, note: str) -> Plan:
        """Advance a `draft` plan to `reviewed` with the reviewer's note (EC5).

        Raises:
            PlanError: The plan is not currently `draft`.
        """
        with self._lock:
            plan = self.get(plan_id)
            if plan.status != DRAFT:
                msg = f"draft 상태의 계획만 리뷰할 수 있습니다 (현재 상태: {plan.status})"
                raise PlanError(msg)
            plan.status = REVIEWED
            plan.review_note = note
            self._save(plan)
            return plan

    def revise(self, plan_id: str, **updates: Any) -> Plan:  # noqa: ANN401
        """Apply field updates and send the plan back to `draft`.

        Args:
            **updates: Any subset of the plan's editable fields; `None`
                values are ignored (leave that field unchanged).

        Raises:
            PlanError: The plan is already `approved` — an approved plan's
                scope cannot be widened by editing it; a fresh plan (or an
                out-of-scope revert, see `revert_to_draft`) is required.
        """
        with self._lock:
            plan = self.get(plan_id)
            if plan.status == APPROVED:
                msg = "승인된 계획은 수정할 수 없습니다. 새 계획을 만들거나 범위 위반으로 되돌려진 뒤 수정하세요."
                raise PlanError(msg)
            for key, value in updates.items():
                if value is None:
                    continue
                if key in _REQUIRED_TEXT_FIELDS:
                    value = _validate_text(key, value)
                elif key in ("target_files", "steps"):
                    value = _validate_str_list(key, value)
                setattr(plan, key, value)
            plan.status = DRAFT
            plan.review_note = None
            self._save(plan)
            return plan

    def approve(self, plan_id: str) -> Plan:
        """Advance a `reviewed` plan to `approved` (CLI-only — D4).

        Raises:
            PlanError: The plan has not been reviewed yet (EC5).
        """
        with self._lock:
            plan = self.get(plan_id)
            if plan.status != REVIEWED:
                msg = f"reviewed 상태의 계획만 승인할 수 있습니다 (현재 상태: {plan.status}) — review_plan을 먼저 호출하세요"
                raise PlanError(msg)
            plan.status = APPROVED
            self._save(plan)
            return plan

    def revert_to_draft(self, plan_id: str, *, reason: str) -> Plan:
        """Force an approved plan back to `draft` after a scope violation (EC7)."""
        with self._lock:
            plan = self.get(plan_id)
            plan.status = DRAFT
            plan.review_note = f"[범위 위반으로 재검토 필요] {reason}"
            self._save(plan)
            return plan
