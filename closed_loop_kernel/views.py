from __future__ import annotations

import json
from datetime import datetime
from html import escape

from .store import KernelStore


def render_events_view(store: KernelStore) -> str:
    lifecycle_rows = store.fetch_all(
        """
        SELECT attempt_id, state, metadata, created_at
        FROM attempt_lifecycle_events
        ORDER BY created_at
        """
    )
    event_rows = store.fetch_all(
        """
        SELECT id, event_type, payload, created_at
        FROM events
        ORDER BY created_at
        """
    )
    timeline_items = [_render_lifecycle_item(row) for row in lifecycle_rows]
    timeline_items.extend(_render_system_event_item(row) for row in event_rows)
    return _page(
        "事件紀錄",
        f"""
        <section class="summary-strip">
          <div><strong>{len(lifecycle_rows)}</strong><span>任務進度</span></div>
          <div><strong>{len(event_rows)}</strong><span>審核事件</span></div>
        </section>
        <section class="timeline">
          {"".join(timeline_items)}
        </section>
        """,
    )


def render_event_detail_view(store: KernelStore, attempt_id: str) -> str:
    attempt = store.fetch_one("SELECT * FROM attempts WHERE id = ?", [attempt_id])
    lifecycle = store.fetch_all(
        "SELECT state, created_at FROM attempt_lifecycle_events WHERE attempt_id = ? ORDER BY created_at",
        [attempt_id],
    )
    calls = store.fetch_all("SELECT tool_name, status, error_message FROM tool_calls WHERE attempt_id = ?", [attempt_id])
    timeline = "\n".join(
        f"""
        <article class="timeline-item">
          <div>
            <h2>{escape(_lifecycle_title(row['state']))}</h2>
            <p>{escape(_lifecycle_note(row['state']))}</p>
          </div>
          <time>{escape(_format_time(row['created_at']))}</time>
        </article>
        """
        for row in lifecycle
    )
    tool_items = "\n".join(
        f"<li>{escape(row['tool_name'])}: {escape(_status_label(row['status']))} {escape(row.get('error_message') or '')}</li>"
        for row in calls
    )
    if not tool_items:
        tool_items = "<li>這次 demo 沒有記錄工具呼叫細節。</li>"
    body = [
        f"""
        <section class="detail-header">
          <div>
            <h2>執行 {_short_id(attempt_id)}</h2>
            <p>這裡保留這次任務的時間線與最後結果，但不改寫原始失敗紀錄。</p>
          </div>
        </section>
        """,
        f"<section class=\"timeline\">{timeline}</section>",
    ]
    if attempt:
        body.append(
            f"""
            <section class="result-card">
              <h2>{escape(_attempt_status_title(attempt['status']))}</h2>
              <p>{escape(_attempt_status_note(attempt['status']))}</p>
            </section>
            """
        )
        if attempt.get("error_message"):
            body.append(
                f"""
                <section class="result-card error">
                  <h2>錯誤原因</h2>
                  <p>系統保留原始錯誤訊息，方便之後 replay 與修正。</p>
                  <pre>{escape(attempt.get('error_message') or '')}</pre>
                </section>
                """
            )
    body.append(f"<section class=\"result-card\"><h2>工具紀錄</h2><ul>{tool_items}</ul></section>")
    return _page("執行詳情", "\n".join(body))


def _render_lifecycle_item(row: dict[str, str]) -> str:
    title = _lifecycle_title(row["state"])
    note = _lifecycle_note(row["state"])
    run_label = f"執行 {_short_id(row['attempt_id'])}"
    href = f"/events/{escape(row['attempt_id'])}"
    return f"""
    <article class="timeline-item">
      <div>
        <h2>{escape(title)}</h2>
        <p>{escape(note)}</p>
      </div>
      <a class="run-link" href="{href}">{escape(run_label)}</a>
      <time>{escape(_format_time(row['created_at']))}</time>
    </article>
    """


def _render_system_event_item(row: dict[str, str]) -> str:
    payload = _loads(row.get("payload"))
    title, note = {
        "approval_required": ("等待審核", "修正案已通過 replay，正在等人類批准。"),
        "approval_granted": ("已批准", "人類審核者已批准這個修正案。"),
        "approval_rejected": ("已拒絕", "人類審核者拒絕了這個修正案。"),
        "candidate_applied": ("已套用", "修正案已套用，新版本已成為目前版本。"),
    }.get(row["event_type"], ("系統事件", row["event_type"].replace("_", " ")))
    candidate_id = payload.get("candidate_id")
    secondary = f"修正案 {_short_id(candidate_id)}" if candidate_id else f"事件 {_short_id(row['id'])}"
    return f"""
    <article class="timeline-item review">
      <div>
        <h2>{escape(title)}</h2>
        <p>{escape(note)}</p>
      </div>
      <span class="run-link">{escape(secondary)}</span>
      <time>{escape(_format_time(row['created_at']))}</time>
    </article>
    """


def render_improvements_view(store: KernelStore) -> str:
    candidates = store.fetch_all(
        """
        SELECT c.id, c.target_artifact_name, c.patch_type, c.status, f.failure_type
        FROM improvement_candidates c
        JOIN failures f ON f.id = c.failure_id
        ORDER BY c.created_at
        """
    )
    items = "\n".join(
        f"<tr><td>{escape(_short_id(row['id']))}</td><td>{escape(row['target_artifact_name'])}</td><td>{escape(_patch_label(row['patch_type']))}</td><td>{escape(row['failure_type'])}</td><td>{escape(_status_label(row['status']))}</td></tr>"
        for row in candidates
    )
    return _page(
        "修正案",
        f"""
        <table>
          <thead><tr><th>編號</th><th>目標</th><th>類型</th><th>錯誤</th><th>狀態</th></tr></thead>
          <tbody>{items}</tbody>
        </table>
        """,
    )


def render_approvals_view(store: KernelStore) -> str:
    candidates = store.fetch_all(
        """
        SELECT c.id, c.target_artifact_name, c.status,
               EXISTS (
                   SELECT 1 FROM replays r
                   WHERE r.candidate_id = c.id AND r.status = 'success'
               ) AS has_successful_replay
        FROM improvement_candidates c
        WHERE c.status IN ('draft', 'sandbox_verified')
        ORDER BY c.created_at
        """
    )
    cards = []
    if not candidates:
        return _page(
            "等待審核",
            """
            <section class="result-card">
              <h2>目前沒有待審核修正案</h2>
              <p>所有可審核的修正案都已處理，或還在等待 replay 通過。</p>
            </section>
            """,
        )
    for row in candidates:
        enabled = row["status"] == "sandbox_verified" and row["has_successful_replay"]
        if enabled:
            button = f"""
              <form method="post" action="/approvals/{escape(row['id'])}/approve">
                <button>批准並套用</button>
              </form>
              <form method="post" action="/approvals/{escape(row['id'])}/reject">
                <button class="secondary">拒絕</button>
              </form>
            """
        else:
            button = "<button disabled>先完成 replay</button>"
        cards.append(
            f"""
            <article>
              <h2>{escape(row['target_artifact_name'])}</h2>
              <p>修正案：{escape(_short_id(row['id']))}</p>
              <p>狀態：{escape(_status_label(row['status']))}</p>
              {button}
            </article>
            """
        )
    return _page("等待審核", "\n".join(cards))


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{escape(title)}</title>
  <style>
    body {{ background: #f7f8fb; font-family: system-ui, sans-serif; margin: 24px; color: #172026; }}
    h1 {{ margin-bottom: 18px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border-bottom: 1px solid #d8dee4; padding: 8px; text-align: left; }}
    article {{ border: 1px solid #d8dee4; border-radius: 8px; padding: 16px; margin-bottom: 12px; }}
    .summary-strip {{ display: flex; gap: 12px; margin-bottom: 18px; }}
    .summary-strip div {{ background: #fff; border: 1px solid #d8dee4; border-radius: 8px; padding: 12px 14px; min-width: 128px; }}
    .summary-strip strong {{ display: block; font-size: 22px; }}
    .summary-strip span {{ color: #5f6b7a; font-size: 13px; }}
    .timeline {{ display: grid; gap: 10px; max-width: 980px; }}
    .timeline-item {{ align-items: center; background: #fff; display: grid; gap: 16px; grid-template-columns: minmax(0, 1fr) auto auto; }}
    .timeline-item h2 {{ font-size: 17px; margin: 0 0 4px; }}
    .timeline-item p {{ color: #4b5563; margin: 0; }}
    .timeline-item.review {{ border-color: #8ab4f8; }}
    .detail-header, .result-card {{ background: #fff; border: 1px solid #d8dee4; border-radius: 8px; margin-bottom: 14px; padding: 16px; max-width: 980px; }}
    .detail-header h2, .result-card h2 {{ font-size: 18px; margin: 0 0 6px; }}
    .detail-header p, .result-card p {{ color: #4b5563; margin: 0; }}
    .result-card.error {{ border-color: #f2a3a3; }}
    .run-link {{ color: #0b57d0; font-weight: 650; text-decoration: none; white-space: nowrap; }}
    time {{ color: #5f6b7a; font-size: 13px; white-space: nowrap; }}
    button {{ padding: 8px 12px; }}
    form {{ display: inline-block; margin-right: 8px; }}
    button.secondary {{ background: #fff; border: 1px solid #b8c0cc; }}
    button[disabled] {{ color: #687078; }}
    pre {{ background: #f6f8fa; padding: 12px; overflow: auto; }}
  </style>
</head>
<body>
  <h1>{escape(title)}</h1>
  {body}
</body>
</html>"""


def _short_id(value: str | None) -> str:
    return (value or "unknown")[:8]


def _loads(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _format_time(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def _status_label(value: str) -> str:
    return {
        "success": "成功",
        "failed": "失敗",
        "draft": "草稿",
        "sandbox_verified": "已通過 replay",
        "approved": "已批准",
        "rejected": "已拒絕",
        "applied": "已套用",
    }.get(value, value)


def _patch_label(value: str) -> str:
    return {
        "code_patch": "程式修正",
        "prompt_update": "Prompt 修正",
        "db_migration": "資料庫修正",
    }.get(value, value)


def _lifecycle_title(value: str) -> str:
    return {
        "started": "任務開始",
        "running": "執行中",
        "finished": "任務完成",
    }.get(value, "任務更新")


def _lifecycle_note(value: str) -> str:
    return {
        "started": "系統已建立這次執行紀錄，開始追蹤。",
        "running": "工具或 agent 正在處理，細節先暫存在執行脈絡中。",
        "finished": "結果已一次寫入；舊的失敗紀錄不會被改寫。",
    }.get(value, "這次執行的狀態有更新。")


def _attempt_status_title(value: str) -> str:
    return {
        "success": "執行成功",
        "failed": "執行失敗",
    }.get(value, value)


def _attempt_status_note(value: str) -> str:
    return {
        "success": "這次任務已產生成功結果。",
        "failed": "這次任務失敗了；失敗紀錄會保留下來，後續修正會用 replay 證明。",
    }.get(value, "")
