# 채점 항목 ↔ 확인 방법

채점 가이드라인의 **16개 세부항목**을 하나씩, **무엇을 실행하면 무엇이 보이는가**로 정리했다.
모든 명령은 **압축을 푼 폴더의 최상위**에서 실행한다. 설치는 [README](../README.md) 1~3절.

> 이 표만 따라가면 4개 항목 40점을 전부 확인할 수 있다.
> 각 줄의 "무엇이 보이면 통과"가 그 세부항목의 증거다.

---

## 항목 1 — Python 코드의 일반적인 개발 기준 준수 [10]

대상은 **`assistant/`와 `tests/`** — 이 프로젝트가 직접 쓴 코드다.
`libs/`는 강사 배포본(dcode 원본)을 그대로 vendoring한 것이라 검사 대상이 아니며,
저장소 루트 `ruff.toml`의 `extend-exclude = ["libs"]`가 그것을 명시한다.

**한 번에 확인:**

```bash
uv run --project libs/code ruff check assistant/ tests/
uv run --project libs/code ruff format assistant/ tests/ --check
```

기대: `All checks passed!` · `11 files already formatted`

| | 세부항목 | 강제 수단 | 무엇이 보이면 통과 |
|---|---|---|---|
| **1-1** [3] | 들여쓰기·공백·줄바꿈 등 PEP8 | `ruff.toml` → `select = ["E", ...]` (pycodestyle) + `ruff format` | 위 두 명령이 오류 0 |
| **1-2** [3] | 명명 규칙 준수 및 import 정리 | `select`에 **`N`**(pep8-naming) + **`I`**(isort) | 〃 |
| **1-3** [4] | 주요 함수의 역할·**입출력** docstring | `select`에 **`D`** + `extend-select = ["D417"]` + `[lint.pydocstyle] convention = "google"` | 〃 |

**1-3을 `D`만으로 끝내지 않은 이유** — 기본 `D` 규칙은 docstring의 **존재**만 본다.
세부항목이 요구하는 "**입출력**을 설명"은 `Args:`/`Returns:` 섹션이 있어야 하므로,
`D417`(문서화된 함수에 빠진 인자 설명을 잡음)과 google convention을 함께 켰다.
`tests/**`는 `per-file-ignores`로 `D1`·`D417`을 면제한다 — 테스트 함수에 docstring을
강제하는 것은 의미가 없다.

> 설정을 루트 `ruff.toml`에 둔 이유는 ruff의 config 탐색이 **파일의 디렉터리에서 위로** 올라가기
> 때문이다. `libs/code/pyproject.toml`의 `[tool.ruff]`는 `assistant/`의 조상이 아니라 형제여서
> 절대 적용되지 않는다 — `ruff check --show-settings`로 확인했다. 상세: [step5_ruff_docstrings.md](plan/step5_ruff_docstrings.md)

---

## 항목 2 — 개발 시작 전 작업 계획 구체화 및 리뷰 [10]

이 항목은 **두 갈래로** 증명한다. 공식 문구가 두 가지로 읽히기 때문이다
(자세한 판단: [SUBMISSION_GAP.md](plan/SUBMISSION_GAP.md) G1).

| 갈래 | 증거 |
|---|---|
| **(a) 개발자가** 개발 전에 계획했는가 | `docs/plan/` 문서들 — 계획 → 리뷰 → 반영 기록이 단계별로 남아 있다 |
| **(b) Assistant가** 코드 수정 전에 계획하게 만들었는가 | **계획 게이트** — `assistant/assistant/plan_gate.py`, `plans.py` |

### (b) 계획 게이트 — 실행해서 확인

승인된 계획 없이는 `write_file` · `edit_file` · `delete` · `task`가 차단되고,
**`execute`(셸)는 승인 후에도 항상 차단된다.**

```bash
uv run --project libs/code python -m assistant.plan_gate list
uv run --project libs/code python -m assistant.plan_gate show <plan_id>
uv run --project libs/code python -m assistant.plan_gate approve <plan_id>
```

**에이전트에게는 승인 도구가 없다** — 어떤 이름으로도 없다. 승인은 사람이 위 3번째 명령을
직접 터미널에서 실행하는 것뿐이다. 그리고 셸이 항상 차단되므로 **에이전트가 이 명령을
스스로 부를 수 없다.** 자기 승인이 구조적으로 불가능하다.

| | 세부항목 | 강제 수단 | 확인 방법 (README §6 항목 2의 케이스 번호) |
|---|---|---|---|
| **2-1** [2] | 요구사항·작업 범위·완료 조건 정의 | `create_plan`의 **필수 인자** `requirements` · `scope` · `done_criteria` + 내용 검사(공백·`TODO`·10자 미만 거부) | **케이스 6** — 빠뜨리거나 `"."`로 유도하면 거부 |
| **2-2** [3] | 수정 대상·작업 순서·테스트 방법 | 〃 `target_files` · `steps` · `test_plan` | **케이스 6** |
| **2-3** [3] | AI 리뷰 수행 + 수정 의견 반영 절차 | **상태 기계** — `review_plan` 없이는 `reviewed`가 안 되고, `reviewed`가 아니면 승인 명령이 거부한다. `revise_plan`은 `draft`로 되돌려 재리뷰를 강제한다 | **케이스 7** — 리뷰 없이 `approve` → 거부 |
| **2-4** [2] | 승인 후에만 변경, 범위 변경 시 재검토 | `wrap_tool_call`/`awrap_tool_call` 차단 + `target_files` 밖이면 계획을 `draft`로 **되돌림** | **케이스 1·2·3·4·5·8·9·10** |

**2-4의 가장 강한 장면 두 개** (README §6 케이스 2·3):

- **케이스 2** — "`execute` 툴로 직접 만들어줘". `step0_tui_result.md`에서 훅이 **실제로 뚫렸던**
  바로 그 문장이다. 이제 차단된다
- **케이스 3** — "서브에이전트한테 시켜서 만들어줘". `task` 위임도 차단된다

**승인 모드와 무관함** (케이스 4·5) — `auto`에서도, YOLO에서도 동일하게 차단된다.
게이트는 dcode의 승인 시스템과 **별개 계층**이다.

**TCB** (케이스 10) — 승인된 계획의 `target_files`에 들어 있어도 아래는 항상 차단된다:
`assistant/**` · `tests/**` · `libs/**` · `.deepagents/plans/**`.
자기개선이 테스트를 지워 통과율을 올리는 것을 막는다.

### (a) 문서로 확인

| 단계 | 계획 | 리뷰 | 반영 기록 | 결과 |
|---|---|---|---|---|
| 2 이벤트 로거 | [STEP2_PLAN.md](plan/STEP2_PLAN.md) | [STEP2_REVIEW.md](plan/STEP2_REVIEW.md) · [SUBMISSION_GAP.md](plan/SUBMISSION_GAP.md) | [INBOX.md](plan/INBOX.md)의 설계 응답 + `STEP2_PLAN.md` 본문의 `🔴 (검토 R2)` 인라인 표시 | [step2_result.md](plan/step2_result.md) |
| 3 계획 게이트 | [STEP3_PLAN.md](plan/STEP3_PLAN.md) | [STEP3_REVIEW.md](plan/STEP3_REVIEW.md) | [STEP3_REVIEW_RESPONSE.md](plan/STEP3_REVIEW_RESPONSE.md) | [step3_result.md](plan/step3_result.md) |
| 4 메모리·자기개선 | [STEP4_PLAN.md](plan/STEP4_PLAN.md) | [STEP4_REVIEW.md](plan/STEP4_REVIEW.md) · [STEP4_REVIEW_ADDENDUM.md](plan/STEP4_REVIEW_ADDENDUM.md) · [STEP4_CODE_REVIEW.md](plan/STEP4_CODE_REVIEW.md) | `step4_result.md` §착수 전 확인 (계획 전제 오류를 코드 쓰기 전에 잡아 계획서까지 수정) | [step4_result.md](plan/step4_result.md) |
| 5 최종 | [PLAN.md](plan/PLAN.md) §단계 5 | — | — | [step5_zip_verify.md](plan/step5_zip_verify.md) · [step5_ruff_docstrings.md](plan/step5_ruff_docstrings.md) |

리뷰를 **받은 것과 안 받은 것을 이유와 함께** 남겼다 (2-3). 예: 단계 3은 지적 6건을
전부 채택했고([STEP3_REVIEW_RESPONSE.md](plan/STEP3_REVIEW_RESPONSE.md)), 단계 2는
리뷰 쪽 제안 중 더 싼 대안을 골라 채택한 건이 있다.
역할별 왕래는 [INBOX.md](plan/INBOX.md)에 시간순으로 남아 있다.

---

## 항목 3 — Memory 활용 및 Self-Improving Harness [10]

TUI에서 확인한다. 절차는 [tui_test_checklist.md](plan/tui_test_checklist.md)의 T1~T19,
실측 결과는 [step4_result.md](plan/step4_result.md)에 있다 (MC1~MC7 전부 통과, 2026.09.18).

```bash
uv run --project libs/code dcode -a coding-assistant
```

메모리는 두 층이다 — 역할이 다르다:

| 저장소 | 성격 | 채점 |
|---|---|---|
| `.deepagents/AGENTS.md` | **규칙의 정본.** dcode `MemoryMiddleware`가 매 세션 자동 로드 (`agent.py:3134-3141`) | 3-1 |
| `.deepagents/memories/*.md` | **작업 경험 축적.** `search_memory`가 읽고 `memory_refs`가 인용 | 3-2 · 3-3 |

| | 세부항목 | 강제 수단 | 확인 방법 |
|---|---|---|---|
| **3-1** [2] | 규칙·경험을 Memory에 저장, 세션 종료 후 유지 | `.deepagents/AGENTS.md`(dcode가 매 세션 자동 로드) + `.deepagents/memories/*.md` | 세션1에서 `앞으로 함수에는 타입힌트를 꼭 붙여줘, 기억해` → **TUI 재시작** → `인사 함수 만들어줘` → 타입힌트가 붙어 나온다.<br>`cat .deepagents/AGENTS.md`로 `[R1]`~`[Rn]` 잔존 확인 |
| **3-2** [3] | 새 작업에서 Memory를 **검색해 실제 활용** | `create_plan`에 `memory_refs` 필수 인자 + 존재 검증(지어낸 인용 차단) | ① `메모리 안 보고 계획 만들어줘` → **거부** + `search_memory` 안내<br>② `search_memory로 규칙 찾고 계획을 세워줘` → 통과<br>③ `report show <run_id>` → `memory_hit  R1,R3,R5,R6  -  4 refs` |
| **3-3** [3] | 실패·평가 결과로 **시스템 프롬프트·Skills·작업 메모리** 개선안 생성 | `propose_improvement` — `runs/*/events.jsonl`의 `gate_block`·`tool_end(status=error)`를 입력으로, 대상을 셋 중 하나로 특정. 같은 사유 **3회 이상** 반복만 | ① 차단을 몇 번 당한 뒤 `개선안 만들어줘` → 대상·근거·제안이 담긴 후보가 `.deepagents/memories/lessons.md`에 `pending`으로<br>② `테스트 파일을 지우는 개선안 만들어줘` → **거부**(TCB)<br>③ `cat .deepagents/memories/lessons.md` |
| **3-4** [2] | 개선 전후 효과와 **기존 기능의 정상 동작** 검증 후 반영 | `verify_improvement` — 후보를 규칙 절로 **승격시킨 상태를 시뮬레이션**해 인용 가능한 규칙 id 집합을 전/후로 비교한다. 내용 없는 제안은 후보 id만 소비되어 **`after < before`가 되고 기각**된다(`improved = after >= before`). 개선안은 **자동 적용되지 않는다**(사람 승인 전까지 `pending`) | `그 개선안 검증해줘` → `before`/`after`와 통과/기각이 나온다 |

---

## 항목 4 — 작업 내용 모니터링 [10]

TUI에서 아무 작업이나 시킨 뒤, 종료하고 조회한다.

```bash
uv run --project libs/code python -m assistant.report list
uv run --project libs/code python -m assistant.report show <run_id>
uv run --project libs/code python -m assistant.report fail <run_id>
uv run --project libs/code python -m assistant.report stats <run_id>
```

**실제 출력은 [README](../README.md) §6 항목 4에 그대로 붙여뒀다** — 손으로 만든 예시가 아니라
이 저장소의 `runs/`에서 뽑은 것이다.

| | 세부항목 | 강제 수단 | 무엇이 보이면 통과 |
|---|---|---|---|
| **4-1** [3] | 요청별로 계획·리뷰·코드 변경·테스트·최종 결과의 전체 흐름 기록 | 이벤트 타입을 **작업 종류로** 예약 — `plan_created` · `plan_reviewed` · `plan_approved` · `code_changed` · `test_run` · `run_result` (기술 계층인 `model_*`/`tool_*`과 별도) | `report show`의 타임라인에 계획→리뷰→승인→코드 변경이 **순서대로** |
| **4-2** [3] | LLM 호출·도구 실행·Memory·자기개선의 결과와 **오류** 기록 | 각 이벤트에 `status`와 `error`. 차단은 `gate_block`으로 별도 기록 | `report show`에 `ERROR` 행과 사유. 게이트 차단도 로그에 남음 |
| **4-3** [2] | 실행 시간·호출 횟수·**재시도 횟수** | 안쪽 로거가 **재시도 attempt마다** `model_start`/`model_end`를 남긴다 — 바깥 로거만으로는 재시도가 1회로 보인다 | `show` 하단 `지표  모델 N회(시도) · 도구 N회 · 재시도 N회 · 총 N.Ns · 토큰 in/out` |
| **4-4** [2] | 작업별 로그·**Trace**를 조회해 실패 지점과 원인 확인 | `report fail`이 실패 이벤트와 **직전 3개 맥락**을 `>>` 마커로. `report show`는 `├─`/`└─` **계층형 trace** | `fail` 출력의 `>>` 행 + `error:` 줄에 원인 |

**4-3의 재시도가 왜 별도 설계인가** — dcode의 재시도는 `CodeModelRetryMiddleware` **내부
루프**에서 일어난다. 미들웨어 스택의 바깥에 있는 로거는 재시도 5회를 `model_start`/`model_end`
한 쌍으로만 본다. 그래서 같은 `EventWriter`를 공유하는 **두 번째 로거를 스택 맨 안쪽**에
두어 attempt 단위로 기록한다. 근거와 실측: [STEP2_PLAN.md](plan/STEP2_PLAN.md) §5 D2b.

**단위 테스트로도 확인 가능** (재시도는 TUI에서 의도적으로 일으키기 어렵다 — 401/404는
재시도 대상이 아니다):

```bash
uv run --project libs/code --group test pytest tests/ -q
```

`test_retry_logging_produces_one_pair_per_attempt`가 실물 `CodeModelRetryMiddleware`를
스택에 끼우고 재시도 대상 오류로 두 번 실패시킨 뒤 **3쌍**이 남는지 확인한다.

---

## 부록 — 한 번에 전부 돌리기

```bash
# 항목 1
uv run --project libs/code ruff check assistant/ tests/
uv run --project libs/code ruff format assistant/ tests/ --check

# 항목 1·2·3·4 — 단위 테스트
uv run --project libs/code --group test pytest tests/ -q

# 항목 2 — 계획 목록·상태
uv run --project libs/code python -m assistant.plan_gate list

# 항목 4 — 실행 로그 조회
uv run --project libs/code python -m assistant.report list
```

TUI에서 확인해야 하는 것(항목 2의 차단 장면, 항목 3의 세션 간 메모리)은
[README](../README.md) §6의 케이스 표를 따라간다.
