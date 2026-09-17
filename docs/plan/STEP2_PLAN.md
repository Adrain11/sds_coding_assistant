# 단계 2 계획 — 이벤트 로거 (채점 항목 4: 모니터링)

**작성** 2026.09.16 · **예상** 4시간 (원 계획 3시간 + 배선 확인 1시간)
**선행** 단계 1 완료 (dcode 소스 vendoring) · **후속** 단계 3 계획 게이트

> 이 문서는 채점 2-1(요구사항·범위·완료조건)과 2-2(수정대상·순서·테스트방법)의 증거물이다.
> 작업 중 범위가 바뀌면 이 문서를 고치고 재검토한 뒤 진행한다 (2-4).

---

## 0. 소스에서 실측한 사실 — 이 계획의 근거

vendoring된 `libs/` 원본을 직접 읽고 확인한 것. **추정이 아니다.**

| # | 사실 | 출처 |
|---|---|---|
| S1 | 미들웨어 조립 지점은 `create_cli_agent`의 `agent_middleware` 리스트 | `libs/code/deepagents_code/agent.py:3073` |
| S2 | **dcode custom 리스트 *안에서* 앞쪽 = 바깥쪽** (`first = outermost`). 단 이 리스트 전체는 SDK core 5종(Skills→Filesystem→SubAgent→Summarization→PatchToolCalls) **뒤에** 통째로 삽입되므로, `agent_middleware[0]`도 그 다섯보다는 **안쪽**이다. `before_agent`는 리스트 순서, **`after_agent`는 역순** | `agent.py:3063-3066`, `agent.py:3101` / 삽입 구현 `graph.py:229-231`, core 목록 `graph.py:860-898` (🔵 검토 R1) |
| S3 | `wrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage \| Command` | `agent.py:960` (`ShellAllowListMiddleware` 실물) |
| S4 | **`awrap_tool_call` 비동기 판이 따로 있고, 서버 그래프는 주로 async로 돈다** | `agent.py:979-983` 주석 + 시그니처 |
| S5 | `wrap_model_call(self, request: ModelRequest, handler) -> ModelResponse` / `awrap_model_call` | `libs/deepagents/deepagents/middleware/memory.py:385, 402` |
| S6 | `before_agent(self, state, runtime)` 2인자가 베이스 시그니처 | `middleware/patch_tool_calls.py:17` |
| S7 | 미들웨어에 `trace_policy = TracePolicy(process_inputs=omit_payload)` 관용구가 있음 | `agent.py:894` |
| S8 | `[tool.uv.sources] deepagents = { path = "../deepagents", editable = true }` — 상대경로 의존이라 `libs/` 구조를 깨면 빌드가 죽는다 | `libs/code/pyproject.toml:213-220` |
| S9 | 휠 패키지 목록은 `packages = ["deepagents_code"]` — **`assistant/`는 그냥 두면 설치 안 된다** | `libs/code/pyproject.toml:198-207` |
| S10 | 확장(extension) API로도 미들웨어 등록이 가능하지만 `DEEPAGENTS_CODE_EXPERIMENTAL=1` + 프로젝트 신뢰 프롬프트가 필요 | `libs/code/EXTENSIONS.md:3-5, 110-113` |
| S11 | 🔴 서버(`langgraph_runtime_inmem`)가 이벤트 루프 스레드의 동기 blocking I/O를 감지하면 예외를 던진다(`--allow-blocking` 미설정 시 기본). `os.mkdir`/`os.getcwd`는 걸린다. `io.*.write`/`threading.Lock.acquire`는 명시적으로 예외 처리돼 안 걸림 | `langgraph_runtime_inmem/queue.py:_enable_blockbuster`(`to_disable` 목록), 2026.09.17 헤드리스 실측(`BlockingError: Blocking call to os.mkdir`/`os.getcwd`) |
| S12 | 🔴 `contextvars.ContextVar`로 든 "현재 run"이 `before_agent`와 이후 훅(`wrap_tool_call`/`after_agent`) 사이에서 안 이어진다 — 서버가 훅마다 별도 task/context를 쓰는 것으로 보임(공통 조상에서 복사, 이어쓰기 아님). `thread_id`는 같은 조건에서 모든 훅에 동일하게 잡혔다 | 2026.09.17 헤드리스 실측(`_safe()`에 트레이스 삽입, `before_agent`/`awrap_tool_call`/`after_agent` 각각의 `current_run_id()`/`thread_id`를 직접 찍어봄) |
| S13 | 🔴 서버 프로세스의 `os.getcwd()`는 저장소 루트가 아니라 `/tmp/deepagents_server_<id>/` 샌드박스다. `dcode`가 "프로젝트 루트"로 쓰는 값(F2)은 별도 메커니즘(`get_server_project_context()`, 클라이언트가 서버에 넘긴 값)이라 `os.getcwd()`와 다르다 | `deepagents_code/project_utils.py:get_server_project_context`, `agent.py`의 `_format_execute_description`이 같은 fallback을 씀. 2026.09.17 헤드리스 실측(`EventWriter.__init__`의 실제 `runs_dir` 값 확인) |

**S10의 의미** — PLAN.md가 "훅 대신 소스 배선"을 고른 판단이 소스로 확인됐다. 확장 API를 썼으면 step0에서 문제였던 신뢰 프롬프트가 그대로 돌아온다. **소스 배선이 맞다.**

**S11~S13의 의미 — D1/D2b/D9를 실측으로 다시 썼다.** 계획서의 "ContextVar로 현재 run을 든다"(D1/검토 I3)와 "EventWriter는 파일에만 쓰면 안전하다"(D5)는 소스 리딩만으로는 안 보이던 두 가지를 놓쳤다: 훅 간 컨텍스트 단절(S12)과 서버 프로세스의 실제 cwd(S13). 둘 다 실제 헤드리스 서버 실행 없이는 발견할 수 없었다. `EventWriter`는 이제 `thread_id`로 직접 키를 잡고(S12), 기본 `runs_dir`/`run_start`의 `cwd` 필드는 `get_server_project_context()`로 구한다(S13). 상세 근거는 `assistant/events.py`의 `EventWriter`·`resolve_project_dir` docstring, `docs/plan/INBOX.md`의 09-17 🟢구현 항목.

### 🔴 먼저 고쳐야 할 것 두 가지

**F1. `libs/libs/` 디렉터리 중복**
`libs/` 안에 `acp, code, deepagents, evals, partners, talon`이 있고, **`libs/libs/` 안에 같은 것이 한 벌 더 있다** (mtime이 더 늦음). `cp -r ... ./libs`를 두 번 돌린 흔적으로 보인다. 저장소 크기·채점자 혼란·ruff 검사 대상이 전부 두 배가 된다.
→ **단계 2 착수 전에 `libs/libs/` 삭제하고, `libs/code`에서 `uv sync`가 여전히 되는지 확인.** (S8 때문에 `libs/` 구조 자체는 건드리면 안 된다.)

**F2. 실행 디렉터리가 정해지지 않았다 — AC1이 여기 걸려 있다**
`dcode`의 프로젝트 루트 = **실행한 디렉터리**다 (handoff.md에서 `dcode config path`로 실측). 그런데 PLAN.md 단계 1의 빌드 절차는 `cd libs/code && uv run dcode`라서, 그대로 하면 프로젝트 루트가 `libs/code`가 되고 **저장소 루트의 `.deepagents/AGENTS.md`도 `runs/`도 안 잡힌다.**
→ 채점자용 실행 커맨드는 **저장소 루트에서** 도는 형태여야 한다:
```bash
uv sync --project libs/code            # 빌드
uv run --project libs/code dcode -a coding-assistant   # 저장소 루트에서 실행
```
`--project`는 의존성 위치만 바꾸고 cwd는 그대로 둔다.

> ✅ **2026.09.17 실측 완료 — 해소됨.** 저장소 루트에서 `uv run --project libs/code dcode config path` 실행 시
> `project hooks.json /home/ubuntu/sds_coding_assistant/.deepagents/hooks.json` → 프로젝트 루트가 **저장소 루트**로 잡힘.
> 위 커맨드를 README 실행 절차로 확정한다. (`project hooks.json (missing)`은 정상 — 훅 대신 미들웨어 배선으로 간다.)

**F4. 모델 프로바이더가 선택 의존성(extra)이다 — AC1의 실제 걸림돌**
09.17 실측: `uv sync --project libs/code` 후 TUI를 띄우면
`MissingProviderPackageError: Missing package for provider 'openrouter'`로 **서버가 뜨지 않는다.**
`libs/code/pyproject.toml:129`에서 `openrouter = ["langchain-openrouter>=0.2.8,<2.0.0"]`로 extra에 빠져 있기 때문.
지금까지는 전역에 `uv tool install`로 깔아둔 dcode를 써서 안 보이던 문제다.

→ 빌드 절차는 **extra를 반드시 포함**해야 한다:
```bash
uv sync --project libs/code --extra all-providers   # 채점자용 기본 (134행, 20개 프로바이더)
uv sync --project libs/code --extra openrouter      # 가벼운 설치 (내 개발용)
```
→ TUI 안의 `/install openrouter`는 쓰지 않는다. vendoring한 editable 설치에서 어디로 깔리는지 불확실하고,
채점자도 같은 곳에서 막힌다. 의존성은 `uv sync`로 명시적으로 고정한다.
→ **README 기본 절차는 `all-providers`.** 채점자가 어떤 프로바이더를 쓸지 모르고, 여기서 막히면
나머지 30점을 볼 기회 자체가 없어진다. 설치가 무거운 건 그 다음 문제다.
→ DC1과 §7 리스크에 반영.

**F3. 단계 1의 "이식"이 안 돼 있었다 — 2026.09.17 처리 완료**
GitHub 저장소를 확인한 결과 커밋 1개(`baseline: dcode 0.1.69 source`)에 루트가 `.gitignore`와 `libs/`뿐이었다.
PLAN.md 단계 1 표의 이식 대상(`.agents/skills/` 8종, `.claude/skills/`, `.env.example`, `SKILLS.md`,
`skills-lock.json`, `.deepagents/AGENTS.md`)이 전부 빠져 있었다.
→ 09.17 오전에 `sds_final_project`에서 복사 완료. `readlink -e .claude/skills/*` = 13개 전부 해소 확인.
→ `.gitignore`에 `.claude/settings.local.json` 추가 (원본 저장소에는 있었는데 빠져 있었다 — 토큰 유출 예방).
→ `hooks/pep8_gate.py`는 로직만 단계 5에서 재사용하므로 복사하지 않는다.

---

## 0-B. 공식 제출 안내 (2026.09.17 수신) — 전 단계에 걸리는 제약

| | 내용 | 영향 |
|---|---|---|
| **기한** | 2026.09.20(일) 23:59:59 | 단계 2~5를 압축하지 않아도 된다 |
| **제출 형식** | **ZIP 파일**. GitHub 링크가 아니다 | 단계 5에 "ZIP 패키징" 작업 추가 |
| **포함 범위** | "dcode를 실행하는데 필요한 **소스코드만**. `.claude/skills` 등 dcode 실행과 관련없는 것은 **금지**" | 🔴 아래 참조 |
| 닉네임 | 성함 금지 | 제출 시 확인 |

### 🔴 제출 ZIP에서 제외할 것

09.17 오전에 `sds_final_project`에서 이식한 것 중 **개발 도구용 자산은 dcode가 읽지 않으므로 제출에서 뺀다.**
저장소에는 그대로 둔다 — 개발에 필요하다. **빼는 것은 ZIP을 만드는 시점이다.**

| 대상 | 저장소 | 제출 ZIP | 이유 |
|---|---|---|---|
| `.claude/` | 유지 | ❌ 제외 | 안내문이 명시적으로 금지 |
| `.agents/skills/` | 유지 | ❌ 제외 | `.claude/skills/`가 심볼릭 링크로 가리키는 실체. 개발 도구용이고 dcode는 읽지 않는다 |
| `CLAUDE.md` | 유지 | ❌ 제외 | Claude Code용 규칙 |
| `docs/plan/` | 유지 | ✅ **포함** | 채점 2번(10점)의 문서 증거. 공식 문구가 "*내가* 계획을 세웠는가"로도 읽히므로 문서와 기능 **둘 다 대비한다**. 강사 확인 후 한쪽을 줄인다 (검토 G1) |
| `.git/` | 유지 | ❌ 제외 | 커밋 author에 **실명·개인 이메일**이 남는다. 닉네임 규칙 위반 소지 (검토 G1) |
| `SKILLS.md`, `skills-lock.json` | 유지 | ❌ 제외 | 위 두 스킬 디렉터리의 관리 문서 |
| `.deepagents/` | 유지 | ✅ 포함 | dcode가 실제로 읽는 프로젝트 규칙·스킬 |
| `assistant/`, `libs/`, `pyproject.toml`, `README.md`, `tests/` | 유지 | ✅ 포함 | 실행에 필요 |

> ⚠️ **2-1·2-2는 문서와 기능 둘 다로 증명한다.**
> 공식 문구 "Coding Assistant 의 개발 시작 전 작업 계획 구체화 및 리뷰"는 두 갈래로 읽힌다 —
> (a) *내가* 개발 전에 계획했는가(→ 문서가 증거), (b) *Assistant가* 코드 수정 전에 계획하게 만들었는가
> (→ 기능이 증거). 문법은 (a), 채점 방식("빌드→TUI→구현 여부 점검")은 (b)를 가리킨다.
> **단정할 근거가 없으므로 둘 다 한다.** `docs/plan/`을 ZIP에 넣고,
> **`.deepagents/skills/`에 계획 작성 절차 스킬**도 넣어 에이전트가 요구사항·범위·완료조건·수정대상·
> 순서·테스트방법을 갖춘 계획을 만들도록 강제한다 (단계 3의 핵심).
> 👤 **강사 확인 필요** — "계획·리뷰 문서를 ZIP에 포함해도 되나요?" 답이 오면 한쪽을 줄인다.

---

## 1. 요구사항 (2-1)

한 번의 사용자 요청에 대해 에이전트가 **무엇을 했고, 얼마나 걸렸고, 어디서 실패했는지**를 사람이 나중에 조회할 수 있어야 한다.

| 채점 세부항목 | 요구사항 |
|---|---|
| 4-1 전체 실행 흐름 기록 | 요청 시작 → 모델 호출 → 도구 실행 → 종료가 시간순 한 줄씩 남는다 |
| 4-2 LLM·도구·메모리·자기개선의 결과와 오류 | 각 이벤트에 성공/실패와 오류 내용이 붙는다. 메모리·자기개선 이벤트는 단계 4에서 채우되 **타입은 지금 예약한다** |
| 4-3 시간·횟수·재시도 지표 | 요청 총 소요, 이벤트별 소요, 모델 호출 횟수, 토큰, 도구 호출 횟수, 재시도 횟수를 집계해 보여준다 |
| 4-4 실패 지점 조회 | 실패한 이벤트만, 그 앞 맥락과 함께 뽑아볼 수 있다 |

## 2. 범위

### 이번 단계에서 하는 것
- `assistant/` 패키지를 dcode 빌드에 얹는 배선 (S9 해결)
- 이벤트 기록 계층 `assistant/events.py`
- 미들웨어 `assistant/observability.py`
- 조회 CLI `assistant/report.py`
- `agent.py` 미들웨어 목록에 1줄 삽입
- 위 넷에 대한 단위 테스트 + **TUI 실측 검증**

### 이번 단계에서 안 하는 것 (범위 밖)
- 계획 게이트·차단 로직 (단계 3)
- 메모리·자기개선 이벤트의 **내용** (단계 4) — 타입 이름만 예약
- PEP8 게이트 (단계 5)
- LangSmith 연동 — **채점자가 자기 키를 넣어야 돌아가므로 증거로 못 쓴다.** 파일 로그가 유일한 증거다
- 로그 시각화(HTML/웹) — 터미널 출력으로 충분

### 범위가 바뀌는 조건
아래 중 하나라도 걸리면 **작업을 멈추고 이 문서를 고친 뒤 재검토**한다 (2-4):
- 도구 호출이 `wrap_tool_call`에 안 들어옴 (T3에서 판명)
- `assistant` 패키지가 `uv sync`로 안 잡힘 → 배치 위치 변경 필요
- `after_agent`가 TUI에서 매 요청마다 안 불림

## 3. 완료 조건 (2-1)

전부 **TUI에서** 확인한다. 헤드리스 결과는 증거로 치지 않는다 (PLAN.md 리스크 표).

- [ ] **DC1** 깨끗한 셸에서 `uv sync --project libs/code --extra all-providers` → `uv run --project libs/code dcode -a coding-assistant`로 **TUI가 뜨고**(F4: extra 없으면 서버가 안 뜬다), `dcode config path`가 **저장소 루트**를 가리킨다
- [ ] **DC2** TUI에서 파일 읽기 한 번 시키면 `runs/<run_id>/events.jsonl`이 생기고, `run_start` / `model_*` / `tool_*` / `run_end`가 전부 들어 있다
- [ ] **DC3** `python -m assistant.report show <run_id>`가 그 요청의 타임라인과 **총 소요 시간**을 보여준다
- [ ] **DC4** 일부러 실패시킨 도구 호출(없는 파일 읽기)이 `status=error`로 남고, `report fail <run_id>`로 **그 지점만** 뽑힌다
- [ ] **DC5** 로그 디렉터리를 읽기 전용으로 만들어도 **TUI가 죽지 않는다** (로거는 fail-open — 아래 §5 D4)
- [ ] **DC6** TUI 화면에 로거가 만든 출력이 **한 글자도 섞이지 않는다**
- [ ] **DC7** 🔴 모델 호출이 재시도된 요청에서 `report`에 **attempt별 기록**이 남고 재시도 횟수가 1 이상으로 집계된다 (검토 R2 — 이게 없으면 4-3의 "재시도"가 증거 없음)
  - 🔴 **1차 증거는 단위 테스트(T11-u)다.** 재시도 대상은 `_RETRYABLE_STATUS_CODES = {408, 409, 429}` + 5xx뿐이라(`model_retry.py:92`), **잘못된 모델명(404)이나 잘못된 키(401)로는 재시도가 안 일어난다** (검토 I1). 이 유일한 예외 — 사람이 TUI에서 확인할 수 없는 완료조건 — 대신 채점자도 `pytest`로 재현할 수 있다
- [ ] **DC8** `report show`가 **계층형 trace 뷰**로 나온다 (4-4의 "Trace" 문구 충족, 검토 G5)

## 4. 수정·생성 대상 파일과 작업 순서 (2-2)

| # | 파일 | 신규/수정 | 내용 | 예상 |
|---|---|---|---|---|
| 0-a | `.agents/`, `.claude/`, `.deepagents/`, `.gitignore` 등 | ~~신규~~ | ~~F3 이식~~ | ✅ 09.17 완료 |
| 0 | `libs/libs/` | **삭제** | F1 중복 제거 후 `uv sync` 재확인. **이미 푸시된 히스토리는 그대로 두고 삭제 커밋만 얹는다** | 15분 |
| 1 | — | ~~확인만~~ | ~~F2 실행 커맨드 실측~~ | ✅ 09.17 완료 |
| 2 | `assistant/__init__.py`, `assistant/pyproject.toml` | 신규 | 빈 패키지 | 10분 |
| 3 | `libs/code/pyproject.toml` | 수정 | `dependencies`에 `"assistant"` 1줄 + `[tool.uv.sources]`에 `assistant = { path = "../../assistant", editable = true }` 1줄 | 10분 |
| 4 | — | 확인만 | `uv run --project libs/code python -c "import assistant"` 통과 | 10분 |
| 5 | `assistant/events.py` | 신규 | `EventWriter` — run_id 발급, jsonl append, 민감정보 절삭, **이벤트 타입 상수 전체(D7)** | 45분 |
| 6 | `tests/test_events.py` | 신규 | 동시 쓰기·절삭·미종료 run 단위 테스트 | 30분 |
| 7 | `assistant/observability.py` | 신규 | `EventLoggerMiddleware`(바깥) + **`EventLoggerInnerMiddleware`(안쪽, D2b)**. 각각 sync/async 훅 | 75분 |
| 8 | `libs/code/deepagents_code/agent.py` | **수정 (3곳 3줄)** | ⓪ `_ev = EventWriter()` 생성 ① `agent_middleware` **맨 앞**에 `EventLoggerMiddleware(_ev)` ② `create_deep_agent` 직전 **맨 끝**에 `EventLoggerInnerMiddleware(_ev)` (검토 I2) | 15분 |
| 9 | — | 확인만 | **T3 실측** — 도구 호출이 실제로 잡히는지. 여기서 갈린다 | 20분 |
| 10 | `assistant/report.py` | 신규 | `list` / `show`(계층형 trace + 하단 지표) / `fail` / `stats`(지표 함수 래퍼) | 75분 |
| 11 | `tests/test_report.py` | 신규 | 고정 jsonl 픽스처로 출력 검증 | 20분 |
| 12 | `docs/plan/step2_result.md` | 신규 | 결과 기록 (실패 포함) | 20분 |

> ⚠️ **2~6번은 리뷰 반영 전에 이미 실행됐다 (2026.09.17).** 저장소에 `assistant/__init__.py`,
> `assistant/events.py`, `assistant/pyproject.toml`, `tests/test_events.py`가 있고
> `libs/code/pyproject.toml:33, 215`에 배선이 들어가 있다.
> **리뷰 대기 중 저위험 배선 작업(패키지 뼈대 · 의존성 1줄)을 선행했고, 로직 구현은 리뷰 반영 후 착수한다.**
> 숨기지 않고 남긴다 — 채점 2-4는 순서를 지켰는지를 보는 항목이고, 어긋난 것을 기록하는 편이
> 커밋 타임스탬프와 모순되지 않는다. (검토 R3)
> **5번의 `events.py`는 D7의 새 타입과 D2b 때문에 다시 손봐야 한다.**

**8번이 dcode 원본을 건드리는 유일한 곳.** import 1줄 + 생성 1줄 + insert 2줄. 그 이상 늘어나면 설계가 틀린 것이다.

## 5. 설계 결정과 근거

**D1. run 단위 = 사용자 요청 1개 (turn)**
`before_agent`에서 run 시작, `after_agent`에서 종료. 4-1의 "전체 실행 흐름"이 요청 단위로 깔끔하고, 4-4의 "실패 지점"도 요청 단위로 짚힌다. 출력은 `runs/<run_id>/events.jsonl`.
`run_id` = `{시각 YYYYMMDD-HHMMSS}-{thread_id 앞 8자}`. thread_id를 못 구하면 랜덤 8자로 떨어진다(죽지 않는다).

> 🔴 **현재 run은 `contextvars.ContextVar`로 들고 간다** *(2026.09.17 추가, 검토 I3 — 구조에 박히는 결정)*
> 바깥 로거가 `before_agent`에서 run을 열고, 안쪽 로거(D2b)는 `wrap_model_call`에서 "지금 어느 run인지"를
> 알아야 한다. `EventWriter`에 `self.current_run_id` 같은 **평범한 속성**으로 들고 있으면
> **병렬 도구 호출과 서브에이전트에서 run이 섞인다.** `model_start`가 엉뚱한 run에 붙으면
> 4-1·4-3이 통째로 신뢰를 잃는다.
> `ContextVar`는 async 태스크마다 독립적으로 상속되므로 이 경합이 구조적으로 사라진다.
> **나중에 고치면 `EventWriter`를 다시 뜯어야 하므로 처음부터 이렇게 만든다.**

**D2. 바깥 로거 — `agent_middleware` 맨 앞**
custom 리스트 안에서 앞쪽일수록 바깥(S2). `ShellAllowList`·`AutoModeHITL`·`ServerHooks`가 모두 이 리스트의 뒤쪽이므로, **다른 미들웨어가 차단한 도구 호출도 우리 로그에 잡힌다** — 단계 3의 계획 게이트 차단을 기록하려면 이게 필수다. `before_agent`는 제일 먼저, `after_agent`는 역순이라 제일 나중에 불린다. run 경계로 딱 맞다.
(SDK core 5종보다는 안쪽이지만, 우리가 기록할 대상은 전부 custom 리스트 안에 있으므로 목적은 달성된다.)

**D2b. 안쪽 로거 — `agent_middleware` 맨 끝** 🔴 *2026.09.17 추가 (검토 R2)*

바깥 로거만으로는 **재시도 횟수가 항상 0으로 나온다.** `CodeModelRetryMiddleware`의 재시도는
그 미들웨어 **내부 루프**(`model_retry.py:633, 685`의 `for attempt in range(max_retries + 1)`)이고,
이 미들웨어는 `agent.py:3552` 근처에서 리스트 뒤쪽에 append된다.
바깥에 있는 로거의 `wrap_model_call`은 재시도 5회를 `model_start`/`model_end` **한 쌍**으로만 본다.
채점 **4-3이 "재시도 횟수"를 명시**하므로 이대로면 그 지표의 증거가 구조적으로 안 나온다.

→ 이름이 다른 얇은 두 번째 미들웨어 `EventLoggerInnerMiddleware`를 `create_deep_agent` 호출 직전
`agent_middleware` **맨 끝**에 append하고, 바깥 로거와 **같은 `EventWriter` 인스턴스를 공유**한다.
맨 끝 = `CodeModelRetry`보다 안쪽이므로 attempt마다 `wrap_model_call`이 불린다.

| | 담당 |
|---|---|
| 바깥 `EventLoggerMiddleware` | `run_start`/`run_end`, `tool_*`, `code_changed`, (단계 3) `gate_block` |
| 안쪽 `EventLoggerInnerMiddleware` | `model_start`/`model_end`/`model_error` — **attempt 단위**. `attempt` 필드 포함 |

**`EventWriter`는 생성자 주입으로 공유한다** *(검토 I2)* — 모듈 전역 싱글턴은 쓰지 않는다.
테스트에서 격리가 안 되고(T3-u가 writer를 일부러 터뜨려야 한다), 서브에이전트·병렬 실행에서 상태가 섞인다.
배선은 **2곳이 아니라 3곳 3줄**이다:

```python
_ev = EventWriter()                                        # ⓪ 공유 인스턴스 생성
agent_middleware = [EventLoggerMiddleware(_ev), ...]       # ① 맨 앞  (바깥)
...
agent_middleware.append(EventLoggerInnerMiddleware(_ev))   # ② 맨 끝  (안쪽)
```

> **"배선은 한 곳" 원칙과 부딪히는 것에 대해** — 원칙을 굽힌다. 그 원칙의 목적은 남의 소스를
> 최소한만 건드려 되돌리기 쉽게 하는 것이지 숫자 1을 지키는 게 아니다. 두 곳 모두
> `import 1줄 + insert 1줄`이라 목적은 그대로다. **원칙이 채점 항목과 충돌하면 채점 항목이 이긴다.**

**D3. sync·async 6개 훅을 전부 구현한다**
S4가 핵심이다. 서버 그래프는 async로 돈다. `wrap_tool_call`만 만들고 `awrap_tool_call`을 빼면 **TUI에서 로그가 한 줄도 안 남는다.** 판정 로직은 `_record()` 하나에 모으고 sync/async 래퍼는 얇게 감싼다 (S3의 `ShellAllowListMiddleware`가 쓰는 구조 그대로).

**D4. 로거는 fail-open, 게이트는 fail-closed**
8일차 22p의 "판정 실패를 통과로 읽지 않는다"는 **판정자**에게 적용되는 원칙이다. 로거는 판정자가 아니라 관측자다. 로그를 못 써서 사용자의 작업이 죽으면 그게 더 나쁘다.
→ 모든 훅을 `try/except Exception`으로 감싸고, 실패 시 **조용히 통과**시키되 `logger.debug`로 남긴다.
→ 단, 단계 3의 `plan_gate`는 **자기 차단 사건을 별도 경로로도 기록**한다. 감사 로그가 없다고 차단 증거가 사라지면 안 된다. (단계 3 계획에서 다룸)

**D5. stdout에 절대 쓰지 않는다**
TUI는 Textual 앱이다. `print()` 한 줄이 화면을 깨뜨린다. `EventWriter`는 파일에만 쓰고, 진단은 `logging` 모듈로만 낸다. DC6이 이걸 검증한다.

**D6. 민감정보 절삭**
도구 인자에 `.env` 내용·API 키가 들어올 수 있다. 저장 규칙: 문자열 값은 **앞 200자까지만**, 그 뒤는 `…(+N chars)`. `content`·`command`처럼 큰 필드는 길이와 SHA-256 앞 8자만. 키 이름이 `key|token|secret|password`에 매칭되면 값 전체를 `***`. 저장소를 제출하므로 `runs/`는 `.gitignore`에 이미 들어 있다 ✓.

> 🔴 **예외 (검토 C4)** — `status=error` 이벤트는 한도를 **1000자**로 올린다.
> 실패 원인이 인자 뒷부분(긴 경로 끝, 명령 뒷단)에 있으면 200자 절삭 때문에 `report fail`로 봐도
> 원인이 안 보인다. **4-4는 "실패 지점과 원인을 확인"이 요구사항**이라 절삭이 채점과 정면으로 부딪힌다.
> 키 마스킹(`***`)은 한도와 무관하게 항상 적용한다.

**D7. 이벤트 스키마 — 한 줄에 하나**
```json
{"ts":"2026-09-17T09:12:33.120+09:00","run_id":"20260917-091233-a1b2c3d4","seq":12,
 "type":"tool_end","name":"write_file","status":"error","dur_ms":84,
 "error":"blocked by PEP8 gate: I001, F401","data":{"file_path":"test_bad.py"}}
```

| type | 발생 지점 | 담는 것 |
|---|---|---|
| `run_start` | `before_agent` | 사용자 입력(절삭), thread_id, cwd, 모델명 |
| `model_start` / `model_end` | `wrap_model_call` | 모델명, 소요, 토큰 in/out, 요청한 도구 이름들 |
| `model_error` | 〃 (예외) | 예외 타입·메시지 |
| `tool_start` / `tool_end` | `wrap_tool_call` | 도구명, 인자(절삭), status, 소요, 결과 길이 |
| `run_end` | `after_agent` | 총 소요, 이벤트 수, 실패 수 |
| `gate_block` | **단계 3 예약** | 차단 사유, 요구한 도구 |
| `memory_hit` / `improve_*` | **단계 4 예약** | — |

**🔴 2026.09.17 추가 — 공식 평가 가이드라인 반영**
4-1의 공식 문구는 "요청별로 **계획·리뷰·코드 변경·테스트·최종 결과**의 전체 실행 흐름 기록 [3]"이다.
위 타입만으로는 로그에 **계획·리뷰·테스트가 이름으로 드러나지 않는다.** 채점자가 로그를 열었을 때
저 다섯 단계가 보여야 3점이 온전하다. 다음 타입을 **단계 2에서 함께 예약**한다:

| type | 채우는 단계 | 담는 것 |
|---|---|---|
| `plan_created` | 단계 3 | 계획 id, 대상 파일 목록, 완료조건 |
| `plan_reviewed` | 단계 3 | 리뷰어(서브에이전트) 의견 요약, 반영 여부 |
| `plan_approved` | 단계 3 | 승인 시각, 승인된 파일 목록 |
| `code_changed` | 단계 2에서 바로 | 변경된 파일 경로, 도구명, 라인 증감 (`tool_end`에서 파생) |
| `test_run` | 단계 5 | 명령, 통과/실패 수, 소요 |
| `run_result` | 단계 2에서 바로 | 최종 결과 요약 (`run_end`와 함께) |

`code_changed`와 `run_result`는 **단계 2에서 실제로 기록한다** — 쓰기 도구(`write_file`/`edit_file`/`execute`)의
`tool_end`에서 파생하면 되므로 추가 비용이 거의 없고, 4-1의 "코드 변경"과 "최종 결과"가 바로 채워진다.
나머지는 상수만 선언해둔다.

`report.py show`는 타임라인을 **계획 → 리뷰 → 승인 → 코드 변경 → 테스트 → 결과** 순서의 구획으로
보여준다. 아직 안 채워진 구획은 `— (단계 N에서 구현)`으로 표시한다. 채점자가 화면 하나로
4-1의 다섯 항목을 확인할 수 있게 하는 것이 목적이다.

**출력은 평면 목록이 아니라 계층형 trace 뷰로 한다** (4-4의 "로그·**Trace**를 조회" 문구, 검토 G5).
들여쓰기 한 단계만 있어도 Trace로 읽힌다 — 비용 대비 효과가 가장 큰 구간이다:

```
run 20260917-091233-a1b2c3d4   (12.4s, 실패 1)
├─ model_call #1          2.1s   in=4820 out=132
├─ tool  read_file        0.1s   ok
├─ model_call #2          3.8s   in=5310 out=88   attempt=2/3
└─ tool  write_file       0.1s   ERROR  blocked by PEP8 gate: I001, F401

지표  모델 3회 · 도구 2회 · 재시도 1회 · 총 12.4s · 토큰 in 10130 / out 220
```

하단 지표는 `_collect_metrics(run)` 하나로 계산하고 **`show`에 항상 붙인다** — 채점자가
`stats` 서브커맨드를 따로 찾아 들어가지 않기 때문이다 (검토 C6). `stats`는 같은 함수를 부르는
얇은 래퍼로 남긴다.

> **결과 길이에 대한 주의 (검토 C5)** — `FilesystemMiddleware.wrap_tool_call`(`filesystem.py:3605-3628`)이
> 큰 도구 결과를 파일로 evict하는데 이건 우리보다 바깥이다. 우리가 기록하는 결과 길이는
> **eviction 전** 값이다. 의도된 동작이며, 스키마 주석에 한 줄 남긴다.

**D8. `assistant/`는 저장소 루트, editable path 의존으로 설치**
S9 때문에 그냥 두면 설치가 안 된다. `[tool.uv.sources]`에 editable path로 얹으면 S8의 `deepagents`와 **같은 방식**이라 채점자 환경에서도 동일하게 동작한다. 내 코드가 vendoring된 원본 트리 안에 섞이지 않아서 "채점자가 읽을 코드"가 `assistant/` 하나로 분명해진다.
**대안(4번에서 실패 시)** — `assistant/`를 `libs/code/assistant/`로 옮기고 `packages = ["deepagents_code", "assistant"]`. 확실히 되지만 원본과 내 코드가 섞인다.

## 6. 테스트 방법 (2-2)

### 단위 (`uv run --project libs/code pytest tests/`)
| | 검증 |
|---|---|
| **T1** | `EventWriter`에 100줄을 동시에 쓰면 100줄이 전부 유효 JSON으로 파싱된다 (async 병렬 도구 호출 대비) |
| **T2** | 절삭 규칙: 300자 문자열 → 200자 + 꼬리표. `api_key` 키 → `***`. `content` → 길이+해시 |
| **T3-u** | 훅 안에서 `EventWriter`가 예외를 던져도 미들웨어가 예외를 밖으로 내보내지 않고 `handler` 결과를 그대로 반환한다 (D4) |
| **T1b** | 🔴 서로 다른 run 2개를 **async로 동시에** 열고 각각 이벤트를 쓴 뒤, 두 `events.jsonl`에 상대 run의 이벤트가 **한 줄도 섞이지 않는다** (D1의 `ContextVar`, 검토 I3). T1은 동시 *쓰기*만 보고 이 경합은 못 본다 |
| **T4-u** | `run_end`가 없는 jsonl을 `report`가 크래시 없이 "미종료"로 표시한다 |
| **T11-u** | 🔴 **DC7의 1차 증거.** `CodeModelRetryMiddleware` + `EventLoggerInnerMiddleware`를 스택으로 조립하고 handler가 429(또는 503)를 **두 번** 던지게 한다 → `model_start`/`model_end`가 attempt 단위로 **3쌍** 남는다 (검토 I1) |

### TUI 실측 (증거는 전부 여기서)
| | 절차 | 기대 |
|---|---|---|
| **T3** | TUI에서 "README.md 읽어줘" | `events.jsonl`에 `tool_start`/`tool_end`(read_file) 존재 → **도구 호출이 잡히는지 확인하는 관문** |
| **T5** | `report show <run_id>` | 타임라인 + 총 소요 (DC3) |
| **T6** | TUI에서 "없는파일.txt 읽어줘" → `report fail <run_id>` | `status=error` 이벤트와 직전 3개 맥락만 출력 (DC4) |
| **T7** | TUI에서 PEP8 위반 코드 `write_file` 요청 | 차단이 `tool_end status=error`로 기록됨 (단계 3 대비 예행) |
| **T8** | 요청 중 Ctrl+C → `report list` | 해당 run이 "미종료"로 표시, 크래시 없음 |
| **T9** | ① `chmod 500 runs/` ② **`runs/`를 지우고 저장소 루트를 읽기전용으로** 만든 뒤 TUI 작업 | 둘 다 **TUI 정상 동작**, 로그만 안 남음 (DC5). ②가 진짜 실패 경로다 — `before_agent`가 처음 하는 일이 `runs/<run_id>/` **생성**이라, 디렉터리를 만들 수 없는 경우가 fail-open이 깨지는 지점이다 (검토 C3) |
| **T10** | 위 전 과정 동안 화면 | 로거 출력 섞임 없음 (DC6) |
| **T11** | 🔴 재시도 유발. ~~잘못된 모델명·키~~ → **꼭 필요하면** 요청 도중 프록시/네트워크를 잠깐 끊어 httpx 전송 오류를 낸다 (`model_retry.py:450`) | `attempt=2/3` 표기 + 지표에 **재시도 1회 이상** (DC7). **1차 증거는 T11-u 단위 테스트다** |
| **T12** | `report show <run_id>` 출력 형태 | 계층형 trace + 하단 지표 (DC8) |

## 7. 리스크

| 리스크 | 왜 | 대응 |
|---|---|---|
| ⚠️⚠️ **서브에이전트 내부가 안 보인다** | GP 서브에이전트는 fork 모드로 부모 미들웨어를 상속하지만, `graph.py:822`의 `_gp_inheritable = [m for m in middleware if m.name in _gp_original_name_to_index]`가 **GP 기본 슬롯과 이름이 겹치는 것만** 상속한다. 새 이름인 `EventLoggerMiddleware`는 안 넘어간다 (검토 C2 — `agent.py:3055-3057`만 보면 반대로 읽히니 주의) | 메인에서는 `task` 도구 호출 1건으로 보인다. **README에 이 경계를 명시.** 필요해지면 이름을 슬롯에 맞추는 꼼수 말고 `_subagent_cli_middleware`(`agent.py:2885`)에 직접 배선 |
| ⚠️ **`before_agent`에서 thread_id를 못 구함** | 베이스 시그니처가 2인자(S6) | **1순위로 `memory.py:279`의 3인자 선례를 그대로 따라 해본다** — `def before_agent(self, state, runtime, config: RunnableConfig)` + `# ty: ignore[invalid-method-override]`. 타입체커만 불평하고 런타임은 config를 준다는 뜻이다. S6은 베이스 시그니처일 뿐 상한이 아니다 (검토 C1). 실패하면 `langgraph.config.get_config()`, 그것도 실패하면 랜덤 id |
| ⚠️ **패키지명 `assistant`가 PyPI에 이미 있을 수 있음** | `[tool.uv.sources]`는 **uv 전용**. 채점자가 `pip install -e libs/code`로 가면 PyPI에서 `assistant`를 찾아 남의 패키지가 깔린다. AC1 직결 (검토 R4) | `curl -s -o /dev/null -w "%{http_code}" https://pypi.org/pypi/assistant/json`로 확인. `200`이면 배포명을 `sds-assistant`로(import 이름 `assistant`는 유지). 어느 쪽이든 **README에 `uv` 사용을 명시** |
| ⚠️ **`after_agent`가 HITL 인터럽트에서 안 불림** | 승인 대기로 그래프가 멈추면 run이 안 닫힘 | `run_end` 없는 run을 `report`가 정상 처리 (T4-u, T8). 다음 `run_start` 때 이전 run을 `interrupted`로 마감 |
| ⚠️ **`libs/libs/` 정리하다 `uv sync`를 깨뜨림** | S8의 상대경로 의존 | 삭제 직후 `uv sync` + `dcode --version` 재확인 (작업 0번) |
| ⚠️⚠️ **채점자가 빌드 단계에서 막힌다** | F4 — 프로바이더 extra 없이 `uv sync`하면 TUI가 안 뜬다. 여기서 막히면 나머지 30점이 채점 자체가 안 된다 | README 기본 절차를 `--extra all-providers`로. 깨끗한 디렉터리 clone→빌드→실행을 단계 5에서 반드시 재현 |
| ⚠️ **내 PC ≠ 채점자 PC (재확인)** | 09.17 `dcode config path`가 전역 `~/.deepagents/config.toml (ok)`, `hooks trust (ok)`, `auth.json (ok)`를 보여줌. 승인 모드 `auto`와 훅 신뢰가 **내 전역 상태에만** 있다 | 게이트·로거를 승인 모드와 무관하게 설계(D2·D4). README에 채점자가 자기 모델 키를 넣는 절차(`dcode auth` 또는 환경변수)를 명시 |
| 이벤트 파일이 커짐 | 큰 도구 결과 | D6 절삭으로 한 이벤트 상한을 둔다 |

## 8. 착수 전 확인 (Claude Code 첫 30분)

순서대로, **하나라도 실패하면 멈추고 보고**한다.

> 0·1번은 2026.09.17에 이미 끝났다. 남은 것은 아래 0과 2·3.

```bash
# 0. 중복 제거 (아직 안 했으면)
rm -rf libs/libs && uv sync --project libs/code && uv run --project libs/code dcode --version
git add -A && git commit -m "drop duplicated libs/libs" && git push

# 1. ✅ 완료 — 실행 커맨드는 `uv run --project libs/code dcode -a coding-assistant` (저장소 루트에서)

# 2. 훅 시그니처 재확인 (문서가 아니라 소스로)
grep -n "def awrap_tool_call\|def wrap_tool_call\|def before_agent\|def after_agent" \
  libs/code/deepagents_code/agent.py libs/deepagents/deepagents/middleware/*.py

# 3. 삽입 지점 확인
sed -n '3070,3080p' libs/code/deepagents_code/agent.py
```

## 9. 기록

단계가 끝나면 `05_프로젝트/step2_result.md`에 남긴다 — **실패한 것도 쓴다** (PLAN.md §6).
다음 단계(계획 게이트)는 이 로거의 `gate_block` 타입 위에 올라간다.
