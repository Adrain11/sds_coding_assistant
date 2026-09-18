# 단계 4 계획 리뷰 (2026-09-18, 🔵검토)

작성: 🔵검토 (Claude Opus 5, VDI)

검증 대상: `libs/code/deepagents_code/agent.py`, `assistant/assistant/{events,plan_gate}.py`,
`docs/plan/step3_result.md`, `README.md`, `.deepagents/` 트리 — 전부 `main`을 직접 읽음.

**전제 P3·P4·P5는 코드에 실재한다.** `gate_block`은 `plan_gate.py:537`에서 실제로 기록되고,
`_TCB_PATH_PREFIXES`는 `:79`에 있고, `memory_hit`/`improve_*`는 `events.py:76-78`에 예약돼 있다.
P1도 기본값이 켜져 있다 — `enable_memory=True`, `memory_auto_save=True` (`agent.py:2586-2587`).

**축소판으로 가는 판단도 옳다.** 시간이 하루뿐이고 §4의 순서를 우선순위로 쓴 것도 맞다.

아래 셋만 고치면 이 계획은 돌아간다. **R1과 R3은 착수 전에 정해야 한다.**

---

## 반드시 고쳐야 할 것

### 🔴 R1. `.deepagents/memories/*.md`는 dcode가 자동 로드하지 않는다 — MC1의 증거 경로가 틀렸다

**무엇이** — P1은 "dcode `MemoryMiddleware`가 `~/.deepagents/<id>/AGENTS.md` + 프로젝트
`AGENTS.md`를 매 세션 로드"라고 정확히 적었다. 그런데 §4-1은 규칙을
`.deepagents/memories/project_rules.md`에 시드하고, MC1(새 세션에서 규칙 적용)의 증거로 삼는다.

소스를 보면 로드 대상에 `memories/`가 없다 (`agent.py:3134-3141`):

```python
memory_sources = [str(get_user_agent_md_path(assistant_id))]
project_agent_md_paths = (
    project_context.project_agent_md_paths()
    if project_context is not None
    else get_project_agent_md_path(runtime_credentials.project_root)
)
memory_sources.extend(str(p) for p in project_agent_md_paths)
```

**`memory_sources`는 AGENTS.md 경로들뿐이다.** `.deepagents/memories/*.md`는 어디서도 안 들어간다.

**왜** — 지금 계획대로면 MC1이 실패한다. `project_rules.md`에 "타입힌트 필수"를 써도
새 세션의 시스템 프롬프트에 안 들어가므로 **적용되지 않는다.**
`memories/`를 로드시키려면 `memory_sources`에 추가해야 하는데, 그건 `agent.py` 수정이고
이 계획이 §2에서 "**`agent.py` 수정 0곳이 목표**"로 못 박은 것과 정면으로 부딪힌다
(그리고 범위 변경이 된다).

**어떻게** — `agent.py`를 건드리지 않고 **저장소를 두 층으로 나눈다.** 역할이 다르다:

| 저장소 | 성격 | 채점 |
|---|---|---|
| `.deepagents/AGENTS.md` | **규칙의 정본.** dcode가 자동 로드하고, `memory_auto_save=True`라 에이전트가 스스로 추가도 한다 | **3-1(세션 유지·적용)** |
| `.deepagents/memories/*.md` | **작업 경험 축적.** `search_memory`가 읽고 `memory_refs`가 인용하는 대상 | **3-2(검색·활용)** · 3-3(개선안 기록) |

→ 완료조건을 이렇게 쪼갠다:

- **MC1** (새 세션에서 적용) → 증거는 **`AGENTS.md`**. M-E1 절차는 그대로 두되,
  세션1에서 가르친 규칙이 `AGENTS.md`에 반영되는지를 본다 (auto-save가 켜져 있으니 된다)
- **MC2** (파일 잔존) → `memories/*.md` **와** `AGENTS.md` 둘 다

→ §4-1의 시드도 양쪽에 한다. `AGENTS.md`에 규칙 3~5줄(자동 로드용),
`memories/project_rules.md`에 같은 내용 + 인용 가능한 id(자동 로드는 안 되지만 `memory_refs`의 대상).

> **이 구분이 오히려 채점에 유리하다.** 3-1(저장·유지)과 3-2(검색·활용)가 서로 다른 항목인데,
> 지금 계획은 저장소 하나로 둘을 다 설명하려 해서 어느 쪽도 선명하지 않았다.
> 층을 나누면 "이 파일이 3-1, 저 파일이 3-2"로 채점자에게 바로 보인다.

### 🔴 R2. M4의 고정 시나리오는 **아무것도 측정하지 못한다** — 3-4가 증거 없이 끝난다

**무엇이** — M4는 이렇게 정한다:

> 고정 시나리오는 **모델을 부르지 않는 것**으로 한다 — 예: "이 계획이 게이트를 통과하는가"를
> `plan_gate`의 판정 함수로 직접 돌린다. 비결정적이지 않고, 빠르고, 채점자 키를 안 쓴다.

**왜** — 개선 대상 셋(M2)은 `memories/lessons.md` · `skills/plan-first/SKILL.md` ·
`AGENTS.md`다. **이 셋은 전부 모델의 행동에만 영향을 준다.** 그런데 `plan_gate`의 판정 함수는
메모리도 스킬도 AGENTS.md도 읽지 않는다 — 계획 상태와 `target_files`만 본다.

즉 개선안을 적용하든 말든 **before와 after가 항상 같은 값**이다.
→ MC6의 before/after 숫자가 무의미하고, V6("after가 before보다 나쁘면 반영 안 함")은
**절대 발동하지 않는다.** 3-4의 2점이 증거 없이 남는다.

**어떻게** — 공식 문구를 다시 보면 요구가 **둘**이다. 계획은 앞쪽만 다룬다:

> 3-4. 개선 **전후의 효과**와 **기존 기능의 정상 동작**을 검증하고, 통과한 개선안을 다음 작업에 반영

| | 무엇 | 결정적인가 | 모델 필요 |
|---|---|---|---|
| (i) 전후의 효과 | 모델 행동이 실제로 바뀌었나 | ❌ 비결정적 | ✅ 필요 |
| (ii) **기존 기능의 정상 동작** | 개선안을 넣고도 안 깨졌나 | ✅ **결정적** | ❌ 불필요 |

**(ii)가 결정적이고 싸고, 계획이 아예 안 다룬다.** 여기를 M4의 본체로 삼아라:

`verify_improvement(id)`가 한 번의 호출 안에서:

1. 개선안 **미적용** 상태로 회귀 스위트를 돌린다 → `before`
   - `pytest tests/ -q`의 통과/실패 수
   - 게이트 판정 스위트 (승인 없이 `write_file` → 차단 / 승인 후 `target_files` 안 → 통과 등 고정 케이스 N개)
2. 개선안을 **임시 적용**하고 같은 것을 돌린다 → `after`
3. `improve_end`에 before/after를 함께 기록
4. **하나라도 나빠지면 반영하지 않는다** (fail-closed — 게이트와 같은 원칙)

이러면 숫자가 실제로 움직인다. 예컨대 개선안이 `AGENTS.md`에 규칙을 넣다가 파일을 깨뜨리면
`pytest`나 게이트 판정이 바로 떨어진다. **그게 "기존 기능의 정상 동작" 검증이다.**

(i)은 모델이 필요하므로 **선택으로 내린다.** 하려면 "개선안 적용 후 같은 요청에서
계획의 `target_files`에 테스트가 포함되는가"를 1회 비교하고, **비결정적임을 로그와 문서에
명시**한다. 채점자 키를 쓰는 증거는 증거로 못 쓴다는 원칙(단계 2 §2)이 여기도 적용된다.

→ **MC6 문구를 고쳐라.** "before/after를 비교한 결과를 보여준다" →
"**회귀 스위트의 before/after 수치가 `improve_end`에 남고, 나빠지면 반영되지 않는다**".
그러면 달성 가능한 완료조건이 된다.

### 🔴 R3. 단계 3의 EC1~EC9가 확인되기 **전에** `create_plan` 시그니처를 바꾸면 안 된다

**무엇이** — `step3_result.md` 첫 줄:

> **구현 완료** 2026.09.17 · **TUI 완료조건(EC1~EC9)은 아직 👤사람 확인 대기**

그리고 M1은 `create_plan`에 `memory_refs`를 **필수 인자로** 추가한다.

**왜** — 두 곳이 깨진다.

1. **`README.md` §6 항목 2의 테스트 케이스 11개가 현재 시그니처 기준이다.** 케이스 6이
   필수 항목을 `requirements`/`scope`/`done_criteria`/`target_files`/`steps`/`test_plan` 여섯으로
   열거한다. `memory_refs`가 추가되면 이 목록이 틀린 문서가 된다
2. **EC6·EC8(승인 후 통과) 흐름이 막힌다.** 사람이 EC를 확인하려고 계획을 만들면
   `memory_refs`가 없다고 거부당한다. 그런데 그 시점에 `memories/`가 시드돼 있지 않으면
   인용할 것도 없다 — EC 확인 자체가 불가능해진다

계획 §8-1은 "단계 3 테스트가 여전히 통과하는가"를 보는데 그건 **단위 테스트**다.
TUI 확인은 사람 몫이라 계획이 놓쳤다.

**어떻게** — 둘 중 하나. 앞쪽을 권한다.

- **(a) EC1~EC9를 단계 4 착수 전에 끝낸다.** 지금 코드로 확인하고 `step3_result.md`를 닫는다.
  그 뒤에 시그니처를 바꾸고, README 케이스 6의 필수 목록에 `memory_refs`를 더한다.
  **확인 한 번 · 문서 수정 한 번**으로 끝난다
- (b) 단계 4를 먼저 하고 EC를 나중에 확인한다 → README 케이스를 **두 번** 고치고
  사람이 **두 번** 확인해야 한다. 시간이 하루뿐인데 이게 더 비싸다

→ §8 착수 전 확인에 **0번**을 추가하라: *"단계 3 EC1~EC9이 `step3_result.md`에서
닫혀 있는가. 아니면 멈추고 사람에게 확인을 요청한다."*

---

## 고려해볼 것

### 🟡 R4. `improve_verified`는 예약된 이벤트 타입이 아니다

M4 3번이 `improve_verified` 이벤트에 before/after를 기록한다고 한다.
그런데 `events.py:76-78`의 예약 목록은 셋뿐이다:

```python
MEMORY_HIT = "memory_hit"      # Step 4
IMPROVE_START = "improve_start" # Step 4
IMPROVE_END = "improve_end"     # Step 4
```

`improve_verified`는 없다. P5가 "`report.py`를 안 고쳐도 된다"고 한 근거가 여기서 깨진다.

→ **`improve_end`에 담아라.** `status="verified"`/`"rejected"`와 before/after를 `data`에 넣으면
새 상수도, `report.py` 수정도 필요 없다. 정말 별도 타입이 필요하면 `events.py`에 상수를
추가하되 **그건 단계 2 산출물 수정**이라 결과 문서에 남겨야 한다.

### 🟡 R5. P2의 근거 `handoff.md`가 저장소에 없다

P2가 "이미 실측된 사실 — 세션1에서 '타입힌트 붙이고 기억해' → 세션2에서 자동 적용
(`handoff.md` §4 R3)"을 든다. 그런데 `docs/plan/handoff.md`가 **없다.**
`PLAN.md` 단계 1의 이식 표에서 "대체 (전제가 바뀜)"으로 버리기로 한 문서다.

사실 자체는 맞을 수 있지만 **채점자가 추적할 수 없는 인용**이다.
3-1이 "이미 한 번 증명됐다"는 주장의 근거가 비어 있으면, MC1을 실제로 다시 확인해야 한다.

→ M-E1을 **반드시 수행하고** 그 결과를 `step4_result.md`에 남긴다. P2는 "과거에 비슷한 것을
봤다"는 참고로만 남기고, 인용은 지우거나 "문서 없음(이월되지 않음)"으로 표시한다.

---

## 계획대로 두는 게 맞다고 본 것

- **M1 (`memory_refs` 필수 인자)** — 맞다. 단계 3 D2와 같은 수법이고, "활용했다고 말하는 것"과
  "활용하지 않으면 진행이 안 되는 것"의 구분이 이 프로젝트 전체를 관통하는 원칙이다.
  **존재 검증으로 지어낸 인용을 막는 것**까지 좋다 — 그게 없으면 모델이 그럴듯한 파일명을 만든다.
  3-2와 4-2를 한 번에 채우는 것도 맞다
- **M2 (개선 대상을 셋으로 명시)** — 맞다. 공식 3-3이 "시스템 프롬프트·Skills·작업 메모리 등"으로
  대상을 특정하므로, "개선안을 만든다"로는 채점자가 무엇이 바뀌었는지 못 본다.
  **파일까지 짝지어 표로 만든 것**이 정확하다
- **M3 (자동 적용 금지)** — 맞다. 단계 3의 "자기 승인 불가"와 같은 원칙이고,
  공식 3-4가 "**통과한** 개선안을 반영"이라 검증 없는 자동 반영은 오히려 감점이라는 판단이 옳다
- **M5 (TCB 재사용)** — 맞다. `_TCB_PATH_PREFIXES`가 이미 `plan_gate.py:79`에 있으니
  새로 만들 게 없다. 자기개선이 테스트를 지워 통과율을 올리는 것을 막는 것이 6일차 TCB의 핵심이다
- **임계치 3회** — 맞다. 한 번의 실패로 개선안을 만들면 잡음이 쌓인다
- **임베딩·벡터 검색을 범위 밖으로 둔 것** — 맞다. 파일 몇 개에 문자열 검색으로 충분하고,
  과설계는 하루짜리 일정에서 치명적이다
- **`agent.py` 수정 0곳을 목표로 둔 것** — 맞다. 도구를 `PlanGateMiddleware`에 얹는 방식은
  S14로 이미 검증됐다. 다만 R1 때문에 이 목표가 위태로워지니 R1의 두 층 분리로 지켜라
- **§4의 순서를 우선순위로 쓴 것** — 맞다. 1·2·3번(3-1·3-2, **5점**)을 먼저 끝내고 커밋하는
  전략이 시간 제약에 맞다. 3-3·3-4를 "가장 싼 형태로"라고 미리 정한 것도 정직하다
- **P3·P4·P5 전부 코드에서 확인됨** — `gate_block`(`plan_gate.py:537`),
  `_TCB_PATH_PREFIXES`(`:79`), `memory_hit`/`improve_*`(`events.py:76-78`).
  P1의 기본값도 확인 — `enable_memory=True`, `memory_auto_save=True`(`agent.py:2586-2587`)

---

## 정리

| | 내용 | 비용 |
|---|---|---|
| 🔴 **R1** | `memories/`는 자동 로드 안 됨 → **AGENTS.md(3-1) / memories(3-2)** 두 층으로. MC1·MC2 증거 분리 | 문구 + 시드 위치 |
| 🔴 **R2** | M4의 고정 시나리오가 측정 불가 → **회귀 검사(결정적)를 본체로**, 효과는 선택. MC6 문구 정정 | 설계 변경 |
| 🔴 **R3** | **EC1~EC9를 단계 4 착수 전에 닫아라.** §8에 0번 추가 | 순서 |
| 🟡 **R4** | `improve_verified` → `improve_end`에 담기 | 한 줄 |
| 🟡 **R5** | `handoff.md` 인용 제거, M-E1을 실제로 수행 | 문구 |

**R3이 시간 면에서 가장 급하다** — 순서를 잘못 잡으면 사람이 TUI 확인을 두 번 하고
README를 두 번 고친다. 하루짜리 일정에서 그게 제일 비싸다.
**R2는 점수 면에서 가장 크다** — 지금 설계로는 3-4의 2점이 증거 없이 남는다.
