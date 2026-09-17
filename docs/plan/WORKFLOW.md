# 작업 분담과 진행 규칙

**미니 PJT** dcode 기반 Coding Assistant · **저장소** github.com/Adrain11/sds_coding_assistant (main)
**최종 갱신** 2026-09-17

> 이 문서를 먼저 읽어라. 네가 어느 환경이든, 여기서 네 역할과 지금 할 일을 찾을 수 있다.

---

## 0. 현재 상태

> ⚠️ **단계가 끝날 때마다 이 절을 갱신하고 커밋한다.** 이게 세 환경이 공유하는 유일한 진행 상황판이다.

| 단계 | 상태 | 산출물 |
|---|---|---|
| 0 — TUI 첫 확인 | ✅ 완료 (09.16) | `docs/plan/step0_tui_result.md` |
| 1 — 소스 vendoring + 빌드 | ✅ 완료 (09.17) | `libs/`, 빌드 통과 (`--extra openrouter`) |
| 1-a — 이식 (skills·설정) | ✅ 완료 (09.17) | `.agents/`, `.claude/`, `.deepagents/`, `SKILLS.md` |
| **2 — 이벤트 로거** | 🔵 **진행 중** | 계획 `docs/plan/STEP2_PLAN.md` · 리뷰 대기 |
| 3 — 계획 게이트 | ⬜ 계획 미작성 | — |
| 4 — 메모리·자기개선 | ⬜ 계획 미작성 | — |
| 5 — PEP8 + README + 최종 | ⬜ 계획 미작성 | — |

**지금 열려 있는 것**
- 다른 Opus: STEP2_PLAN.md 리뷰 → `docs/plan/STEP2_REVIEW.md`
- VS Code: STEP2_PLAN.md §8의 2번부터 구현
- Cowork Opus: 리뷰 반영 후 단계 3 계획 착수

**남은 시간** 09.17(목) 오후 + 09.18(금) 하루

---

## 1. 세 환경의 역할

한 가지 일은 한 곳에서만 한다. 겹치면 서로 다른 답이 나오고 저장소가 갈린다.

| 이름 | 어디 | 한 줄 |
|---|---|---|
| 🟣 **설계** | Cowork Opus | 계획서를 쓰고, 리뷰를 받을지 판단한다 |
| 🔵 **검토** | 다른 Opus | 계획을 비판한다. 고치지는 않는다 |
| 🟢 **구현** | VS Code (Claude Code / Sonnet) | 코드를 쓰고 돌린다 |

이 문서 안에서는 이 이름으로 부른다.

### 🟣 설계 (Cowork Opus) — 계획과 판단
- 각 단계의 **계획서 작성** (`STEP2~5_PLAN.md`)
- 리뷰 결과를 **받을지 말지 판단**하고 계획에 반영
- 소스를 읽고 설계 근거 확인 (GitHub API·raw URL)
- 저장소 상태 점검
- **하지 않는 것** — 구현 코드 작성, 명령 실행

### 🔵 검토 (다른 Opus) — 리뷰어
- 계획서를 **비판적으로 검토** → `STEP*_REVIEW.md`
- 막혔을 때 설계 대안 제시
- **하지 않는 것** — 계획서 직접 수정, 구현
- **예외** — Cowork Opus의 토큰이 떨어지면 §6에 따라 계획 역할을 넘겨받는다

### 🟢 구현 (VS Code · Claude Code / Sonnet)
- 계획서 §4의 작업 순서대로 **실제 코드 작성·실행·테스트**
- 계획의 전제가 소스와 다르면 **코드를 맞추지 말고 보고**
- 단계 결과를 `docs/plan/step*_result.md`에 기록 (실패도 기록)
- **하지 않는 것** — 계획서 범위 밖 작업. 필요하면 먼저 물어본다

### 사람(김)
- 환경 사이의 전달, 커밋·푸시
- **TUI 완료 조건 확인** — 이건 사람만 할 수 있다
- 범위 변경 승인

---

## 2. 단일 원본 규칙

**GitHub `main` 브랜치가 유일한 원본이다.** 다른 어디에 있는 사본도 최신이 아닐 수 있다.

| 위치 | 성격 |
|---|---|
| GitHub `main` | ✅ **원본** |
| WSL `~/sds_coding_assistant` | 작업 사본 — 커밋·푸시로 원본에 반영 |
| Windows `05_프로젝트\` | Cowork Opus의 초안 출력 자리. 반드시 `docs/plan/`으로 복사해야 원본이 된다 |

### 문서 동기화
Cowork Opus가 Windows 폴더에 계획서를 쓰면, 사람이 옮긴다:

```bash
cd ~/sds_coding_assistant
SRC="/mnt/c/Users/SDS/Desktop/2026 9월 AX advanced/05_프로젝트"
cp "$SRC"/PLAN.md "$SRC"/STEP*_PLAN.md "$SRC"/step*_result.md docs/plan/ 2>/dev/null
git add -A && git commit -m "docs: sync plan" && git push
```

> ⚠️ `$PJT_WIN`은 프로젝트 폴더까지 포함한 경로다. 계획 문서는 그 **한 단계 위**에 있다.
> 위처럼 `SRC`를 직접 잡아라. (09.16·09.17에 이걸로 두 번 헤맸다.)

### 다른 환경이 읽는 법
```
https://raw.githubusercontent.com/Adrain11/sds_coding_assistant/main/docs/plan/<파일>
```

---

## 3. 각 환경 시작 프롬프트

### 🟢 VS Code
```
docs/plan/WORKFLOW.md 와 docs/plan/STEP<N>_PLAN.md 를 읽어라.

규칙:
1. 계획서 §4의 작업 순서표를 그대로 따른다. 번호를 건너뛰지 않는다.
2. dcode 원본(libs/) 수정은 계획서가 명시한 곳만. 그 이상 고쳐야 할 것 같으면
   고치지 말고 먼저 왜 필요한지 보고한다.
3. 계획서의 전제가 실제 소스와 다르면 코드를 맞추지 말고 그 차이를 먼저 보고한다.
   범위가 바뀌면 계획서를 고치고 승인을 받은 뒤 진행한다.
4. 완료 판정은 계획서 §3의 DC 항목이다. 단위 테스트 통과만으로 완료라고 하지 마라.
   내가 TUI에서 확인할 수 있게 실행할 명령과 기대 화면을 정리해서 내놓아라.
5. 끝나면 docs/plan/step<N>_result.md 에 결과를 쓴다. 실패한 것도 쓴다.
```

### 🔵 다른 Opus (리뷰)
```
너는 리뷰어다. 코드를 쓰거나 파일을 고치지 마라.

대상: https://raw.githubusercontent.com/Adrain11/sds_coding_assistant/main/docs/plan/STEP<N>_PLAN.md
배경: 같은 경로의 PLAN.md, step0_tui_result.md, WORKFLOW.md
소스: https://github.com/Adrain11/sds_coding_assistant (공개, main)

평가 기준은 PLAN.md §1의 채점 4항목이다.

검토 관점:
1. 계획이 소스와 어긋나는 곳. §0의 S항목은 파일·줄번호를 인용한 주장이다.
   저장소에서 직접 확인하고 틀린 게 있으면 지적해라.
2. 계획대로 만들었는데 채점 세부항목 중 증거가 안 나오는 것.
3. §3의 완료조건이 실제로 각 채점 항목을 증명하는지.
4. 빠진 실패 모드. 특히 TUI(Textual), async 실행, 병렬 도구 호출.
5. 남은 단계 대비 과설계인 부분.

출력:
# 단계 <N> 계획 리뷰 (<날짜>, <모델명>)
## 반드시 고쳐야 할 것   (무엇이 / 왜 / 어떻게. 근거는 파일·줄번호로)
## 고려해볼 것
## 계획대로 두는 게 맞다고 본 것   (이것도 반드시 적어라)

규칙: 계획서를 통째로 다시 쓰지 마라. 근거 없는 일반론 금지.
확신 없으면 "확인 필요"로 표시하고 어떻게 확인하는지 써라.
```

### 🟣 Cowork Opus
```
github.com/Adrain11/sds_coding_assistant 의 docs/plan/ 을 보고 이어서 하자.
```

---

## 4. 한 단계를 도는 순서

```
[🟣 Cowork]  계획서 작성 → Windows 폴더
     ↓  사람이 docs/plan/ 으로 복사·커밋·푸시
[🔵 Opus]    리뷰 → STEP<N>_REVIEW.md → 커밋
     ↓
[🟣 Cowork]  리뷰 판단 → 계획서에 반영 + 반영 내역 기록 → 커밋
     ↓
[🟢 VS Code] 구현 → 단위 테스트
     ↓
[사람]        TUI에서 DC 완료조건 확인
     ↓
[🟢 VS Code] step<N>_result.md 기록 → 커밋
     ↓
[🟣 Cowork]  WORKFLOW.md §0 갱신 → 다음 단계 계획
```

**2번(리뷰 반영)이 채점 2-3의 증거다.** 리뷰를 다 받아들이면 리뷰가 아니라 지시고, 하나도 안 받으면 리뷰한 척이다. **받은 것과 안 받은 것을 이유와 함께 남긴다.**

---

## 5. 커밋 규칙

- 커밋 전에 항상: `git ls-files --cached | grep -iE "settings\.local\.json|\.env$"` → **반드시 빈 출력**
- 브랜치는 `main` 하나만 쓴다
- 메시지 접두사: `docs:` 계획·문서 / `feat:` 기능 / `fix:` 수정 / `test:` 테스트 / `chore:` 정리
- `runs/`, `.venv/`, `.env`, `.claude/settings.local.json`은 `.gitignore`에 있다 — 확인만 하고 지우지 말 것

---

## 6. 토큰이 떨어졌을 때

Cowork Opus의 토큰이 부족하면 🔵 다른 Opus가 계획 역할을 넘겨받는다. 넘길 때 줄 것:

```
이제 네가 계획 담당이다. 리뷰어 역할은 끝났다.
다음을 읽고 이어서 해라:
https://raw.githubusercontent.com/Adrain11/sds_coding_assistant/main/docs/plan/WORKFLOW.md
docs/plan/ 의 나머지 문서와 저장소 소스도 필요한 만큼 읽어라.
WORKFLOW.md §0의 현재 상태에서 다음 할 일을 찾아서 시작해라.
```

**인계가 되려면 §0이 최신이어야 한다.** 그게 이 문서를 매 단계 갱신하는 이유다.

> ⚠️ **검토가 설계를 겸하면 리뷰의 독립성이 사라진다.** 자기가 쓴 계획을 자기가 리뷰하는 꼴이라
> 채점 2-3("AI 리뷰 후 반영")의 증거로 약해진다.
> 그 상황이 오면 **리뷰 역할은 🟢 구현(Sonnet)에게 넘긴다.** 다른 모델이고, 코드를 직접 만져본
> 입장이라 오히려 실전적인 지적이 나온다.

---

## 7. 지금까지 밟은 지뢰 (반복하지 말 것)

| | 무엇 | 교훈 |
|---|---|---|
| 09.16 | `$PJT_WIN`에 프로젝트 폴더명을 또 붙여 rsync 실패 | 경로 변수는 끝이 어디인지 확인하고 쓴다 |
| 09.16 | `cp -r ... ./libs`를 두 번 돌려 `libs/libs` 중복 생성 | 디렉터리 복사 전에 대상이 이미 있는지 본다 |
| 09.17 | 단계 1의 "이식"을 안 하고 넘어갔음 (저장소에 `libs/`만 있었다) | 단계 완료 판정을 눈으로 확인한다 |
| 09.17 | 브랜치가 `main`인데 `master`를 보고 있었다 | 원격 상태는 `git ls-remote --heads origin`으로 본다 |
| 09.17 | 프로바이더 extra 없이 `uv sync` → TUI 안 뜸 | 빌드 절차는 채점자 환경 기준으로 쓴다 |
