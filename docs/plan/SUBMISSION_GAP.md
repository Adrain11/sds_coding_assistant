# 제출 안내 vs 계획 — 어긋난 곳 (2026-09-17, Claude Opus 5 / 🔵 검토)

출처: 「[삼성SDS] AX Advanced 2026-2 프로젝트 결과물 제출」 공식 안내문.
대조 대상: `docs/plan/PLAN.md`, `docs/plan/STEP2_PLAN.md`, `docs/plan/WORKFLOW.md`.

**배점은 16개 세부항목 전부 일치한다.** 계획서가 강사 브리핑을 정확히 옮겼다.
어긋난 것은 **제출 조건 2개**와 **채점 문구 3개**, 그리고 **닉네임 규칙 1개**다.

---

## 🔴 G1. 제출 형식이 계획과 정반대다

| | 공식 안내 | 계획서 전제 |
|---|---|---|
| 형태 | **ZIP 파일 업로드** | "채점자가 저장소를 받아" (PLAN.md §2 목표) |
| 내용 | dcode **실행에 필요한 소스코드만** | 저장소 전체 |
| 금지 | **`.claude/skills` 등 dcode 실행과 관련없는 것** | 단계 1에서 `.claude/skills` 13종 + `.agents/skills` 8종을 **일부러 이식** |

PLAN.md 단계 1의 "기존 `sds_final_project`에서 가져올 것" 표가
공식 안내가 명시적으로 금지한 항목을 이식 대상으로 올려놨다.

### 제출 ZIP에서 빼야 할 것

| 대상 | 이유 |
|---|---|
| `.claude/skills/` (13종) | Claude Code용. dcode와 무관. **안내문이 지목한 바로 그 예시** |
| `.agents/skills/` (8종) | langchain/langgraph 학습자료. dcode 실행과 무관 |
| `SKILLS.md`, `skills-lock.json` | 위 둘의 관리 문서 |
| `.git/` | 커밋 author가 실명·개인 이메일. **닉네임 규칙 위반 소지** (G4 참조) |
| `runs/`, `.venv/`, `.env` | 이미 `.gitignore` 대상 |

### 반드시 남겨야 할 것

- `libs/` **전체** — `libs/code/pyproject.toml`의 `[tool.uv.sources]`가
  `../deepagents`, `../acp`, `../partners/*`를 상대경로로 참조한다.
  하나라도 빠지면 `uv sync`가 죽는다 (STEP2_PLAN S8).
- `assistant/`, `tests/`, `pyproject.toml`, `README.md`
- `.deepagents/AGENTS.md` — dcode가 실제로 읽는 지침 파일이고 채점 3-1의 증거다

### 판단이 갈리는 것 — `docs/plan/`

"실행에 필요한 소스"는 아니지만 **채점 2번(10점) 전체의 유일한 증거물**이다.
빼면 2-1~2-4가 통째로 날아간다. 넣는 쪽이 맞다고 본다.

> 👤 **강사 확인 필요** — "계획·리뷰 문서(`docs/`)는 채점 2번 항목의 증거물인데
> ZIP에 포함해도 되나요?"

---

## 🔴 G2. 기간이 계획보다 2일 더 있다

> 공식: 프로젝트 기간 **2026년 09월 17일(목) ~ 09월 20일 오후 11시 59분 59초(일)**

PLAN.md는 "오늘 약 2시간 + 내일·모레 약 16시간",
WORKFLOW.md §0은 "09.17 오후 + 09.18 하루" = **1.5일** 기준이다.
수강기간(~09.18)과 제출마감(~09.20)을 혼동한 것으로 보인다.
**실제 가용 시간은 3.5일이다.**

### 이게 뒤집는 판단

- 단계 3·4·5 계획을 **축소하지 않는다.** 채점 2-2가 "수정 대상·작업 순서·테스트 방법이
  포함된 **구체적인** 계획"이라, 여기서 줄이는 것은 직접 감점이다.
  단계 2 수준의 계획서를 3·4·5에도 쓸 시간이 있다.
- PLAN.md §5 리스크의 "시간 부족 → 4·5는 축소 가능" 항목을 재검토 대상으로 둔다.

→ **WORKFLOW.md §0의 "남은 시간"을 `09.17 오후 ~ 09.20 23:59`로 정정할 것.**

---

## 🔴 G3. 4-1의 요구가 현재 이벤트 스키마에 없다

> 공식 4-1. 요청별로 **계획·리뷰·코드 변경·테스트·최종 결과**의 전체 실행 흐름 기록 [3]

STEP2_PLAN §5 D7의 이벤트 타입은
`run_start` / `model_start` / `model_end` / `model_error` / `tool_start` / `tool_end` / `run_end`.

이건 **기술 계층**(모델 호출·도구 호출)이지 채점이 요구하는 **작업 종류**
(계획·리뷰·코드 변경·테스트)가 아니다.
채점자가 `events.jsonl`을 열어도 "여기가 계획 단계, 여기가 리뷰"를 짚을 수 없다.
`tool_end name=write_file`은 "코드 변경"이라고 읽히지만, "계획"과 "리뷰"는 어떤 도구 호출에도
직접 대응하지 않는다.

**조치** — D7의 예약 타입에 다음을 추가한다. 지금은 `events.py`에 상수 선언만 하면 되므로 비용이 0이다.

| 타입 | 발생 지점 | 채점 |
|---|---|---|
| `plan_created` | 계획 문서 작성 완료 (단계 3) | 4-1, 2-1 |
| `plan_reviewed` | plan-reviewer 서브에이전트 응답 (단계 3) | 4-1, 2-3 |
| `plan_approved` | 사람 승인 (단계 3) | 4-1, 2-4 |
| `code_changed` | 쓰기 도구 성공 시 파일 경로와 함께 | 4-1 |
| `test_run` | 테스트 실행 결과·통과율 (단계 4의 전후 비교에도 씀) | 4-1, 3-4 |

기존 예약 타입 `gate_block`(단계 3), `memory_hit`·`improve_*`(단계 4)와 같은 취급이다.
**단계 2에서 R2(재시도)와 함께 반영해야 한다.** 나중에 넣으면 `report.py`를 다시 고쳐야 한다.

---

## 🟡 G4. 닉네임 규칙

> 공식: 닉네임은 담당자와 약속된 내용을 입력하고 **절대로 성함을 입력하지 마세요.**

| 위치 | 내용 | 조치 |
|---|---|---|
| `docs/plan/WORKFLOW.md:64` | `### 사람(김)` — 성이 들어 있다 | `### 사람(운영)` 등으로 교체 |
| `.git/` (ZIP 포함 시) | 커밋 author 실명 + 개인 이메일이 전부 남는다 | ZIP에서 **제외** (G1) |
| `README.md` (작성 예정) | 작성자 표기 | 약속된 닉네임만 |

`docs/plan/`의 나머지 문서(PLAN, STEP2_PLAN, step0_tui_result, REVIEW_PROMPT, STEP2_REVIEW)는
실명 노출 없음을 확인했다.

---

## 🟡 G5. 채점 문구가 미묘하게 다른 것 셋

### 3-3 — 개선 **대상**이 특정되어 있다

> 공식: Agent가 **시스템 프롬프트·Skills·작업 메모리 등** 개선안을 생성 [3]

PLAN.md 단계 4는 "실패·차단 이벤트를 모아 임계치 초과 시 개선안 자동 생성"으로,
**무엇을 개선하는지**가 없다. 채점자는 셋 중 무엇이 바뀌었는지를 본다.
→ 단계 4 계획에서 최소 둘(예: `.deepagents/AGENTS.md`의 규칙 + `memories/*.md`)을
개선 대상으로 명시하고, 개선 전후 diff를 로그에 남긴다.

### 4-4 — "Trace"라는 단어가 명시돼 있다

> 공식: 작업별 로그·**Trace**를 조회하여 실패 지점과 원인을 확인 [2]

STEP2_PLAN §2는 LangSmith를 범위 밖으로 뺐다. **그 판단 자체는 옳다**
(채점자가 자기 키를 넣어야 돌아가는 것은 증거로 못 쓴다).
다만 "Trace"를 자체 구현으로 충족시켜야 한다.
→ `report show <run_id>`를 평면 타임라인이 아니라 **계층형 trace 뷰**로 만든다:

```
run 20260917-091233-a1b2c3d4  (12.4s, 실패 1)
├─ model_call #1              2.1s   in=4820 out=132
├─ tool  read_file            0.1s   ok
├─ model_call #2              3.8s   in=5310 out=88   retry=1
└─ tool  write_file           0.1s   ERROR  blocked by PEP8 gate: I001, F401
```

들여쓰기 한 단계만 있어도 "Trace"로 읽힌다. 비용 대비 효과가 크다.

### 1-3 — 배점 최고(4점)인데 ruff `D`만으로는 부족하다

> 공식: 주요 함수의 역할·**입출력**을 설명하는 docstring 및 필요한 주석 [4]

PLAN.md 단계 5는 ruff에 `D`(docstring) 룰을 켜는 것으로 잡았다.
그런데 기본 `D` 룰은 **docstring의 존재**만 검사하고 Args/Returns 섹션의 유무는 안 본다.
→ `pyproject.toml`에 아래를 넣어야 "입출력 설명"이 강제된다:

```toml
[tool.ruff.lint.pydocstyle]
convention = "google"

[tool.ruff.lint]
extend-select = ["D417"]   # Missing argument descriptions in the docstring
```

`D417`이 Args 누락을, `convention = "google"`이 Args/Returns 형식을 잡는다.
`libs/`(vendoring된 원본)는 검사 대상에서 제외해야 한다 — 남의 코드다.

---

## 조치 목록

| # | 할 일 | 담당 | 관련 |
|---|---|---|---|
| 1 | WORKFLOW.md §0 남은 시간을 `09.17 오후 ~ 09.20 23:59`로 정정 | 🟣 설계 | G2 |
| 2 | 단계 5에 **"제출 ZIP 생성"** 작업 신설 — 제외 목록 + 깨끗한 환경에서 압축 해제 후 빌드 검증 | 🟣 설계 | G1 |
| 3 | D7 이벤트 타입에 `plan_created`/`plan_reviewed`/`plan_approved`/`code_changed`/`test_run` 추가 | 🟣 설계 → 🟢 구현 | G3 |
| 4 | `WORKFLOW.md:64` "사람(김)" → 역할명으로 교체 | 🟣 설계 | G4 |
| 5 | 단계 3·4·5 계획을 **축소하지 않기로** 결정 재확인 | 🟣 설계 | G2 |
| 6 | 단계 4 계획에 개선 대상(시스템 프롬프트/Skills/메모리) 명시 | 🟣 설계 | G5 |
| 7 | `report show`를 계층형 trace 뷰로 | 🟣 설계 → 🟢 구현 | G5 |
| 8 | ruff에 `convention="google"` + `D417`, `libs/` 제외 | 🟣 설계 → 🟢 구현 | G5 |
| 9 | 강사 확인 — `docs/`를 ZIP에 포함해도 되는지 | 👤 | G1 |

3번은 `STEP2_REVIEW.md`의 **R2(재시도 횟수)**와 같은 파일(`assistant/events.py`)을 건드린다.
**두 개를 한 번에 반영하는 것이 싸다.** 🟢 구현이 `events.py` 인터페이스를 굳히기 전에 결정할 것.
