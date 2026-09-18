"""Memory search + self-improvement (Step 4 — see `docs/plan/STEP4_PLAN.md`).

**M1 — `.deepagents/AGENTS.md` is the only auto-loaded project memory.**
dcode's `MemoryMiddleware` loads a fixed list of `AGENTS.md` paths and
nothing else (`libs/code/deepagents_code/project_utils.py:150-224`
`find_project_agent_md` checks exactly two candidates; no directory is ever
scanned). The step's original plan assumed a project-scoped
`.deepagents/memories/project_rules.md` would be auto-loaded the same way —
it would not have been. Project rules therefore live directly in
`.deepagents/AGENTS.md`, tagged `[R1]`, `[R2]`, ... so `memory_refs` (see
`assistant/plan_gate.py`) can cite a specific one and have that citation
verified against real content instead of a free-text claim.

`.deepagents/memories/lessons.md` holds `propose_improvement`'s candidates,
tagged `[L1]`, `[L2]`, ... — this file is *not* meant to be auto-loaded
(M3 below), so it not being in `MemoryMiddleware.sources` is fine.

**M2 — `search_memory`/`memory_refs` do real existence checks, not vibes.**
`known_ref_ids`/`invalid_refs` parse the two files above for genuine
`[Rn]`/`[Ln]` tags; `plan_gate.create_plan` rejects any `memory_refs` entry
that is not one of them (3-2 — "검색해서 실제 활용", not "활용했다고 말함").

**M3 — `propose_improvement` never applies anything.** It only appends a
`## [후보] [Ln]` block to `lessons.md`, status `pending`. A human promotes it
by hand-editing the real target file; nothing in this module writes to
`.deepagents/AGENTS.md` or `.deepagents/skills/`.

**M4 — `verify_improvement` is a fixed, model-free before/after check.** For
an `AGENTS.md`/`memories` target, it asks whether the candidate's own
proposed text names a fresh `[Rn]` id nothing currently cites — the same
existence check `memory_refs` validation runs, so "verified" means "this
citation would actually resolve," not a vague self-assessment. For a
`skills` target (no id convention), it asks whether the proposed text is
genuinely new content, not an already-present duplicate. Both cases are
plain string/set operations — no model call, no `runs/` mutation.

**M5 — TCB (Step 3 D7) applies to improvement targets too.** `propose_improvement`
rejects any `target_path` under `assistant/`, `tests/`, `libs/`, or
`.deepagents/plans/` — self-improvement can touch memory, skills, and the
system prompt, never the gate/logger/tests/vendored source that enforce it.
The TCB prefix list itself is `assistant.plan_gate`'s (`_is_tcb_path`); it is
imported lazily inside the one function that needs it, not duplicated here,
to avoid a module-load cycle (`plan_gate` imports this module too, for
`memory_refs` validation).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from assistant.events import GATE_BLOCK, TOOL_END, iter_events

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_RULE_TAG_RE = re.compile(r"\[(R\d+)\]")
"""Matches a project-rule id anywhere in a `.deepagents/AGENTS.md` line."""

_CANDIDATE_HEADER_RE = re.compile(r"^## \[후보\] \[(L\d+)\]\s*$", re.MULTILINE)
"""Matches only a candidate's own heading line in `lessons.md` — deliberately
narrower than `_RULE_TAG_RE`-style matching, so a candidate's free-text
`- 제안:` line (which may itself describe adding a `[Rn]`/`[Ln]` tag) can
never be mistaken for that tag already existing."""

_CANDIDATE_BLOCK_RE = re.compile(
    r"^## \[후보\] \[(L\d+)\]\n(.*?)(?=^## \[후보\] |\Z)", re.MULTILINE | re.DOTALL
)

_ALLOWED_TARGET_PREFIXES = (
    ".deepagents/AGENTS.md",
    ".deepagents/memories/",
    ".deepagents/skills/",
)
"""The three improvement targets the official 3-3 wording names: system
prompt, working memory, skills (M2)."""

_MIN_TEXT_LEN = 10
_PLACEHOLDER_RE = re.compile(r"^(todo|tbd|n/a|na|-|\.+)$", re.IGNORECASE)
"""Mirrors `assistant.plans`' own placeholder check — kept local rather than
imported so this module has no dependency on the plan state machine."""

_THRESHOLD_DEFAULT = 3
"""How many times the same failure reason must repeat before
`propose_improvement` will act on it (M2 — "한 번의 실패로는 만들지 않는다")."""

_LESSONS_HEADER = (
    "# lessons.md — 개선 후보 (자기개선, Step 4)\n\n"
    "`propose_improvement`가 만든 후보만 담는다. 사람이 검토해서 "
    "`.deepagents/AGENTS.md`나 `.deepagents/skills/`로 옮기기 전까지는 적용되지 "
    "않는다 (M3 — 자동 반영 금지).\n"
)


class MemoryError(Exception):  # noqa: N818 - matches assistant.plans.PlanError's naming
    """Raised for invalid propose/verify_improvement input.

    Callers (the tool wrappers in `plan_gate.py`) catch this and turn it into
    a message string, mirroring `assistant.plans.PlanError`.
    """


def _agents_md_path(project_root: Path) -> Path:
    return project_root / ".deepagents" / "AGENTS.md"


def _lessons_path(project_root: Path) -> Path:
    return project_root / ".deepagents" / "memories" / "lessons.md"


def _rule_entries(project_root: Path) -> list[tuple[str, str]]:
    """Every `[Rn]`-tagged line in `.deepagents/AGENTS.md`.

    Args:
        project_root: Repository root.

    Returns:
        `(ref_id, line_text)` pairs, in file order.
    """
    path = _agents_md_path(project_root)
    if not path.exists():
        return []
    entries: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _RULE_TAG_RE.search(line)
        if match:
            entries.append((match.group(1), line.strip()))
    return entries


def _candidate_entries(project_root: Path) -> list[tuple[str, str]]:
    """Every `## [후보] [Ln]` block in `.deepagents/memories/lessons.md`.

    Args:
        project_root: Repository root.

    Returns:
        `(ref_id, block_text)` pairs, in file order.
    """
    path = _lessons_path(project_root)
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    entries: list[tuple[str, str]] = []
    for match in _CANDIDATE_BLOCK_RE.finditer(text):
        entries.append((match.group(1), match.group(0).strip()))
    return entries


def known_ref_ids(project_root: Path) -> set[str]:
    """Every real `[Rn]`/`[Ln]` id `memory_refs` can legally cite.

    Args:
        project_root: Repository root.

    Returns:
        The union of project-rule ids (`AGENTS.md`) and improvement-candidate
        ids (`lessons.md`).
    """
    ids = {ref_id for ref_id, _line in _rule_entries(project_root)}
    ids |= {ref_id for ref_id, _block in _candidate_entries(project_root)}
    return ids


def invalid_refs(refs: list[str], project_root: Path) -> list[str]:
    """The subset of `refs` that do not exist as a real tag (3-2's M1 check).

    Args:
        refs: Candidate `memory_refs` values, e.g. `["R1", "L2"]`.
        project_root: Repository root.

    Returns:
        Entries of `refs` not found by `known_ref_ids` — empty if every ref
        is real.
    """
    known = known_ref_ids(project_root)
    return [ref for ref in refs if ref not in known]


def search(query: str, project_root: Path) -> list[tuple[str, str, str]]:
    """Case-insensitive substring search over both memory files (3-2).

    Args:
        query: Search text; matched against each rule line and each
            candidate block as a whole.
        project_root: Repository root.

    Returns:
        `(ref_id, source_label, snippet)` triples for every match.
    """
    needle = query.strip().lower()
    if not needle:
        return []
    hits: list[tuple[str, str, str]] = []
    for ref_id, line in _rule_entries(project_root):
        if needle in line.lower():
            hits.append((ref_id, "AGENTS.md", line))
    for ref_id, block in _candidate_entries(project_root):
        if needle in block.lower():
            first_line = block.splitlines()[0]
            hits.append((ref_id, "memories/lessons.md", first_line))
    return hits


def format_search_results(query: str, hits: list[tuple[str, str, str]]) -> str:
    """Render `search()` output as the agent-facing `search_memory` reply.

    Args:
        query: The search text that produced `hits` (echoed back).
        hits: Output of `search()`.

    Returns:
        A message naming each hit's citable id, or a no-match notice.
    """
    if not hits:
        return (
            f"'{query}'에 대한 메모리 검색 결과가 없습니다. "
            "관련 규칙/교훈이 없다는 뜻이니 다른 검색어를 시도하거나, "
            "인용할 것이 정말 없다면 create_plan은 만들 수 없습니다 (3-2)."
        )
    lines = [f"'{query}' 검색 결과 {len(hits)}건:"]
    for ref_id, source, snippet in hits:
        lines.append(f"  [{ref_id}] ({source}) {snippet}")
    lines.append(
        'create_plan(memory_refs=[...])에 위 대괄호 안 id만(따옴표 포함, 예: "R1") '
        "인용하세요."
    )
    return "\n".join(lines)


# --- propose_improvement (3-3, M2/M3/M5) ------------------------------------


def _normalize_rel(path_str: str) -> str:
    rel = path_str.replace("\\", "/")
    if rel.startswith("./"):
        rel = rel[2:]
    return rel


def _check_target_allowed(target_path: str, project_root: Path) -> str | None:
    """A rejection reason, or `None` if `target_path` is a legal improvement target.

    Args:
        target_path: Project-relative path the candidate proposes to change.
        project_root: Repository root, for the TCB check.

    Returns:
        `None` when `target_path` is under one of the three allowed roles and
        is not a TCB path; otherwise a Korean rejection message.
    """
    from assistant.plan_gate import _is_tcb_path  # deferred: see module docstring, M5

    if _is_tcb_path(target_path, project_root):
        return (
            f"'{target_path}'는 게이트·로거·테스트·원본 코드(TCB)라 "
            "자기개선 대상이 될 수 없습니다 (단계 3 D7 / M5)."
        )
    rel = _normalize_rel(target_path)
    allowed = any(
        rel == prefix.rstrip("/") or rel.startswith(prefix)
        for prefix in _ALLOWED_TARGET_PREFIXES
    )
    if not allowed:
        return (
            f"'{target_path}'는 허용된 개선 대상이 아닙니다. "
            "`.deepagents/AGENTS.md` · `.deepagents/memories/` · "
            "`.deepagents/skills/` 중 하나여야 합니다 (공식 3-3 문구)."
        )
    return None


def _validate_content(name: str, value: str) -> str:
    stripped = value.strip()
    if len(stripped) < _MIN_TEXT_LEN or _PLACEHOLDER_RE.match(stripped):
        msg = f"{name}이(가) 너무 짧거나 자리표시자입니다 (받은 값: {value!r})."
        raise MemoryError(msg)
    return stripped


def _iter_run_events(project_root: Path) -> Iterator[dict[str, Any]]:
    runs_dir = project_root / "runs"
    if not runs_dir.exists():
        return
    for run_dir in sorted(runs_dir.iterdir()):
        if run_dir.is_dir():
            yield from iter_events(run_dir / "events.jsonl")


def _matches_reason(event: dict[str, Any], needle: str) -> bool:
    event_type = event.get("type")
    if event_type == GATE_BLOCK:
        text = (event.get("data") or {}).get("reason") or ""
    elif event_type == TOOL_END and event.get("status") == "error":
        text = event.get("error") or ""
    else:
        return False
    return needle in text.lower()


def count_matching_failures(reason: str, project_root: Path) -> int:
    """How many past `gate_block`/`tool_end(error)` events match `reason` (M2).

    Args:
        reason: Free-text substring to look for in each event's own reason
            (`gate_block`) or error text (`tool_end`), case-insensitive.
        project_root: Repository root; events are read from `runs/*/events.jsonl`.

    Returns:
        The match count, across every run on disk.
    """
    needle = reason.strip().lower()
    if not needle:
        return 0
    events = _iter_run_events(project_root)
    return sum(1 for event in events if _matches_reason(event, needle))


def _next_candidate_id(project_root: Path) -> str:
    existing = {
        int(ref_id[1:])
        for ref_id in known_ref_ids(project_root)
        if ref_id.startswith("L") and ref_id[1:].isdigit()
    }
    return f"L{max(existing, default=0) + 1}"


def propose_improvement(
    target_path: str,
    reason: str,
    proposed_text: str,
    project_root: Path,
    *,
    threshold: int = _THRESHOLD_DEFAULT,
) -> str:
    """Record a pending improvement candidate in `lessons.md` (3-3).

    Args:
        target_path: Where the change would eventually land — must be
            `.deepagents/AGENTS.md`, under `.deepagents/memories/`, or under
            `.deepagents/skills/` (M2), and never a TCB path (M5).
        reason: The repeated failure this addresses, e.g. `"execute는 승인
            후에도 항상 차단됩니다"`. Must have occurred at least `threshold`
            times in `runs/*/events.jsonl` (M2).
        proposed_text: The concrete sentence to add. For an `AGENTS.md`/
            `memories` target, include a fresh `[Rn]` id if this is meant to
            become a citable rule — `verify_improvement` checks for exactly
            that.
        project_root: Repository root.
        threshold: Minimum repeat count required (default 3).

    Returns:
        The new candidate's citable id, e.g. `"L1"`.

    Raises:
        MemoryError: `target_path` is disallowed, `reason`/`proposed_text`
            is empty or a placeholder, or `reason` has not repeated enough.
    """
    error = _check_target_allowed(target_path, project_root)
    if error:
        raise MemoryError(error)
    stripped_reason = _validate_content("reason", reason)
    stripped_text = _validate_content("proposed_text", proposed_text)

    count = count_matching_failures(stripped_reason, project_root)
    if count < threshold:
        msg = (
            f"사유 '{stripped_reason}'가 {count}회뿐입니다 (임계치 {threshold}회) — "
            "더 반복되기 전에는 개선안을 만들지 않습니다 (M2)."
        )
        raise MemoryError(msg)

    lessons_path = _lessons_path(project_root)
    lessons_path.parent.mkdir(parents=True, exist_ok=True)
    if not lessons_path.exists():
        lessons_path.write_text(_LESSONS_HEADER, encoding="utf-8")

    candidate_id = _next_candidate_id(project_root)
    block = (
        f"\n## [후보] [{candidate_id}]\n"
        f"- 대상: `{target_path}`\n"
        f"- 근거: 사유 '{stripped_reason}' 반복 {count}회 (`runs/*/events.jsonl`)\n"
        f"- 제안: {stripped_text}\n"
        "- 상태: pending\n"
    )
    with lessons_path.open("a", encoding="utf-8") as f:
        f.write(block)
    return candidate_id


# --- verify_improvement (3-4, M4) -------------------------------------------


def _find_candidate_block(candidate_id: str, project_root: Path) -> re.Match[str]:
    lessons_path = _lessons_path(project_root)
    if not lessons_path.exists():
        msg = f"lessons.md가 없습니다 — 후보 {candidate_id}를 찾을 수 없습니다."
        raise MemoryError(msg)
    text = lessons_path.read_text(encoding="utf-8")
    for match in _CANDIDATE_BLOCK_RE.finditer(text):
        if match.group(1) == candidate_id:
            return match
    msg = f"후보를 찾을 수 없음: {candidate_id}"
    raise MemoryError(msg)


def _parse_candidate(candidate_id: str, project_root: Path) -> dict[str, str]:
    match = _find_candidate_block(candidate_id, project_root)
    body = match.group(2)
    target_match = re.search(r"^- 대상: `([^`]+)`", body, re.MULTILINE)
    proposal_match = re.search(r"^- 제안: (.+)$", body, re.MULTILINE)
    return {
        "target_path": target_match.group(1) if target_match else "",
        "proposed_text": proposal_match.group(1).strip() if proposal_match else "",
    }


def verify_improvement(candidate_id: str, project_root: Path) -> dict[str, Any]:
    """Fixed, model-free before/after check for one pending candidate (3-4).

    Args:
        candidate_id: A `propose_improvement` result, e.g. `"L1"`.
        project_root: Repository root.

    Returns:
        `{"candidate_id", "target_path", "before", "after", "improved"}`.
        For an `AGENTS.md`/`memories` target, `before`/`after` are the count
        of known `[Rn]`/`[Ln]` ids without/with the candidate's own newly
        cited id(s); for a `skills` target they are `0`/`1` unless the
        proposed text is already present verbatim (then `1`/`1`,
        `improved=False`). `improved=False` means M4's "나빠지면 반영하지
        않는다" — this function only measures; it never writes the
        candidate's proposal anywhere.

    Raises:
        MemoryError: `candidate_id` does not exist.
    """
    candidate = _parse_candidate(candidate_id, project_root)
    target_path = candidate["target_path"]
    proposed_text = candidate["proposed_text"]

    if target_path.startswith(".deepagents/skills/"):
        target_file = project_root / target_path
        current_text = (
            target_file.read_text(encoding="utf-8") if target_file.exists() else ""
        )
        already_present = proposed_text in current_text
        before, after = (1, 1) if already_present else (0, 1)
        improved = not already_present
    else:
        before_ids = known_ref_ids(project_root)
        # The candidate's own `[Ln]` id already counts as "known" the moment
        # `propose_improvement` created it — excluding it here keeps this
        # scenario about whether the *proposed text* names something new
        # (M4), not about the bookkeeping id that always pre-exists itself.
        cited_ids = set(_RULE_TAG_RE.findall(proposed_text)) - {candidate_id}
        new_ids = cited_ids - before_ids
        before = len(before_ids)
        after = len(before_ids | new_ids)
        improved = bool(new_ids)

    return {
        "candidate_id": candidate_id,
        "target_path": target_path,
        "before": before,
        "after": after,
        "improved": improved,
    }


def update_candidate_status(
    candidate_id: str, project_root: Path, *, verified: bool, before: int, after: int
) -> None:
    """Rewrite one candidate's `- 상태:` line after `verify_improvement` (M4).

    Args:
        candidate_id: The candidate whose status line to update.
        project_root: Repository root.
        verified: `verify_improvement`'s `improved` result.
        before: `verify_improvement`'s `before` count, recorded for context.
        after: `verify_improvement`'s `after` count, recorded for context.

    Raises:
        MemoryError: `candidate_id` does not exist.
    """
    lessons_path = _lessons_path(project_root)
    text = lessons_path.read_text(encoding="utf-8")
    match = _find_candidate_block(candidate_id, project_root)
    new_label = (
        f"- 상태: verified (before={before}, after={after})"
        if verified
        else f"- 상태: rejected — 개선이 확인되지 않음 (before={before}, after={after})"
    )
    new_block = re.sub(
        r"^- 상태: .*$", new_label, match.group(0), count=1, flags=re.MULTILINE
    )
    new_text = text[: match.start()] + new_block + text[match.end() :]
    lessons_path.write_text(new_text, encoding="utf-8")
