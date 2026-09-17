# 단계 2 결과 — 이벤트 로거

**완료** 2026.09.17 · 담당 🟢구현

## 완료 조건 (DC1~DC8)

| | 결과 | 근거 |
|---|---|---|
| DC1 | ✅ TUI 실측(👤사람) | INBOX "TUI 실측 결과" |
| DC2 | ✅ TUI 실측(👤사람) — run_start~run_end 전부 확인 | 〃 |
| DC3 | ✅ `report show` 타임라인+총 소요 | `assistant/report.py::cmd_show` + `tests/test_report.py` |
| DC4 | ✅ `report fail` — 실패 + 직전 3개 맥락 | `cmd_fail` + 테스트 |
| DC5 | ✅ TUI 실측(👤사람) — `runs/` 읽기전용·생성불가 둘 다 정상 동작 | INBOX |
| DC6 | ✅ TUI 실측(👤사람) — 로거 출력 미섞임 | INBOX |
| DC7 | ✅ **1차 증거는 단위 테스트** `test_retry_logging_produces_one_pair_per_attempt` (실물 `CodeModelRetryMiddleware` 스택, 3쌍 확인) | `tests/test_observability.py` |
| DC8 | ✅ `report show`의 계층형 trace(`├─`/`└─`) | `cmd_show`/`_render_trace` |

## 실패·시행착오 (숨기지 않고 기록)

1. **`os.mkdir`/`os.getcwd` 블로킹(S11)** — dcode 서버(Blockbuster)가 이벤트 루프 스레드의 동기 blocking I/O에 예외를 던진다. 최초 설계(요청마다 새 `EventWriter`, 생성 시 직접 `mkdir`)는 헤드리스 실행에서 매번 조용히 실패해 로그가 아예 안 남았다. → 파일 I/O를 전용 백그라운드 스레드로 옮김.
2. **`contextvars.ContextVar`가 훅 사이에서 안 이어짐(S12)** — 검토가 제안한 "현재 run을 ContextVar로" 설계는 `before_agent`와 이후 `wrap_tool_call`/`after_agent` 사이에서 값이 사라졌다(서버가 훅마다 별도 task/context를 씀). 헤드리스 실행에 트레이스를 심어 확인. → `thread_id` 키 방식의 `dict`로 교체.
3. **서버 프로세스의 cwd가 저장소 루트가 아님(S13)** — `Path.cwd()`가 `/tmp/deepagents_server_<id>/`를 가리켰다. → `deepagents_code.project_utils.get_server_project_context()`로 교체.
4. **`id(request)`로 재시도 attempt를 세던 것(검토 P3)** — 최종 실패 시 dict 항목이 안 지워지고, `id()` 재사용 가능성이 있었다. → `thread_id` 키 + 턴 경계(`before_agent`)에서 리셋으로 교체.
5. **`flush()`를 만들어놓고 비정상 종료 경로가 안 덮임(검토 P2)** — `after_agent`의 `flush()`는 정상 종료만 커버. → `EventWriter.__init__`에 `atexit.register(self.flush)` 추가.

1·2·3은 계획서·리뷰 어느 쪽도 실제 서버 실행 없이는 발견하지 못했던 것들이다 (`docs/plan/STEP2_PLAN.md` §0 S11~S13, `docs/plan/INBOX.md` 09-17 🟢구현 항목).

## 테스트

`uv run --project libs/code pytest tests/` — 40개 전부 통과 (T1·T1b·T2·T3-u·T4-u·T11-u 포함, `test_report.py` 10개).

## 다음 단계

단계 3(계획 게이트)은 이 로거의 `gate_block` 타입(예약됨, `assistant/events.py`) 위에 올라간다.
