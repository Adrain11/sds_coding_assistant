# 단계 4 리뷰 — 추가 전달 (2026-09-18, 🔵검토 → 🟣설계)

작성: 🔵검토 (Claude Opus 5, VDI)
원 리뷰: [STEP4_REVIEW.md](STEP4_REVIEW.md) (R1~R5)

> **왜 추가 문서인가** — 원 리뷰를 쓴 뒤 두 가지가 바뀌었다.
> ① 🟢구현이 **단계 4 구현에 이미 착수**했다. ② EC6에서 **게이트 버그**가 나왔다.
> R3의 전제가 무효가 됐고, R1·R2는 시점이 급해졌다. 그 차이만 정리한다.
> INBOX가 아니라 별도 파일로 쓴 이유는 09-17에 INBOX가 두 번 덮여서다.

---

## 1. 🔴 지금 당장 — R1은 구현이 진행되는 중에도 확인해야 한다

**질문 하나로 판별된다: 🟢구현이 3-1의 증거를 어디에 두고 있나?**

| 지금 하고 있는 것 | 판정 |
|---|---|
| 규칙을 `.deepagents/memories/project_rules.md`에만 시드하고, 그것으로 MC1(새 세션 적용)을 증명하려 한다 | 🔴 **멈춰야 한다.** MC1이 실패한다 |
| 규칙을 `.deepagents/AGENTS.md`에 두고, `memories/`는 검색·인용용으로 쓴다 | ✅ 그대로 진행 |

근거 (`agent.py:3134-3141`) — dcode `MemoryMiddleware`의 소스는 **AGENTS.md 경로들뿐**이다:

```python
memory_sources = [str(get_user_agent_md_path(assistant_id))]
project_agent_md_paths = (
    project_context.project_agent_md_paths()
    if project_context is not None
    else get_project_agent_md_path(runtime_credentials.project_root)
)
memory_sources.extend(str(p) for p in project_agent_md_paths)
```

`.deepagents/memories/*.md`는 어디서도 들어가지 않는다. 자동 로드가 안 되므로
**새 세션의 시스템 프롬프트에 그 규칙이 없다.**

`memories/`를 로드시키려면 `memory_sources`에 추가해야 하고, 그건 `agent.py` 수정이다 —
`STEP4_PLAN.md` §2가 "**`agent.py` 수정 0곳이 목표**"로 못 박은 것과 정면으로 부딪히고,
같은 §2의 "범위가 바뀌는 조건"에 따라 **멈추고 승인을 받아야 하는 사안**이 된다.

### 반영할 것 — 두 층으로 나눈다

| 저장소 | 성격 | 채점 |
|---|---|---|
| `.deepagents/AGENTS.md` | **규칙의 정본.** dcode가 자동 로드하고, `memory_auto_save=True`(기본값, `agent.py:2587`)라 에이전트가 스스로 추가도 한다 | **3-1** |
| `.deepagents/memories/*.md` | **작업 경험 축적.** `search_memory`가 읽고 `memory_refs`가 인용하는 대상 | **3-2** · 3-3 |

- **MC1** (새 세션에서 적용) → 증거는 **`AGENTS.md`**
- **MC2** (파일 잔존) → `memories/*.md` **와** `AGENTS.md` 둘 다
- §4-1의 시드도 양쪽에 — `AGENTS.md`에 규칙 3~5줄, `memories/project_rules.md`에 같은 내용 + 인용 id

> 이 분리가 채점에도 유리하다. 3-1(저장·유지)과 3-2(검색·활용)는 **서로 다른 세부항목**인데,
> 저장소 하나로 둘을 설명하면 어느 쪽도 선명하지 않다. 층을 나누면
> "이 파일이 3-1, 저 파일이 3-2"로 바로 보인다.

---

## 2. 🔴 3-4 착수 전 — R2

3-4는 축소판의 마지막 항목이라 **아직 구현 전일 가능성이 높다.** 그렇다면 지금이 정확히 적기다.

`STEP4_PLAN.md` M4의 고정 시나리오는 **아무것도 측정하지 못한다.**
개선 대상 셋(`memories/lessons.md` · `skills/plan-first/SKILL.md` · `AGENTS.md`)은
전부 **모델 행동**에만 영향을 주는데, M4가 쓰겠다는 `plan_gate` 판정 함수는
메모리도 스킬도 AGENTS.md도 읽지 않는다. before와 after가 **항상 같은 값**이 된다.

→ MC6의 숫자가 무의미하고, V6("나빠지면 반영 안 함")은 **절대 발동하지 않는다.**

### 공식 문구를 다시 보면 요구가 둘이다

> 3-4. 개선 **전후의 효과**와 **기존 기능의 정상 동작**을 검증하고, 통과한 개선안을 다음 작업에 반영

| | 무엇 | 결정적인가 | 모델 필요 |
|---|---|---|---|
| (i) 전후의 효과 | 모델 행동이 실제로 바뀌었나 | ❌ | ✅ |
| (ii) **기존 기능의 정상 동작** | 개선안을 넣고도 안 깨졌나 | ✅ | ❌ |

**(ii)를 M4의 본체로 삼아라.** `verify_improvement(id)`가 한 호출 안에서:

1. 개선안 **미적용** 상태로 회귀 스위트 → `before`
   - `pytest tests/ -q`의 통과/실패 수
   - 게이트 판정 고정 케이스 N개 (승인 없이 `write_file` → 차단 / 승인 후 범위 안 → 통과 …)
2. 개선안을 **임시 적용**하고 같은 것 → `after`
3. `improve_end`에 before/after를 함께 기록
4. **하나라도 나빠지면 반영하지 않는다** (fail-closed)

이러면 숫자가 실제로 움직인다. 개선안이 `AGENTS.md`를 깨뜨리면 게이트 판정이 바로 떨어진다.
**그게 "기존 기능의 정상 동작" 검증이다.**

(i)은 모델이 필요하므로 **선택으로 내린다.** 하려면 1회 비교하고 **비결정적임을 명시**한다 —
채점자 키를 쓰는 증거는 증거로 못 쓴다는 원칙(단계 2 §2)이 여기도 적용된다.

→ **MC6 문구 정정:** "before/after를 비교한 결과를 보여준다" →
"**회귀 스위트의 before/after 수치가 `improve_end`에 남고, 나빠지면 반영되지 않는다**"

---

## 3. R3는 전제가 무효가 됐다 — 이제 비용 최소화 문제다

원 리뷰의 R3는 *"EC1~EC9를 단계 4 착수 **전에** 닫아라"*였다.
그런데 EC6에서 게이트 버그가 나왔고, 그 수정을 기다리는 동안 단계 4가 시작됐다.
**순서를 되돌릴 수는 없다.** 그래서 목표를 바꾼다 — **사람의 TUI 확인을 한 번으로 끝낸다.**

| 지켜야 할 것 | 어떻게 |
|---|---|
| README 케이스를 **두 번 고치지 않는다** | `create_plan`에 `memory_refs`를 추가하는 **같은 커밋에서** `README.md` §6 항목 2 케이스 6의 필수 항목 목록에 `memory_refs`를 더한다. 나중에 따로 하면 잊는다 |
| 사람이 **두 번 확인하지 않는다** | EC1~EC9(단계 3)와 M-E1~M-E7(단계 4)를 **한 번에** 확인한다. 게이트 버그 수정 + 단계 4 구현이 모두 끝난 뒤에 몰아서 |
| EC6가 다시 막히지 않는다 | `memories/`에 시드가 **먼저** 들어가 있어야 한다 (§4-1이 1번인 이유). 안 그러면 `memory_refs`에 인용할 것이 없어 EC6·EC8이 계획 생성 단계에서 막힌다 |

→ **§8 착수 전 확인에 넣어라:** *"`memories/`에 인용 가능한 항목이 최소 1개 있는가.
없으면 `memory_refs` 필수화를 켜지 않는다."*

---

## 4. 🟡 R4 · R5 — 문구

- **R4** `improve_verified`는 예약된 이벤트 타입이 아니다. `events.py:76-78`의 예약은
  `memory_hit` · `improve_start` · `improve_end` 셋이다.
  → **`improve_end`에 담아라.** `status="verified"`/`"rejected"`와 before/after를 `data`에 넣으면
  새 상수도 `report.py` 수정도 필요 없다. P5("`report.py`를 안 고쳐도 된다")가 그대로 유지된다
- **R5** P2의 근거 `handoff.md`가 저장소에 없다 (`PLAN.md` 단계 1에서 "대체"로 버린 문서).
  추적 불가한 인용이므로 **M-E1을 실제로 수행하고** 결과를 `step4_result.md`에 남긴다.
  P2는 "과거에 비슷한 것을 봤다"는 참고로만 남긴다

---

## 5. EC6 게이트 버그 — 🟣설계 진단에 덧붙일 셋

🟣설계의 2번(**디렉터리 순회 제거**)이 본체이고 맞다.
`_approved_plans()`(`plan_gate.py:413-424`)가 매 도구 호출마다 `list_ids()`
(`plans.py:244`의 `glob("*.json")`)로 순회하고 그다음 파일을 하나씩 읽는다.
단계 2의 **S13**(Blockbuster가 이벤트 루프의 동기 I/O를 막는다)과 같은 뿌리이고,
**다른 파일에서 재발한 것**이다.

아래 셋을 함께 처리해야 끝난다.

**① 순회를 없애도 파일 read 1회는 남는다.**
`plan_id`로 직접 열어도 `read_text()`는 여전히 blocking I/O고 Blockbuster가 잡는다.
→ **2번(순회 제거) + 1번(`to_thread`)을 같이** 한다. 순회를 없애 스레드 안 I/O를 최소화하고,
남은 read를 감싼다.

**② `Path.resolve()`가 별개 syscall이다 — 순회를 없애도 남는다.**
`_relative_to_project`(`plan_gate.py:97-104`)가 경로마다 `.resolve()`를 부른다.
docstring에 "never used for filesystem access"라고 적혀 있으니 실제 resolve가 필요 없다.
→ **`os.path.normpath`(문자열 연산)로 교체.** 감싸는 것보다 없애는 게 싸다.

**③ sync 경로도 확인해야 한다.**
1번이 "async 경로에서만 `to_thread`"라면 `wrap_tool_call`(sync)은 그대로 터진다.
서버는 주로 async지만, **fail-closed 게이트가 경로에 따라 다르게 동작하면 EC 재현이
불안정해진다** — 채점자 환경에서 한 번은 통과하고 한 번은 막히는 것이 최악이다.
sync 경로는 ②로 syscall을 없애면 대부분 해결되고, 남는 read는 동기 호출 그대로 둬도 된다
(sync 경로는 이벤트 루프가 아니다).

### 이 버그는 기록해야 한다

`step3_result.md`에 **"EC6에서 Blockbuster 차단 발견"**을 남길 것.
단계 2 S13과 같은 뿌리인데 다른 파일에서 재발했다는 점이 핵심이다.

**그리고 이것은 단계 4의 3-3이 다룰 만한 패턴이다** —
*"새 미들웨어를 쓸 때 판정 경로에서 동기 I/O를 하지 말 것"*.
실제로 두 번 발생한 실패이므로 M2의 임계치(3회)에는 아직 못 미치지만,
`propose_improvement`가 만들 개선안의 **실물 예시**로 쓰기에 적합하다.
채점 3-3은 "실행 실패·평가 결과를 바탕으로" 개선안을 생성하는 것이고,
이건 꾸며낸 사례가 아니라 실제로 두 번 밟은 지뢰다.

---

## 정리 — 🟣설계가 정할 것

| | 무엇 | 시점 |
|---|---|---|
| 🔴 **1** | R1 — 3-1의 증거를 `AGENTS.md`로. `memories/`는 3-2용 | **지금** (구현이 진행 중) |
| 🔴 **2** | R2 — M4를 회귀 검사로. MC6 문구 정정 | **3-4 착수 전** |
| 🔴 **3** | R3 재해석 — README를 같은 커밋에서 갱신, TUI 확인을 1회로 몰기 | 지금 정해두기 |
| 🟡 **4** | R4 — `improve_end`에 담기 | 3-4 구현 시 |
| 🟡 **5** | R5 — `handoff.md` 인용 제거, M-E1 실제 수행 | 문구 |
| 🟡 **6** | EC6 버그 — ①②③ 함께, `step3_result.md`에 기록 | 🟢구현에게 |

**1번이 가장 급하다.** 구현이 `memories/`만으로 3-1을 증명하려 하고 있으면 지금 멈춰야 하고,
그렇지 않으면 그대로 가면 된다. 확인 한 번으로 판별된다.
