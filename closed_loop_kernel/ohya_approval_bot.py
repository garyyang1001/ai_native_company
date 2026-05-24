"""
OhyaApprovalBot — Telegram 批准 bot 中介。

職責：
  1. 監聽 ohya_kernel events 表的 `approval_required` 事件
  2. 推 Telegram 訊息給 Gary（含 inline button: 批准 / 拒絕）
  3. 長輪詢（long poll）抓 Gary 的 callback
  4. 寫回 ohya_kernel `approvals` 表 + 標 candidate 狀態

依賴：只用 Python 標準函式庫（urllib + json），不引入額外 framework。

Telegram token 來源：
  從 `HermesRuntime/clients/skimm3r918_bot/profiles/skimm3r918_bot/.env`
  讀 `TELEGRAM_BOT_TOKEN`。**永遠不在 log / stdout 印 token 實值。**

執行：
  KERNEL_DATABASE_URL=postgresql:///ohya_kernel \\
  python3 -m closed_loop_kernel.ohya_approval_bot
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .store import KernelStore, json_param


DEFAULT_ENV_PATH = Path(
    "/Volumes/Hermes System/HermesArchive/HermesRuntime/clients/skimm3r918_bot/profiles/skimm3r918_bot/.env"
)
TELEGRAM_API_BASE = "https://api.telegram.org/bot"
APPROVAL_REQUEST_EVENT = "approval_required"
APPROVAL_DISPATCHED_EVENT = "ohya_telegram_approval_dispatched"
APPROVAL_RECEIVED_EVENT = "ohya_telegram_approval_received"

# callback_data 結構：`appr:<candidate_id>:<approve|reject>`
CALLBACK_PREFIX = "appr"


class TelegramError(Exception):
    pass


def load_env(path: Path = DEFAULT_ENV_PATH) -> dict[str, str]:
    """讀 .env 檔。**不在 log 或 stdout 印出 value。**"""
    if not path.exists():
        raise FileNotFoundError(f".env not found: {path}")
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


class OhyaApprovalBot:
    def __init__(self, bot_token: str, kernel_url: str, chat_id: int | None = None):
        if not bot_token:
            raise ValueError("bot_token is required")
        self._token = bot_token
        self.kernel_url = kernel_url
        self.chat_id = chat_id

    # ────────────────── Telegram HTTP API（最小集） ──────────────────
    def _telegram(self, method: str, params: dict | None = None, timeout: int = 30) -> dict:
        url = f"{TELEGRAM_API_BASE}{self._token}/{method}"
        data = urllib.parse.urlencode(params or {}).encode("utf-8") if params else None
        req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise TelegramError(f"{method} failed: {exc}") from exc
        if not payload.get("ok"):
            raise TelegramError(f"{method} error: {payload.get('description')}")
        return payload["result"]

    def get_me(self) -> dict:
        """測 token 有效。"""
        return self._telegram("getMe")

    def get_updates(self, offset: int | None = None, timeout_seconds: int = 10) -> list[dict]:
        params: dict = {"timeout": timeout_seconds}
        if offset is not None:
            params["offset"] = offset
        return self._telegram("getUpdates", params, timeout=timeout_seconds + 5)

    def send_message(self, chat_id: int, text: str, inline_keyboard: list[list[dict]] | None = None) -> dict:
        # 不使用 parse_mode — Telegram MarkdownV2 對中文 / emoji / 程式碼片段 escape 規則嚴格，
        # 純文字 + emoji 既穩定又夠用；未來要顯示程式碼差異再考慮 HTML mode。
        params: dict = {"chat_id": chat_id, "text": text}
        if inline_keyboard:
            params["reply_markup"] = json.dumps({"inline_keyboard": inline_keyboard})
        return self._telegram("sendMessage", params)

    def answer_callback(self, callback_query_id: str, text: str = "") -> None:
        self._telegram("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text})

    # ────────────────── 高層業務邏輯 ──────────────────
    def discover_chat_id(self, prompt_message: str | None = None) -> int | None:
        """
        從 getUpdates 抓任何使用者最近送來的 message，取出 chat_id。
        用於 first-run：Gary 對 bot 講一聲就能拿到 ID。
        """
        updates = self.get_updates(timeout_seconds=2)
        for u in updates:
            msg = u.get("message")
            if msg and msg.get("chat"):
                return int(msg["chat"]["id"])
        return None

    def dispatch_pending_approvals(self, store: KernelStore) -> int:
        """
        掃描 ohya_kernel events，找 `approval_required` 但尚未派 Telegram 的，推給 Gary。
        回傳這次派出去的張數。
        """
        if not self.chat_id:
            raise RuntimeError("chat_id not set — run discover_chat_id() first or pass via constructor")

        # 找尚未派發的（用 ohya_telegram_approval_dispatched 事件去重）
        rows = store.fetch_all(
            """
            SELECT e.id, e.payload, e.created_at
            FROM events e
            WHERE e.event_type = ?
              AND NOT EXISTS (
                  SELECT 1 FROM events d
                  WHERE d.event_type = ?
                    AND d.payload::jsonb ->> 'source_event_id' = e.id::text
              )
            ORDER BY e.created_at ASC
            """,
            [APPROVAL_REQUEST_EVENT, APPROVAL_DISPATCHED_EVENT],
        )

        dispatched = 0
        for row in rows:
            payload = _parse_json(row["payload"])
            candidate_id = payload.get("candidate_id")
            if not candidate_id:
                continue
            candidate = store.fetch_one(
                "SELECT id, target_artifact_name, patch_type, proposed_content FROM improvement_candidates WHERE id = ?",
                [candidate_id],
            )
            if not candidate:
                continue
            text = self._format_approval_message(candidate)
            keyboard = [[
                {"text": "✅ 批准", "callback_data": f"{CALLBACK_PREFIX}:{candidate_id}:approve"},
                {"text": "❌ 拒絕", "callback_data": f"{CALLBACK_PREFIX}:{candidate_id}:reject"},
            ]]
            try:
                msg = self.send_message(self.chat_id, text, inline_keyboard=keyboard)
            except TelegramError as exc:
                # 推送失敗只記事件、不寫派發紀錄（下次重試）
                self._record_event(store, "ohya_telegram_dispatch_failed", {
                    "candidate_id": candidate_id, "source_event_id": row["id"], "error": str(exc),
                })
                continue
            self._record_event(store, APPROVAL_DISPATCHED_EVENT, {
                "candidate_id": candidate_id,
                "source_event_id": row["id"],
                "telegram_message_id": msg.get("message_id"),
                "chat_id": self.chat_id,
            })
            dispatched += 1
        return dispatched

    def poll_and_record_callbacks(self, store: KernelStore, timeout_seconds: int = 60) -> int:
        """
        Long-poll Telegram getUpdates，收 callback_query，寫進 ohya_kernel approvals 表。
        timeout_seconds 是單次 getUpdates 的等候上限；正常會在收到第一筆 callback 後返回。
        回傳本次處理的 callback 筆數。
        """
        # 從 events 找上次處理過的 update_id
        last_row = store.fetch_one(
            "SELECT payload FROM events WHERE event_type = ? ORDER BY created_at DESC LIMIT 1",
            [APPROVAL_RECEIVED_EVENT],
        )
        last_update_id = 0
        if last_row:
            last_update_id = int(_parse_json(last_row["payload"]).get("update_id", 0))
        offset = last_update_id + 1 if last_update_id else None

        updates = self.get_updates(offset=offset, timeout_seconds=timeout_seconds)
        processed = 0
        for u in updates:
            cb = u.get("callback_query")
            if not cb:
                continue
            data = cb.get("data", "")
            parts = data.split(":")
            if len(parts) != 3 or parts[0] != CALLBACK_PREFIX:
                continue
            _, candidate_id, action = parts
            if action not in ("approve", "reject"):
                continue
            try:
                self._apply_decision(store, candidate_id, action, cb)
                self.answer_callback(cb["id"], f"已記錄：{action}")
                self._record_event(store, APPROVAL_RECEIVED_EVENT, {
                    "candidate_id": candidate_id, "action": action,
                    "update_id": u["update_id"], "from_user_id": cb["from"]["id"],
                })
                processed += 1
            except Exception as exc:
                self.answer_callback(cb["id"], f"處理失敗：{exc}")
        return processed

    # ────────────────── helpers ──────────────────
    def _apply_decision(self, store: KernelStore, candidate_id: str, action: str, cb: dict) -> None:
        decision = "approved" if action == "approve" else "rejected"
        from_user = cb.get("from", {})
        approver = f"telegram:{from_user.get('username') or from_user.get('id')}"
        with store.transaction() as conn:
            conn.execute(
                """
                INSERT INTO approvals (id, candidate_id, approved_by, decision, comments, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    str(uuid.uuid4()),
                    candidate_id,
                    approver,
                    decision,
                    f"via Telegram inline button (update {cb.get('id')})",
                    _now(),
                ],
            )
            if decision == "rejected":
                conn.execute("UPDATE improvement_candidates SET status = 'rejected' WHERE id = ?", [candidate_id])

    def _format_approval_message(self, candidate: dict) -> str:
        """
        白話為主、技術詞 / 程式引用放括弧的訊息格式。
        非技術人也能讀懂「發生什麼事、要改什麼、改了會怎樣」。
        """
        short_id = candidate["id"][:8]
        patch_type = candidate.get("patch_type") or "unknown"
        target = candidate.get("target_artifact_name") or "(no target)"
        assertions = _parse_json(candidate.get("validation_assertions"))
        failure_type = assertions.get("source_failure_type") or "unknown"
        summary = assertions.get("summary") or "（無摘要）"
        target_hint = assertions.get("target_hint") or target

        patch_type_label = {
            "code_patch": "程式修正",
            "sql_patch": "SQL 修正",
            "prompt_update": "Prompt 修正（業務語氣）",
        }.get(patch_type, patch_type)

        failure_label = {
            "crash": "agent 程式崩潰",
            "timeout": "agent 執行超時",
            "spawn_failed": "agent 啟動失敗",
            "gave_up": "agent 連續失敗放棄",
            "failed": "agent 一般失敗",
        }.get(failure_type, failure_type)

        # 從 candidate 找對應的 replay 資訊（sandbox 跑過的測試結果）
        replay_summary = self._summarize_replay(candidate["id"])

        return (
            "🛠 OHYA 自我修復 — 待你批准\n"
            "━━━━━━━━━━━━━━\n"
            "【發生了什麼】\n"
            f"   {failure_label}\n\n"
            "【建議怎麼修】\n"
            f"   {summary}\n\n"
            f"【已自動驗證】\n{replay_summary}\n\n"
            "【會改哪個檔案 / 設定】\n"
            f"   {target_hint}\n"
            f"   修正類型：{patch_type_label}\n\n"
            "【批准後會發生什麼】\n"
            "   舊版本下架、新版本上架（version + 1）\n"
            "   舊版仍保留在資料庫供回溯（append-only）\n\n"
            "━━━━━━━━━━━━━━\n"
            f"案件編號：{short_id}\n"
            f"目標 artifact：{target}"
        )

    def _summarize_replay(self, candidate_id: str) -> str:
        from .store import KernelStore  # avoid top-level circular
        # 用 self 的 kernel_url 開一個短暫連線取 replay 資訊
        store = KernelStore.from_url(self.kernel_url)
        try:
            replay = store.fetch_one(
                "SELECT status, validation_results FROM replays WHERE candidate_id = ? ORDER BY created_at DESC LIMIT 1",
                [candidate_id],
            )
        finally:
            store.close()
        if not replay:
            return "   ⚠️ 尚未跑過 sandbox 驗證"
        status_icon = "✅" if replay["status"] == "success" else "❌"
        results = _parse_json(replay["validation_results"])
        # 嘗試從 result 抓「跑了幾次嘗試」之類的具體數字
        details = results.get("result") if isinstance(results.get("result"), dict) else {}
        attempts = details.get("attempts_taken")
        final = details.get("final_result")
        lines = [f"   {status_icon} 在隔離沙盒裡真實跑過候選程式碼"]
        if attempts is not None:
            lines.append(f"   ✅ 模擬連續失敗後第 {attempts} 次成功（attempts_taken={attempts}）")
        if isinstance(final, dict):
            lines.append(f"   ✅ 最終回傳：{final}")
        return "\n".join(lines)

    def _record_event(self, store: KernelStore, event_type: str, payload: dict) -> None:
        store.execute(
            "INSERT INTO events (id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
            [str(uuid.uuid4()), event_type, json_param(payload), _now()],
        )


def _parse_json(value) -> dict:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ────────────────── CLI entry ──────────────────
def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="OHYA approval bot — bridges ohya_kernel ↔ Telegram")
    parser.add_argument("--env", default=str(DEFAULT_ENV_PATH), help=".env path containing TELEGRAM_BOT_TOKEN")
    parser.add_argument("--mode", default="dispatch-and-poll", choices=["whoami", "discover", "dispatch", "poll", "dispatch-and-poll"])
    parser.add_argument("--chat-id", type=int, default=None, help="Override chat_id; if not given, will try discover")
    parser.add_argument("--poll-seconds", type=int, default=60, help="long-poll timeout per getUpdates")
    args = parser.parse_args()

    env = load_env(Path(args.env))
    token = env.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not found in .env")

    bot = OhyaApprovalBot(bot_token=token, kernel_url=_database_url(), chat_id=args.chat_id)

    if args.mode == "whoami":
        me = bot.get_me()
        print(json.dumps({"id": me.get("id"), "username": me.get("username"), "first_name": me.get("first_name")}, ensure_ascii=False, indent=2))
        return

    if args.mode == "discover":
        cid = bot.discover_chat_id()
        if cid is None:
            print("no recent message — please send any message to the bot first, then re-run")
        else:
            print(json.dumps({"chat_id": cid}))
        return

    store = KernelStore.from_url(_database_url())
    try:
        if args.mode in ("dispatch", "dispatch-and-poll"):
            if not bot.chat_id:
                bot.chat_id = bot.discover_chat_id()
                if not bot.chat_id:
                    raise RuntimeError("no chat_id — pass --chat-id or have Gary message the bot first")
            n = bot.dispatch_pending_approvals(store)
            print(f"dispatched {n} approval request(s) to Telegram chat {bot.chat_id}")
        if args.mode in ("poll", "dispatch-and-poll"):
            n = bot.poll_and_record_callbacks(store, timeout_seconds=args.poll_seconds)
            print(f"processed {n} callback(s)")
    finally:
        store.close()


def _database_url() -> str:
    url = os.environ.get("KERNEL_DATABASE_URL")
    if not url:
        raise RuntimeError("KERNEL_DATABASE_URL is required")
    return url


if __name__ == "__main__":
    _main()
