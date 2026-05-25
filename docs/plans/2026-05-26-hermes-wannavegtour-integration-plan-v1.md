# Plan: wannavegtour Foundation + Capabilities Roadmap (v1)

**Supersedes**: `docs/plans/2026-05-25-hermes-wannavegtour-integration-plan-v0.md` (drafted in isolation from session-context, premise-incorrect).
**Author**: drafted by Claude on DGX Spark `spark-8035`, for CEO-mode review by Gary.
**Status**: DRAFT v1 — under `/plan-ceo-review`.
**Anchored to**:
- `docs/handoffs/2026-05-25-wannavegtour-session-context.md` (the 10 premises + 4 worker tracks Gary named)
- `docs/handoffs/2026-05-25-wannavegtour-op-bot-handoff.md` (current shipped state on DGX)
- `docs/hermes-integration-assessment-v0.md`, `docs/hermes-agent-first-architecture.md`
- `docs/agent-profile-registry-v0.md`
- `spec/code-is-law-v0.md`, `spec/closed-loop-kernel-v0.md`
- `closed_loop_kernel/` (working OHYA demo: `2cebb1a`)

---

## Re-Framing (why v0 was wrong)

v0 framed the question as **"v1 (standalone listener) vs v2 (Hermes-integrated) cutover"**. This is incorrect, per session-context premises:

- **P1**: current architecture is correct — next step is to **expand + add capability**, not refactor.
- **P3**: Hermes deep integration **waits for the second customer or multi-channel trigger**.
- **LINE platform constraint**: one LINE group → one OA only. **Atomic cutover only, no parallel run** — invalidates v0's "tee in parallel" Phase 1.
- **P5**: foundation order is **Stage 3 (replay) first**, because every future candidate must be replay-validated before shipping.

Real question: **what foundation makes Gary's named capabilities (4 worker tracks) shippable, and how does each new capability flow into the closed-loop kernel from day one?** Hermes-native LINE plugin migration (β1) is Phase 2, gated on the second-customer or multi-channel trigger.

---

## Architecture (authoritative — from session-context)

```
每客戶一台 DGX Spark:
  ├─ Clean Hermes Runtime  (今天 spark-8035 上 Hermes runtime 是 fresh,未跑)
  │   ├─ LINE plugin
  │   │   ├─ v1 (現行 shipped):  自寫 standalone listener
  │   │   └─ v2 (Phase 2, 等觸發點): Hermes-native LINE plugin β1 解法
  │   ├─ wannavegtour profile
  │   │   ├─ 查詢 workers       (現有: availability_checker, historical_lookup)
  │   │   ├─ 上架 worker         (Phase 1.A,新)
  │   │   ├─ 主動通知 worker      (Phase 1.C,新)
  │   │   └─ 修復 escalation    (Phase 1.B,新)
  │   └─ Local LLM (DGX GPU,META 路徑)
  │       └─ audit log → LLM 判讀 → candidate → sandbox → Gary ✓ → apply
  └─ closed_loop_kernel + audit log (本機留資料,不外傳)
              ↓
  Telegram (Gary 統一管理窗口,透過 Hermes / skimm3r918_bot)
  ─ approval / escalation / dashboard
```

**Data sovereignty**: 對話 + LLM 推論留客戶硬體。**Multi-tenant 靠硬體隔離,不靠軟體層** — 所以 v0 的 multi-tenant FK / Control Plane 分析在 wannavegtour 階段都不需要。

---

## Premises Locked (10 條 + 1)

P1. **Expand, don't refactor**. v1 listener stays. New work is additive.
P2. AI 原生部門 = 複製/多開既有 worker pattern,不是新部門抽象。
P3. **Hermes 深整合 = 等第 2 個客戶 / 多 channel** 才動。
P4. **Code is Law**: control flow 在 Python,LLM 只能當 classifier sensor (回 structured JSON),**LLM 永遠不能直接 action 或寫 reply 文字**。
P5. 五階段順序:**Stage 3 (replay) 先**,再 Stage 0 (retention) → 1 (observer) → 2 (proposer) → 4 (approval) → 5 (applier)。
P6. 自我演化目前 = Gary 手動 review audit log → 改 code。Stage 1-5 蓋完才自動。
P7. **wannavegtour = dogfooding 第一站**。跑通的能力擴張到其他客戶。
P8. **能力 = worker**。新 intent 上線必走 (a) parser 加 keyword / hybrid LLM 偵測 (b) 寫 worker code (c) sandbox replay 過去 audit log (d) ship。
P9. **Telegram (透過 Hermes / skimm3r918_bot) = Gary 統一管理窗口**。
P10. Hermes runtime 已安裝 (DGX `~/.hermes/hermes-agent/`),**fresh 未啟動**,可開始接。

**P11 (new, from review)**: kernel 寫入是 **process 內 audit**(不是 LINE platform 層的並行),所以 P3 + LINE 硬約束都不阻擋我們從 day 1 就 record kernel events。

---

## Phase 0 — Foundation (1-2 週,不動 LINE 那一側)

三件事互為前提,**一起上才有意義**。

### 0.1 audit-to-kernel pipeline (~30 min code,~2 hr 含 DB 設定)

**做什麼**:`wannavegtour/line_router.py` 在每次 dispatch 結尾 (現有 JSONL 寫入旁邊) 多寫一筆進 `closed_loop_kernel.events` 表。

**為什麼**:
- 滿足 AI Native Company 「everything recorded」原則
- JSONL 維持當 debug log,kernel 是 single source of truth
- Stage 3 (replay) 的資料來源

**具體 diff** (~20 行):

```python
# wannavegtour/line_router.py 加 import + helper
from closed_loop_kernel.store import KernelStore
import uuid, json, hashlib, os
from datetime import datetime, timezone

_KERNEL_URL = os.getenv("KERNEL_DATABASE_URL")  # None = skip kernel write

def _record_kernel_event(event, action, intent, worker, extras):
    if not _KERNEL_URL:
        return  # graceful no-op
    payload = {
        "tenant": "wannavegtour", "source": "line",
        "message_id": event.message_id, "group_id": event.group_id,
        "user_id": event.user_id, "text": event.text,
        "action": action, "intent": intent, "worker": worker, "extras": extras,
    }
    content = hashlib.sha256(
        f"{event.message_id}|{event.text}|{action}|{intent}".encode()
    ).hexdigest()
    store = KernelStore.from_url(_KERNEL_URL)
    try:
        store.execute(
            "INSERT INTO events (id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), "wannavegtour_line_event",
             json.dumps({**payload, "content_hash": content}),
             datetime.now(timezone.utc).isoformat()),
        )
    finally:
        store.close()
```

**前置**:
- DGX 上 PostgreSQL 開 db `wannavegtour_kernel`,跑 `closed_loop_kernel.store.initialize()` 建 11 張表
- credentials `~/.hermes/credentials/wannavegtour/kernel-db.json` (mode 600)
- systemd unit / launcher 載入 `KERNEL_DATABASE_URL` env

**驗收**: 7 天每筆 LINE event 同時出現在 JSONL + kernel events,`content_hash` 對得起來,zero divergence。

**Code is Law 保留**: `_record_kernel_event` 是純記錄,沒有 control flow。

### 0.2 Stage 3 — replay 過去 audit log (~3-5 hr)

**做什麼**: 寫一個 CLI 工具 `python -m wannavegtour.replay`,讀過去 N 天 kernel events,把 `event.payload.text` 餵給目前的 `query_parser`,輸出「現在的 parser 跟當時實際 dispatch 結果差多少」。

**為什麼**(per P5): 未來任何 candidate (修 parser、加 worker、改 intent) 都要在這個 replay harness 過一次才能 ship。沒這個 → 沒法驗證 → 不能自動化任何 self-improvement。

**輸出格式**:
```
replay 2026-05-19..2026-05-26: 142 events
  +0  no behavior change (matches historical action)
  +12 new dispatches  (parser now catches what it didn't)
  -3  regressions     (parser no longer catches what it did) ← BLOCKER
  ±0  none of the above
```

**驗收**: 對既有 `query_parser` 跑 replay,結果是「全 match」(因為沒改);對「故意改壞的 parser」跑 replay,要報出 regression。

**Code is Law 保留**: replay 是 deterministic Python,沒有 LLM。

### 0.3 Path α — Telegram bridge 第一步 (~3 hr,D7 未選的 B)

**做什麼**: 寫一個 `wannavegtour/telegram_notify.py`,把「需要 Gary 注意」事件 (Type 2 PRICE_EDIT_HINT、kernel 出現 failure、replay 出現 regression) 推 Telegram 給 Gary。

**為什麼**:
- D7 上次沒選的 B,Gary 已 named 為「接 Hermes 的下一步」
- 是 Stage 4 (approval) 的物理通道 (未來 candidate 出來要 Gary 一鍵批准)
- 是 Phase 1.B (修復 escalation handoff) 的傳輸層
- 走 Hermes / skimm3r918_bot,是接 Hermes 的第一個切點 — **不用等第 2 個客戶 (這部分跟 P3 不矛盾,因為這是 Gary 端的管理通道,不是客戶 LINE 端的 channel)**

**選擇**:
- (a) 直接用 `python-telegram-bot` 跟 Telegram Bot API,自己一條 bot
- (b) 走 Hermes / skimm3r918_bot,訊息經過 Hermes runtime

(b) 更符合「Telegram = Gary 統一管理窗口,所有客戶都從這條進」的長期方向,但要 ramp up Hermes;(a) 快但之後要遷移。**推薦 (b)** — 接 Hermes 從這裡開始,而不是等第 2 個客戶。

**Code is Law 保留**: 通知決策由 Python 規則 (例如「kernel failure → notify」),Telegram 訊息文字是 template,LLM 不參與。

### Phase 0 退路

如果 PostgreSQL 在 DGX 上的設定卡住 (auth / Docker network / etc.),0.1 可以先用 SQLite 落地 (`KernelStore.from_url("sqlite:///...")`),日後再遷 Postgres。但 OHYA / production 路徑都用 Postgres,所以這只是 escape hatch。

---

## Phase 1 — Capabilities (Gary 親口 4 條,每條 = 1 worker = 1 intent)

每個 worker 走 P8 標準流程: parser 加偵測 → 寫 worker code → sandbox replay → ship。**這些工作不需要動 listener / LINE 那邊,純加 worker code**。

### 1.A 上架 worker (高風險,需 approval gate)

**Trigger**: OP 在群裡說「幫我新增一個 X 行程,N9900,...」

**做什麼**: WC `create_product` API,協助同事建新行程。

**為什麼風險高**:
- 寫操作,商品上架是業務臉面
- 同事說錯 → bot 真的上架錯 → 業務後果

**Approval flow**:
1. parser 認出「上架意圖」
2. worker 生成 candidate (WC create_product payload)
3. **不直接執行** — 寫進 kernel `improvement_candidates`
4. Telegram (0.3) 推給同事和 Gary 看 payload
5. OP / Gary 回 ✓ 才 apply
6. apply 後寫 audit + kernel event

### 1.B 「修復」escalation handoff

**Trigger**: OP 說「你寫得不好」「答錯了」「重講」

**做什麼**:
1. listener 把上下文 (上一筆 reply、原 query、相關歷史) 打包
2. 推 Hermes 主 Agent (走 Telegram bridge)
3. Hermes 主 Agent 跑 LLM 修一輪 (LLM 在這裡是 worker,不是 router — Code is Law 仍保留)
4. 把新版本送回邊緣 listener 重發
5. OP 再評

**意義**: 真實的「人在迴圈中」多輪修復。是 closed-loop 在 reply 品質的應用。

### 1.C 主動通知 worker (cron + WC + LINE push)

**Trigger**: cron (例如每天 9am)

**做什麼**:
1. 掃 WC: 哪些團未滿、哪些客戶缺資料、哪些待出團
2. 邊緣 listener 主動 `push` LINE 給 OP 群
3. 「跟現有等同事問」是反向

**Code is Law 保留**: cron 觸發、邏輯純 Python、push 訊息是 template。

### 1.D LLM 判讀 → 改善建議 (META 路徑,Stage 1)

**Trigger**: Stage 1 (observer) 啟動後,LLM 定期讀 kernel events

**做什麼**:
1. LLM 讀過去 N 天 audit log,找模式(這類問題沒被處理 / 那個回應太囉嗦)
2. 提 candidate (例如:「`小弟 X 團賣得怎樣` 應該觸發 historical_lookup 但 parser 沒接,建議加 keyword `賣得怎樣`」)
3. 走 closed_loop_kernel 五階段: candidate → sandbox replay (用 0.2 工具) → Telegram 給 Gary → ✓ → apply
4. Gary 在 Telegram 收「要不要加這個 keyword?」

**Code is Law 保留**: LLM 是 classifier sensor,輸出 structured JSON (proposed_keyword, sandbox_replay_diff, confidence)。kernel 規則決定要不要進 Stage 4。

**依賴**: 0.1 (有資料) + 0.2 (能 replay) + 0.3 (能通知 Gary) + Local LLM 設好。

---

## Phase 2 — Hermes Deep Integration (defer until trigger)

**觸發點 (per P3)**: 出現 (a) 第 2 個客戶 (Daguantech / OHYA / fujioh / tazimac), 或 (b) wannavegtour 第 2 個 channel (例如多一個 LINE OA、加 Telegram inbound)。

**做什麼 (β1 解法)**:
1. 註冊「假 agent」(non-LLM): Hermes profile 設成 type=agent,backend 接到 wannavegtour deterministic dispatcher,Hermes 以為自己接 LLM
2. 切換 LINE webhook URL: 從現有 `wannavegtour/line/webhook` 換到 Hermes plugin `~/.hermes/hermes-agent/plugins/platforms/line/adapter.py` 的 endpoint
3. 原子 cutover (LINE 平台只認一個 URL,沒有並行可能)
4. 卡點: 需深挖 Hermes agent backend 接口 — session-context 標註「本 session 沒深挖」

**不做的事 (現階段)**:
- 不寫 line-gateway profile from scratch (Hermes plugin 1606 行已存在)
- 不引入 multi-tenant FK / Control Plane / customer_kernel_map (single-tenant 不需要)
- 不重寫 wannavegtour package 的 worker code (改寫成 Hermes skill 是 Phase 2 後半段,gate on Phase 1 完成)

---

## NOT in scope (explicit non-goals)

- **v1↔v2 atomic cutover 在現階段**(因為 P3 觸發點還沒到)
- **Multi-tenant 軟體層**(P3 + 硬體隔離原則)
- **LLM in routing path**(P4 Code is Law 紅線)
- **Type 2 (WC write) — 編輯既有商品 / 改頁**(handoff doc 標 deferred,風險評估未完成)
- **無 retention / 沒 logrotate 的 audit**(現況 — 但 TaskList #6 在追)
- **Hermes plugin β1 深整合 (現在)** — gate on Phase 2 trigger

---

## What already exists (leverage,不要重建)

| 需求 | 已存在 code | 動作 |
|---|---|---|
| Event 寫入 kernel | `closed_loop_kernel.store.execute(INSERT events...)` (OHYA pattern) | 0.1 直接呼叫 |
| Append-only audit | `prevent_mutation` PG trigger | 0.1 寫入後自然有 |
| Sandbox replay (SQL) | `closed_loop_kernel/sql_sandbox.py` | 1.D 重用 |
| Sandbox replay (Python) | `closed_loop_kernel/sandbox.py` (subprocess + rlimit) | 1.D 重用 |
| Improvement candidate | `closed_loop_kernel.engine` (OHYA demo `2cebb1a` 跑過) | 1.A / 1.B / 1.D 重用 |
| Approval (4-point fingerprint) | `closed_loop_kernel.engine.apply_candidate` | 1.A / 1.D 重用 |
| Telegram bridge in Hermes | `~/.hermes/hermes-agent/...` (fresh 但已安裝) | 0.3 走這條 |
| LINE webhook listener (working) | `wannavegtour/line_listener.py` 等 | Phase 1 不動,Phase 2 才考慮 |
| Hermes-native LINE plugin | `hermes-agent/plugins/platforms/line/adapter.py` (1606 行) | Phase 2 β1 接 |
| Profile registry schema | `docs/agent-profile-registry-v0.md` | Phase 2 註冊 wannavegtour profile 時用 |

**結論**: 我們在 wire,不是 build。

---

## Success Criteria

### Phase 0 done when:
- **0.1**: 7 連續天,每筆 LINE event 在 JSONL + kernel events 兩邊都有,content_hash 對得起來,zero divergence。Listener latency 不變(沒新增 hot path)。
- **0.2**: 對現有 parser 跑 replay = 全 match;對故意改壞的 parser 跑 = 報出 regression count。
- **0.3**: Gary 在 Telegram 收到至少一筆真實 event 通知 (例如 Type 2 PRICE_EDIT_HINT 或測試手動觸發)。

### Phase 1 done when:
- **1.A**: 一個 OP 確實透過 bot 加上新商品(從 OP 提需求 → kernel candidate → Telegram 雙批准 → WC 真的新增 → audit 留證)。
- **1.B**: 一次完整修復循環(OP 不滿 → escalation → Hermes 主 Agent LLM 修 → 新版本送回 → OP ✓)。
- **1.C**: cron 跑滿 14 天,push 出至少一筆真實「未滿團」警示,OP 確認有用。
- **1.D**: Stage 1 (observer) 提出第一個 candidate,經 replay (0.2 工具) 驗證,Gary 透過 Telegram (0.3) 批准,apply 後降低原 failure rate。

### Phase 2 done when:
- 第 2 個客戶 / 第 2 個 channel 出現 → β1 切換完成 → wannavegtour 走 Hermes-native LINE plugin → 行為跟 v1 一致 (regression test 全綠)

---

## Open Questions for Gary

1. **Phase 0 全做還是擇一**: 0.1 + 0.2 + 0.3 三件互為前提,但 Telegram bridge (0.3) 牽涉 Hermes runtime 啟動,要不要 Phase 0 包含啟動 Hermes(只接 Telegram)?還是 Telegram 先用 raw bot API,Hermes 整合留到 Phase 2?
2. **kernel DB**: DGX 上目前 PostgreSQL 在跑(processes 有,服務 inactive,猜在 Docker)。要我先確認連線方式還是你自己處理?
3. **Local LLM 設置**: Phase 1.D 需要 DGX GPU 上跑 Local LLM。session-context 提到但沒指定 model / runtime。哪一個 model? llama.cpp / vLLM / Ollama?
4. **Phase 1 順序**: A/B/C/D 哪個先做?A (上架) 業務價值高但風險最高;C (主動通知) 業務價值高、風險低,做為 Phase 1 第一個 worker 比較合理。
5. **Stage 順序 vs Phase 順序**: P5 說 Stage 3 (replay) 先,但 Stage 0 (retention) 在第二。Phase 0 沒包 retention (logrotate 在 TaskList #6 追)。是否要把 retention 拉進 Phase 0 變 0.4?
6. **Mac token revoke**: session-context 標註「Mac mini 上 token 在 LINE / WP 還是有效」,要 reissue。這是 0.0 (Phase 0 之前的硬性 prerequisite) 還是已經做完?
