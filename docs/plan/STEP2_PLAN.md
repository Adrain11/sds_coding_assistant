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
| S2 | **리스트 앞쪽 = 바깥쪽** (`first = outermost`). `before_agent`는 리스트 순서, **`after_agent`는 역순** | `agent.py:3063`, `agent.py:3101` 주석 |
| S3 | `wrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage \| Command` | `agent.py:960` (`ShellAllowListMiddleware` 실물) |
| S4 | **`awrap_tool_call` 비동기 판이 따로 있고, 서버 그래프는 주로 async로 돈다** | `agent.py:979-983` 주석 + 시그니처 |
| S5 | `wrap_model_call(self, request: ModelRequest, handler) -> ModelResponse` / `awrap_model_call` | `libs/deepagents/deepagents/middleware/memory.py:385, 402` |
| S6 | `before_agent(self, state, runtime)` 2인자가 베이스 시그니처 | `middleware/patch_tool_calls.py:17` |
| S7 | 미들웨어에 `trace_policy = TracePolicy(process_inputs=omit_payload)` 관용구가 있음 | `agent.py:894` |
| S8 | `[tool.uv.sources] deepagents = { path = "../deepagents", editable = true }` — 상대경로 의존이라 `libs/` 구조를 깨면 빌드가 죽는다 | `libs/code/pyproject.toml:213-220` |
| S9 | 휠 패키지 목록은 `packages = ["deepagents_code"]` — **`assistant/`는 그냥 두면 설치 안 된다** | `libs/code/pyproject.toml:198-207` |
| S10 | 확장(extension) API로도 미들웨어 등록이 가능하지만 `DEEPAGENTS_CODE_EXPERIMENTAL=1` + 프로젝트 신뢰 프롬프트가 필요 | `libs/code/EXTENSIONS.md:3-5, 110-113` |

**S10의 의미** — PLAN.md가 "훅 대신 소스 배선"을 고른 판단이 소스로 확인됐다. 확장 API를 썼으면 step0에서 문제였던 신뢰 프롬프트가 그대로 돌아온다. **소스 배선이 맞다.**

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

**F3. 단계 1의 "이식"이 안 돼 있었다 — 2026.09.17 처리 완료**
GitHub 저장소를 확인한 결과 커밋 1개(`baseline: dcode 0.1.69 source`)에 루트가 `.gitignore`와 `libs/`뿐이었다.
PLAN.md 단계 1 표의 이식 대상(`.agents/skills/` 8종, `.claude/skills/`, `.env.example`, `SKILLS.md`,
`skills-lock.json`, `.deepagents/AGENTS.md`)이 전부 빠져 있었다.
→ 09.17 오전에 `sds_final_project`에서 복사 완료. `readlink -e .claude/skills/*` = 13개 전부 해소 확인.
→ `.gitignore`에 `.claude/settings.local.json` 추가 (원본 저장소에는 있었는데 빠져 있었다 — 토큰 유출 예방).
→ `hooks/pep8_gate.py`는 로직만 단계 5에서 재사용하므로 복사하지 않는다.

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

- [ ] **DC1** 깨끗한 셸에서 `uv run --project libs/code dcode -a coding-assistant`로 TUI가 뜨고, `dcode config path`가 **저장소 루트**를 가리킨다
- [ ] **DC2** TUI에서 파일 읽기 한 번 시키면 `runs/<run_id>/events.jsonl`이 생기고, `run_start` / `model_*` / `tool_*` / `run_end`가 전부 들어 있다
- [ ] **DC3** `python -m assistant.report show <run_id>`가 그 요청의 타임라인과 **총 소요 시간**을 보여준다
- [ ] **DC4** 일부러 실패시킨 도구 호출(없는 파일 읽기)이 `status=error`로 남고, `report fail <run_id>`로 **그 지점만** 뽑힌다
- [ ] **DC5** 로그 디렉터리를 읽기 전용으로 만들어도 **TUI가 죽지 않는다** (로거는 fail-open — 아래 §5 D4)
- [ ] **DC6** TUI 화면에 로거가 만든 출력이 **한 글자도 섞이지 않는다**

## 4. 수정·생성 대상 파일과 작업 순서 (2-2)

| # | 파일 | 신규/수정 | 내용 | 예상 |
|---|---|---|---|---|
| 0-a | `.agents/`, `.claude/`, `.deepagents/`, `.gitignore` 등 | ~~신규~~ | ~~F3 이식~~ | ✅ 09.17 완료 |
| 0 | `libs/libs/` | **삭제** | F1 중복 제거 후 `uv sync` 재확인. **이미 푸시된 히스토리는 그대로 두고 삭제 커밋만 얹는다** | 15분 |
| 1 | — | ~~확인만~~ | ~~F2 실행 커맨드 실측~~ | ✅ 09.17 완료 |
| 2 | `assistant/__init__.py`, `assistant/pyproject.toml` | 신규 | 빈 패키지 | 10분 |
| 3 | `libs/code/pyproject.toml` | 수정 | `dependencies`에 `"assistant"` 1줄 + `[tool.uv.sources]`에 `assistant = { path = "../../assistant", editable = true }` 1줄 | 10분 |
| 4 | — | 확인만 | `uv run --project libs/code python -c "import assistant"` 통과 | 10분 |
| 5 | `assistant/events.py` | 신규 | `EventWriter` — run_id 발급, jsonl append, 민감정보 절삭 | 45분 |
| 6 | `tests/test_events.py` | 신규 | 동시 쓰기·절삭·미종료 run 단위 테스트 | 30분 |
| 7 | `assistant/observability.py` | 신규 | `EventLoggerMiddleware` — 6개 훅 (sync 3 + async 3) | 60분 |
| 8 | `libs/code/deepagents_code/agent.py` | **수정 (1곳)** | `agent_middleware` 리스트 **맨 앞**에 `EventLoggerMiddleware()` 삽입 (S2: 바깥쪽) | 10분 |
| 9 | — | 확인만 | **T3 실측** — 도구 호출이 실제로 잡히는지. 여기서 갈린다 | 20분 |
| 10 | `assistant/report.py` | 신규 | `list` / `show` / `fail` / `stats` | 60분 |
| 11 | `tests/test_report.py` | 신규 | 고정 jsonl 픽스처로 출력 검증 | 20분 |
| 12 | `05_프로젝트/step2_result.md` | 신규 | 결과 기록 (실패 포함) | 20분 |

**8번이 dcode 원본을 건드리는 유일한 곳.** import 1줄 + insert 1줄. 그 이상 늘어나면 설계가 틀린 것이다.

## 5. 설계 결정과 근거

**D1. run 단위 = 사용자 요청 1개 (turn)**
`before_agent`에서 run 시작, `after_agent`에서 종료. 4-1의 "전체 실행 흐름"이 요청 단위로 깔끔하고, 4-4의 "실패 지점"도 요청 단위로 짚힌다. 출력은 `runs/<run_id>/events.jsonl`.
`run_id` = `{시각 YYYYMMDD-HHMMSS}-{thread_id 앞 8자}`. thread_id를 못 구하면 랜덤 8자로 떨어진다(죽지 않는다).

**D2. 리스트 맨 앞에 삽입 = 가장 바깥**
S2에 따라 앞쪽일수록 바깥. 바깥에 있어야 **다른 미들웨어가 차단한 도구 호출도 우리 로그에 잡힌다** — 단계 3의 계획 게이트 차단을 기록하려면 이게 필수다. `before_agent`는 제일 먼저, `after_agent`는 역순이라 제일 나중에 불린다. run 경계로 딱 맞다.

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

예약 타입은 지금 `events.py`의 상수로만 선언해둔다. 단계 3·4에서 `report.py`를 안 고치고 바로 쓰기 위해서다.

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
| **T4-u** | `run_end`가 없는 jsonl을 `report`가 크래시 없이 "미종료"로 표시한다 |

### TUI 실측 (증거는 전부 여기서)
| | 절차 | 기대 |
|---|---|---|
| **T3** | TUI에서 "README.md 읽어줘" | `events.jsonl`에 `tool_start`/`tool_end`(read_file) 존재 → **도구 호출이 잡히는지 확인하는 관문** |
| **T5** | `report show <run_id>` | 타임라인 + 총 소요 (DC3) |
| **T6** | TUI에서 "없는파일.txt 읽어줘" → `report fail <run_id>` | `status=error` 이벤트와 직전 3개 맥락만 출력 (DC4) |
| **T7** | TUI에서 PEP8 위반 코드 `write_file` 요청 | 차단이 `tool_end status=error`로 기록됨 (단계 3 대비 예행) |
| **T8** | 요청 중 Ctrl+C → `report list` | 해당 run이 "미종료"로 표시, 크래시 없음 |
| **T9** | `chmod 500 runs/` 후 TUI에서 아무 작업 | **TUI 정상 동작**, 로그만 안 남음 (DC5) |
| **T10** | 위 전 과정 동안 화면 | 로거 출력 섞임 없음 (DC6) |

## 7. 리스크

| 리스크 | 왜 | 대응 |
|---|---|---|
| ⚠️⚠️ **서브에이전트 내부가 안 보인다** | `_subagent_cli_middleware`는 별도 스택 (`agent.py:3023`). 우리 미들웨어는 메인에만 있음 | 메인에서는 `task` 도구 호출 1건으로 보인다. **README에 이 경계를 명시.** 단계 3·4에서 필요해지면 서브에이전트 스택에도 같은 인스턴스를 넣는다 (agent.py 2888 라인 근처, 배선 1줄 추가) |
| ⚠️ **`before_agent`에서 thread_id를 못 구함** | 베이스 시그니처가 2인자(S6)라 `config`가 안 들어옴. `memory.py`는 3인자로 받지만 타입 무시 주석이 붙어 있음 | `langgraph.config.get_config()`를 `try/except`로 시도, 실패하면 랜덤 id. **작업 7번의 첫 30분에 실측** |
| ⚠️ **`after_agent`가 HITL 인터럽트에서 안 불림** | 승인 대기로 그래프가 멈추면 run이 안 닫힘 | `run_end` 없는 run을 `report`가 정상 처리 (T4-u, T8). 다음 `run_start` 때 이전 run을 `interrupted`로 마감 |
| ⚠️ **`libs/libs/` 정리하다 `uv sync`를 깨뜨림** | S8의 상대경로 의존 | 삭제 직후 `uv sync` + `dcode --version` 재확인 (작업 0번) |
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
