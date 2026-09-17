# CLAUDE.md — AX Advanced 미니 PJT (dcode 기반 Coding Assistant)

이 저장소는 dcode(`deepagents-code`) 소스를 vendoring해서 기능을 얹는 미니 프로젝트입니다.
전체 계획은 `docs/plan/PLAN.md`, 지금 진행 중인 단계는 `docs/plan/STEP2_PLAN.md`를 따릅니다.
(이전에 별도로 진행했던 `sds_final_project`와는 무관한 저장소입니다.)

## 1. 아키텍처

- `dcode`는 pip 설치가 아니라 **소스를 `libs/`에 통째로 vendoring**한 것이다 (2026.09.14 배포본,
  MIT 라이선스, `fb2b1a2` baseline 커밋). 그 위에 두 가지 방식으로만 커스터마이즈한다:
  1. **소스 배선** — `libs/code/deepagents_code/agent.py`의 `create_cli_agent` 미들웨어
     리스트에 직접 삽입한다. (Step 2: `EventLoggerMiddleware` 1줄)
  2. **`assistant/` 패키지** — 내가 쓰는 코드는 전부 여기 둔다. `libs/code/pyproject.toml`의
     `[tool.uv.sources]`에 editable path 의존으로 얹는다 (`libs/deepagents`와 같은 방식).
- **훅(`.deepagents/hooks.json`) 방식은 채택하지 않는다.** step0 TUI 실측
  (`docs/plan/step0_tui_result.md`)에서 훅이 `write_file`만 막고 셸(`execute`) 우회에는
  뚫리는 게 확인돼 폐기했다. 실제 강제는 미들웨어 코드로만 한다.
- 게이트(Step 3)는 승인 모드(Manual/Auto/YOLO)와 무관하게 동작해야 한다 — 모드가 아니라
  "승인된 계획이 있는가"만 본다.

## 2. 디렉토리 구성

```
sds_coding_assistant/
├── CLAUDE.md                  ← 이 문서
├── docs/plan/
│   ├── PLAN.md                  전체 계획 (5단계)
│   ├── step0_tui_result.md      TUI 첫 실측 결과 (훅 우회 발견 등)
│   └── STEP2_PLAN.md            현재 단계 계획 (이벤트 로거)
├── libs/                       dcode + DeepAgents SDK 원본. 수정은 §1의 두 지점만
│   ├── code/                    dcode 본체 (deepagents_code)
│   └── deepagents/               DeepAgents SDK
├── assistant/                  ★ 내 코드 (Step 2부터 생성 — observability.py, report.py 등)
├── tests/                      차단 경로·이벤트 로거 단위 테스트
├── .agents/skills/              DeepAgents 참고 스킬 8종 (langchain-ai/langchain-skills)
├── .claude/skills/              위 8종은 .agents/skills 심볼릭 링크,
│                                나머지 5종(systematic-debugging 등, obra/superpowers)은 실제 복사
├── .deepagents/AGENTS.md        dcode 프로젝트 스코프 규칙 (저장소 루트에서 dcode 실행 시 항상 로드)
├── .env.example                 모델 API 키 템플릿
├── SKILLS.md / skills-lock.json 스킬 설치 기록
└── runs/                       실행 이벤트 로그 (.gitignore, Step 2부터 생성)
```

`README.md`(재현 절차), `docs/evaluation-mapping.md`(평가기준 매핑)는 아직 없음 — 단계 5에서 작성.

## 3. 코딩 가이드

- `assistant/`는 규모가 작은 동안 폴더별 `AGENTS.md`를 따로 두지 않는다. 전역 규칙은 이 문서에만.
- 완료 기준은 각 단계 계획서의 DC(완료조건) 번호로 문장화하고, **전부 TUI에서 사람이 직접
  확인**한다. 헤드리스 실행 결과는 증거로 치지 않는다 (`PLAN.md` 리스크 표).
- 기능 검증(단위 테스트)과 완료 판정(TUI 실측)을 구분한다 — 단위 테스트 통과가 완료를
  의미하지 않는다.

## 4. 스킬

`langchain-ai/langchain-skills`에서 DeepAgents 핵심 8개, `obra/superpowers`에서 개발
프랙티스 5개를 골라 설치했습니다. 설치 이유·히스토리·재설치 명령은 [`SKILLS.md`](./SKILLS.md)에,
정확한 출처는 `skills-lock.json`에 있습니다.

- `deep-agents-core`, `deep-agents-memory`, `deep-agents-orchestration`
- `deepagents-python-quickstart`, `ecosystem-primer`
- `langchain-dependencies`, `langchain-fundamentals`, `langgraph-fundamentals`
- `systematic-debugging`, `test-driven-development`, `verification-before-completion`,
  `writing-plans`, `using-git-worktrees`

## 5. 메모리

Claude Code 쪽은 이 `CLAUDE.md`가 프로젝트 메모리입니다. dcode(결과물) 쪽 메모리는
`.deepagents/AGENTS.md` + `~/.deepagents/<agent>/memories/*.md`로 별도 층입니다 — 단계 4에서
다룹니다.

## 6. 알려진 미해결 항목

- `.deepagents/AGENTS.md`가 아직 `hooks/pep8_gate.py` · `.deepagents/hooks.json`을
  언급한다 — 이 저장소에는 둘 다 없다 (§1 참고). Step 3(계획 게이트)에서 미들웨어 배선
  설명으로 교체 필요.

## 7. 환경

- 수업 폴더(`~/sds_ax_advanced_2026_2`) 하위에 이 프로젝트를 두지 않는다.
- WSL 내부에서만 작업 (제출 시 압축파일로 변환 고려).
