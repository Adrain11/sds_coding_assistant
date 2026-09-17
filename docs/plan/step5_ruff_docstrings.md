# 단계 5 — ruff 설정 + docstring (작업 2)

**완료** 2026.09.18 · 담당 🟢구현 · 근거 채점 1-3(PEP8/코드 스타일, 4점 — 배점 최대)

## 🔴 계획 전제가 실제 소스와 달랐다 — 위치를 바꿔서 진행했다

지시는 `libs/code/pyproject.toml`의 `[tool.ruff.lint]`를 고치라는 것이었다. 실행하기 전에
확인해보니 두 가지가 지시의 전제와 어긋났다. **코드를 지시대로 맞추지 않고, 실제로 동작하는
위치로 바꿔 진행했다** — 아래가 그 근거다.

### 1. `libs/code/pyproject.toml`을 고쳐도 `assistant/`·`tests/`에는 적용되지 않는다

`ruff check assistant/ tests/`를 저장소 루트에서 실행하면, ruff는 대상 파일의 디렉터리에서
**위쪽으로** `pyproject.toml`/`ruff.toml`을 찾는다. `libs/code/`는 `assistant/`·`tests/`의
**형제 디렉터리**이지 조상이 아니라서 이 탐색 경로에 아예 들어오지 않는다. 저장소 루트에는
`pyproject.toml`이 없어서, 실제로는 **ruff의 내장 기본값**이 적용되고 있었다 —
`ruff check --show-settings`로 직접 확인했다: `select=["ALL"]`도, 이미 있는
`pydocstyle.convention="google"`도 전혀 적용되지 않고 있었다.

지시대로 `libs/code/pyproject.toml`만 고쳤다면, 그 파일 스스로도 이미 `select=["ALL"]`과
`convention="google"`을 갖고 있어서(각각 라인 251, 286) **변경 자체가 무의미했을 것**이다 —
파일은 바뀌지만 `assistant/`·`tests/` 검사 결과는 한 글자도 안 바뀐다.

### 2. `libs/code/pyproject.toml` 안에서 "`libs/`를 제외"하는 것은 성립하지 않는다

그 파일 자체가 `libs/code/` **안에 있는** dcode 소스다. 자기 자신의 설정 파일에 "libs/ 전체를
검사에서 뺀다"는 규칙을 넣는 것은 대상 경로가 애초에 그 프로젝트 범위 밖이라 아무 파일에도
안 걸린다.

### → 대신 한 것: 저장소 루트에 `ruff.toml` 신설

`assistant/`와 `tests/`는 **저장소 루트**를 공통 조상으로 두므로, 루트에 `ruff.toml`을 두면
두 디렉터리 모두에 한 설정이 적용된다. `libs/`는 이 파일의 `extend-exclude`로 명시적으로
제외한다(지시가 원했던 정확히 그 효과 — 안전망 성격이고, 실제로는 `ruff check assistant/
tests/`처럼 대상 경로를 명시하므로 없어도 `libs/`는 애초에 검사되지 않는다).

`libs/code/pyproject.toml`은 **손대지 않았다** — 그 파일은 여전히 자기 자신(dcode 소스)에게만
적용되고, 이미 필요한 설정(`select=["ALL"]`, google 컨벤션)을 갖고 있어 고칠 이유가 없었다.

```toml
# ruff.toml (저장소 루트, 신규)
extend-exclude = ["libs"]

[lint]
select = ["E", "F", "I", "N", "D"]
extend-select = ["D417"]

[lint.pydocstyle]
convention = "google"

[lint.per-file-ignores]
"tests/**" = ["D1", "D417"]
```

**`F`(pyflakes)를 지시에 없던 것을 추가했다** — 근거: 설정 파일이 하나도 없던 지금까지도
ruff의 내장 기본값(`E4`/`E7`/`E9`/`F`)이 이미 `F`를 검사하고 있었다. `select`에서 `F`를 빼면
그 기본 커버리지가 **후퇴**한다. 추가가 아니라 회귀 방지다.

`ruff check assistant/ tests/`가 이 새 설정으로 실제 동작하는지, `libs/code`가 자기 설정을
그대로 유지하는지 둘 다 `--show-settings`로 확인했다 — 아래 §3.

## 2. 위반 수정

`ruff check assistant/ tests/` 최초 실행: **145개**. 순서대로 처리했다.

| 도구 | 결과 |
|---|---|
| `ruff check --fix` (I001, D209만) | 자동 고침 — import 정렬, 닫는 따옴표 위치 |
| `ruff format assistant/ tests/` | 145 → 47. 긴 줄 대부분(코드 구조)이 자동으로 줄바꿈됨 |
| 수동 | 나머지 47 — 아래 |

### 🔴 F821(8건) — 린터가 맞았다, 진짜 취약점이었다

`observability.py`의 네 군데(`wrap_tool_call`/`awrap_tool_call`/`wrap_model_call`/
`awrap_model_call`)가 전부 같은 모양이었다:

```python
except Exception as exc:
    _safe(lambda: self._ev.record(..., error=f"{type(exc).__name__}: {exc}"))
    raise
```

지금 동작은 맞다 — `_safe()`가 람다를 **즉시** 호출하므로 `except` 블록을 빠져나가기 전에
`exc`가 쓰인다. 하지만 `except ... as exc`로 바인딩된 이름은 **그 블록이 끝나는 순간
파이썬이 자동으로 `del`한다** — 클로저가 나중에(예: `_safe`가 큐에 넣고 나중에 실행하는
식으로 바뀌면) 불리면 `NameError`가 난다. 지금은 괜찮지만 `_safe`의 구현이 바뀌는 순간
조용히 깨지는 지뢰였다.

**고침** — `exc`를 람다 밖에서 즉시 문자열로 굳힌다:

```python
except Exception as exc:
    error = f"{type(exc).__name__}: {exc}"  # exc가 지워지기 전에 즉시 평가
    _safe(lambda: self._ev.record(..., error=error))
    raise
```

네 곳 전부 동일하게 고쳤다. `error` 지역 변수가 생기면서 F841(사용되지 않는 변수, 4건)도
같이 사라졌다 — 같은 원인의 다른 증상이었다.

### 나머지 — 문법적 정리

- **I001**(4건) import 정렬 — 자동 고침
- **E501**(94→21→0) — 대부분 `ruff format`이 해결. 남은 21개는 긴 한국어 문자열
  리터럴(코드 구조가 아니라 **문자열 안의 텍스트**라 포매터가 못 건드림) — 문장을 여러
  줄로 나눠 수동 정리
- **D205/D209**(23건) — 요약 줄과 본문 사이 빈 줄, 닫는 따옴표 위치. 전부 내가 쓴 여러 줄
  docstring 스타일이 pydocstyle 관례와 안 맞았던 것 — 형식만 정리, 내용은 안 바꿈

## 3. docstring — 채점 1-3의 핵심

**D102/D103/D107**(11건, 공개 메서드/함수/`__init__`에 docstring 없음) + **D417**(1건,
`revise`가 `plan_id` 인자 설명 누락) 전부 Args/Returns를 갖춘 google 스타일로 채웠다:

- `PlanGateMiddleware.__init__` — 생성자 인자 3개(`event_writer`/`project_root`/`reviewer`) 설명
- `PlanGateMiddleware.wrap_tool_call`/`awrap_tool_call` — Args/Returns
- CLI 함수 4개(`cmd_list`/`cmd_show`/`cmd_approve`, `plan_gate.py`·`report.py`의 `main`) — Args/Returns
- `Plan.to_dict`/`from_dict`, `PlanStore.__init__` — Args/Returns
- `PlanStore.revise`의 D417 — 누락된 `plan_id` 설명 추가

`tests/**`는 `D1`(docstring 없음)을 예외로 뒀다 — 테스트 함수 이름 자체가 설명이고, 이미 있는
docstring(회귀 사유 설명용)은 그대로 두되 형식(D205/D209)만 통일했다.

## 4. 결과

```
uv run --project libs/code ruff check assistant/ tests/     → All checks passed!
uv run --project libs/code ruff format assistant/ tests/ --check → 11 files already formatted
uv run --project libs/code pytest tests/ -q                  → 87 passed
```

`libs/code` 자신의 ruff 설정·검사는 안 건드렸다는 것도 확인했다 —
`uv run ruff check --show-settings`(libs/code 안에서 실행)의 `cache_dir`이 여전히
`libs/code/.ruff_cache`를 가리킨다. 저장소 루트에서 `ruff check .`를 돌려도 `libs/`가
`extend-exclude`로 빠져 0건이 나온다(안전망이 실제로 동작함을 확인).

## 5. 남은 것 / 반영해야 할 문서

- `docs/plan/step5_zip_verify.md`의 ZIP 포함 목록에 **`ruff.toml`을 추가해야 한다** —
  이 작업으로 새로 생긴 루트 파일이라 원래 목록(작업 1 시점)에는 없었다. 다음 ZIP
  재검증 때 반영한다.
- README §6에 "코드 스타일(ruff)" 절을 추가해 `ruff check`/`ruff format --check` 명령을
  적어뒀다 — 지시에는 없던 항목이지만, 채점 1-3의 확인 방법을 README에 남기는 게
  기존 §6 관례(항목마다 확인 명령 명시)와 일치해 추가했다.
