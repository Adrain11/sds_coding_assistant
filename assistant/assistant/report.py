"""`python -m assistant.report` — read-only CLI over `runs/*/events.jsonl`.

Evidence for DC3 (timeline + total duration), DC4 (failure lookup with
context), DC7 (retry count — see D2b's `attempt` field), and DC8
(hierarchical trace view, 4-4's "Trace" wording — 검토 G5).

`stats` is a thin wrapper around the same `_collect_metrics()` that `show`'s
footer already calls (D7: "하단 지표는 `_collect_metrics(run)` 하나로 계산하고
`show`에 항상 붙인다... `stats`는 같은 함수를 부르는 얇은 래퍼로 남긴다").

Never imported by `assistant/observability.py` or `agent.py` — this module
only reads what the middleware already wrote, on a separate process
(`python -m assistant.report ...`), never inside the TUI (D5 does not apply
here, but there is no reason to import this into the agent process either).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from assistant.events import (
    CODE_CHANGED,
    GATE_BLOCK,
    IMPROVE_END,
    IMPROVE_VERIFIED,
    MEMORY_HIT,
    PLAN_APPROVED,
    PLAN_CREATED,
    PLAN_REVIEWED,
    iter_events,
    resolve_project_dir,
)

_CONTEXT_LINES = 3
"""How many preceding events `fail` shows before each failure (T6)."""


def _load_events(runs_dir: Path, run_id: str) -> list[dict[str, Any]]:
    return list(iter_events(runs_dir / run_id / "events.jsonl"))


def _collect_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate the 4-3 indicators from one run's events.

    Returns:
        model_calls: number of model-call attempts (each `model_start`).
        tool_calls: number of completed tool calls.
        retries: number of attempts beyond the first for any model call
            (D2b's `attempt` field; `attempt=2` already means one retry).
        errors: number of `status="error"` events.
        blocks: number of `gate_block` events (Step 3 — 2-4/4-2 evidence).
        total_dur_ms: the run's own `run_end.dur_ms`, or `None` if the run
            never closed (T4-u/T8 — "미종료", not a crash).
        input_tokens / output_tokens: summed across `model_end` events.
    """
    model_starts = [e for e in events if e["type"] == "model_start"]
    model_ends = [e for e in events if e["type"] == "model_end"]
    tool_ends = [e for e in events if e["type"] == "tool_end"]
    run_end = next((e for e in events if e["type"] == "run_end"), None)

    retries = sum(1 for e in model_starts if (e.get("attempt") or 1) >= 2)
    errors = sum(1 for e in events if e.get("status") == "error")
    blocks = sum(1 for e in events if e["type"] == GATE_BLOCK)
    input_tokens = sum(
        (e.get("data") or {}).get("input_tokens") or 0 for e in model_ends
    )
    output_tokens = sum(
        (e.get("data") or {}).get("output_tokens") or 0 for e in model_ends
    )

    return {
        "model_calls": len(model_starts),
        "tool_calls": len(tool_ends),
        "retries": retries,
        "errors": errors,
        "blocks": blocks,
        "total_dur_ms": run_end.get("dur_ms") if run_end is not None else None,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def _format_metrics_line(metrics: dict[str, Any]) -> str:
    total_s = (
        f"{metrics['total_dur_ms'] / 1000:.1f}s"
        if metrics["total_dur_ms"] is not None
        else "미종료"
    )
    # "모델 N회(시도)" — `model_calls` counts attempts, not logical calls
    # (검토 R-B): spelling that out here keeps it from being misread as
    # 4-3's separate "재시도 횟수" figure right next to it.
    return (
        f"지표  모델 {metrics['model_calls']}회(시도) · "
        f"도구 {metrics['tool_calls']}회 · "
        f"재시도 {metrics['retries']}회 · 차단 {metrics['blocks']}회 · 총 {total_s} · "
        f"토큰 in {metrics['input_tokens']} / out {metrics['output_tokens']}"
    )


class _Row:
    """One collapsed line of the trace view: a model-call or tool-call pair."""

    __slots__ = ("detail", "dur_ms", "is_error", "label")

    def __init__(
        self, label: str, dur_ms: float | None, detail: str, *, is_error: bool
    ) -> None:
        self.label = label
        self.dur_ms = dur_ms
        self.detail = detail
        self.is_error = is_error


def _build_rows(events: list[dict[str, Any]]) -> list[_Row]:
    """Collapse start/end event pairs into one display row each (DC8).

    `model_start`+`model_end`/`model_error` become one `model_call #N` row;
    `tool_start`+`tool_end` become one `tool <name>` row. Rows appear in the
    order their *closing* event was recorded, matching how the events were
    actually observed to complete.

    `#N` numbers *logical* calls, not attempts (검토 R-B): `model_start`
    fires once per retry attempt (D2b), so incrementing on every one of
    them made a single retried call read as several distinct calls
    (`#1`, `#2 attempt=2`, `#3 attempt=3`). Only the first attempt of a
    call advances the counter; later attempts keep its number and add
    `attempt=N`, matching `STEP2_PLAN.md` §5 D7's example output.
    """
    rows: list[_Row] = []
    model_call_number = 0
    for event in events:
        event_type = event["type"]
        if event_type == "model_start":
            if (event.get("attempt") or 1) == 1:
                model_call_number += 1
            continue
        if event_type in ("model_end", "model_error"):
            attempt = event.get("attempt")
            label = f"model_call #{model_call_number}"
            if attempt and attempt >= 2:  # noqa: PLR2004 - "attempt 1" is not worth flagging
                label += f"  attempt={attempt}"
            if event_type == "model_end":
                data = event.get("data") or {}
                detail = (
                    f"in={data.get('input_tokens')} out={data.get('output_tokens')}"
                )
                is_error = False
            else:
                detail = event.get("error", "")
                is_error = True
            rows.append(_Row(label, event.get("dur_ms"), detail, is_error=is_error))
        elif event_type == "tool_end":
            name = event.get("name", "?")
            is_error = event.get("status") == "error"
            detail = event.get("error", "") if is_error else "ok"
            rows.append(
                _Row(f"tool  {name}", event.get("dur_ms"), detail, is_error=is_error)
            )
        elif event_type in (PLAN_CREATED, PLAN_REVIEWED, PLAN_APPROVED, CODE_CHANGED):
            rows.append(_Row(*_plan_lifecycle_row(event_type, event), is_error=False))
        elif event_type == MEMORY_HIT:
            data = event.get("data") or {}
            rows.append(
                _Row(
                    f"memory_hit  {event.get('name', '?')}",
                    None,
                    f"refs={data.get('refs', [])}",
                    is_error=False,
                )
            )
        elif event_type == IMPROVE_END:
            data = event.get("data") or {}
            is_error = data.get("status") == "error"
            target = data.get("target_path", "?")
            detail = data.get("error") if is_error else f"target={target}"
            rows.append(
                _Row(
                    f"improve_end  {event.get('name', '?')}",
                    None,
                    detail or "",
                    is_error=is_error,
                )
            )
        elif event_type == IMPROVE_VERIFIED:
            data = event.get("data") or {}
            improved = bool(data.get("improved"))
            detail = f"before={data.get('before')} after={data.get('after')}"
            rows.append(
                _Row(
                    f"improve_verified  {event.get('name', '?')}",
                    None,
                    detail,
                    is_error=not improved,
                )
            )
        elif event_type == GATE_BLOCK:
            data = event.get("data") or {}
            rows.append(
                _Row(
                    f"gate_block  {event.get('name', '?')}",
                    None,
                    data.get("reason", ""),
                    is_error=True,
                )
            )
    return rows


def _plan_lifecycle_row(
    event_type: str, event: dict[str, Any]
) -> tuple[str, float | None, str]:
    """Build the (label, dur_ms, detail) triple for one plan-lifecycle event.

    Step 3, DC9/EC9 — `plan_created`/`plan_reviewed`/`plan_approved`/
    `code_changed` each get their own single-line row, in file order.
    """
    data = event.get("data") or {}
    plan_id = data.get("plan_id")
    if event_type == PLAN_CREATED:
        return f"plan   created  {event.get('name', '?')}", None, plan_id or "-"
    if event_type == PLAN_REVIEWED:
        return f"plan   reviewed {event.get('name', '?')}", None, plan_id or "-"
    if event_type == PLAN_APPROVED:
        return f"plan   approved {event.get('name', '?')}", None, plan_id or "-"
    # CODE_CHANGED
    return f"code_changed  {event.get('name', '?')}", event.get("dur_ms"), "-"


def _render_trace(
    run_id: str, events: list[dict[str, Any]], metrics: dict[str, Any]
) -> str:
    total_s = (
        f"{metrics['total_dur_ms'] / 1000:.1f}s"
        if metrics["total_dur_ms"] is not None
        else "미종료"
    )
    lines = [f"run {run_id}   ({total_s}, 실패 {metrics['errors']})"]

    rows = _build_rows(events)
    for i, row in enumerate(rows):
        branch = "└─" if i == len(rows) - 1 else "├─"
        dur_s = f"{row.dur_ms / 1000:.1f}s" if row.dur_ms is not None else "  -"
        status = "ERROR  " if row.is_error else ""
        lines.append(f"{branch} {row.label:<24} {dur_s:>6}   {status}{row.detail}")

    lines.append("")
    lines.append(_format_metrics_line(metrics))
    return "\n".join(lines)


def cmd_list(runs_dir: Path) -> int:
    """List every run under `runs_dir`, newest first."""
    if not runs_dir.exists():
        print("(no runs yet)")
        return 0

    run_dirs = sorted((p for p in runs_dir.iterdir() if p.is_dir()), reverse=True)
    if not run_dirs:
        print("(no runs yet)")
        return 0

    for run_dir in run_dirs:
        events = list(iter_events(run_dir / "events.jsonl"))
        if not events:
            continue
        metrics = _collect_metrics(events)
        run_end = next((e for e in events if e["type"] == "run_end"), None)
        status = run_end.get("status", "ok") if run_end is not None else "미종료"
        total_s = (
            f"{metrics['total_dur_ms'] / 1000:.1f}s"
            if metrics["total_dur_ms"] is not None
            else "-"
        )
        print(f"{run_dir.name}  {status:<12} {total_s:>7}  실패 {metrics['errors']}")
    return 0


def cmd_show(run_id: str, runs_dir: Path) -> int:
    """Print the hierarchical trace + metrics footer for one run (DC3, DC8)."""
    events = _load_events(runs_dir, run_id)
    if not events:
        print(f"run {run_id}: 이벤트를 찾을 수 없음 (runs_dir={runs_dir})")
        return 1
    metrics = _collect_metrics(events)
    print(_render_trace(run_id, events, metrics))
    return 0


def cmd_fail(run_id: str, runs_dir: Path) -> int:
    """Print each failure with its preceding context (DC4, T6)."""
    events = _load_events(runs_dir, run_id)
    if not events:
        print(f"run {run_id}: 이벤트를 찾을 수 없음 (runs_dir={runs_dir})")
        return 1

    failure_indices = [i for i, e in enumerate(events) if e.get("status") == "error"]
    if not failure_indices:
        print(f"run {run_id}: 실패한 이벤트 없음")
        return 0

    for idx in failure_indices:
        failure = events[idx]
        start = max(0, idx - _CONTEXT_LINES)
        name = failure.get("name", "-")
        print(f"--- seq={failure.get('seq')} {failure['type']} ({name}) ---")
        for e in events[start : idx + 1]:
            marker = ">>" if e is failure else "  "
            print(
                f"{marker} seq={e.get('seq', '?'):<4} {e['type']:<12} "
                f"{e.get('name', '-'):<15} status={e.get('status', '-')}"
            )
        if failure.get("error"):
            print(f"    error: {failure['error']}")
        print()
    return 0


def cmd_stats(run_id: str, runs_dir: Path) -> int:
    """Print the same metrics `show`'s footer computes, on their own (D7)."""
    events = _load_events(runs_dir, run_id)
    if not events:
        print(f"run {run_id}: 이벤트를 찾을 수 없음 (runs_dir={runs_dir})")
        return 1
    print(_format_metrics_line(_collect_metrics(events)))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m assistant.report")
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=None,
        help="Defaults to the project root's runs/",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List all runs, newest first")
    show_parser = sub.add_parser(
        "show", help="Timeline + metrics for one run (DC3, DC8)"
    )
    show_parser.add_argument("run_id")
    fail_parser = sub.add_parser("fail", help="Failures with context for one run (DC4)")
    fail_parser.add_argument("run_id")
    stats_parser = sub.add_parser("stats", help="Just the metrics line for one run")
    stats_parser.add_argument("run_id")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for `python -m assistant.report`.

    Args:
        argv: Command-line arguments, or `None` to use `sys.argv` (argparse's
            default).

    Returns:
        The invoked subcommand's exit code.
    """
    args = _build_parser().parse_args(argv)
    runs_dir = (
        args.runs_dir if args.runs_dir is not None else resolve_project_dir() / "runs"
    )

    if args.command == "list":
        return cmd_list(runs_dir)
    if args.command == "show":
        return cmd_show(args.run_id, runs_dir)
    if args.command == "fail":
        return cmd_fail(args.run_id, runs_dir)
    if args.command == "stats":
        return cmd_stats(args.run_id, runs_dir)
    return 1  # argparse's `required=True` makes this unreachable


if __name__ == "__main__":
    sys.exit(main())
