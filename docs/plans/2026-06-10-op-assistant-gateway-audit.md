# OP Assistant Gateway 整合盤點(2026-06-10)

> Sub-agent 全面研究 + 當日修復紀錄。目的:確認內部助理(小弟 LINE OA → Hermes op-assistant gateway)的工具、串接、工作流程完整性。

## 當日已處理

| 事項 | 結果 |
|---|---|
| Hermes 更新 | `cea87d913` → `b4170f3ac`(+1,634 commits),三 profile skill 同步,服務自動重啟 |
| 本地補丁 | openai SDK None-guard **存活**;`codex_runtime.py` 防禦補丁**過時移除**(上游重寫串流處理),PATCHES.md 已記錄 |
| **P0-1 圖片/檔案炸彈** | ✅ **已修**:`adapter.py:1338` 寫死 `MessageType.IMAGE`(上游已改名 `PHOTO`),6/3 起同仁傳圖/檔必 crash 且**留痕前就炸**(事件全漏)。改成完整型別對照(image→PHOTO、file→DOCUMENT、video/audio/sticker/location 各歸位、未知退回 TEXT)。`~/.hermes` 兩路徑實為 hardlink(不會漂移),Gary repo fork 已同步。重啟驗證:router 初始化、webhook 401、無錯誤 |
| 設定殘留 | ✅ 已從 profile `config.yaml` `plugins.enabled` 移除已退役的 `op-assistant-tools` |
| roadmap #7(kernel 留痕驗證) | ✅ **驗證通過**:events 125 筆(`op_assistant_line_inbound` 88),outbox 0 pending,flush 正常 |

## 架構現況(訊息全路徑)

```
小弟 LINE OA(內部員工群)
 → Tailscale Funnel(443 → 127.0.0.1:8646)
 → hermes-gateway-op-assistant.service
 → op-assistant-line plugin adapter
    ├ HMAC 簽章驗證(/line/webhook + legacy alias /wannavegtour/line/webhook)
    ├ ① 全量留痕 → outbox.sqlite → PostgreSQL op-assistant-kernel(:5434, events 表)
    ├ ② Python 喚醒過濾(小弟 / @小弟 / /小弟;沒喚醒 = 只留痕不回)
    ├ ③ LineRouter(Gary repo wannavegtour/line_router.py,全 Python 零 LLM):
    │    查空位→WooCommerce REST、歷史查詢、改價一律拒絕、HELP/UNCLEAR 固定文字
    │    回覆 reply token 優先,逾時 fallback Push API
    └ ④ LLM fallback 僅限三種故障情形(SOUL.md 規定只回固定故障訊息)
旁路:cron ×5(ETL/日結/週報/月維護/清理)→ 同一 kernel DB,全部 last_status=ok
```

模型:gpt-5.5 @ openai-codex。本地 gpt-oss:120b 切換 diff 在 `~/.hermes/proposed-changes/` **等批准 11 天**(卡在下面 P0-2)。

## 未解缺口(待 Gary 決定/後續處理)

1. **P0-2 Telegram 控制面斷頭**:webhook 從未註冊(`getWebhookInfo` url 空)、kernel `telegram_inbound` 0 筆、無 tunnel 到 8647;且 root gateway 用同一個 bot token 在 polling(互斥)→ 控制面永遠收不到訊息。模型切換提案因此卡死。**建議:開專用 bot token(BotFather)+ 控制面改 polling(免對外開洞)。等 Gary 給 token。**
2. **P1-3 每日摘要從未送達**:curate script 要的 `TELEGRAM_BOT_TOKEN`/`TELEGRAM_HOME_CHANNEL` 不在 op-assistant profile `.env`(只在 root)。解了 P0-2 之後補進去即可。
3. **P2 留痕未去識別**:`op_assistant_line_inbound` 存原文+原始 LINE user_id。內部員工群可接受,在此明文記載為**刻意決定**;若日後要餵知識管線,需先過 redact。
4. 無害殘跡(不急):`SOUL.md.bak-*`、`wc-api.json.bak-*`、`listener.log.final-*`、gateway_state.json stale entry。

## 健康基準(供日後比對)

- 三服務 active:`hermes-gateway-op-assistant` / `hermes-gateway` / `hermes-telegram-op-control`(後者 process 活但見 P0-2)。
- 最後一次確定性回覆:2026-06-03 09:49;LLM fallback 觸發:0 次(文字路由穩定)。
- 健檢順序見 memory `reference_op_bot_runtime`(webhook 401 = 正常)。
