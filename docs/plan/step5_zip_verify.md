# 단계 5 — 제출 ZIP 패키징 + 풀어서 검증 (작업 1)

**완료** 2026.09.18 · 담당 🟢구현 · 근거 `PLAN.md` 단계 5 5번(검토 X3), `STEP2_PLAN.md` §0-B

> 이 작업의 목적은 clone이 아니라 **실제 제출 형식(ZIP)** 으로, 이미 설정이 끝나 있는
> 개발 환경이 아니라 **완전히 새 디렉터리**에서 README를 그대로 따라갔을 때 정말로
> 빌드되는지 확인하는 것이다(X3: clone 검증은 "ZIP에서 뺀 파일에 의존하는 문제"를
> 구조적으로 못 잡는다). 실제로 이 방식으로만 잡히는 버그를 하나 찾았다 — 아래 참조.

## 1. ZIP 구성

`git archive`로 git이 추적하는 파일만 모았다 — `.venv/`·`__pycache__/`·`runs/`·
`.deepagents/plans/`·`*.egg-info/`는 `.gitignore` 덕에 애초에 후보에 안 들어가고,
`.pytest_cache/`·`.benchmarks/`는 git이 추적한 적도 없어 자동으로 빠진다.

```bash
git archive --format=zip --output=/tmp/sds_coding_assistant_submit.zip HEAD -- \
  README.md docs/plan .deepagents assistant tests libs .env.example
```

| | 포함 여부 | 비고 |
|---|---|---|
| `libs/` (전체 — `acp`·`code`·`deepagents`·`evals`·`partners/*`·`talon`) | ✅ | `libs/code/pyproject.toml`의 `[tool.uv.sources]`가 `../deepagents`·`../acp`·`../partners/{daytona,modal,quickjs,runloop,vercel}`를 상대경로로 참조한다 — 하나라도 빠지면 `uv sync`가 죽는다(X3 #4 그대로). 지시대로 `libs/` **전체**를 넣었다 |
| `assistant/`, `tests/`, `.deepagents/`, `README.md`, `docs/plan/` | ✅ | 지시된 포함 목록 그대로 |
| `.env.example` | ✅ (지시 목록에 없던 추가) | README §8이 `cp .env.example .env`를 안내한다 — 없으면 그 안내가 거짓말이 된다. 비밀값 없는 4줄짜리 템플릿이라 위험은 없다고 판단해 넣었다. **필요 없다고 보면 다음 빌드 때 목록에서 빼면 된다** |
| `.claude/`, `.agents/`, `CLAUDE.md`, `SKILLS.md`, `skills-lock.json`, `.git/` | ❌ | 지시대로 제외 |
| `runs/`, `.venv/`, `__pycache__/`, `.deepagents/plans/` | ❌ | git이 추적 안 함 (`.gitignore`) — 애초에 후보에 없음, 확인만 함 |

결과: 22MB, 최상위 항목 `.deepagents/ .env.example README.md assistant/ docs/ libs/ tests/` — 지시한 것과 정확히 일치.

## 2. 완전히 다른 디렉터리에서 재현

`~/zip_verify/`(저장소와 무관한 디렉터리)에 풀고, README를 그대로 따라갔다.

```bash
cd ~/zip_verify
uv sync --project libs/code --extra all-providers   # README 2절
uv run --project libs/code dcode --version           # README 2절 "설치 확인"
uv run --project libs/code dcode config path          # README 4절
```

| 단계 | 결과 |
|---|---|
| `uv sync` | ✅ 성공. `sds-assistant==0.1.0 (from file:///home/ubuntu/zip_verify/assistant)` — 로컬 editable 의존성이 새 경로에서 정상 해석됨 |
| `dcode --version` | 🔴 **README와 실제 출력이 다름** — 아래 참조 |
| `dcode config path` | ✅ `project hooks.json` 줄이 `/home/ubuntu/zip_verify/.deepagents/hooks.json`을 정확히 가리킴(전역 줄들은 홈 디렉터리) — README 4절의 판정 기준 그대로 성립 |

## 3. 발견한 문제 2건 — README를 고쳤다

### 🔴 A. `pytest`가 기본 설치에 안 들어간다

README 6절이 그대로 `uv run --project libs/code pytest tests/`를 시키는데, 새 디렉터리에서는:

```
error: Failed to spawn: `pytest`
  Caused by: No such file or directory (os error 2)
```

`libs/code/pyproject.toml`의 `[dependency-groups]`는 그룹 이름이 `test`이고(`dev`가 아니다),
`[tool.uv] default-groups` 설정이 없어 `uv sync`가 기본으로 설치하지 않는다. 원래 저장소에서
`pytest`가 됐던 건 과거에 이미 `--group test`(또는 동등한 명령)로 sync한 적이 있는 `.venv`가
남아 있었기 때문이다 — **clone/기존 환경 검증으로는 못 잡고, 완전히 새 디렉터리에서만 드러났다**
(X3가 예고한 정확한 실패 유형).

이 문제는 09.17 README 검토(N5)가 이미 예견했었다 — "`--group dev`를 넣거나 확인하라"고
적었지만 실제 그룹 이름(`test`)까지는 확인하지 않았다.

**고침** (README 6절):
```bash
uv sync --project libs/code --extra all-providers --group test
uv run --project libs/code pytest tests/
```
9절 문제해결 표에도 한 줄 추가.

### 🟡 B. `dcode --version`의 성공 문구가 실제 출력과 다름

README: "`dcode v0.1.69`가 나오면 성공." 실제 첫 줄: `deepagents-code 0.1.69` (버전 번호는
맞지만 문구가 다르다 — 그대로 찾으면 실패로 오인할 수 있다).

**고침** — "첫 줄에 `deepagents-code 0.1.69`가 나오면 성공"으로 정정. 겸사겸사 4절의
`config path` 예시도 실제 출력 형식(`(ok)`/`(missing)` 태그, 버전에 따라 줄이 더 있을 수
있음)에 맞춰 정정했다.

## 4. 고친 뒤 재검증

README를 고친 뒤 ZIP을 다시 만들어 **다시 새 디렉터리**(`~/zip_verify/` 재생성)에 풀고 처음부터 반복했다.

```bash
uv sync --project libs/code --extra all-providers --group test   # ✅
uv run --project libs/code dcode --version                        # ✅ deepagents-code 0.1.69
uv run --project libs/code dcode config path                      # ✅ project hooks.json이 새 디렉터리를 가리킴
uv run --project libs/code pytest tests/ -q                       # ✅ 87 passed
```

전부 통과. `assistant/` 쪽 단위 테스트(87개)가 원본 저장소가 아닌, ZIP에서 막 풀어낸 사본에서도
그대로 통과한다는 것까지 확인했다.

## 5. 결정 사항 (기록)

- **`uv.lock`은 ZIP에 안 넣는다.** 지시된 포함 목록에 없었고, 이번 검증에서 lock 없이도
  `uv sync`가 매번 안정적으로 해석되는 것을 확인했다 — 넣을 이유가 새로 생기지 않았다.
  (X3 #5가 "결정해서 적어야 한다"고 한 항목 — 여기 적는다.)
- **`.env.example`을 지시 목록에 없이 추가로 넣었다.** 위 표 참조. 문제라고 판단되면 다음
  ZIP부터 빼면 된다 — `git archive` 명령의 pathspec에서 한 항목만 지우면 된다.
- ZIP 산출물 자체(`/tmp/sds_coding_assistant_submit.zip`)는 저장소에 커밋하지 않았다 —
  실행 산출물이라 `runs/`와 같은 취급이다. 실제 제출 시 이 문서의 `git archive` 명령을
  다시 돌려 새로 만들면 된다.

## 다음

작업 2(ruff 설정 + docstring)로 넘어간다. 끝나면 이 문서에 마지막으로 한 번 더
(ruff 규칙 활성화 이후) ZIP 재검증을 추가할지는 작업 2 결과에 따라 판단한다.
