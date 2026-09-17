# SDS Coding Assistant

dcode(v0.1.69)에 **계획 게이트 · 메모리/자기개선 · 실행 모니터링**을 얹은 코딩 어시스턴트.

추가 기능은 전부 `assistant/` 한 곳에 있고, dcode 원본(`libs/`)은 미들웨어 배선 3줄만 수정했다.

---

## 1. 요구사항

| | |
|---|---|
| Python | **3.12 이상** (`>=3.12,<4.0`) |
| 패키지 관리자 | **[uv](https://docs.astral.sh/uv/) 필수** — 아래 참조 |
| 모델 | 프로바이더 API 키 1개 (OpenAI / Anthropic / OpenRouter 등) |

> ### ⚠️ `pip`이 아니라 `uv`를 써야 한다
>
> 이 프로젝트는 `libs/` 안의 패키지들을 **상대경로 editable 의존**으로 묶는다
> (`[tool.uv.sources]`). 이건 uv 전용 기능이라 `pip install -e libs/code`로는
> 로컬 패키지를 찾지 못하고 **설치 단계에서 실패한다.**
>
> uv 설치:
> ```bash
> curl -LsSf https://astral.sh/uv/install.sh | sh     # macOS / Linux
> ```
> ```powershell
> powershell -c "irm https://astral.sh/uv/install.ps1 | iex"   # Windows
> ```

---

## 2. 설치

**저장소 루트에서** 실행한다. 아래 모든 명령이 그렇다.

```bash
uv sync --project libs/code --extra all-providers
```

> `--extra all-providers`를 빼면 의존성은 깔리지만 **모델 프로바이더가 없어 TUI가 뜨지 않는다.**
> 특정 프로바이더만 쓸 거면 `--extra openai`처럼 좁혀도 된다.

설치 확인:

```bash
uv run --project libs/code dcode --version
```

`dcode v0.1.69`가 나오면 성공.

---

## 3. 모델 키 설정

둘 중 편한 쪽을 쓴다.

**(a) dcode에 저장** — 키는 stdin으로 받으며 화면에 남지 않는다

```bash
uv run --project libs/code dcode auth set openai
```

환경변수에서 복사하려면:

```bash
uv run --project libs/code dcode auth set openai --from-env OPENAI_API_KEY
```

확인: `dcode auth list` · `dcode auth status openai`

**(b) 환경변수만 쓰기**

```bash
export OPENAI_API_KEY=sk-...
```

주요 프로바이더별 변수명:

| 프로바이더 | 환경변수 |
|---|---|
| `openai` | `OPENAI_API_KEY` |
| `anthropic` | `ANTHROPIC_API_KEY` |
| `openrouter` | `OPENROUTER_API_KEY` |
| `google_genai` | `GOOGLE_API_KEY` |
| `deepseek` | `DEEPSEEK_API_KEY` |
| `groq` | `GROQ_API_KEY` |
| `mistralai` | `MISTRAL_API_KEY` |
| `together` | `TOGETHER_API_KEY` |
| `xai` | `XAI_API_KEY` |

(전체 목록은 `dcode auth list`)

---

## 4. 실행

```bash
uv run --project libs/code dcode -a coding-assistant
```

**반드시 저장소 루트에서 실행한다.** dcode는 실행한 디렉터리를 프로젝트 루트로 잡는다.
다른 곳에서 띄우면 `.deepagents/AGENTS.md`(프로젝트 규칙)와 `runs/`(실행 로그)를 찾지 못한다.

확인:

```bash
uv run --project libs/code dcode config path
```

출력에서 **`project hooks.json` 줄만** 이 저장소를 가리키면 정상이다.
나머지는 전역 설정이라 홈 디렉터리를 가리키는 것이 맞다:

```
config.toml          ~/.deepagents/config.toml                              ← 전역
global .env          ~/.deepagents/.env                                     ← 전역
project hooks.json   <저장소 루트>/.deepagents/hooks.json   (missing)        ← 이 줄만 확인
user hooks.json      ~/.deepagents/hooks.json                               ← 전역
auth.json            ~/.deepagents/.state/auth.json                         ← 전역
```

`project hooks.json`이 `(missing)`인 것도 정상이다. 이 프로젝트는 훅을 쓰지 않고
미들웨어를 소스에 배선했다 — 훅 신뢰 프롬프트에 의존하지 않기 위한 설계다.
`project hooks.json`이 홈 디렉터리를 가리키면 **저장소 루트가 아닌 곳에서 실행한 것**이니
디렉터리를 옮겨 다시 띄운다.

> `-a coding-assistant`는 에이전트 프로필을 분리하는 옵션이다. 기존에 dcode를 쓰던 환경에서도
> 이 프로젝트의 설정이 섞이지 않는다.

---

## 5. 무엇이 추가되었나

| 기능 | 위치 | 상태 |
|---|---|---|
| **실행 모니터링** — 요청별 실행 흐름·지표·실패 지점 기록과 조회 | `assistant/assistant/events.py`, `observability.py`, `report.py` | 🔵 단계 2 |
| **계획 게이트** — 승인된 계획 없이는 쓰기·실행 도구를 차단 | `assistant/assistant/plan_gate.py` | ⬜ 단계 3 |
| **메모리·자기개선** — 규칙 저장/검색, 실패 기반 개선안 생성과 검증 | `assistant/assistant/memory.py` | ⬜ 단계 4 |
| **PEP8 게이트** — 변경된 `.py`를 ruff로 검사해 피드백 | `assistant/assistant/style_gate.py` | ⬜ 단계 5 |

dcode 원본 수정은 `libs/code/deepagents_code/agent.py` **3곳 3줄**이 전부다
(`EventWriter` 생성 1줄 + 미들웨어 삽입 2줄).

---

## 6. 테스트 케이스

> 🚧 **작성 중** — 각 단계가 끝날 때마다 채운다. 현재 단계 2 진행 중.

### 항목 4 — 모니터링

1. TUI를 띄우고 아무 작업이나 시킨다 (예: "README.md 읽어줘")
2. 종료 후 조회:
   ```bash
   uv run --project libs/code python -m assistant.report list
   uv run --project libs/code python -m assistant.report show <run_id>
   ```
3. 요청의 타임라인(모델 호출 · 도구 실행)과 총 소요 시간, 하단 지표가 보인다
4. 실패 지점만 보려면:
   ```bash
   uv run --project libs/code python -m assistant.report fail <run_id>
   ```

**실제 출력 (2026.09.17, 이 저장소의 `runs/`에서 그대로 뽑음 — 손으로 만든 예시가 아니다):**

```
$ uv run --project libs/code python -m assistant.report list
20260917-163808-01a0ae4d  미종료                -  실패 1
20260917-161247-01a0ae34  ok              9.5s  실패 1
20260917-161203-01a0ae34  ok             18.0s  실패 0
```

```
$ uv run --project libs/code python -m assistant.report show 20260917-161203-01a0ae34
run 20260917-161203-01a0ae34   (18.0s, 실패 0)
├─ model_call #1             10.7s   in=17175 out=82
├─ tool  read_file            0.0s   ok
└─ model_call #2              6.5s   in=19473 out=462

지표  모델 2회(시도) · 도구 1회 · 재시도 0회 · 총 18.0s · 토큰 in 36648 / out 544
```

```
$ uv run --project libs/code python -m assistant.report fail 20260917-163808-01a0ae4d
--- seq=3 model_error (deepseek/deepseek-v4.1-flash) ---
   seq=1    run_start    -               status=-
   seq=2    model_start  deepseek/deepseek-v4.1-flash status=-
>> seq=3    model_error  deepseek/deepseek-v4.1-flash status=error
    error: ForbiddenResponseError: Key limit exceeded (total limit). Manage it using https://openrouter.ai/... (계정별 URL은 여기서 생략)
```

세 번째 예시는 `list`에도 나오듯 실제로 있었던 실패다 — 이 프로젝트를 진행하며 모델 프로바이더
키가 한도를 넘겨서 난 실패를 그대로 잡은 것이다(원인이 `>>` 표시 줄과 `error:` 줄에 그대로 나온다).
`미종료`로 표시된 것은 `run_end`가 안 남았기 때문 — 모델 호출 자체가 실패해 턴이 안 끝났다.

### 항목 2 — 계획 게이트

<!-- TODO(단계 3) -->

### 항목 3 — 메모리·자기개선

<!-- TODO(단계 4) -->

### 항목 1 — 코드 스타일

<!-- TODO(단계 5) -->

### 단위 테스트

```bash
uv run --project libs/code pytest tests/
```

---

## 7. 프로젝트 구조

```
.
├─ assistant/               ★ 추가한 코드 (채점 대상)
│   ├─ pyproject.toml
│   └─ assistant/
│       ├─ events.py            이벤트 기록기
│       ├─ observability.py     실행 감시 미들웨어
│       └─ report.py            로그 조회 CLI
├─ tests/                   추가 코드의 단위 테스트
├─ libs/                    dcode 원본 (v0.1.69, 강사 배포본)
│   └─ code/deepagents_code/agent.py   ← 3줄만 수정
├─ .deepagents/             프로젝트 규칙·스킬 (dcode가 읽음)
├─ docs/plan/               계획·리뷰 문서
└─ runs/                    실행 로그 (git 제외)
```

---

## 8. 알아둘 것

- **실행 로그는 `runs/`에 쌓이며 git에 올라가지 않는다.** 도구 인자에 들어온 API 키·
  토큰은 기록 시점에 `***`로 가려지고, 긴 값은 절삭된다.
- **서브에이전트 내부는 로그에 안 보인다.** 메인 에이전트 관점에서 `task` 도구 호출
  한 건으로 기록된다. (dcode SDK가 서브에이전트에 별도 미들웨어 스택을 쓰기 때문)
- LangSmith 트레이싱은 선택이다. 쓰려면 `.env.example`을 `.env`로 복사해 채운다.
  **채점에 필요하지 않다** — 모든 증거는 `runs/`의 파일 로그로 확인할 수 있다.

---

## 9. 문제가 생기면

| 증상 | 원인과 해결 |
|---|---|
| `dcode: command not found` | `uv run --project libs/code dcode ...` 형태로 실행한다 |
| TUI가 안 뜨고 바로 종료 | `--extra all-providers` 없이 sync했다. 2절을 다시 실행 |
| 모델 호출이 인증 오류 | 3절의 키 설정. `dcode auth status <provider>`로 확인 |
| `runs/`가 안 생김 | 저장소 루트가 아닌 곳에서 실행했다. `dcode config path`로 확인 |
| `No solution found` / `sds-assistant` 설치 실패 | `pip`으로 설치하려 했다. 1절 참조 — `uv`를 써야 한다 |

---

제출자: **Adrian**
