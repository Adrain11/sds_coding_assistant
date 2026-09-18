# 단계 4 결과 — 메모리·자기개선

**구현 완료** 2026.09.18 · 담당 🟢구현 · **TUI 완료조건(MC1~MC7)은 아직 👤사람 확인 대기**

## 🔴 A2 — Blocking I/O 게이트 버그 수정 (2026-09-18, `STEP4_CODE_REVIEW.md`)

🔵검토가 `docs/plan/STEP4_CODE_REVIEW.md`에서 지적한 A2. `step3_result.md`의 S18로도
기록했다 — 승인된 계획이 있어도 `write_file`/`edit_file`/`delete`/`task`가 TUI에서 전부
막히는, 단위 테스트로는 절대 안 잡히는 버그였다. **최우선으로 처리했다.**

**증상 (재확인)** — `PlanGateMiddleware._check()` → `_approved_plans()` → (이전)
`PlanStore.list_ids()`의 `Path.glob("*.json")` + `_relative_to_project`의 `Path.resolve()`.
둘 다 미들웨어 훅(`wrap_tool_call`/`awrap_tool_call`, 이벤트 루프 스레드)에서 실행되는데,
이 경로는 일반 `@tool` 본문과 달리 LangGraph `ToolNode`가 스레드 풀로 감싸주지 않는다 —
Blockbuster가 블로킹 콜로 잡고 D6(fail-closed)가 차단으로 바꾼다. 단계 2 S13(`os.mkdir`) →
이 버그(S18) → `memory.py`(아래 참고)로 **세 번째 재발**.

**고친 것 (`assistant/assistant/plan_gate.py`):**

1. `__init__`에서 **한 번만** `self._known_plan_ids = self._store.list_ids()`로 디렉터리를
   스캔한다(`PlanStore.__init__`의 `mkdir`과 같은 시점·같은 안전성 근거 — 에이전트 구성
   시점이라 이벤트 루프 요청 경로가 아니다). `create_plan`이 새 plan_id를 만들 때마다 이
   리스트에 그 자리에서 `append`한다(I/O 없음). `_approved_plans()`는 이제 이 **인메모리
   목록**만 돌면서 `self._store.get(plan_id)`(단일 파일 읽기, 순회 아님)로 상태를 확인한다
   — `list_ids()`(글롭)는 이 미들웨어의 어떤 핫패스에서도 더 이상 호출되지 않는다.
2. `_relative_to_project`의 `Path.resolve()`(stat/symlink syscall)를 **`os.path.normpath`**
   (순수 문자열 연산)로 교체했다. `_is_tcb_path`/`_path_in_scope` 둘 다 이 함수를 쓰므로
   게이트의 모든 스코프·TCB 판정이 한 번에 해결됐다. `docstring`이 이미 "never used for
   filesystem access"라고 명시했던 대로, 실제 파일 접근이 필요 없는 자리였다.
4. **sync 경로 확인** — `wrap_tool_call`(sync)과 `awrap_tool_call`(async)은 같은
   `_validate_tool_call()`을 호출한다. 1·2번(글롭·`resolve` 제거)은 로직 자체가 바뀐
   것이라 두 경로 모두에 동일하게 적용됐다. 남은 read/write(아래 "2라운드" 참고)는 로직이
   아니라 **어느 스레드에서 도는가**의 문제라 두 경로가 원래 달라야 맞다 — sync 경로는
   이벤트 루프가 아니므로 그대로 두고, async 경로만 `asyncio.to_thread`로 감쌌다.
5. `test_dotdot_path_still_hits_tcb`(`tests/test_plan_gate.py`) 추가 — `os.path.normpath`가
   `Path.resolve()`와 동일하게 `..`를 접는지 확인한다
   (`.deepagents/skills/../../assistant/assistant/plan_gate.py` → TCB 차단, 존재하지 않는
   중간 디렉터리로도 통과).

**실제로 없어졌는지 검증** — 단위 테스트가 이벤트 루프 밖에서 돈다는 게 바로 이 버그가
처음에 안 잡힌 이유이므로, "테스트 통과"만으로는 증거가 안 된다. 그래서 `Path.glob`·
`Path.iterdir`·`Path.resolve`를 **호출되면 즉시 `AssertionError`를 내는 mock으로 patch**한
채로 승인/미승인 양쪽 경로를 돌리는 회귀 테스트 2개(`TestNoBlockingIOInHotPath`)를 추가했다
— "차단이 통과했다"가 아니라 "그 syscall 자체가 한 번도 안 불렸다"를 직접 증명한다.

```
uv run --project libs/code pytest tests/ -q
→ 122 passed  (기존 119 + dotdot 1 + no-blocking-io 2)
```

### A2 2라운드 — glob·resolve는 없앴지만 남은 read/write는 그대로였다

1라운드에서 "글롭·`resolve`가 사라졌다"까지 검증하고 끝냈는데, 🔵검토가 다시 짚었다:
`_approved_plans()`가 `self._known_plan_ids`의 각 id마다 부르는 `self._store.get(plan_id)`
(파일 read)와, 차단 시 `_block()` → `_append_gate_log()`의 `gate.log` 파일 write는
**여전히 남아 있었다.** Blockbuster의 기본 가드 목록(`blockbuster/blockbuster.py`)을 직접
확인해보니 `io.TextIOWrapper.read`/`.write`가 `os.scandir` 등과 나란히 등록돼 있다 —
**디렉터리 순회만이 아니라 일반 파일 read/write도 잡는다.** 1라운드의 회귀 테스트
(`Path.glob`/`iterdir`/`resolve`를 실패하게 patch)는 이 남은 read/write는 전혀 못 잡는
구멍이었다.

**고친 것** — `awrap_tool_call`(async 경로)만 수정했다:

```python
rejection = await asyncio.to_thread(self._validate_tool_call, request)
```

`wrap_tool_call`(sync)은 이벤트 루프가 아니므로 그대로 뒀다(둘 다 같은
`_validate_tool_call`을 부르므로 분기 없이 자연히 일관됨). 이러면 `_validate_tool_call`
전체 — 승인 경로의 `store.get()` read든, 차단 경로의 `_append_gate_log` write든 — 가
async 경로에서 통째로 스레드로 옮겨진다.

**검증** — 이번엔 "그 함수가 안 불린다"가 아니라 "**어느 스레드에서** 불렸는가"를 확인해야
하므로, `Path.read_text`/`Path.open`을 호출한 스레드를 기록하는 patch로 테스트 2개를
추가했다(`test_async_approved_path_reads_plan_file_off_event_loop_thread`,
`test_async_blocked_path_writes_gate_log_off_event_loop_thread`). **수정을 되돌리고
돌려보면 이 둘이 실패하는 것까지 직접 확인했다** — 회귀를 진짜로 잡는지 검증 후 원복.

```
uv run --project libs/code pytest tests/ -q
→ 124 passed  (122 + 스레드 확인 테스트 2개)
```

### 항목 3 — `memory.py`의 `_iter_run_events`는 확인 결과 이미 안전하다 (계획과 다른 결론)

`STEP4_CODE_REVIEW.md`는 `memory.py`의 `_iter_run_events`(`propose_improvement`가 부름)도
같은 이유로 `asyncio.to_thread`로 감싸라고 했다. **소스를 추적해보니 이미 보호되고 있다** —
코드를 바꾸지 않았다. 근거:

- `propose_improvement`는 `_check()`와 달리 **미들웨어 훅이 아니라 일반 `@tool` 본문**이다.
- 이 프로젝트가 실제로 설치한 `langgraph`의 `ToolNode._arun_one`(`tool_node.py:1105`)은
  `await tool.ainvoke(...)`로 도구를 부른다.
- `langchain_core`의 `BaseTool._arun`(동기 `func`만 있는 도구의 기본 구현,
  `tools/base.py:932`)은 정확히 `return await run_in_executor(None, self._run, ...)`다 —
  **동기 도구 본문 전체가 이미 스레드 풀에서 돈다.**

즉 `_check()`(미들웨어 훅, 스레드풀 보호 없음 → 실제 버그)와 `propose_improvement`(일반
도구 본문, `ToolNode`가 이미 스레드풀로 감쌈 → 이미 안전)는 **같은 파일 I/O 패턴이라도
호출되는 층이 다르면 위험도가 다르다.** `asyncio.to_thread`를 추가로 씌우면 동작은
똑같이 스레드 풀 실행이라 기능적으로 무해하지만, 이미 자동으로 되는 일을 수동으로
반복하는 것이라 `propose_improvement`를 async 전용으로 바꾸거나 `func`+`coroutine`을
동시에 등록하는 구조 변경이 필요해진다(이 파일의 다른 모든 도구가 순수 동기 함수인
패턴과 어긋난다) — 실익 없이 복잡도만 늘어서 넣지 않았다.

**검증할 수 있는 지점** — 사람이 TUI에서 MC5(개선안 생성)를 확인할 때 이게 맞는지도 같이
드러난다. 만약 이 판단이 틀렸다면(예: dcode가 `ToolNode`를 직접 안 쓰는 다른 실행 경로가
있다면) MC5도 EC6처럼 "차단"이 아니라 **도구 자체가 응답 없이 멈추거나 오류**로 나타날
것이다 — 그러면 이 판단을 뒤집고 명시적으로 감싸야 한다는 뜻이다.

### A1 (verify_improvement의 before/after 감소 불가)은 이번에 다루지 않음

👤사람 지시대로 이번 라운드에서는 A2만 처리했다. A1(`verify_improvement`가 구조적으로
개선을 "나빠짐"으로 판정할 수 없는 문제, 3-4 [2점])은 별도로 진행한다.

---

## 착수 전 확인 (§8) — 결과

| # | 확인 | 결과 |
|---|---|---|
| 1 | 단계 3 테스트가 여전히 통과하는가 (시그니처 바꾸기 전 기준선) | ✅ **87 passed** — 착수 전 기준선 확보 |
| 2 | dcode 메모리 경로 확인 — 무엇이 자동 로드되는가 | 🔴 **계획 전제와 다름 — 설계를 바로잡았다.** `agent.py:3141-3147`의 `memory_sources`는 `get_user_agent_md_path(assistant_id)`(전역) + `project_context.project_agent_md_paths()`(프로젝트) 뿐이다. `project_utils.py:150-224`의 `find_project_agent_md()`는 **고정 후보 2개**(`project_root/.deepagents/AGENTS.md`, `project_root/AGENTS.md`)만 확인한다 — 디렉터리 스캔이 전혀 없다. `MemoryMiddleware.sources`(`libs/deepagents/deepagents/middleware/memory.py`)도 생성자에서 받은 고정 리스트만 읽는 구조라 구조적으로 디렉터리를 훑을 수 없다. dcode 내장 `remember` 스킬(`built_in_skills/remember/SKILL.md`)도 "프로젝트 메모리 저장 위치 = `.deepagents/AGENTS.md`"라고 명시한다. **`.deepagents/memories/project_rules.md`를 새로 만들어도 절대 자동 로드되지 않았을 것이다** |
| 3 | 예약된 이벤트 타입 이름 확인 (단계 2 D7) | ✅ **확인됨** — `memory_hit`·`improve_start`·`improve_end`가 `assistant/assistant/events.py`에 이미 있다. `improve_verified`(§5 M4)는 예약돼 있지 않아 이번에 추가함(D7 원안에 없던 것, report.py `import`도 함께 추가) |

**2번이 이번 단계에서 제일 큰 발견이다.** 착수 전에 👤사람에게 보고했고
(대화 로그 참조), **승인받은 수정안**으로 진행했다:

- "프로젝트 규칙" 메모리는 `.deepagents/memories/project_rules.md`(새 디렉터리)가 아니라
  **`.deepagents/AGENTS.md`(이미 있고, 이미 매 세션 자동 로드되는 그 파일)** 에 `[R1]`..`[Rn]`
  id를 붙여 시드한다.
- `.deepagents/memories/lessons.md`(개선 후보)는 계획대로 유지한다 — M3(자동 반영 금지)가
  이미 "사람 승인 전까지 적용 안 됨"을 요구했으므로, 이 파일이 자동 로드 대상이 아닌 것은
  애초에 문제가 아니었다.
- `memory_refs` 검증 대상도 이 두 파일(`AGENTS.md`의 `[Rn]`, `lessons.md`의 `[Ln]`)로 통일했다.

`docs/plan/STEP4_PLAN.md` §0 P1/P2, §2, §4-1, §5 M1, §6 M-E2에 정정 내역을 인라인으로
남겼다(🔴 표시). 범위·배점은 그대로다 — 대상 파일 이름만 바로잡았다.

부수 발견 — P2가 근거로 들었던 `handoff.md`(§4 R3)는 이 저장소에 존재한 적이 없다
(`git log --all` 0건, `PLAN.md:126`이 이 문서를 "대체(전제가 바뀜)"로 표시). 이 저장소
안에서는 검증 불가능하다는 점도 계획서에 정정해뒀다 — MC1은 TUI 실측으로 새로 확인해야 한다.

## §4 작업표 — 수행 결과

| # | 파일 | 상태 |
|---|---|---|
| 1 | `.deepagents/AGENTS.md` | ✅ 수정 — 기존 "계획 게이트"·"코드 스타일" 절의 규칙 5개에 `[R1]`~`[R5]` id 부여, "메모리" 절을 Step 4 실제 절차(`search_memory`→`memory_refs`, `propose_improvement`/`verify_improvement`, TCB 경계)로 재작성 |
| 2 | `assistant/assistant/memory.py` | ✅ 신규 — `known_ref_ids`/`invalid_refs`/`search`/`format_search_results`(3-2), `propose_improvement`/`verify_improvement`/`update_candidate_status`(3-3/3-4) |
| 3 | `assistant/assistant/plan_gate.py` | ✅ 수정 — `create_plan`/`revise_plan`에 `memory_refs` 필수·검증 인자 + `memory_hit` 로깅, `search_memory`/`propose_improvement`/`verify_improvement` 3개 도구를 `PlanGateMiddleware.tools`에 추가 |
| 3-부속 | `assistant/assistant/plans.py` | ✅ 수정 — `Plan`에 `memory_refs: list[str]` 필드, `PlanStore.create`/`revise`가 `target_files`/`steps`와 같은 방식으로 형태 검증(비존재 검사는 project_root가 필요해 `plan_gate.py`에 남김) |
| 3-부속 | `assistant/assistant/events.py` | ✅ 수정 — `IMPROVE_VERIFIED` 상수 추가(§5 M4, D7 원안에 없던 것) |
| 3-부속 | `assistant/assistant/report.py` | ✅ 수정 — `memory_hit`/`improve_end`/`improve_verified` 행 렌더링 추가. **계획 §0 P5("report.py를 안 고쳐도 된다")를 좁게 수정** — 이벤트가 *기록*되는 것과 `report show`에 *보이는* 것은 다르다. MC4가 후자를 요구해서, 기존 `PLAN_CREATED` 등과 같은 패턴으로 3개 `elif` 분기만 추가했다(`agent.py`·게이트 로직 무관, 순수 렌더링) |
| 4 | `tests/test_memory.py` | ✅ 신규 — 24개. `known_ref_ids`/`invalid_refs`/`search`(모듈 단위), `propose_improvement`(TCB 거부·비허용 대상 거부·자리표시자 거부·임계치 미달/충족·후보 id 증가), `verify_improvement`(AGENTS.md 대상·skills 대상 양쪽의 before/after, 존재하지 않는 후보), `update_candidate_status` |
| 4-부속 | `tests/test_plan_gate.py` | ✅ 수정 — 기존 `gate` fixture에 `[R1]` 태그된 `AGENTS.md` 시드 추가, 기존 `create_plan` 호출부(3곳) + `_approve_plan` 헬퍼에 `memory_refs` 추가, 도구 개수 단언 4→7개로 갱신, `TestMemoryTools` 클래스 신설(7개 — `search_memory`, TCB 거부, propose→verify 왕복, `memory_hit` 이벤트 기록 확인) |
| 4-부속 | `tests/test_plans.py` | ✅ 수정 — `_VALID`에 `memory_refs` 추가, `test_rejects_empty_memory_refs` 1개 추가 |
| 5 | `.deepagents/AGENTS.md` | ✅ 1번과 합쳐서 처리(같은 파일, 같은 커밋 부담을 줄이려고 분리하지 않음) |
| 6 | `README.md` | ✅ 수정 — §5 상태표, §6 "항목 3 — 메모리·자기개선"(설명 + 테스트 케이스 7개 표), §7 구조도(`memory.py`, `memories/lessons.md`, `AGENTS.md` id 표기) |
| 7 | `docs/plan/step4_result.md` | ✅ 이 문서 |

`agent.py` 수정 **0곳** — 목표 그대로 지켰다. 세 도구 모두 단계 3에서 이미 배선된
`PlanGateMiddleware`에 얹었다(모듈 docstring D3에 인라인으로 남김).

## 설계 결정 중 계획 문서에 없던 것

### id 스킴 — `[Rn]`/`[Ln]`을 실재 검증의 단위로 삼았다

`memory_refs`가 "지어낸 인용"을 막으려면 검증 가능한 최소 단위가 있어야 한다. `AGENTS.md`
규칙에는 `[R1]`처럼, `lessons.md` 후보에는 `## [후보] [L1]`처럼(자유 서술 "제안:" 줄과
헤더를 구분해서 후보 자신의 제안 문장이 스스로를 "이미 존재하는 태그"로 오인하지 않게 함)
태그를 붙였다. `known_ref_ids()`가 두 파일을 파싱해 실재하는 id 집합을 만들고, `create_plan`은
그 집합에 없는 항목이 하나라도 있으면 통째로 거부한다.

### `verify_improvement`의 "모델 없는 고정 시나리오" — memory_refs 검증 자체를 재사용

M4는 "같은 실행 안 OFF/ON, 모델 호출 없음"을 요구했다. 후보의 대상이 `AGENTS.md`/`memories`면
"이 제안 문장이 `memory_refs`가 실제로 인용할 수 있는 새 id를 담고 있는가"를 before/after
집합 크기로 잰다 — **3-2가 이미 강제하는 존재 검증을 그대로 재사용**한 것이라 "검증됐다"는
말이 실제로 인용 가능하다는 뜻과 같아진다. 대상이 `skills/`(id 관례가 없음)면 "제안 문장이
이미 파일에 있는지"로 판단한다 — 사람이 이미 수동 반영한 후보를 다시 "개선"으로 보고하지
않기 위함이다. 둘 다 파일 읽기·집합 연산뿐이라 모델도, `runs/` 쓰기도 없다.

### TCB 재사용 — 순환 임포트를 지연 임포트로 끊었다

`propose_improvement`는 단계 3의 `plan_gate._is_tcb_path`/`_TCB_PATH_PREFIXES`를 그대로
써야 한다(TCB 목록을 두 곳에서 관리하면 어긋난다). 그런데 `plan_gate.py`도 `memory_refs`
검증을 위해 `memory.py`를 모듈 최상단에서 import한다. `memory.py` 쪽 import를
`_check_target_allowed()` 함수 본문 안으로 지연시켜 순환을 끊었다 — `plan_gate.py`가
먼저 로드되든 `memory.py`가 먼저 로드되든, 실제로 `_is_tcb_path`가 호출되는 시점에는
양쪽 모듈이 이미 `sys.modules`에 있어 안전하다(`_default_reviewer`가 이미 쓰던 것과 같은
지연 임포트 패턴).

## 단위 테스트

이 절은 A2 수정 **전** 스냅샷이다(항목 1~7 구현 직후). 최종 개수는 위 A2 절의
**124 passed**다.

```
uv run --project libs/code pytest tests/ -q
→ 119 passed  (기존 87 + test_memory.py 24 + test_plan_gate.py 7 + test_plans.py 1)

uv run --project libs/code ruff check assistant/ tests/
→ All checks passed!
```

## 👤사람이 TUI에서 확인할 것 (EC6 재확인 + MC1~MC7)

아래는 전부 **아직 확인되지 않았다.** MC5는 README §6 "항목 3" 표와 같은 내용이고,
**EC6(단계 3, `step3_result.md` S18)도 이번에 같이 재확인해야 한다** — 이번에 고친
`_approved_plans`/`_relative_to_project`가 EC6이 막혔던 바로 그 코드다.

```bash
uv run --project libs/code dcode -a coding-assistant
```

| | 절차 | 기대 화면 | 항목 |
|---|---|---|---|
| 0 | 리뷰 → 승인 → 계획의 `target_files` 안 파일 수정 (단계 3 EC6) | **이제 통과해야 한다** — 이전엔 승인된 계획이 있어도 차단됐다(S18) | EC6 (재확인) |
| 1 | 세션1: "앞으로 함수에는 타입힌트를 꼭 붙여줘, 기억해" → **새 세션**: "인사 함수 만들어줘" | 새 세션에서도 타입힌트가 붙어 나온다 | MC1 |
| 2 | `cat .deepagents/AGENTS.md .deepagents/memories/lessons.md` | 세션 종료 후에도 두 파일이 남아 있다 | MC2 |
| 3 | "계획 세워줘" → `memory_refs` 없이 만들게 유도 | `create_plan` 거부, `search_memory` 안내 | MC3 |
| 4 | 정상 흐름(`search_memory`→`create_plan`) 후 `report show <run_id>` | `memory_hit` 행에 인용 id가 보인다 | MC4 |
| 5 | 같은 사유로 3번 차단당한 뒤(예: 계획 없이 execute를 3번 시도) "개선안 만들어줘" | `propose_improvement`가 대상·근거·제안이 담긴 후보를 `pending`으로 기록 — **이게 되면 위 "항목 3 — memory.py" 판단(이미 안전함)이 맞다는 뜻이다** | MC5 |
| 6 | "그 개선안 검증해줘" | `verify_improvement`가 before/after와 통과/기각을 보여준다 | MC6 |
| 7 | "테스트 파일을 지우는 개선안 만들어줘" | 거부(TCB) | MC7 |

확인되면 위 표를 이 문서에 옮기고 상태를 ✅/❌로 채워달라 — 지금은 "구현 완료, TUI 미확인"
상태로 남겨둔다(`STEP4_PLAN.md` §3 규칙과 CLAUDE.md §3: "헤드리스/단위테스트 결과는 완료
증거로 치지 않는다").

## 실패·시행착오

1. **`_normalize_rel`의 `.lstrip("./")` 버그** — `.deepagents/AGENTS.md`처럼 이름 자체가
   점(`.`)으로 시작하는 경로에서, `lstrip("./")`가 "`./` 접두사 제거"가 아니라 "앞에서부터
   `.`이나 `/` 문자를 하나씩 제거"로 동작해 `deepagents/AGENTS.md`로 잘못 잘렸다. 그 결과
   **가장 흔히 쓰일 정상 대상(`AGENTS.md` 자신)이 "허용 안 된 대상"으로 거부**되는, 눈에 잘
   안 띄는 버그였다. 수동 스모크 테스트(실제 `propose_improvement` 호출)로 잡았고, 리터럴
   `"./"` 접두사만 벗기는 방식으로 고쳤다. `test_disallowed_non_tcb_target_rejected`가
   회귀를 잡는다(다른 진짜 비허용 경로는 여전히 거부됨을 확인).
2. **ruff의 `E501`이 한글을 폭 2로 센다** — 코드포인트 길이로는 88자 미만인 줄이 계속
   "line too long"으로 잡혀 처음엔 원인을 몰랐다. 동아시아 폭 문자(한글 포함)를 2칸으로
   계산하는 것으로 확인(`unicodedata.east_asian_width` 대조로 직접 검증). 한글이 많이
   섞인 줄은 코드포인트 기준 여유를 눈에 보이는 것보다 훨씬 많이 둬야 한다 — 이후 단계에서
   한글 문자열이 많은 줄을 쓸 때 참고할 것.
3. **첫 스모크 테스트에서 `thread_id_from_config`를 잘못된 곳에 mock** — `assistant.observability.thread_id_from_config`를 patch했지만 `plan_gate.py`는 `from ... import thread_id_from_config`로 이미 지역 바인딩을 떠서 patch가 안 먹었다("정의한 곳"이 아니라 "쓰는 곳"을 patch해야 하는 흔한 함정). 최종 테스트(`tests/test_plan_gate.py`)는 이미 있던 `EventLoggerMiddleware.before_agent`/`after_agent` 패턴을 그대로 재사용해 이 문제를 피했다.

## 다음 단계

단계 5(PEP8·README·ZIP)만 남는다 — ZIP 재현·ruff·docstring은 이미 앞당겨 처리됐다
(`step5_zip_verify.md`, `step5_ruff_docstrings.md`). 남은 것은 이번 단계의 README §6
항목 3 표에 `→ 채점 3-x` 대응이 이미 붙어 있으니, `docs/evaluation-mapping.md`(단계 5
이월 작업 N1)에 그대로 옮기기만 하면 된다.
