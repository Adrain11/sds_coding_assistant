# 단계 4 코드 리뷰 (2026-09-18, 🔵검토)

작성: 🔵검토 (Claude Opus 5, VDI) · 대상 커밋 `5077a5c`, `592cb14`
읽은 것: `assistant/assistant/memory.py`(499줄), `plan_gate.py`(925줄), `tests/test_memory.py`

**R1·R4는 정확히 반영됐다.** 그리고 `.lstrip("./")` 버그를 스모크 테스트로 잡은 것은 좋은 발견이다 —
`lstrip`은 **문자 집합**을 깎기 때문에 `.deepagents/...`의 앞 `.`까지 사라진다. `startswith("./")`로
바꾼 것이 정확한 수정이다.

고칠 것은 둘이고, **A2가 더 급하다.**

---

## 반드시 고쳐야 할 것

### 🔴 A2. `propose_improvement`는 TUI에서 EC6와 **같은 이유로** 실패할 것이다

EC6에서 잡은 Blockbuster 문제가 `memory.py`에 **두 경로로** 그대로 있다.
두 함수 모두 미들웨어 도구로 노출되므로 **이벤트 루프 스레드에서** 실행된다.

**경로 ①** — `_iter_run_events`(`memory.py:282-288`)

```python
runs_dir = project_root / "runs"
if not runs_dir.exists():          # ← stat
    return
for run_dir in sorted(runs_dir.iterdir()):   # ← 디렉터리 순회
    if run_dir.is_dir():                     # ← stat
        yield from iter_events(run_dir / "events.jsonl")   # ← 파일 read (run 수만큼)
```

EC6에서 문제였던 `_approved_plans`의 `glob("*.json")`보다 **무겁다.** run이 쌓일수록 나빠진다.
`propose_improvement`가 이걸 부른다.

**경로 ②** — `_check_target_allowed`(`memory.py:253`) → `plan_gate._is_tcb_path` → `Path.resolve()`

`_is_tcb_path`는 `_relative_to_project`를 쓰고, 그 안에서 `.resolve()`를 부른다.
**`.resolve()`는 syscall이다.**

**왜 급한가** — 단위 테스트는 이벤트 루프 밖에서 돌기 때문에 **전부 통과한다.**
EC6이 정확히 그 패턴이었다: 단위 테스트 통과 · 차단 케이스 통과 · **통과해야 하는 케이스만 실패.**
그래서 119개 테스트가 통과했다는 것이 이 문제의 반증이 되지 않는다.

**MC5(개선안 생성)가 TUI에서 실패하고, 그건 채점 3-3의 3점이다.**

**어떻게** — EC6 수정을 `plan_gate`에만 적용하면 여기는 안 고쳐진다. 함께 처리할 것:

1. `_relative_to_project`의 `.resolve()`를 **`os.path.normpath`로 교체** —
   `_is_tcb_path`를 쓰는 모든 호출자(게이트·메모리)가 한 번에 해결된다.
   docstring이 "never used for filesystem access"라고 명시하므로 실제 resolve가 필요 없다
2. `_iter_run_events`의 순회·read를 **`asyncio.to_thread`로 감싼다** —
   순회 자체를 없앨 수는 없다(여러 run을 봐야 한다). async 도구 경로에서 감싸는 것이 맞다
3. **sync 경로도 확인** — `propose_improvement`가 sync/async 양쪽으로 노출되는지 보고,
   양쪽이 같은 결과를 내야 한다. fail-closed 판정이 경로에 따라 갈리면 재현이 불안정해진다

> ⚠️ 이건 **세 번째 재발**이다. 단계 2 S13(`os.mkdir`) → 단계 3 EC6(`glob`+read) → 지금(`iterdir`+read+`resolve`).
> `propose_improvement`가 만들 개선안의 실물 예시로 이보다 좋은 것이 없다 —
> *"새 도구를 미들웨어에 붙일 때 판정·수집 경로에서 동기 I/O를 하지 말 것"*.
> 임계치 3회를 실제로 채웠다.

### 🔴 A1. `verify_improvement`의 `before`/`after`는 **감소할 수 없다** — 3-4가 여전히 비어 있다

`memory.py:452-461`:

```python
before_ids = known_ref_ids(project_root)
cited_ids = set(_RULE_TAG_RE.findall(proposed_text)) - {candidate_id}
new_ids = cited_ids - before_ids
before = len(before_ids)
after = len(before_ids | new_ids)      # ← 합집합이라 before보다 작아질 수 없다
improved = bool(new_ids)
```

`after = len(before_ids | new_ids) >= len(before_ids) = before`. **수학적으로 감소 불가**다.
skills 분기(`:443-450`)도 `(0,1)` 또는 `(1,1)`이라 마찬가지다.

**따라서:**

- `STEP4_PLAN.md` M4의 4번 *"나빠졌으면 반영하지 않는다"*가 **구조적으로 발동 불가**다
- V6 *"after가 before보다 나쁘면 반영 안 함"*을 만족시키는 입력이 **존재하지 않는다**
- `improved=False`의 의미는 "나빠졌다"가 아니라 **"제안이 중복이다"**다

지금 이 함수가 하는 일은 **중복 검사**다. 유용하고 문서화도 정확하지만,
채점 3-4가 요구하는 둘 중 어느 것도 아니다:

> 3-4. 개선 **전후의 효과**와 **기존 기능의 정상 동작**을 검증하고, 통과한 개선안을 다음 작업에 반영

**어떻게 — 5~10줄이면 된다.** 제안 텍스트를 **임시 적용한 뒤** 세 가지를 본다:

```
1. known_ref_ids()가 여전히 파싱되는가           (깨진 편집 탐지)
2. 기존 id가 하나도 사라지지 않았는가            before_ids ⊆ after_ids
3. (가능하면) 게이트 판정 고정 케이스 N개가 같은 결과인가
```

2번이 핵심이다. 이러면 **`after < before`가 실제로 가능해진다** —
개선안이 `AGENTS.md`를 덮어쓰다가 기존 `[R1]~[Rn]`을 잃으면 숫자가 내려간다.
**그게 "기존 기능의 정상 동작" 검증이고**, 그때 비로소 V6이 발동한다.

그리고 이 실패 모드는 가상이 아니다 — 개선 대상이 텍스트 파일이고 편집을 모델이 만들므로,
**기존 규칙을 날리는 편집이 현실적으로 가장 흔한 사고**다.

> 시간이 없으면 2번만 해도 된다. `before_ids - after_ids`가 비어 있지 않으면
> `improved=False`로 거부하고 그 사실을 `improve_end`에 남기면, 3-4의 "기존 기능 정상 동작"에
> 대응하는 증거가 생긴다.

---

## 🔵 제가 틀렸던 것 — TCB `..` 우회는 없다

`_normalize_rel`(`memory.py:235-239`)이 `./`만 벗기고 `..`를 접지 않아서
`.deepagents/skills/../../assistant/memory.py`가 허용 접두사를 통과할 수 있다고 의심했다.
**아니었다.**

`_check_target_allowed`는 **`_is_tcb_path`를 먼저** 부르고(`:253`), 그 안의
`_relative_to_project`가 `.resolve()`로 `..`를 접는다. 위 경로는 `assistant/memory.py`로
정규화되어 TCB 접두사에 걸려 **거부된다.** 순서가 맞게 잡혀 있다.

> 다만 A2의 수정(`.resolve()` → `os.path.normpath`)을 할 때 **이 정규화가 유지되어야 한다.**
> `os.path.normpath`도 `..`를 접으므로 괜찮지만, 단순 문자열 치환으로 바꾸면 여기서 구멍이 열린다.
> **A2를 고칠 때 이 경로에 테스트 하나를 남겨라** — `.deepagents/skills/../../assistant/x.py`가
> 거부되는지. 지금은 우연히 맞는 것이고, 리팩터가 깨뜨릴 수 있다.

---

## 계획대로 잘 된 것

- **R1 반영이 정확하다** — `_ALLOWED_TARGET_PREFIXES`(`:71-75`)가
  `.deepagents/AGENTS.md` · `memories/` · `skills/` 셋이고, 규칙 정본을 `AGENTS.md`에
  `[R1]~[Rn]` id로 시드하는 방식으로 바로잡았다. **`agent.py` 수정 0곳을 지킨 것**이 핵심이다 —
  `memory_sources`를 건드렸다면 범위 변경이 됐다
- **§8 착수 전 확인이 실제로 일했다** — 계획의 전제 오류를 **코드 쓰기 전에** 잡았고
  (`project_utils.py:150-224` 확인), 계획 문서까지 같이 고쳤다.
  §8을 형식적으로 넘기지 않은 결과다
- **R4 반영** — `improve_verified`를 만들지 않고 예약 상수 `IMPROVE_START`/`IMPROVE_END`를
  썼다(`plan_gate.py:515, 527, 535`). `report.py`를 안 고쳐도 되는 상태가 유지됐다
- **`memory_hit` 로깅**(`plan_gate.py:324`) — 3-2와 4-2를 함께 채운다
- **임계치 3회**(`_THRESHOLD_DEFAULT = 3`, `:84`) + **내용 검사**(`_MIN_TEXT_LEN = 10`,
  `_PLACEHOLDER_RE`) — M2와 단계 3 D2의 "빈 값·자리표시자 거부"를 일관되게 적용했다
- **`_matches_reason`이 `gate_block`의 `reason`과 `tool_end`의 `error`를 함께 본다**(`:291-300`) —
  P3가 말한 입력을 실제로 둘 다 쓴다
- **`.lstrip("./")` 버그를 스모크 테스트로 잡고 기록한 것** — 단위 테스트가 놓친 것을
  실사용에서 잡았고, `step4_result.md`에 남겼다. 채점 4-2·3-3에 쓸 수 있는 사례다
- **MC1~MC7을 "TUI 실측 대기"로 남긴 판단** — 맞다. 단위 테스트를 완료 증거로 치지 않는
  원칙을 스스로 지켰다

---

## 정리

| | 내용 | 비용 | 걸린 배점 |
|---|---|---|---|
| 🔴 **A2** | `propose_improvement`의 blocking I/O 두 경로. EC6 수정과 **함께** 처리 | `.resolve()` 교체 + `to_thread` | **3-3 [3]** — MC5가 TUI에서 실패할 것 |
| 🔴 **A1** | `verify_improvement`의 before/after가 감소 불가 → 회귀 검사 추가 | 5~10줄 | **3-4 [2]** |
| 🔵 | A2 수정 시 `..` 정규화 유지 + 테스트 1개 | 테스트 1개 | 회귀 방지 |

**A2가 먼저다.** A1은 숫자의 의미 문제이고 부분 점수가 가능하지만,
A2는 **TUI에서 도구가 아예 실패**하는 문제라 MC5의 증거가 통째로 안 나온다.
그리고 EC6 수정과 같은 자리를 고치는 일이라 **한 번에 하는 게 싸다.**
