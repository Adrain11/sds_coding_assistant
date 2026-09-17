# Coding Assistant (dcode) — 프로젝트 규칙

이 파일은 이 저장소 루트에서 `dcode`를 실행할 때마다 항상 로드되는 프로젝트 메모리입니다.
(전역/개발 도구 레벨 규칙은 `CLAUDE.md`에 따로 있음 — 이 파일은 dcode 앱 레벨 규칙만 담습니다.)

## 코드 스타일

- 모든 Python 코드는 PEP8을 따른다. `write_file`로 `.py` 파일을 쓰면 `hooks/pep8_gate.py`가
  `ruff check`로 자동 검사하고, 위반이 있으면 쓰기 자체가 거부된다(`.deepagents/hooks.json`).
  거부되면 ruff가 알려주는 위반 내용을 그대로 고쳐서 다시 시도할 것 — 스타일을 두고 다투지 말 것.
- `edit_file`(부분 수정)은 이 훅이 검사하지 않는다. 기존 파일을 부분 수정할 때도 PEP8을 스스로
  지킬 것.

## 작업 전 리뷰 워크플로우

- 여러 단계가 필요한 작업은 시작 전에 `/goal add <목표>`로 acceptance criteria 초안을 먼저
  만들고, 사용자 리뷰(accept/edit/revise)를 받은 뒤에 작업을 시작한다.
- YOLO 모드로 리뷰를 건너뛰지 않는다. 헤드리스/비대화형 실행(`-n`)에서는 `--rubric "..."`으로
  대체한다.

## 메모리 (Self-Improving)

- 작업을 시작하기 전에 관련 메모리(`~/.deepagents/<agent>/memories/*.md`)를 먼저 확인한다.
- 사용자가 컨벤션/선호/실수 교정을 알려주면 `/remember`로 명시적으로 저장하거나, 자동 메모리
  저장(memory.auto_save)에 맡긴다. 같은 피드백을 반복해서 받지 않도록 한다.

## 모니터링

- LangSmith 트레이싱이 켜져 있으면(`.env`의 `LANGSMITH_TRACING=true`) 모든 작업은 자동으로
  추적된다. 비용이 크거나 오래 걸리는 작업 뒤에는 `/cost`, `/tokens`로 확인해 볼 것.

## 참고 문서

- 평가 기준 ↔ 구현 매핑: `docs/evaluation-mapping.md`
- 실행 방법: 저장소 루트 `README.md`
