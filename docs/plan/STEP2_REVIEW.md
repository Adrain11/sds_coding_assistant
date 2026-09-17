# 단계 2 계획 리뷰 (2026-09-17, Claude Opus 5)

검증 대상: `libs/code/deepagents_code/agent.py`, `libs/deepagents/deepagents/graph.py`,
`.../middleware/{memory,patch_tool_calls,filesystem}.py`, `libs/code/deepagents_code/model_retry.py`,
`libs/code/pyproject.toml`, `libs/code/EXTENSIONS.md` — 전부 `main` 원본을 raw로 받아 직접 읽음.

## 반드시 고쳐야 할 것

### R1. S2가 반쪽이다 — "리스트 맨 앞 = 가장 바깥"은 dcode 리스트 **안에서만** 참이다

**무엇이** — S2는 `agent.py:3063`("리스트 앞쪽일수록 … first = outermost") 한 줄만 인용했는데,
**바로 다음 줄인 3064~3066**이 그 전제를 제한한다:

> `이 리스트는 SDK _apply_custom_middleware로 병합된다: … 나머지는 이 리스트의 순서를 유지한 채
> 마지막 core(PatchToolCalls 또는 AsyncSubAgent) 뒤 … 삽입`

**왜** — `graph.py:204-236`의 실제 구현이 이렇다.
`pos = max(i for i, m in enumerate(result) if m.name in core_names) + 1` 위치에 통째로 끼워 넣는다
(`graph.py:229-231`). core는 `graph.py:860-898`에서 잡히는
`Skills → Filesystem → SubAgent → Summarization → PatchToolCalls`.
즉 `agent_middleware[0]`에 넣어도 **이 다섯보다는 안쪽**이다.

**어떻게** — D2의 실무 목적(단계 3 게이트의 차단을 로그에 남기기)은 그대로 성립한다.
`ShellAllowList`·`AutoModeHITL`·`ServerHooks`가 전부 같은 리스트의 뒤쪽이라 여전히 우리가 바깥이다.
문구만 정정하면 된다 — S2를 "**dcode custom 리스트 내에서** 앞쪽 = 바깥쪽이며,
SDK core 5종보다는 안쪽(`graph.py:229`)"으로.

### R2. 4-3의 "재시도 횟수"가 이 설계로는 항상 0으로 나온다 ← 가장 중요

**무엇이** — 재시도는 `CodeModelRetryMiddleware` **내부 루프**다.
`model_retry.py:633`, `:685`에 `for attempt in range(max_retries + 1)`.
이 미들웨어는 `agent.py:3552-3558`에서 리스트 **뒤쪽**에 append된다.

**왜** — 맨 앞(=바깥)에 넣은 로거의 `wrap_model_call`은 재시도 5번을
`model_start`/`model_end` **한 쌍**으로 본다. 재시도가 안쪽에서 다 끝나고 최종 결과만 밖으로 나오기 때문.
채점 4-3은 "시간·횟수·**재시도** 지표"인데 재시도만 증거가 안 나온다.
그리고 §3의 DC1~DC6 어디에도 재시도 검증 항목이 없어서 이 구멍이 완료 판정에서도 안 걸린다.

**어떻게** — 이름이 다른 얇은 두 번째 미들웨어(`EventLoggerInnerMiddleware`)를
`agent_middleware` **맨 끝**에 추가하고 같은 `EventWriter` 인스턴스를 공유한다.
맨 끝 = `CodeModelRetry`보다 안쪽이므로 attempt마다 `wrap_model_call`이 불린다.
바깥 로거는 run·tool·gate_block, 안쪽 로거는 model attempt 담당.

- `agent.py` 수정이 1곳에서 2곳으로 늘어난다. §5의 "배선은 한 곳" 원칙과 부딪히지만,
  **원칙보다 채점 항목이 우선**이다. 대신 둘 다 import 1줄 + insert 1줄이라 원칙의 정신은 유지된다.
- §3에 `DC7 — report stats에 재시도 횟수가 attempt별로 나온다`를 추가하고,
  §6 TUI 실측에 재시도 유발 케이스(잘못된 키로 1회 실패 등)를 넣어라.

> 참고: dcode는 이미 `{"type":"model_retry", "attempt", "max_retries"}`를 custom 스트림으로 쏜다
> (`model_retry.py:1001` 생성, `:1179` `writer(event)`).
> 다만 이건 클라이언트(TUI 스피너)가 받는 경로라 미들웨어에서 주워담기 어렵다. 위 방식을 권한다.

### R3. 작업 2·3·4가 리뷰 전에 이미 실행됐다 — 기록하지 않으면 2-4 감점 요인이다

**무엇이** — `libs/code/pyproject.toml:33`에 `"assistant"`,
`:215`에 `assistant = { path = "../../assistant", editable = true }`가 이미 있다.
저장소에 `assistant/__init__.py`, `assistant/events.py`, `assistant/pyproject.toml`,
`tests/test_events.py`가 존재한다. §4 표의 2~6번이 진행된 상태다.

**왜** — WORKFLOW.md §0은 단계 2를 "리뷰 대기"로, §4 순서도는 `[리뷰] → [반영] → [구현]`으로 적어놨다.
채점 2-4는 "승인 후에만 변경, 범위 변경 시 재검토"다. 순서 위반이 커밋 타임스탬프에 그대로 남는다.

**어떻게** — 숨기는 것보다 기록하는 게 유리하다. §4 표의 2~6번에 0-a처럼 `✅ 09.17 완료` 표시를 달고,
"리뷰 대기 중 저위험 배선 작업(패키지 뼈대·의존성 1줄)을 선행함. 로직 구현은 리뷰 반영 후 착수"
한 줄을 남겨라. WORKFLOW.md §0도 같이 갱신.

### R4. 패키지 이름 `assistant`는 PyPI와 충돌할 수 있다 — **확인 필요**

**무엇이** — `dependencies`에 `"assistant"`가 들어갔고 `[tool.uv.sources]`가 이걸 로컬 경로로 돌린다.
`uv sync --project libs/code`로는 문제없다.

**왜** — `[tool.uv.sources]`는 **uv 전용**이다. 채점자가 `pip install -e libs/code`로 가면
uv sources가 무시되고 pip이 PyPI에서 `assistant`라는 이름을 찾는다.
`assistant`는 충분히 흔한 이름이라 남의 패키지가 설치될 수 있다. AC1이 여기 걸린다.

**어떻게** — 확인 방법: `pip index versions assistant` 또는
`https://pypi.org/pypi/assistant/json`에 GET(200이면 존재).
존재하면 `sds-assistant` 같은 고유한 배포명으로 바꾸고(import 이름 `assistant`는 유지 가능),
README 실행 절차에 **uv 사용을 명시**해라. 지금 파일 3개일 때 바꾸는 게 싸다.

## 고려해볼 것

**C1. thread_id — `get_config()`보다 나은 선례가 소스에 있다.**
`memory.py:279`가 `def before_agent(self, state: MemoryState, runtime: Runtime, config: RunnableConfig)`
— 3인자에 `# ty: ignore[invalid-method-override]`가 붙어 있다.
타입체커만 불평하고 런타임은 config를 준다는 뜻이다.
S6(`patch_tool_calls.py:17`의 2인자)은 베이스 시그니처일 뿐 상한이 아니다.
§7 리스크의 "작업 7번 첫 30분 실측" 대상에 이 선례를 1순위로 넣어라.

**C2. 서브에이전트 미가시 리스크 — 결론은 맞고 근거가 부정확하다.**
계획서는 "별도 스택(`agent.py:3023`)"이라 했는데, `agent.py:3055-3057`은 GP 서브에이전트가
fork 모드로 "**부모 미들웨어 전체를 상속**"한다고 쓰여 있어서 그것만 보면 계획이 틀린 것처럼 읽힌다.
실제 구현은 `graph.py:822`:
`_gp_inheritable = [m for m in middleware if m.name in _gp_original_name_to_index]`
— **GP 기본 슬롯과 이름이 겹치는 것만** 상속한다. 새 이름인 `EventLoggerMiddleware`는 안 넘어간다.
→ 결론 유지, 근거를 `graph.py:822`로 교체. 나중에 서브에이전트까지 보고 싶으면
이름을 슬롯에 맞추는 꼼수 말고 `_subagent_cli_middleware`(`agent.py:2885`)에 직접 배선해라.

**C3. DC5의 검증 방법이 실제 실패 경로를 안 건드린다.**
`chmod 500 runs/`는 **이미 만들어진** 디렉터리의 쓰기를 막는다.
하지만 `before_agent`가 처음 하는 일은 `runs/<run_id>/` **생성**이다.
T9에 "`runs/`의 부모를 읽기전용으로 만들어 디렉터리 생성 자체가 실패하는 경우"를 추가해라.
fail-open이 깨지는 건 대개 이쪽이다.

**C4. D6 절삭이 4-4와 상충한다.**
문자열 200자 절삭 + `content`는 해시만. 그런데 도구 실패 원인이 인자 뒷부분
(긴 경로 끝, 명령 뒷단)에 있으면 `report fail`로 봐도 원인이 안 보인다.
`status=error` 이벤트에 한해 한도를 1000자로 올리는 걸 고려.

**C5. 결과 길이가 원본 길이가 아닐 수 있다.**
`FilesystemMiddleware.wrap_tool_call`(`filesystem.py:3605-3628`)이 큰 도구 결과를 파일로 evict한다.
이게 우리보다 바깥이므로 우리가 기록하는 결과 길이는 **eviction 전** 값이다.
의도라면 그대로 두되 D7 스키마 주석에 한 줄 명시.

**C6. `report stats`는 과설계다.**
§0 기준 남은 시간이 1.5일인데 단계 3·4·5가 전부 계획 미작성이다.
4-3 지표는 `show` 출력 하단에 붙이면 된다.
`list`/`show`/`fail` 셋만 먼저 만들고, `stats`는 시간이 남으면.

## 계획대로 두는 게 맞다고 본 것

- **D3 (sync/async 6훅 전부 구현)** — 맞다. 이게 이 단계의 성패다.
  `ShellAllowListMiddleware`가 `agent.py:960`(sync) / `:979`(async)에서 정확히 계획이 말한 구조
  (`_validate_tool_call` 하나 + 얇은 래퍼 둘)로 돼 있다. 그대로 베껴라.
- **D4 (로거 fail-open, 게이트 fail-closed)** — 맞다. "판정 실패를 통과로 읽지 않는다"를
  관측자에게까지 확대하지 않은 구분이 타당하고, 단계 3에서 차단 사건만은 별도 경로로도 남기겠다는
  보완까지 있어서 감사 로그 구멍도 막힌다.
- **D5 (stdout 절대 금지)** — 맞다. TUI가 Textual이고 DC6이 이걸 검증한다.
  `EventWriter`를 파일 전용으로 두고 진단은 `logging`으로만 낸다는 것까지 정확하다.
- **D7의 예약 타입 (`gate_block`, `memory_hit`, `improve_*`)** — 맞다.
  단계 3·4에서 `report.py`를 안 고치려는 의도가 실제로 시간을 아낀다. 상수만 선언해두는 비용이 거의 0이다.
- **S10 판단 (확장 API 대신 소스 배선)** — 맞다.
  `EXTENSIONS.md:3-5`의 `DEEPAGENTS_CODE_EXPERIMENTAL=1`,
  `:108-113`의 프로젝트 확장 신뢰 프롬프트(`--trust-project-extensions`)를 확인했다.
  step0에서 훅 신뢰가 문제였던 것과 **같은 함정**이 그대로 돌아온다. 소스 배선이 맞다.
- **S1·S3·S4·S5·S6·S7·S8·S9 전부 실측과 일치.** 줄번호까지 맞다
  (S9는 실제 `:200`, 계획의 `198-207` 범위 표기로 문제없음). 인용 정확도가 높아서 리뷰가 빨랐다.
- **§2 "안 하는 것"에 LangSmith를 넣은 판단** — 맞다.
  채점자 키에 의존하는 증거는 증거가 아니다. 파일 로그를 유일한 증거로 삼은 게 옳다.

---

**요약** — 치명적인 건 하나다. **R2(재시도 횟수)**.
나머지는 문구 정정(R1, C2), 기록 위생(R3), 싼 예방(R4)이다. R2만 반영하면 항목 4의 10점이 다 나온다.
