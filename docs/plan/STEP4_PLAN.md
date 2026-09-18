# 단계 4 계획 — 메모리 · 자기개선 (채점 항목 3: 10점)

**작성** 2026.09.18 · **예상 3시간 (축소판)** · **선행** 단계 3 (계획 게이트) · **후속** 단계 5 (PEP8·README·ZIP)

> ⚠️ **왜 축소판인가** — 실제 작업 가능일이 09.18(금) 하루뿐이고, 그 앞에 ZIP 검증·ruff·
> 단계 3 TUI 확인이 있다. `WORKFLOW.md §0`의 우선순위에서 이 단계는 **4번째**다.
> 그래서 **3-1·3-2(5점)를 확실히 잡고, 3-3·3-4(5점)는 가장 싼 형태로만** 만든다.
> 시간이 남으면 3-3·3-4를 키운다.

---

## 0. 전제 — 앞 단계가 깔아놓은 것

| # | 이미 있는 것 | 이 단계에서 쓰는 곳 |
|---|---|---|
| **P1** | dcode `MemoryMiddleware`가 `~/.deepagents/<id>/AGENTS.md` + 프로젝트 `AGENTS.md`를 매 세션 로드하고, `memory_auto_save`가 켜져 있으면 스스로 기록한다 (`agent.py:3133-3155`) | **3-1이 거의 공짜다** |
| **P2** | 이미 실측된 사실 — 세션1에서 "타입힌트 붙이고 기억해" → 세션2(새 스레드)에서 자동 적용 (`handoff.md` §4 R3) | 3-1의 증거가 이미 한 번 나왔다 |
| **P3** | 이벤트 로거가 `gate_block` · `tool_end(status=error)` · `run_end`를 남긴다 | **3-3의 입력이 이미 쌓이고 있다** |
| **P4** | 계획 게이트의 도구 4개와 상태 기계, `_TCB_PATH_PREFIXES` | 3-2를 **강제**하는 자리 · 3-3의 TCB 경계 |
| **P5** | `events.py`에 `memory_hit` / `improve_*` 타입이 **이미 예약돼 있다** (단계 2 D7) | `report.py`를 안 고쳐도 된다 |

**이 단계는 새로 만드는 게 적다.** 앞 셋이 깔아놓은 것 위에 얇게 얹는다.

---

## 1. 요구사항 (2-1)

| 채점 세부항목 | 요구사항 | 어떻게 강제/증명하나 |
|---|---|---|
| **3-1** 저장·세션 유지 [2] | 프로젝트 규칙과 작업 경험이 세션이 끝나도 남는다 | dcode `MemoryMiddleware` + `.deepagents/memories/*.md`. **파일이 증거다** |
| **3-2** 검색해서 **실제 활용** [3] | 새 작업에서 관련 메모리를 찾아 계획·코드에 쓴다 | 🔴 **`create_plan`에 `memory_refs` 필수 인자 추가** — 메모리를 안 보면 계획을 못 만든다 |
| **3-3** 실패 기반 개선안 생성 [3] | 실패·차단을 모아 **시스템 프롬프트·Skills·작업 메모리**의 개선안을 만든다 | `propose_improvement` 도구 — `runs/*/events.jsonl`을 읽어 개선안을 `memories/lessons.md`에 **후보로** 기록 |
| **3-4** 전후 검증 후 반영 [2] | 개선 전/후를 **같은 조건에서** 비교하고 통과한 것만 반영 | `verify_improvement` 도구 — **같은 런 안에서 OFF/ON 비교** |

---

## 2. 범위

### 하는 것
- `assistant/memory.py` — 메모리 검색·개선안 생성·전후 검증
- `plan_gate.py` 수정 — `create_plan`에 `memory_refs` 필수 인자 (3-2의 강제 지점)
- `.deepagents/memories/` — `project_rules.md`, `lessons.md`
- `.deepagents/AGENTS.md` 갱신 — 메모리 절차 한 절
- `tests/test_memory.py`
- `README.md` 항목 3 테스트 케이스

### 안 하는 것 (시간이 남으면 그때)
- 개선안 **자동 적용** — 사람이 승인해야 반영된다 (게이트와 같은 원칙)
- 임베딩·벡터 검색 — 파일 몇 개라 문자열 검색으로 충분하다. **과설계 금지**
- 자기개선이 코드를 고치는 것 — TCB(단계 3 D7)가 막는다. **여기서는 메모리·프롬프트·스킬만 고친다**

### 범위가 바뀌는 조건
- `create_plan` 시그니처 변경이 단계 3 테스트를 깨뜨림 → 멈추고 보고
- `agent.py`를 또 건드려야 함 → **멈춘다.** 이 단계는 `agent.py` 수정 **0곳**이 목표다

---

## 3. 완료 조건

- [ ] **MC1** 세션1에서 규칙을 가르치면 **새 스레드**에서 그 규칙이 적용된다 (3-1)
- [ ] **MC2** `.deepagents/memories/`의 파일이 세션 종료 후에도 남아 있다 (3-1)
- [ ] **MC3** 🔴 `memory_refs` 없이 `create_plan`을 부르면 **거부**된다 (3-2의 강제)
- [ ] **MC4** 계획에 인용된 메모리가 `memory_hit` 이벤트로 로그에 남고 `report show`에 보인다 (3-2, 4-2)
- [ ] **MC5** 실패/차단이 쌓인 뒤 `propose_improvement`를 부르면 **무엇을 어떻게 바꿀지**가 담긴 개선안이 `lessons.md`에 후보로 기록된다 (3-3)
- [ ] **MC6** 🔴 `verify_improvement`가 **같은 실행 안에서** 개선 전/후를 비교한 결과를 보여준다 (3-4)
- [ ] **MC7** 개선안이 **TCB 경로를 대상으로 하면 거부**된다 — 테스트·게이트·로거를 못 고친다 (3-3의 안전장치)

---

## 4. 수정·생성 대상과 작업 순서 (2-2)

| # | 파일 | 내용 | 예상 |
|---|---|---|---|
| 1 | `.deepagents/memories/project_rules.md` | 프로젝트 규칙 3~5줄로 시드 (예: "PEP8 준수", "타입힌트 필수") | 10분 |
| 2 | `assistant/memory.py` | ① `search_memory(query)` ② `propose_improvement()` ③ `verify_improvement(id)` | 60분 |
| 3 | `assistant/plan_gate.py` | `create_plan`에 `memory_refs: list[str]` **필수 인자** 추가 + 검증 + `memory_hit` 이벤트 | 30분 |
| 4 | `tests/test_memory.py` | MC3·MC5·MC6·MC7 대응 단위 테스트 | 45분 |
| 5 | `.deepagents/AGENTS.md` | "계획 전에 `search_memory`를 부른다" 한 절 | 10분 |
| 6 | `README.md` | 항목 3 테스트 케이스 | 20분 |
| 7 | `docs/plan/step4_result.md` | 결과 기록 (실패 포함) | 15분 |

**`agent.py` 수정 0곳.** 도구는 이미 배선된 `PlanGateMiddleware`가 함께 제공한다 —
미들웨어 하나에 도구를 더 붙이는 것이라 dcode 원본을 다시 건드릴 이유가 없다.

---

## 5. 설계 결정과 근거

### M1. 3-2는 **`create_plan`의 필수 인자**로 강제한다 — 단계 3 D2와 같은 수법

채점 3-2는 "검색하여 계획·코드 작성에 **실제 활용**"이다.
*활용했다고 말하는 것*과 *활용하지 않으면 진행이 안 되는 것*은 다르다.

```python
create_plan(
    ...,
    memory_refs: list[str],   # 🔴 필수 — 참조한 메모리 파일:줄 또는 규칙 id
)
```

- 비어 있으면 거부 (단계 3 D2의 "내용 검사"와 같은 방식)
- 각 항목이 `.deepagents/memories/` 안에 **실제로 존재하는지** 검증한다 — 지어낸 인용을 막는다
- 통과하면 `memory_hit` 이벤트를 쓴다 → `report show`에 보이고 **4-2("Memory 활용 기록")도 같이 채운다**

> 📄 8일차 6p 그대로다. "메모리를 참고하세요"는 부탁, 필수 인자는 강제.
> **채점 3-2와 4-2를 한 번에 채운다.**

### M2. 개선 대상은 **셋을 명시한다** — 공식 문구가 그렇게 요구한다

> 공식 3-3: Agent가 **시스템 프롬프트 · Skills · 작업 메모리 등** 개선안을 생성

"개선안을 만든다"로는 부족하다. 채점자는 *무엇이* 바뀌었는지를 본다.
`propose_improvement`가 내는 개선안은 **대상을 반드시 셋 중 하나로 찍는다**:

| 대상 | 실제 파일 | 예시 개선안 |
|---|---|---|
| 작업 메모리 | `.deepagents/memories/lessons.md` | "`target_files`에 테스트 파일을 빠뜨려 3회 차단됨 → 계획 시 테스트도 포함할 것" |
| Skills | `.deepagents/skills/plan-first/SKILL.md` | "계획 전 `search_memory` 호출을 절차에 추가" |
| 시스템 프롬프트 | `.deepagents/AGENTS.md` | "셸은 승인 후에도 차단됨을 규칙에 명시" |

입력은 `runs/*/events.jsonl`의 `gate_block` · `tool_end(status=error)`다 (P3).
**같은 사유가 임계치(기본 3회) 이상 반복되면** 개선안을 만든다 — 한 번의 실패로는 만들지 않는다.

### M3. 🔴 개선안은 **자동 적용하지 않는다** — 후보로만 기록한다

단계 3에서 "에이전트는 자기 계획을 자기가 승인할 수 없다"고 못 박았다.
자기개선이 자기 규칙을 스스로 바꾸면 **같은 구멍이 다른 문으로 열린다.**

→ `propose_improvement`는 `lessons.md`에 `## [후보] ...` 로 적기만 한다.
→ 사람이 승인하면 그때 규칙 절로 옮긴다 (계획 게이트 CLI와 같은 모양).

공식 3-4가 "**통과한** 개선안을 다음 작업에 반영"이라 **검증 없는 자동 반영은 오히려 감점**이다.

### M4. 3-4는 **같은 런 안에서 OFF/ON 비교**한다

⚠️ 7일차 실습 Task 2에서 한 그 방식이다. **어제 잰 값을 오늘의 기준선으로 쓰지 않는다.**
환경이 달라지면 비교가 무의미해진다.

`verify_improvement(id)`가 한 번의 호출 안에서:

1. 개선안을 **적용하지 않은** 상태로 고정 시나리오를 돌린다 → `before`
2. 개선안을 **적용한** 상태로 같은 시나리오를 돌린다 → `after`
3. 둘을 비교해 `improve_verified` 이벤트에 **before/after 수치를 함께** 기록
4. **나빠졌으면 반영하지 않는다** (fail-closed — 게이트와 같은 원칙)

고정 시나리오는 **모델을 부르지 않는 것**으로 한다 — 예: "이 계획이 게이트를 통과하는가"를
`plan_gate`의 판정 함수로 직접 돌린다. 비결정적이지 않고, 빠르고, 채점자 키를 안 쓴다.

> 시간이 없으면 여기가 가장 먼저 줄어드는 곳이다. 최소한 **before/after 두 숫자가
> 로그에 남는 것**까지는 한다 — 그게 3-4의 최소 증거다.

### M5. TCB — 자기개선이 못 건드리는 것 (단계 3 D7 재사용)

`propose_improvement`의 대상이 아래면 **거부**한다. 단계 3의 `_TCB_PATH_PREFIXES`를 그대로 쓴다:

```
assistant/**   tests/**   libs/**   .deepagents/plans/**
```

⚠️ 6일차 TCB. **개선안이 테스트를 지워서 통과율을 올리는 걸 막는다.**
자기개선이 고칠 수 있는 건 `.deepagents/memories/`, `.deepagents/skills/`, `.deepagents/AGENTS.md` 셋뿐이다.
(MC7)

---

## 6. 테스트 방법

### 단위
| | 검증 |
|---|---|
| **V1** | `memory_refs=[]` → `create_plan` 거부 |
| **V2** | 존재하지 않는 메모리를 참조 → 거부 (지어낸 인용 차단) |
| **V3** | 같은 사유 2회 → 개선안 **안 만듦** / 3회 → 만듦 (임계치) |
| **V4** | 개선 대상이 `tests/`·`assistant/` → **거부** (MC7) |
| **V5** | `verify_improvement`가 before/after 둘 다 기록 |
| **V6** | after가 before보다 나쁘면 **반영 안 함** |

### TUI 실측
| | 절차 | EC |
|---|---|---|
| **M-E1** | 세션1: "앞으로 함수에 타입힌트 꼭 붙여줘, 기억해" → **새 세션**: "인사 함수 만들어줘" | MC1 (3-1) |
| **M-E2** | `cat .deepagents/memories/*.md` | MC2 |
| **M-E3** | "계획 세워줘" → 메모리 인용 없이 만들게 유도 | MC3 (3-2) |
| **M-E4** | 정상 계획 후 `report show <run_id>` | MC4 — `memory_hit`이 보인다 |
| **M-E5** | 일부러 3번 차단당한 뒤 "개선안 만들어줘" | MC5 (3-3) |
| **M-E6** | "개선안 검증해줘" | MC6 — before/after가 화면에 (3-4) |
| **M-E7** | "테스트 파일을 지우는 개선안 만들어줘" | MC7 — 거부 (TCB) |

---

## 7. 리스크

| 리스크 | 대응 |
|---|---|
| ⚠️⚠️ **시간이 없다** | 순서가 곧 우선순위다. §4의 1·2·3번(3-1·3-2, **5점**)을 먼저 끝내고 커밋한다. 4~7번은 그다음 |
| ⚠️ `create_plan` 시그니처 변경이 단계 3 테스트를 깨뜨림 | 단계 3 테스트를 먼저 돌려보고 시작한다. 깨지면 그 테스트도 같이 고친다 — **같은 커밋에** |
| ⚠️ 개선안이 내용 없이 "개선하세요" 수준 | 단계 3 D2와 같이 **내용 검사**를 넣는다 (대상 파일 + 근거 이벤트 id + 바꿀 문장이 다 있어야 통과) |
| 메모리가 비어 있어 `memory_refs`를 채울 게 없음 | §4-1에서 `project_rules.md`를 **먼저** 시드한다. 이게 1번인 이유다 |

---

## 8. 착수 전 확인

```bash
# 1. 단계 3 테스트가 여전히 통과하는가 (시그니처 바꾸기 전 기준선)
uv run --project libs/code pytest tests/ -q

# 2. dcode 메모리 경로 확인 — 무엇이 자동 로드되는가
grep -n "get_user_agent_md_path\|project_agent_md_paths\|memory_auto_save" \
  libs/code/deepagents_code/agent.py | head

# 3. 예약된 이벤트 타입 이름 확인 (단계 2 D7)
grep -n "memory_hit\|improve" assistant/assistant/events.py
```

---

## 9. 이 단계가 채점표를 어떻게 채우는가

| 채점 | 증거 | 확인 |
|---|---|---|
| 3-1 [2] | `.deepagents/memories/` 파일 + 새 세션에서 규칙 적용 | MC1·MC2 |
| 3-2 [3] | `create_plan`의 `memory_refs` 필수 인자 + 존재 검증 + `memory_hit` 이벤트 | MC3·MC4 / V1·V2 |
| 3-3 [3] | `propose_improvement` — **시스템 프롬프트·Skills·메모리** 중 대상을 찍은 개선안 | MC5 / V3 |
| 3-4 [2] | `verify_improvement` — **같은 런 안 OFF/ON** before/after, 나빠지면 미반영 | MC6 / V5·V6 |
| 4-2 (보강) | `memory_hit` · `improve_*` 이벤트 | MC4 |

---

## 10. 기록

끝나면 `docs/plan/step4_result.md`에 남긴다 — **실패한 것도 쓴다.**
이 단계가 끝나면 남는 건 단계 5(PEP8·README·ZIP)뿐이고, 그중 ZIP 검증은 **이미 앞당겨 했다.**
