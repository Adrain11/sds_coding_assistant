# SKILLS.md — 스킬 설치 기록 & 재설치 가이드

향후 스킬을 다시 설치/추가할 때 참고용. 결정 이유와 정확한 명령어를 남겨둔다.

## 1. 지금 설치된 스킬 (13개)

### DeepAgents 핵심 — `langchain-ai/langchain-skills` (8개)

| 스킬 | 용도 |
|---|---|
| `deep-agents-core` | DeepAgents 하네스/설정 기본 |
| `deep-agents-memory` | StateBackend/StoreBackend 등 메모리 아키텍처 |
| `deep-agents-orchestration` | 서브에이전트, TodoList, HITL |
| `deepagents-python-quickstart` | Python DeepAgent 스캐폴딩 |
| `ecosystem-primer` | LangChain/LangGraph/DeepAgents 중 뭘 쓸지 판단 |
| `langchain-dependencies` | 패키지/버전 관리 |
| `langchain-fundamentals` | create_agent, 툴, 미들웨어 기초 |
| `langgraph-fundamentals` | DeepAgents가 내부적으로 올라가는 LangGraph 기초 |

### 개발 프랙티스 — `obra/superpowers` (5개)

| 스킬 | 용도 |
|---|---|
| `systematic-debugging` | 버그/실패 재현 시, 고치기 전에 먼저 |
| `test-driven-development` | 기능/버그 구현 전 테스트부터 |
| `verification-before-completion` | 완료 주장 전 검증 명령 실행 + 증거 확인 (6일차 "완료 요청은 제안" 그대로) |
| `writing-plans` | 코드 건드리기 전 계획 작성 |
| `using-git-worktrees` | 격리된 작업공간이 필요할 때 |

두 소스 모두 `.claude/skills/`(Claude Code)와 `.gjc/skills/`(GJC)에 동일하게 들어가 있음.
`skills-lock.json`이 각 스킬의 출처(`source`)를 기록.

## 2. 왜 이렇게 됐는지 (설치 히스토리)

1. **1차 — 전체 설치.** 처음엔 `npx skills add langchain-ai/langchain-skills --skill '*' --yes`로 22개
   전부 설치. 이유: 과제(`task.md`)에 스킬 목록이 없었고, 참고하라고 지정된 course repo
   (`sds_ax_advanced_2026_2/README.md`)가 실제로 쓴 명령을 그대로 재현한 것.
2. **2차 — 14개 정리.** DeepAgents 프로젝트에 당장 안 쓰는 것(TS 퀵스타트 3종, `langchain-rag`,
   `langgraph-cli/persistence/human-in-the-loop`, `langchain-python-quickstart`/
   `langgraph-python-quickstart`(퀵스타트 중복), `langchain-middleware`, `eval-engineering`,
   `langsmith-online-eval-engineering`, `managed-deep-agents`, `swarm`)를 `npx skills remove`로 제거.
   → 핵심 8개만 남김.
3. **3차 — 외부 저장소 검토.** `sds_ax_advanced_2026_2/Day04/good_skill.md`(강사가 정리한 외부 Skill
   저장소 목록)를 참고해서 8개 저장소를 `npx skills add <repo> --list`로 미리보기만 하고 검토:

   | 저장소 | 확인 결과 | 결정 |
   |---|---|---|
   | `obra/superpowers` | 디버깅/TDD/검증/계획/worktree 등 14개. 6일차 수업(완료 Gate, 근거 기반 검증)과 내용이 거의 그대로 겹침 | ✅ 5개만 선별 설치 |
   | `mattpocock/skills` | TS 교육/글쓰기 콘텐츠 위주, 우리 프로젝트(Python)와 안 맞음 | ❌ 스킵 |
   | `garrytan/gbrain` | 개인 "세컨드 브레인"(음성노트·정체성 인터뷰) 도구, 코딩과 무관 | ❌ 스킵 |
   | `addyosmani/agent-skills` | 내용 좋으나 obra/superpowers와 상당 부분 중복(TDD 등), 메타 스킬 두 개를 동시에 깔면 충돌 우려 | ❌ 스킵 |
   | `fivetaku/insane-review` | ChatGPT Pro 웹 구독 필요 — 이 환경엔 없음 | ❌ 스킵 |
   | `fivetaku/insane-search` | 차단 사이트 우회 스크래핑, 지금 불필요 + 의존성 무거움 | ❌ 스킵 |
   | `garrytan/gstack` | 껍데기 라우터뿐, 실체 없음 | ❌ 스킵 |
   | `tt-a1i/archify` | 아키텍처/시퀀스 다이어그램 HTML 생성 | ❌ 스킵 (필요해지면) |
   | `browser-use/browser-use` | 브라우저 자동화. 이 프로젝트에 브라우저 tool이 필요한지 아직 불명확 | ❌ 스킵 (필요해지면) |

   `obra/superpowers`에서도 **`using-superpowers`(매 응답 전 스킬 사용을 강제하는 메타 스킬)와
   `brainstorming`(모든 창작 작업 전 강제)은 Claude Code의 기본 동작을 바꾸는 것이라 설치 안 함.**
   `dispatching-parallel-agents`/`subagent-driven-development`/`executing-plans`/
   `finishing-a-development-branch`/`receiving-code-review`/`requesting-code-review`/`writing-skills`는
   팀 협업·다세션 워크플로용이라 1인 프로젝트 지금 단계엔 과함 → 스킵.

## 3. 재설치 / 추가 설치 명령어

```bash
# 저장소에 어떤 스킬이 있는지 미리보기 (설치 안 함)
npx skills add <owner>/<repo> --list

# 특정 스킬만 설치 — comma로 묶으면 안 먹힘. -s를 스킬마다 반복해야 함
npx skills add <owner>/<repo> -s <skill1> -s <skill2> -a claude-code -y

# 저장소 전체 설치
npx skills add <owner>/<repo> --skill '*' --yes

# 제거 (공백으로 여러 개, --skill 불필요)
npx skills remove <skill1> <skill2> -y
```

**GJC 동기화 — 이 CLI는 GJC를 모른다. 설치 후 항상 `.gjc/skills/`에 수동으로 맞춰야 함:**

```bash
# 실제로 symlink인지 copy인지 먼저 확인
ls -la .claude/skills/<새 스킬 이름>

# symlink였으면 (langchain-ai/langchain-skills 계열이 이 방식):
ln -sfn "../../.agents/skills/<name>" ".gjc/skills/<name>"

# 실제 디렉토리(copy)였으면 (obra/superpowers 계열이 이 방식):
cp -r ".claude/skills/<name>" ".gjc/skills/<name>"
```

저장소마다 방식이 다르다 — `langchain-ai/langchain-skills`는 `.agents/skills/`에 실물을 두고
`.claude/skills/`에 symlink, `obra/superpowers`는 `.claude/skills/`에 바로 실물 복사.
설치 후 `ls -la`로 매번 확인할 것.

## 4. 참고

- 스킬은 `SKILL.md` 텍스트일 뿐이지만 **"full agent permissions"로 실행**된다 (CLI 자체 경고).
  설치 전 `--list`로 미리 보고, 낯선 저장소는 내용을 한번 읽어볼 것.
- 외부 저장소 후보 원본 목록: `sds_ax_advanced_2026_2/Day04/good_skill.md`
- 이번 프로젝트 스킬 선정 근거는 `CLAUDE.md`의 "스킬" 절에도 요약돼 있음.
