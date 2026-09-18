# Coding Assistant (dcode) — 프로젝트 규칙

이 파일은 이 저장소 루트에서 `dcode`를 실행할 때마다 항상 로드되는 프로젝트 메모리입니다.
(전역/개발 도구 레벨 규칙은 `CLAUDE.md`에 따로 있음 — 이 파일은 dcode 앱 레벨 규칙만 담습니다.)

## 계획 게이트 (Step 3)

- **[R1]** `write_file`·`edit_file`·`delete`·`task`는 승인된 계획이 없으면 코드로 차단된다.
  이건 훅(`.deepagents/hooks.json`)이 아니라 `libs/code/deepagents_code/agent.py`에 배선된
  `PlanGateMiddleware`(소스: `assistant/assistant/plan_gate.py`)가 한다 — 이전에 이 파일이
  말하던 `hooks/pep8_gate.py` 기반 강제는 이 저장소에 없다 (step0 실측 결과 훅은
  `write_file`만 막고 `execute`로 쉽게 우회됐다).
- **[R2]** `execute`(셸)는 승인 후에도 **항상** 차단된다 — 셸이 열리면 사람만 할 수 있는
  승인을 에이전트가 대신할 수 있게 되기 때문이다.
- 절차는 `.deepagents/skills/plan-first/SKILL.md`를 따른다: `create_plan`(`memory_refs` 필수,
  아래 "메모리" 절 참고) → `review_plan` → (필요하면 `revise_plan`) → 사람이
  `python -m assistant.plan_gate approve <plan_id>`로 승인. 승인 도구는 에이전트에게 없다 —
  어떤 이름으로도 없다.
- **[R3]** 승인된 계획의 `target_files` **밖**을 고치려 하면 다시 차단되고 계획이 `draft`로
  되돌아간다. 더 넓은 범위가 필요해지면 차단당하기 전에 `revise_plan`으로 먼저 넓혀라.
- **[R4]** 게이트 자신(`assistant/assistant/plan_gate.py`·`plans.py`·`memory.py`),
  로거(`events.py`·`observability.py`), 테스트(`tests/**`), 원본 코드(`libs/**`)는 계획에
  적혀 있어도 항상 차단된다 (TCB, 자기개선도 이 목록은 못 건드린다 — 아래 "메모리" 절 M5).

## 코드 스타일

- **[R5]** 모든 Python 코드는 PEP8을 따른다. 단계 5에서 ruff 기반 검사가 추가되기 전까지는
  스스로 PEP8을 지킬 것 — 지금은 강제하는 코드가 없다.

## 작업 전 리뷰 워크플로우

- 여러 단계가 필요한 작업은 시작 전에 `/goal add <목표>`로 acceptance criteria 초안을 먼저
  만들고, 사용자 리뷰(accept/edit/revise)를 받은 뒤에 작업을 시작한다. (이건 위 계획 게이트와
  별개다 — `/goal`은 dcode 자체의 목표 추적 기능이고, 계획 게이트는 쓰기·실행 도구를 코드로
  차단하는 이 프로젝트의 강제 장치다. 둘 다 따른다.)
- YOLO 모드로 리뷰를 건너뛰지 않는다. 헤드리스/비대화형 실행(`-n`)에서는 `--rubric "..."`으로
  대체한다.

## 메모리 (Step 4, Self-Improving)

- **계획을 세우기 전에 `search_memory(query)`를 부른다.** 위 규칙 절의 `[R1]`..`[R5]`와
  `.deepagents/memories/lessons.md`의 개선 후보(`[L1]`..)를 검색한다.
- **`create_plan`은 `memory_refs`가 비어 있거나 지어낸 id면 거부된다** — 실제로 존재하는
  `[Rn]`/`[Ln]` id만 인용할 수 있다 (`assistant/assistant/plan_gate.py`, `memory.py`).
  "메모리를 참고했다"는 말이 아니라 검증 가능한 인용이어야 통과한다.
- 반복되는 실패(`gate_block`·도구 실패, 같은 사유로 3회 이상)는 `propose_improvement`로
  개선 **후보**를 만들 수 있다. 대상은 `.deepagents/AGENTS.md` · `.deepagents/memories/` ·
  `.deepagents/skills/` 셋뿐이다 — 게이트·로거·테스트·원본 코드(위 TCB, `[R4]`)는 자기개선도
  못 건드린다.
- 후보는 사람이 검토해서 실제 규칙 절로 옮기기 전까지 **적용되지 않는다.**
  `verify_improvement(candidate_id)`로 같은 실행 안에서 전/후를 비교해볼 수 있지만, 이것도
  검증일 뿐 반영이 아니다.
- 사용자가 컨벤션/선호/실수 교정을 알려주면 `/remember`로 명시적으로 저장하거나, 자동 메모리
  저장(memory.auto_save)에 맡긴다 — 이건 dcode 자체 기능으로 `.deepagents/AGENTS.md`에 쓴다.
  같은 피드백을 반복해서 받지 않도록 한다.

## 모니터링

- LangSmith 트레이싱이 켜져 있으면(`.env`의 `LANGSMITH_TRACING=true`) 모든 작업은 자동으로
  추적된다. 비용이 크거나 오래 걸리는 작업 뒤에는 `/cost`, `/tokens`로 확인해 볼 것.

## 참고 문서

- 평가 기준 ↔ 구현 매핑: `docs/evaluation-mapping.md`
- 실행 방법: 저장소 루트 `README.md`
