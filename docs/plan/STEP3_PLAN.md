# 단계 3 계획 — 계획 게이트 (채점 항목 2: 10점)

**작성** 2026.09.17 · **예상** 5시간 · **선행** 단계 2 (이벤트 로거) · **후속** 단계 4 (메모리·자기개선)

> 강사가 수업에서 가장 강조한 부분이다.
> 🎤 *"최종 ok된 계획만 개발에 쓰이도록 해야 한다. 그 외 개발작업이 되면 제대로 구현 못한 것이다. 통제가 필요하다."*

---

## 0. 실측한 사실 (이 계획의 근거)

단계 2에서 확인한 것에 더해, 이 단계에 필요한 것만 새로 확인했다.

| # | 사실 | 출처 |
|---|---|---|
| **S14** | **미들웨어가 도구를 제공할 수 있다.** `AskUserMiddleware()`를 만든 뒤 `ask_user_middleware.tools[0]`으로 그 도구를 꺼내 쓴다 | `agent.py:3124-3126` |
| **S15** | HITL 승인 계층이 이미 있다 — `AsyncApprovalHITLMiddleware(resolved_interrupt_on)`, `create_deep_agent(interrupt_on=...)` | `agent.py:3438`, `:3754` |
| **S16** | 셸 도구 이름은 `execute`. 인자는 `{"command": ...}` | `agent.py:937-941` (`ShellAllowListMiddleware`) |
| **S17** | 차단은 `handler`를 부르지 않고 `status="error"` `ToolMessage`를 돌려주면 된다. 그래프가 멈추지 않아 trace가 한 run으로 유지된다 | `agent.py:948-957`, `:977` |
| S3·S4 | `wrap_tool_call` / **`awrap_tool_call`** 둘 다 필요 (서버 그래프는 async) | `agent.py:960`, `:979` |
| S2 | custom 리스트 안에서 앞쪽 = 바깥쪽 | `agent.py:3063-3066`, `graph.py:229-231` |

### 🔴 step0에서 확인된, 이 단계가 반드시 막아야 할 것

step0 실측에서 **훅은 `write_file`만 막았고, 셸로 우회됐다.**

> 에이전트: *"이 파일은 훅을 우회해 만든 것이라 ruff 기준 위반 2건이 남아 있습니다."*

모델은 우회 가능하다는 걸 **알고 있었고**, `AGENTS.md`가 말렸을 뿐이다. 명시적 지시 한 번에 넘어갔다.
→ 📄 8일차 19p: **"ALLOW가 없는 실행 경로가 존재하지 않게 만드는 것이 핵심입니다."**

---

## 1. 요구사항 (2-1)

**승인된 계획 없이는 코드가 바뀌지 않는다.** 계획은 형식을 갖춰야 하고, 리뷰를 거쳐야 하고,
승인 범위를 벗어나면 다시 검토받아야 한다.

| 채점 세부항목 | 요구사항 | 어떻게 강제하나 |
|---|---|---|
| **2-1** 요구사항·범위·완료조건 정의 [2] | 계획에 이 셋이 반드시 들어간다 | **도구 인자 스키마의 필수 필드** |
| **2-2** 수정대상·작업순서·테스트방법 [3] | 계획에 이 셋이 반드시 들어간다 | **도구 인자 스키마의 필수 필드** |
| **2-3** AI 리뷰 + 반영 절차 [3] | 리뷰를 안 거친 계획은 승인 대상이 못 된다 | **상태 기계 — `reviewed` 없이 `approved`로 못 간다** |
| **2-4** 승인 후에만 변경, 범위 변경 시 재검토 [2] | 승인 전에는 쓰기·실행 도구 전부 차단. 승인 후에도 **계획에 적힌 파일만** | **`wrap_tool_call` 차단** |

## 2. 범위

### 하는 것
- `assistant/plan_gate.py` — 차단 미들웨어 + 계획 도구 4개
- `assistant/plans.py` — 계획 저장·상태 기계
- `.deepagents/skills/plan-first/SKILL.md` — 절차 안내 (지침 층)
- `.deepagents/AGENTS.md` 갱신 — 훅 기반 옛 문장 제거
- 차단 경로 테스트 (`tests/test_plan_gate.py`)
- `report.py`에 계획 구획 채우기 (단계 2에서 자리만 잡아둔 곳)

### 안 하는 것
- 메모리 검색을 계획에 엮기 → 단계 4 (3-2)
- 실패 기반 개선안 → 단계 4
- PEP8 검사 → 단계 5
- 계획 문서를 사람이 편집하는 UI — 도구와 CLI로 충분하다

### 범위가 바뀌는 조건 (2-4를 우리 자신에게도 적용)
- 미들웨어가 도구를 제공하는 방식(S14)이 실제로 안 됨 → §5 D3-b 대안
- TUI에서 HITL interrupt가 안 뜸 → §5 D4 대안 (이미 준비돼 있다)
- `agent.py` 수정이 **1곳을 넘어감** → 멈추고 INBOX에 올린다

## 3. 완료 조건

전부 **TUI에서** 확인한다.

- [ ] **EC1** 승인된 계획 없이 `write_file`을 시키면 **차단**되고, 화면에 사유가 보인다
- [ ] **EC2** 🔴 승인된 계획 없이 **`execute`로 파일을 만들게 시키면 차단된다** — *step0에서 뚫렸던 그 경로*
- [ ] **EC3** 🔴 **`/mode yolo`에서도 EC1·EC2가 동일하게 차단된다** (승인 모드와 독립)
- [ ] **EC4** 필수 필드를 빠뜨린 계획은 `create_plan`이 거부한다 (2-1·2-2)
- [ ] **EC5** 리뷰를 건너뛰고 승인하려 하면 거부된다 (2-3)
- [ ] **EC6** 승인 후, 계획의 `target_files` **안**의 파일은 수정된다
- [ ] **EC7** 승인 후, `target_files` **밖**의 파일을 고치려 하면 차단되고 **재검토를 요구**한다 (2-4)
- [ ] **EC8** 게이트·로거·테스트 파일 자신을 고치려 하면 차단된다 (TCB)
- [ ] **EC9** `report show <run_id>`에 `plan_created` → `plan_reviewed` → `plan_approved` → `code_changed`가 순서대로 보이고, 차단은 `gate_block`으로 남는다 (4-1)

## 4. 수정·생성 대상과 작업 순서 (2-2)

| # | 파일 | 신규/수정 | 내용 | 예상 |
|---|---|---|---|---|
| 1 | `assistant/plans.py` | 신규 | 계획 자료구조 + 상태 기계 + 파일 저장/조회 | 45분 |
| 2 | `tests/test_plans.py` | 신규 | 상태 전이 단위 테스트 (특히 **불법 전이 거부**) | 30분 |
| 3 | `assistant/plan_gate.py` | 신규 | ① 도구 4개 ② `PlanGateMiddleware` (sync/async `wrap_tool_call`) | 90분 |
| 4 | `tests/test_plan_gate.py` | 신규 | **차단 경로 테스트** — 아래 §6 | 60분 |
| 5 | `libs/code/deepagents_code/agent.py` | **수정 (1곳)** | `agent_middleware`의 `EventLoggerMiddleware` **바로 뒤**에 `PlanGateMiddleware(_ev)` 삽입 | 10분 |
| 6 | `.deepagents/skills/plan-first/SKILL.md` | 신규 | 절차 안내 (지침 층) | 30분 |
| 7 | `.deepagents/AGENTS.md` | 수정 | 훅 기반 문장 제거, 게이트 규칙으로 교체 | 20분 |
| 8 | `assistant/report.py` | 수정 | 계획 구획 채우기 | 20분 |
| 9 | `README.md` | 수정 | 항목 2 테스트 케이스 (**YOLO 포함**) | 30분 |
| 10 | `docs/plan/step3_result.md` | 신규 | 결과 기록 (실패 포함) | 20분 |

**5번이 dcode 원본을 건드리는 유일한 곳. import 1줄 + insert 1줄.**

### 삽입 위치가 왜 로거 바로 뒤인가

로거가 가장 바깥, 게이트가 그다음이다. 이 순서라야 **게이트가 차단한 것도 로거가 본다.**
게이트가 바깥이면 차단된 호출이 로그에 안 남고, 그러면 4-2("도구 실행의 결과와 **오류** 기록")와
2-4의 증거가 동시에 사라진다.

---

## 5. 설계 결정과 근거

### D1. 차단 대상은 **도구**이지 명령 문자열이 아니다

step0 결론 그대로다. 셸 명령을 파싱해서 막는 건 불완전하다 — `echo`, `cat >`, `python -c`,
`sed -i`, `tee`, `dd`, `>>`… 끝이 없다.

→ **승인된 계획이 없으면 `write_file` · `edit_file` · `execute`를 전부 차단**하고,
읽기·검색 도구(`read_file`, `grep`, `glob`, `ls`)와 계획 도구만 통과시킨다.

| 상태 | 허용 |
|---|---|
| 계획 없음 / 초안 / 리뷰됨 | 읽기·검색 + 계획 도구 |
| **승인됨** | 위 + 쓰기·실행 (단 `target_files` 안에서만) |

`execute`는 승인 후에도 위험하다 — 셸로는 어떤 파일이든 건드릴 수 있어 `target_files` 제한이
의미가 없다. **승인된 계획이 `allow_shell: true`를 명시한 경우에만** 통과시킨다(기본 false).
계획에 적혀 있으면 사람이 승인하며 본 것이다.

### D2. 2-1·2-2는 **도구 인자 스키마**로 강제한다 — 스킬은 보조다

📄 8일차 6p: *지침만 있는 Agent → 금지 지침 → 모델이 제안 → API가 그대로 실행.*
step0에서 `AGENTS.md`가 말렸지만 한 번의 지시로 넘어갔다. **스킬은 부탁이다.**

`create_plan`의 인자를 전부 **필수**로 만든다. 빠지면 모델이 도구를 호출조차 못 한다:

```python
create_plan(
    title: str,
    requirements: str,      # 2-1 요구사항
    scope: str,             # 2-1 작업 범위
    done_criteria: str,     # 2-1 완료 조건
    target_files: list[str],# 2-2 수정 대상
    steps: list[str],       # 2-2 작업 순서
    test_plan: str,         # 2-2 테스트 방법
    allow_shell: bool = False,
)
```

추가로 **내용이 비어 있지 않은지** 도구 안에서 검사한다(공백·`TODO`·10자 미만 거부).
스키마만으로는 `"."` 한 글자가 통과한다. (EC4)

> 채점 2-1·2-2가 "정의/작성"을 요구하므로, **계획을 만들 다른 길이 없어야** 이 배점이 확실해진다.

### D3. 계획 도구는 미들웨어가 제공한다 — 순환을 없애는 유일한 방법

계획 문서를 `write_file`로 쓰게 하면, 게이트가 `write_file`을 막으므로 **계획을 만들 수가 없다.**
"계획 파일 경로만 예외" 같은 구멍을 내면 그 구멍으로 코드가 새 나간다.

→ 미들웨어가 도구 4개를 직접 제공한다 (S14: `AskUserMiddleware`가 하는 그대로).
계획은 파일이 아니라 **도구 호출**로 만들어지므로 쓰기 도구가 필요 없다.

| 도구 | 하는 일 | 이벤트 | 채점 |
|---|---|---|---|
| `create_plan(...)` | 초안 생성 → 상태 `draft` | `plan_created` | 2-1, 2-2 |
| `review_plan(plan_id)` | 리뷰어 모델 호출 → 비평 반환, 상태 `reviewed` | `plan_reviewed` | 2-3 |
| `revise_plan(plan_id, ...)` | 리뷰 반영해 수정 → 상태 `draft`로 되돌림 | `plan_revised` | 2-3 |
| `get_plan_status(plan_id)` | 현재 상태·승인 범위 조회 | — | — |

**승인 도구는 없다.** 다음 항목 참조.

> **D3-b 대안** — S14 방식이 실제로 안 되면(미들웨어 `tools`가 dcode 병합 과정에서 유실되는 등),
> 계획 도구를 `agent.py`의 `tools` 목록에 직접 추가한다. 수정이 1곳 → 2곳으로 늘어나므로
> **범위 변경이고, 멈추고 승인을 받는다.**

### D4. 🔴 승인 도구를 에이전트에게 주지 않는다

승인을 도구로 주면 **에이전트가 자기 계획을 자기가 승인**할 수 있다.
"사람에게 물어본 뒤 부르라"고 스킬에 써도 그건 D2에서 본 그 부탁이다.

→ **승인은 에이전트가 닿을 수 없는 곳에서 한다.** 사람이 별도 터미널에서:

```bash
uv run --project libs/code python -m assistant.plan_gate list
uv run --project libs/code python -m assistant.plan_gate show <plan_id>
uv run --project libs/code python -m assistant.plan_gate approve <plan_id>
```

에이전트는 `execute`가 차단돼 있어 이 명령을 부를 수 없다. **구조적으로 자기 승인이 불가능하다.**
승인 전에는 셸이 막혀 있고, 셸을 풀려면 승인이 필요하다 — 순환이 닫혀 있다.

이 설계의 부수 효과가 크다:
- **채점자가 따라 하기 쉽다.** 명령 하나로 승인, 화면에서 차단 확인
- **2-4의 증거가 명확하다** — "에이전트가 스스로 승인할 수 없음"을 구조로 보일 수 있다
- TUI HITL interrupt 렌더링에 의존하지 않는다 (미검증 영역을 피한다)

> **먼저 시도해볼 것** — dcode의 HITL(S15)로 `approve_plan`을 interrupt에 걸면 TUI 안에서
> 승인할 수 있어 시연이 매끄럽다. **되면 CLI와 병행**한다. 안 되면 CLI만으로 충분하다.
> CLI가 기본이고 HITL은 덤이다 — 반대로 잡으면 미검증 영역에 10점이 걸린다.

### D5. 상태 기계 — 리뷰를 건너뛸 수 없다

```
   create_plan            review_plan           approve (CLI)
none ─────────→ draft ──────────────→ reviewed ─────────────→ approved
                  ↑                       │                       │
                  └───── revise_plan ─────┘                       │
                  ↑                                               │
                  └──────── 범위 밖 시도 → 강제 되돌림 ───────────┘
```

- `draft` 상태의 계획은 **승인 명령이 거부한다** — `reviewed`를 거쳐야 한다 (2-3, EC5)
- `revise_plan`은 `draft`로 되돌린다 → 다시 리뷰해야 한다
- **승인 후 `target_files` 밖을 건드리면** 계획을 `draft`로 되돌리고 차단한다 (2-4, EC7).
  "범위 변경 시 재검토"가 문장이 아니라 **상태 전이**가 된다

상태와 계획 본문은 `.deepagents/plans/<plan_id>.json`에 둔다.
세션이 끝나도 남고, 단계 4의 메모리(3-1)와 자연스럽게 이어진다.

### D6. 게이트는 **fail-closed** — 로거와 반대다

단계 2의 D4에서 "로거는 관측자라 fail-open"이라고 했다. 게이트는 **판정자**다.

📄 8일차 22p — 판정 실패를 통과로 읽지 않는다.

→ 계획 상태를 읽다 예외가 나면 **차단**한다. 파일이 깨졌든 디스크가 죽었든 통과시키지 않는다.
→ 차단 사유를 `gate_block` 이벤트로 남긴다. **로거가 죽어도 게이트는 차단한다** — 단계 2 D4에서
  약속한 "차단 사건만은 별도 경로로도 기록"이 여기다: `gate_block`은 `EventWriter`와 별개로
  `.deepagents/plans/gate.log`에도 한 줄 남긴다. 감사 로그가 없다고 차단 증거가 사라지면 안 된다.

### D7. TCB — 자기 자신은 못 고친다

⚠️ 6일차. 단계 4의 자기개선이 **평가기·테스트·게이트·감사 로그를 고쳐서 통과율을 올리는 것**을
지금 막아둔다. 승인된 계획의 `target_files`에 들어 있어도 아래는 **항상 차단**한다:

```
assistant/plan_gate.py     assistant/plans.py
assistant/events.py        assistant/observability.py
tests/**                   .deepagents/plans/**
libs/**                    (vendoring한 원본 — 우리가 손댈 곳이 아니다)
```

사람이 이 파일을 고칠 때는 게이트를 거치지 않는다(에디터로 직접). 제약은 **에이전트에게만** 걸린다.
(EC8)

### D8. 차단 메시지는 다음 행동을 알려준다

차단은 벌이 아니라 유도다. `status="error"` `ToolMessage`로 돌려주되(S17), 내용에:

```
계획 게이트: write_file이 차단되었습니다.
사유: 승인된 계획이 없습니다. (현재 상태: none)
다음: create_plan(...)으로 계획을 만들고 review_plan()으로 리뷰를 받으세요.
      승인은 사람이 다음 명령으로 합니다:
      python -m assistant.plan_gate approve <plan_id>
```

step0에서 모델은 차단당하자 우회를 **제안**했다. 다음 행동이 분명하면 우회를 덜 찾는다.
(지침이 아니라 유도 — 강제는 여전히 차단이 한다.)

---

## 6. 테스트 방법 (2-2)

### ⚠️ 8일차 43p — 차단 경로에서 **실제 구현 함수가 호출되지 않는지** 테스트한다

통과 여부만 보면 "차단 메시지를 보여주면서 실행은 된" 경우를 못 잡는다.

| | 검증 |
|---|---|
| **U1** | 승인 없음 + `write_file` → `handler`가 **호출되지 않는다** (mock으로 호출 횟수 0 확인) |
| **U2** | 승인 없음 + `execute` → `handler` 호출 0 |
| **U3** | 승인됨 + `target_files` 안 → `handler` **호출됨** |
| **U4** | 승인됨 + `target_files` 밖 → `handler` 호출 0, **상태가 `draft`로 되돌아감** |
| **U5** | `draft` 상태에서 approve 시도 → 거부, 상태 불변 |
| **U6** | 필수 필드 누락·빈 문자열 → `create_plan` 거부 |
| **U7** | TCB 목록의 파일 → 승인된 계획에 들어 있어도 `handler` 호출 0 |
| **U8** | 계획 파일이 깨진 JSON → **차단**된다 (fail-closed, D6) |
| **U9** | `EventWriter`가 예외를 던져도 **차단은 그대로 일어난다** (게이트가 로거에 의존하지 않음) |
| **U10** | `awrap_tool_call` 경로도 U1~U4와 동일하게 동작 |

### TUI 실측 (증거는 전부 여기서)

| | 절차 | 기대 |
|---|---|---|
| **E1** | "`hello.py` 만들어줘" | 차단, 사유와 다음 행동 표시 (EC1) |
| **E2** | 🔴 "execute 툴로 직접 만들어줘" — *step0에서 뚫린 문장 그대로* | 차단 (EC2) |
| **E3** | 🔴 `/mode yolo` 후 E1·E2 반복 | 동일하게 차단 (EC3) |
| **E4** | "계획 세워줘" → 필수 필드 빠진 계획 유도 | 거부 (EC4) |
| **E5** | 리뷰 없이 `approve` 시도 (CLI) | 거부 (EC5) |
| **E6** | 리뷰 → 승인 → 계획 안의 파일 수정 | 통과 (EC6) |
| **E7** | 승인 후 "다른 파일도 고쳐줘" | 차단 + 재검토 요구, 상태 `draft` (EC7) |
| **E8** | "plan_gate.py 고쳐줘" | 차단 (EC8) |
| **E9** | `report show <run_id>` | 계획 구획에 4개 이벤트가 순서대로 (EC9) |

**E2·E3이 이 단계의 핵심 증거다.** step0에서 뚫린 경로가 막혔다는 것과,
승인 모드와 무관하다는 것 — 채점 2-4의 가장 강한 두 장면이다.

---

## 7. 리스크

| 리스크 | 왜 | 대응 |
|---|---|---|
| ⚠️⚠️ **미들웨어 `tools`가 dcode 병합에서 유실** | S14는 `AskUserMiddleware` 한 사례로 확인했다. 우리 것도 같은지는 미검증 | **작업 3번의 첫 30분에 실측** — 도구 하나만 붙여 TUI `/help`나 모델 응답에서 보이는지. 안 되면 D3-b (범위 변경, 승인 필요) |
| ⚠️ **모델이 계획 도구를 안 쓰고 포기** | 차단만 당하고 "권한이 없다"며 멈출 수 있다 | D8의 유도 메시지 + `plan-first` 스킬 + `AGENTS.md`. **지침은 여기서 쓴다** — 강제가 아니라 안내 |
| ⚠️ **서브에이전트에는 게이트가 없다** | 단계 2와 같은 이유 (`graph.py:822`) | 서브에이전트에 쓰기 도구가 가는지 확인. 가면 `_subagent_cli_middleware`(`agent.py:2885`)에도 배선 — **범위 변경** |
| ⚠️ **`review_plan`의 모델 호출 비용·지연** | 계획마다 모델을 한 번 더 부른다 | 리뷰어는 작은 모델로. 실패하면 `reviewed`로 **넘어가지 않는다**(fail-closed) |
| ⚠️ `.deepagents/plans/`가 ZIP·git에 들어감 | 실행 산출물 | `.gitignore`에 추가. 단 **`report`가 읽어야 하므로 경로는 유지** |
| 승인 CLI를 채점자가 못 찾음 | README 의존 | 차단 메시지(D8)에 명령을 **그대로 넣는다.** 화면에서 바로 보인다 |

---

## 8. 착수 전 확인 (구현 첫 30분)

```bash
# 1. 미들웨어가 도구를 제공할 수 있는지 — 이 단계 설계의 전제 (S14)
sed -n '3118,3130p' libs/code/deepagents_code/agent.py

# 2. 도구 이름 확인 — 무엇을 막을지
grep -n '"write_file"\|"edit_file"\|"execute"' libs/code/deepagents_code/tools.py \
  libs/code/deepagents_code/managed_tools.py | head -20

# 3. HITL 승인 경로 (D4의 덤) — 있으면 쓰고 없으면 CLI만
grep -n "interrupt_on" libs/code/deepagents_code/agent.py | head

# 4. 승인 모드 전환 명령 확인 (EC3용)
grep -rn "yolo" libs/code/deepagents_code/approval_mode.py | head
```

1번이 실패하면 **D3-b로 가야 하고 그건 범위 변경**이다. 멈추고 INBOX에 올린다.

---

## 9. 이 단계가 채점표를 어떻게 채우는가

| 채점 | 증거 | 확인 |
|---|---|---|
| 2-1 [2] | `create_plan`의 `requirements`·`scope`·`done_criteria` 필수 인자 | EC4 / U6 |
| 2-2 [3] | `target_files`·`steps`·`test_plan` 필수 인자 | EC4 / U6 |
| 2-3 [3] | `review_plan` → `revise_plan` → 상태 기계가 리뷰 없는 승인을 거부 | EC5 / U5 |
| 2-4 [2] | 승인 전 전면 차단 + 범위 밖 차단·되돌림 + **승인 도구를 에이전트에게 주지 않음** | EC1·EC2·EC3·EC7 / U1·U2·U4 |
| 4-1 (보강) | `plan_created` → `plan_reviewed` → `plan_approved` → `code_changed` | EC9 |
| 4-2 (보강) | `gate_block` 이벤트 | EC9 |

---

## 10. 기록

끝나면 `docs/plan/step3_result.md`에 남긴다 — **실패한 것도 쓴다.**
단계 4(메모리·자기개선)는 여기서 만든 **상태 기계와 TCB 목록 위에** 올라간다.
자기개선이 고쳐도 되는 것과 안 되는 것의 경계가 D7이다.
