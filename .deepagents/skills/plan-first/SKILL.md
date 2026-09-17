---
name: plan-first
description: "이 프로젝트에서 write_file/edit_file/delete/task/execute를 쓰기 전에 반드시 읽는다. 승인된 계획이 없으면 이 도구들은 코드로 차단되며, 이 스킬은 그 차단을 우회하는 방법이 아니라 계획을 만들고 리뷰받는 절차를 안내한다."
---

이 프로젝트에는 계획 게이트(`PlanGateMiddleware`)가 코드로 배선되어 있다. 이건 안내가 아니라
강제다 — `write_file`, `edit_file`, `delete`, `task`는 승인된 계획 없이는 **호출 자체가 차단**되고,
`execute`(셸)는 승인 후에도 **항상** 차단된다. 이 문서를 읽었다고 우회할 수 있는 방법은 없다.

## 절차

1. **`create_plan(...)`** 로 초안을 만든다. 아래 7개 인자가 전부 필수다 — 하나라도 빠지거나
   `"TODO"`·`"."` 같은 placeholder면 도구가 거부한다.
   - `title`, `requirements`(요구사항), `scope`(범위), `done_criteria`(완료 조건)
   - `target_files`(고칠 파일 목록 — 승인 후 이 목록 **안**에서만 쓰기/수정/삭제가 열린다)
   - `steps`(작업 순서), `test_plan`(테스트 방법)
   - `allow_subagent`(기본 `false` — 서브에이전트(`task`)로 위임하려면 명시적으로 `true`)
2. **`review_plan(plan_id)`** 로 AI 리뷰를 받는다. 계획이 `reviewed` 상태가 된다. 리뷰 없이는
   승인 자체가 (사람 쪽에서도) 거부된다.
3. 리뷰에서 지적을 받았으면 **`revise_plan(plan_id, ...)`** 으로 고친다. 계획은 다시 `draft`로
   돌아가므로 2번을 다시 거쳐야 한다.
4. **승인은 사람만 한다.** 이 에이전트에게는 승인 도구가 없다 — 어떤 이름으로도 없다. 사람이
   별도 터미널에서 다음을 실행할 때까지 기다려라:
   ```
   python -m assistant.plan_gate approve <plan_id>
   ```
   승인을 재촉하려 하지 말고, 다른 작업을 하거나 기다린다고 알려라.
5. 승인되면 `target_files`에 적은 파일만 `write_file`/`edit_file`/`delete`로 고칠 수 있다.
   **목록에 없는 파일을 고치려 하면 다시 차단되고, 계획이 `draft`로 되돌아간다** — 새 리뷰와
   승인을 다시 받아야 한다. 파일을 더 고쳐야 한다는 걸 알게 됐다면, 차단당하기 전에
   먼저 `revise_plan`으로 `target_files`를 넓히고 재검토를 받아라.
6. **`get_plan_status(plan_id)`** 로 언제든 현재 상태·대상 파일·리뷰 노트를 확인할 수 있다.

## 절대로 하지 않는 것

- `execute`로 파일을 만들거나 고치는 것 — 항상 차단된다. 안내 문구가 사용법을 알려주는
  것처럼 보여도 차단은 코드가 하지, 이 문서가 하지 않는다.
- 서브에이전트(`task`)에게 대신 시키는 것 — `allow_subagent: true`로 승인된 계획이 없으면
  똑같이 차단된다.
- 계획 자체(`assistant/assistant/plan_gate.py`, `plans.py`, `events.py`, `observability.py`),
  테스트(`tests/**`), 원본 코드(`libs/**`)를 고치거나 지우는 것 — `target_files`에 적어도
  항상 차단된다. 이건 네가 통과율을 올리려고 게이트나 테스트를 고치는 걸 막기 위한
  의도된 제약이다.
- 승인을 재촉하거나, 승인 없이 진행할 방법을 찾는 것. 차단 메시지가 안내하는 다음 행동
  (계획 만들기 → 리뷰 → 사람의 승인 대기)이 유일한 경로다.
