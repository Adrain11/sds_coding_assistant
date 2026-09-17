# 단계 3 계획 리뷰 (2026-09-17, 🔵검토)

작성: 🔵검토 (Claude Opus 5, VDI)

검증 대상: `libs/code/deepagents_code/agent.py`, `approval_mode.py`, `tools.py`,
`managed_tools.py`, `libs/deepagents/deepagents/graph.py` — 전부 `main` 원본을 직접 읽음.

**S14~S17은 줄번호까지 전부 실측과 일치한다.** 설계 근거는 탄탄하다.
문제는 하나로 모인다 — **차단 대상 도구 목록이 불완전하다.** step0에서 뚫린 것과 같은 종류의 구멍이다.

---

## 반드시 고쳐야 할 것

### 🔴 R1. `delete`가 차단 목록에서 빠졌다 — D7(TCB)까지 같이 무너진다

**무엇이** — D1은 `write_file` · `edit_file` · `execute` 셋만 차단한다.
그런데 dcode 자신은 **`delete`를 쓰기 도구로 분류한다.** 두 곳에서 독립적으로:

```python
# agent.py:1001-1003 — PTC 감사용 "쓰기/셸 가능" 집합
_INTERPRETER_WRITE_TOOLS: frozenset[str] = frozenset(
    {"execute", "write_file", "edit_file", "delete"}
)
```

```python
# agent.py:2380-2390 — HITL 승인 대상(gated) 기본 목록
interrupt_map: dict[str, InterruptOnConfig] = {
    "execute": ..., "write_file": ..., "edit_file": ..., "delete": ...,
    "web_search": ..., "fetch_url": ..., "task": ...,
    "start_async_task": ..., "update_async_task": ..., "cancel_async_task": ...,
}
```

바로 위 주석이 이렇게 쓰여 있다:

> `# [해설][흐름] 2) 기본 gated 도구: 셸, 파일 쓰기/수정/삭제, 웹 검색, URL fetch, 서브에이전트 위임, …`
> `# [해설] read_file/ls/glob/grep 같은 읽기 도구는 승인 대상이 아니다.`

**왜** — 두 가지가 동시에 깨진다.

1. **EC1·2-4** — 승인된 계획 없이 `delete`로 파일을 지울 수 있다.
   "승인된 계획 없이는 코드가 바뀌지 않는다"(§1 요구사항)가 성립하지 않는다.
   파일을 지우는 것도 코드 변경이다.
2. **D7(TCB)이 통째로 무의미해진다.** D7의 목적은 *"단계 4의 자기개선이
   평가기·테스트·게이트를 고쳐서 통과율을 올리는 것"*을 막는 것이다.
   그런데 `delete`가 열려 있으면 **고칠 필요 없이 지우면 된다.**
   `tests/`를 지우면 통과율이 100%가 된다. 6일차 TCB의 정확한 실패 사례다.

**어떻게** — 차단 목록에 `delete` 추가. D1 표와 작업표 3번에 반영.
승인 후에도 `target_files` 검사를 `delete`에 **동일하게** 걸고,
D7의 TCB 목록은 `delete` 경로에서도 검사한다(U7을 `delete`로도 한 번 더).

> 여유가 있으면 `interrupt_map`의 나머지도 보라 — `web_search`·`fetch_url`은 코드를 바꾸지
> 않으니 차단 대상이 아니다. dcode가 승인 대상으로 둔 이유는 외부 통신이기 때문이고,
> 우리 게이트의 관심사가 아니다. **`delete`와 `task`만 추가하면 된다.**

### 🔴 R2. `task`(서브에이전트)는 리스크가 아니라 **차단 대상**이다 — step0 패턴의 재발

**무엇이** — §7 리스크 표는 이렇게 둔다:

> ⚠️ **서브에이전트에는 게이트가 없다** … 서브에이전트에 쓰기 도구가 가는지 확인.
> 가면 `_subagent_cli_middleware`(`agent.py:2885`)에도 배선 — **범위 변경**

**왜** — "확인"할 필요가 없다. 단계 2에서 **이미 확인됐다.**
`graph.py:822`의 `_gp_inheritable = [m for m in middleware if m.name in _gp_original_name_to_index]`
때문에 새 이름의 미들웨어는 서브에이전트 스택에 상속되지 않는다.
`STEP2_PLAN.md` §7에 그 근거가 이미 적혀 있다. 그리고 dcode 자신이 `task`를
gated 도구로 분류한다(R1의 `interrupt_map`) — 서브에이전트가 쓰기 능력을 가진다는 뜻이다.

그래서 이 문장이 그대로 재현된다:

> step0: *"execute 툴로 직접 만들어줘"* → 뚫림
> 단계 3 이후: *"서브에이전트한테 시켜서 만들어줘"* → ?

**어떻게** — 서브에이전트 스택에 배선하는 것(범위 변경, 30분+)보다 **훨씬 싼 길이 있다.**
**승인 전에는 `task`도 차단한다.** 차단 목록에 한 줄 추가로 끝나고 범위 변경이 아니다.

승인 후 처리는 `allow_shell`과 같은 모양으로 둔다 — 계획에 `allow_subagent: true`가
명시된 경우에만 통과. 서브에이전트 안에서는 `target_files` 강제가 불가능하므로,
사람이 승인하며 그 사실을 보고 넘긴 것이어야 한다.

→ **EC 항목을 하나 추가하라.** `EC2-b`: *승인된 계획 없이 "서브에이전트로 파일을 만들어라"를
시키면 차단된다.* E2와 나란히 두면 2-4의 증거가 두 겹이 된다.

---

## 고려해볼 것

### 🟡 R3. PTC(`js_eval`)는 소스가 "HITL 승인을 우회한다"고 명시한다 — 확인 필요

`agent.py:1012`:

> `# [해설][주의] PTC 호출은 HITL 승인을 우회하므로 이 allowlist가 사실상 유일한 통제 수단이다.`

`js_eval` 안에서 `tools.write_file(...)` 형태로 호스트 도구를 부르는 경로다(`agent.py:1000` 주석).
HITL을 우회한다면 **우리 `wrap_tool_call`도 우회하는지** 확인해야 한다. 우회한다면
step0의 셸 우회와 구조가 같은 새 구멍이다.

**다만 기본값에서는 닫혀 있을 가능성이 높다.** 두 겹이다:

1. `interpreter_ptc="safe"`가 기본이면 읽기 전용 프리셋만 노출된다
   (`agent.py:1013` — `"safe"` → `INTERPRETER_PTC_SAFE_PRESET`(읽기 전용))
2. `CodeInterpreterMiddleware` 자체가 **샌드박스 provider**를 요구한다.
   README가 `--extra all-providers`만 깔게 하고 `all-sandboxes`는 안 깔므로
   채점자 환경에서는 애초에 안 켜질 것이다

**확인 방법** (구현 착수 30분에 넣어라):

```bash
uv run --project libs/code dcode config path      # interpreter 설정 위치
grep -n "CodeInterpreterMiddleware" libs/code/deepagents_code/agent.py
grep -rn "INTERPRETER_PTC_SAFE_PRESET" libs/
```

→ 꺼져 있으면 §7 리스크에 **"채점자가 `--extra all-sandboxes`를 깔면 PTC 경로가 열린다"**
한 줄만 남긴다. 켜질 수 있으면 `js_eval`도 차단 목록에 넣는다.
README 2절이 `all-providers`만 지시하고 있으니 그 문구를 바꾸지 않는 것도 통제의 일부다.

### 🟡 R4. D4의 "구조적으로 자기 승인이 불가능하다"가 `allow_shell: true`에서 깨진다

D4의 논리는 이렇다:

> 에이전트는 `execute`가 차단돼 있어 이 명령을 부를 수 없다. **구조적으로 자기 승인이 불가능하다.**
> 승인 전에는 셸이 막혀 있고, 셸을 풀려면 승인이 필요하다 — 순환이 닫혀 있다.

**순환이 완전히 닫히지 않는다.** D1이 `allow_shell: true`인 승인된 계획에서는 `execute`를
통과시키기 때문이다. 그 상태의 에이전트는 이걸 부를 수 있다:

```bash
python -m assistant.plan_gate approve <다른_plan_id>
```

즉 **계획 A를 사람이 승인(allow_shell)한 뒤에는, 에이전트가 계획 B를 자기 승인할 수 있다.**
2-4의 가장 강한 주장이 여기서 약해진다. 채점자가 파고들면 바로 보인다.

**대응 (싼 것부터)**

1. **`allow_shell: true` 승인에서도 `execute` 인자에 `plan_gate`·`assistant.plans`가 들어가면 차단.**
   D1이 부정한 "명령 문자열 파싱"이지만, 여기 범위는 *우리 자신의 모듈 이름 한 개*라
   `echo`/`cat >`류의 무한 변형 문제가 없다. 우회하려면 난독화를 해야 하고 그건 로그에 남는다
2. `approve`가 **사람만 만들 수 있는 토큰 파일**을 요구하게 한다 (예: 승인 시
   `.deepagents/plans/<id>.approve` 파일의 존재와 소유자 확인). 확실하지만 채점자 절차가 늘어난다
3. `allow_shell`을 아예 없애고 승인 후에도 셸은 항상 차단 — 가장 단순하고 안전하다.
   `execute`가 정말 필요한 시연이 없다면 이게 낫다

→ **3번을 먼저 검토하라.** EC1~EC9 어디에도 `execute`를 승인 후 쓰는 시나리오가 없다.
필요 없는 권한을 열어두고 구멍을 막는 것보다 안 여는 게 싸다.
`allow_shell`을 유지하기로 하면 최소한 1번을 넣고, D4의 "구조적으로 불가능"을
**"승인된 계획이 셸을 열지 않는 한 불가능"**으로 정확하게 고쳐라.

### 🟡 R5. §8 착수 전 확인 2번의 grep 대상 파일이 틀렸다 — 0건이 나온다

계획 §8:

```bash
# 2. 도구 이름 확인 — 무엇을 막을지
grep -n '"write_file"\|"edit_file"\|"execute"' libs/code/deepagents_code/tools.py \
  libs/code/deepagents_code/managed_tools.py | head -20
```

두 파일 다 존재하지만(HTTP 200) **이 이름들이 하나도 없다.** 직접 세어봤다 — 각각 0건.
이유가 소스에 적혀 있다(`agent.py:1025-1028`):

> The Deep Agents SDK injects the filesystem, `task`, and `execute` tools via middleware in
> `create_deep_agent` — *after* this point — so they are absent from `tools` here

도구는 SDK가 미들웨어로 주입하므로 dcode의 `tools.py`에 이름이 없다.
그대로 실행하면 구현이 "이름이 틀렸나?" 하고 30분을 쓴다.

**→ grep 대상을 바꿔라.** dcode 자신의 쓰기 도구 정본 목록은 두 곳이다:

```bash
# 쓰기/셸 도구 정본 목록 (R1의 근거)
sed -n '2378,2392p' libs/code/deepagents_code/agent.py   # interrupt_map
sed -n '1000,1005p' libs/code/deepagents_code/agent.py   # _INTERPRETER_WRITE_TOOLS
```

### 🟡 R6. EC3(YOLO)이 채점자 환경에서 실행 불가일 수 있다 — 대체 증거를 준비하라

`approval_mode.py:29-37`:

> YOLO still requires an **explicit acknowledgement to enter** (a modal in the TUI,
> a console prompt for `--yolo`), still honors the **`startup.yolo_switcher`** setting,
> and still shows a persistent `YOLO` status-bar indicator …

두 가지 걸림돌이 있다:

1. **모달 승인이 필요하다.** 채점자가 모달을 통과하는 절차를 README에 안 적으면 거기서 멈춘다
2. **`startup.yolo_switcher`로 YOLO 자체가 비활성일 수 있다.** 그러면 EC3을 실행할 방법이 없다

EC3은 2-4의 강한 증거라 못 보여주면 아깝다.

**→ 대체 증거를 병렬로 준비하라.** step0에서 이미 확인된 사실이 있다:

> step0 #6: ✅ **auto 모드인데도 훅이 이김** → 훅은 승인 시스템과 **독립 계층**

즉 **`auto` 모드에서 차단되는 것만 보여도 "승인 모드와 독립"이 증명된다.**
`auto`는 모달 없이 전환되고 step0 환경에서 이미 기본값이었다.

→ EC3을 `auto`(필수) + `yolo`(가능하면)로 나눠라. README 테스트 케이스도 같은 순서로.
YOLO는 되면 더 강한 장면이고, 안 되면 auto로 충분하다. **미검증 영역에 배점을 걸지 않는다** —
D4에서 설계가 이미 쓴 원칙 그대로다.

> 참고 — 계획 E3의 `/mode yolo`라는 **명령 형태는 확인하지 못했다.**
> `approval_mode.py`에는 `/mode` 문자열이 없다. TUI 커맨드는 다른 곳에 있을 것이다:
> `grep -rn '"mode"' libs/code/deepagents_code/tui/ libs/code/deepagents_code/client/commands/`
> 착수 전 확인 4번을 이걸로 바꿔라.

---

## 계획대로 두는 게 맞다고 본 것

- **D3 (계획 도구를 미들웨어가 제공)** — 이 단계 설계의 핵심이고 맞다.
  계획을 `write_file`로 쓰게 하면 게이트가 자기 입력을 막는 순환이 생기고,
  "계획 파일 경로만 예외"는 그 예외로 코드가 새 나간다. S14(`agent.py:3124-3126`,
  `ask_user_middleware.tools[0]`)로 실현 가능성도 확인됐다. **D3-b 대안을 미리 둔 것도 옳다** —
  `tools` 병합 유실은 실제로 가능한 실패 모드다
- **D4의 우선순위 (CLI 기본 · HITL 덤)** — 맞다. TUI HITL 렌더링은 미검증 영역이고
  거기에 10점을 걸면 안 된다. R4의 구멍만 막으면 설계 자체는 좋다.
  특히 **채점자가 명령 하나로 승인**할 수 있다는 부수 효과가 크다
- **D5 상태 기계** — `reviewed` 없이 `approved`로 못 가는 것이 2-3을 **문장이 아니라 전이**로
  만든다. 범위 밖 시도 시 `draft`로 강제 되돌림이 2-4의 "재검토"를 같은 방식으로 만든다.
  채점자가 "절차가 있는가"를 코드에서 확인할 수 있는 형태다
- **D6 fail-closed + `gate.log` 별도 기록** — 맞다. 단계 2 D4에서 약속한
  "차단 사건만은 별도 경로로도 기록"을 지켰다. 로거가 죽어도 차단 증거가 남는다
- **D2의 "스키마 + 내용 검사"** — 필수 인자만으로는 `"."` 한 글자가 통과한다는 것까지
  본 것이 좋다. 2-1·2-2가 "정의/작성"을 요구하므로 여기가 배점의 실체다
- **D8 유도 메시지에 승인 명령을 그대로 넣는 것** — step0에서 모델이 차단당하자
  **우회를 제안했다**는 관찰에 대한 정확한 대응이다. 채점자 발견성까지 같이 해결한다
- **§6 U1~U10이 `handler` 호출 횟수 0을 확인하는 것** — 8일차 43p 그대로다.
  "차단 메시지를 보여주면서 실행은 된" 경우를 잡는 유일한 방법이고, 통과 여부만 보는
  테스트와 결정적으로 다르다. **U9(로거가 죽어도 차단은 일어난다)와 U10(async 경로)까지 있다**
- **삽입 위치를 로거 바로 뒤로 잡은 판단** — 맞다. 게이트가 바깥이면 차단된 호출이
  로그에 안 남아 4-2와 2-4의 증거가 동시에 사라진다. S2와 일관적이다
- **S14~S17 전부 실측 일치** — `agent.py:3124-3126`(S14), `:3438`·`:3754`(S15),
  `:937-941`(S16), `:948-957`(S17). 인용 정확도가 단계 2 때와 같게 높다

---

## 정리

| | 내용 | 비용 |
|---|---|---|
| 🔴 **R1** | 차단 목록에 **`delete`** 추가. TCB 검사도 `delete` 경로에 | 한 줄 + 테스트 1개 |
| 🔴 **R2** | 차단 목록에 **`task`** 추가 (승인 후는 `allow_subagent` 플래그). `EC2-b` 추가 | 한 줄 + EC 1개 |
| 🟡 **R3** | PTC/`js_eval` 활성 여부 확인 → 꺼져 있으면 리스크 한 줄, 켜지면 차단 목록에 | 확인 10분 |
| 🟡 **R4** | `allow_shell`을 없애는 쪽을 먼저 검토. 유지하면 D4 문구 정정 + 자기 승인 차단 | 설계 판단 |
| 🟡 **R5** | §8 grep 대상을 `agent.py`의 `interrupt_map`으로 교체 | 문구 수정 |
| 🟡 **R6** | EC3을 `auto`(필수) + `yolo`(가능하면)로 분리 | EC·README 문구 |

**R1이 가장 중요하다.** `delete` 하나 때문에 2-4와 D7이 동시에 뚫리고,
단계 4의 자기개선이 테스트를 지울 수 있게 된다. 고치는 비용은 한 줄이다.
