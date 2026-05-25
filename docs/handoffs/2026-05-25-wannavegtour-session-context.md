# Session Context: 2026-05-25 wannavegtour OP Bot Architectural Discussion

Date: 2026-05-25 (續日 — Mac mini → NVIDIA DGX Spark `spark-8035` 遷移當天)
Companion to: `docs/handoffs/2026-05-25-wannavegtour-op-bot-handoff.md`

## Purpose

Handoff doc 講「怎麼搬」，這份 context doc 講「為什麼架構長這樣 + 接下來該想什麼」。
新機器 / 新 session 從這裡接手不會漏掉今天討論過的決策與 vision。

## Architecture (Gary 親口校正最終版)

```
每客戶一台 DGX Spark：
  ├─ Clean Hermes Runtime (將來重構乾淨版，目前是 v1 standalone listener)
  │   ├─ LINE plugin
  │   │    ├─ v1 (現行)：自寫 standalone listener (line_listener.py 等)
  │   │    └─ v2 (待決)：Hermes 原生 LINE plugin
  │   │         (.hermes/hermes-agent/plugins/platforms/line/adapter.py)
  │   ├─ wannavegtour profile
  │   │    ├─ 查詢 workers (現有，availability_checker / historical_lookup)
  │   │    ├─ 上架 worker (新，待寫)
  │   │    ├─ 主動通知 worker (新，待寫)
  │   │    └─ 修復 escalation (新，待寫)
  │   └─ Local LLM (DGX Spark GPU 跑，META 路徑用)
  │       └─ audit log → LLM 判讀 → candidate → sandbox → Gary ✓ → apply
  └─ closed_loop_kernel + audit log (本機留資料、不外傳)
              ↓
  Telegram (Gary 跟所有客戶 DGX Spark 對話的窗口)
  ─ approval / escalation / dashboard
  ─ 透過 Hermes / skimm3r918_bot
```

### 重點理解

- **不是 edge/central 分離** — 每客戶一台 DGX Spark 上跑「整套」(Hermes + listener + workers + LLM)
- **資料主權**：客戶對話、模型推論全部留客戶硬體，無外流
- **Multi-tenant** 靠硬體隔離，不靠軟體層
- **LLM 成本** 一次性硬體 (~$3-4K USD)，無 API 費用
- **Telegram = Gary 的儀表板**，不是 OP 群回應通道 (OP 群仍由 LINE OA 回應)

## Premises (P1-P10) — Session 2026-05-25 對齊的真理

```
P1. 現有架構 (worker → kernel → listener / LINE) 是正確答案。
    下一步是「擴張+加能力」，不是 refactor。

P2. "AI 原生部門" = 把目前 worker pattern 複製 / 多開 / 互相協作。
    不是發明新部門抽象。

P3. 持續演化 = 加 worker + 加 intent + 加 kernel candidate type。
    Hermes 深整合等到「第 2 個客戶」或「多 channel」才動。

P4. Code is Law 不可協商：
    - 所有 control flow 在 Python，不在 prompt
    - LLM 只能當 classifier sensor (回 structured JSON)
    - LLM 永遠不能直接動 action 或寫 reply 文字

P5. 五階段基礎建設 (self-learning / 修正 / 測試 / 修復 / commit) 是
    closed_loop_kernel 的理想型。蓋順序：
      Stage 3 (replay) → Stage 0 (retention) → Stage 1 (observer) →
      Stage 2 (proposer) → Stage 4 (approval) → Stage 5 (applier)
    Stage 3 先解鎖原因：未來所有 candidate 都靠 replay 驗證才能 ship。

P6. 「自我演化」目前只能 Gary 手動 review audit log → 改 code。
    Stage 1-5 蓋完後變自動：observer → proposer → sandbox →
    Telegram 一鍵批准 → kernel applier 自動改 code。

P7. wannavegtour 是 dogfooding 第一站。跑通的能力會擴張到
    Daguantech / OHYA / fujioh / tazimac 等客戶。
    順序：「先把單客戶玩到精，再 multi-tenant」。

P8. 「能力」單位是 worker (availability_checker / historical_lookup /
    未來的 pricing_editor / 上架 worker / 主動通知 worker 等)。
    每個 worker = 一個 intent。新 intent 上線必走：
    (a) parser 加 keyword 或 hybrid LLM 偵測
    (b) 寫 worker code
    (c) sandbox replay 過去 audit log
    (d) ship

P9. Telegram (透過 Hermes / skimm3r918_bot) = Gary 統一管理窗口。
    所有 approval / 通知 / 跨客戶事件都從這裡進出。

P10. Hermes agent 已就緒 (profile registry / gateway / kanban.db 都活)。
     可以開始接，不用等。
```

## LINE 平台硬約束 (2026-05-25 用 LINE 官方文件驗證)

> **"At any time, only one LINE Official Account can be in a group chat
> or multi-person chat."**
> — [LINE Developers — Group Chats](https://developers.line.biz/en/docs/messaging-api/group-chats/)

含義：

- 一個 LINE 群只能有一個 OA — LINE 平台級硬約束
- 任何「shadow OA 並存」設計都不可能
- v1 → v2 migration 必須是「同一個 channel 換 webhook URL」的原子 cutover
- 沒有 graceful「並行 → 慢慢搬」這條路

但**一個 OA 能同時做** (Messaging API 標準能力)：

- 接收 webhook events (監聽 + 收集) ✅
- Reply API (1 分鐘 reply token 免費回應) ✅
- Push API (主動推播，按條計費) ✅
- Multicast / Broadcast ✅
- Group/User profile 查詢 ✅

## Hermes 原生 LINE Plugin 發現 (2026-05-25 驗證)

- 位置：`HermesRuntime/.hermes/hermes-agent/plugins/platforms/line/adapter.py`
- 大小：64KB / 1606 行 / 企業級成熟
- 能力：HMAC-SHA256 / reply token + push fallback / template buttons /
  allowlist / pairing / 慢回應 postback / Plugin yaml config

**Code is Law 張力**：plugin 是為 LLM agent 設計，`platform_hint` 給 LLM 看：

```python
platform_hint = (
    "You are chatting via LINE Messaging API. LINE does NOT render "
    "Markdown — text bubbles show ** and # literally..."
)
```

預設假設「plugin 收訊息 → 丟 LLM → LLM 生回應 → plugin 送回 LINE」。

**3 條與現有 wannavegtour 整合解法**（v2 採用時要選一條）：

| | 解法 | Code is Law | 工作量 |
|---|---|---|---|
| β1 | 註冊「假 agent」(非 LLM)，接 wannavegtour deterministic dispatcher。Hermes 以為自己接 LLM | ✅ 完全保留 | 中 |
| β2 | 用 Hermes generic `webhook.py` (不是 LINE plugin) + 自寫 LINE signature 驗證 | ✅ 完全保留 | 高 (浪費既有 LINE plugin) |
| β3 | 用 LINE plugin + LLM-as-classifier 路由 | ⚠️ 部分破壞 (LLM 進 control flow) | 低 |

**推薦：β1**，但細節要看 Hermes agent backend 接口 (本 session 沒深挖)。

## Gary 親口的 4 條未來工作線

```
A. 上架 worker
   - 寫 WC create_product，協助同事建新行程
   - 風險高 (寫操作 + 商品上架是業務臉面)
   - 必需 approval flow (同事 ✓ 才真的上)

B. 「修復」escalation handoff
   - OP 同事說「你寫得不好」→ listener 把上下文打包 → 推 Hermes 主 Agent
   - Hermes 主 Agent 修一輪 (LLM) → 把新版本送回邊緣 → 等同事再評
   - 真實的「人在迴圈中」多輪修復

C. 主動通知 worker (cron + WC + LINE push)
   - 每天掃 WC：未滿團 / 缺資料客戶
   - 邊緣 listener 主動 push LINE 給 OP
   - 跟現有「等同事問」是反向

D. LLM 判讀對話 → 改善建議 (META 路徑)
   - 讀 audit log → 找模式 (這類問題沒被處理 / 那個回應太囉嗦)
   - 提 candidate → 走 closed_loop_kernel 五階段
   - Gary 在 Telegram 收到「要不要加這個 keyword？」
```

## Session 沒做完的決策 (D7 未選 — 未來要回來)

「下一個 commit 動哪個」當時 4 個選項，Gary 後來轉去談架構釐清，沒選定：

```
A. launchd + healthz endpoint (~2hr) — listener 存活性
   ↑ 改成 systemd (Linux on DGX Spark)，計畫已寫進 handoff doc
B. Path α Telegram bridge 第一步 (~3hr) — escalation 通道雛形
C. 寫 design doc 存檔 (~1hr) — 已用本檔 + handoff doc 解決
D. A + C 一起 (~3hr)
```

**現況 (2026-05-25 結尾)**：

- D7 的 A 已被 NVIDIA 機器上的 systemd 計畫取代 (commit `b24c927` / `df1c711`)
- D7 的 C 已被本檔 + handoff doc 完成
- D7 的 B (Telegram bridge) 還沒動 — 是接 Hermes 的下一步

## 已 Verified 過的事實 (省得 NVIDIA 機器再驗一次)

- ✅ LINE OA `2010186381` 對應 wannavegtour 公司帳號 (`@283nbnhf`)
- ✅ target_group `C24cf0311116b96f22aced7cc2f7cac8d` 是 OP 內部群
- ✅ chatMode 必須是 `"bot"` (不是 `"chat"`) 才會發 webhook
  - 在 LINE OA Manager → 應答設定 → 關閉「聊天」
- ✅ 桌面版 LINE 沒有 @ 自動補完 — 所以需要 text-prefix invocation
  (`小弟` / `@小弟` / `/小弟`) 跟 mention 並存
- ✅ WP 認證實際是 Application Password (BasicAuth)，但欄位名沿用
  `consumer_key` / `consumer_secret` (config.py:5-7 註解)
- ✅ WC orderby=popularity 比 fan-out 15 API calls 快 5x
  (歷史 aggregate 查詢)
- ✅ Tailscale Funnel 是「客戶辦公室裝 DGX Spark」的暴露方案
  (現在新 URL: `https://spark-8035.tailb40323.ts.net/...`)

## Codex Review 已修的 P1/P2 安全 finding (省得再被 review)

```
P1 (whitelist bypass): DM/room source 在 target_groups 設定時應直接 reject
P1 (slowloris DoS): Handler.timeout = SOCKET_READ_TIMEOUT_SECONDS (5s)
P1 (gitleaks): 測試 fixture 用 "FIXTURE-not-a-real-secret" + # gitleaks:allow
P2 (PID file race): down script 加 kill_if_matches() ps cmdline 驗證
```

詳見：commit history + `wannavegtour/tests/test_*` 對應 Codex regression 測試。

## Mac mini (這台 Mac) 已退場

2026-05-25 結束時：

- ✅ Listener stopped (`bin/wannavegtour-line-down`)
- ✅ Tailscale Funnel off
- ✅ caffeinate stopped (Mac 可正常睡眠)
- ✅ `~/.hermes/credentials/wannavegtour/` 刪除
- ✅ `~/.hermes/line_events/wannavegtour.jsonl` (52 筆對話) 刪除
- ✅ worktree `.claude/worktrees/wannavegtour-availability-checker` 刪除

**安全提醒** (Mac mini 上的 token 在 LINE / WP 那邊還是有效)：

- LINE Developers Console → Reissue channel access token (作廢舊那把)
- WP Admin → `hermes-availability-checker` user → Revoke 舊 Application Password
- 新 token 給 DGX Spark 用，避免一把鑰匙兩台機器在手

## Cross-References

- `docs/handoffs/2026-05-25-wannavegtour-op-bot-handoff.md` — 完整 migration
  手順 (12 步 Bootstrap on New Machine)
- `docs/handoffs/2026-05-23-private-dev-handoff.md` — private repo / public
  repo split 決策
- `docs/hermes-integration-assessment-v0.md` — Hermes 4 層架構評估
- `docs/hermes-agent-first-architecture.md` — Hermes profile / Kanban context
- `docs/line-credentials-setup.md` — LINE OA setup 手順
- `closed_loop_kernel/` — 五階段 self-evolution kernel 程式碼
- `PROTOTYPE.md` — Closed Loop Kernel 原型現況
- `tracking/next-actions.md` — 持續更新的下一步清單

## 完整對話 transcript 在這

(僅 Mac mini 本機可讀，不在 git history 裡)

```
/Users/garyyang/.claude/projects/-Volumes-Hermes-System-HermesArchive-Gary--claude-worktrees-wannavegtour-availability-checker/010083d7-77a3-40d4-9f40-d0433653ca4a.jsonl
```

如果想 deep-dive 哪個決策的細節，可以從這個 JSONL 撈。但本檔已是高品質摘要，
應該不需要回去查 transcript。
