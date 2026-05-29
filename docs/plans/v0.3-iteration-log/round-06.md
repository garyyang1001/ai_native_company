# Round 06 — sandbox + Phase 3-8 + 1000 case 大架構諮詢(codex xhigh)

**Date**:2026-05-29
**Participants**:Claude ↔ codex `gpt-5.5 xhigh`(session `019e7341-741e-73c3-...`)
**Status**:collapsed — Round 7 起進 contract lock + parallel implementation

---

## 1. 情境

Gary 2026-05-29 「出發」mandate:從 OP 群組記錄 sandbox 模擬至少 1000 不同情境,基於 AI Native Company Close-Loop + Code is Law + Guardrail + Determinism。包 Phase 3-8 全鏈 ship。完美 = Telegram 確認/返回 + gemma4 越用越聰明 + DB 小腳本自動整理。

Round 5 Phase 2 ship 後,沒花時間 ping-pong 細問,我直接帶 codex xhigh 跳大架構。

## 2. Codex Round 6 4 個 architectural question 結論

完整 codex output:`.claude/jobs/1d06a75b/round06_output.md`

### Q1 Sandbox 環境 → Option A 新 PG DB(同 container)

```
op_assistant_kernel        ← production (5-6 同事真實流量)
op_assistant_sandbox_kernel ← sandbox(1000 case 模擬)
                              ↑
                              同 docker container 旁邊
```

- Transaction rollback 拒絕:1000 case 跑長了會碰 production 連線池 / lock / sequence / 背景 job → production 風險變隱性
- 新 container 過早 ops cost
- **必加 fake clock**:所有 `created_at` / `NOW()` 用 sandbox 內部 monotonic 時鐘,否則 determinism 是口號
- production 真實訊息進 sandbox **必先 PII 匿名化**(LINE user_id → 雜湊化偽名,訊息文本保留)

### Q2 1000 case 生成 → Option C(LLM seed + Python expand)

```
gemma4 看 production 24 筆 → 整理 80-120「人類問法種子」(LLM 只在這層)
                              ↓
Python template + slot 展開 1000(deterministic seed,可重 generate)
                              ↓
分布 70% 正常 / 20% 模糊應失敗 / 10% edge 或惡意
```

**8 個典型 template**(codex 提):
1. 日期 + 目的地 + 空位
2. 日期範圍 + 國內團
3. 目的地 + 預算
4. 客人數 + 房型
5. 臨時改日期
6. 還有沒有賣完
7. 模糊「小弟有團嗎」
8. 多句混在一起

**6 個 edge case**(codex 提):空白 / 貼圖 / 超長訊息 / SQL injection 字串 / 中英台混雜 / 多個目的地互相矛盾

### Q3 Phase 3-8 ship 順序 → 先鎖 contracts + 兩條平行線

**真正 hard dependency**:
- Phase 4 ← Phase 3(callback_data 格式)
- Phase 5 ← Phase 4(approval record 結構)
- Phase 7 ← Phase 6(replay metric)
- Phase 8 ← Phase 5 + Phase 7(同時依賴雙線)

**兩條平行線**:
- **人類審核線**:Phase 3 → 4 → 5(Telegram inline keyboard → dispatcher → audit chain)
- **實驗室線**:Phase 6 → 7(sandbox replay + 4 metric → AST guard + patch emitter)

**ship sequence**(codex 推 — Round 7 起跑):
1. **Round 7 lock 4 contracts**(callback_data / approval audit / sandbox run record / replay metric schema)
2. Round 8-9 **平行**:Phase 6 sandbox replay MVP ↔ Phase 3 Telegram fake client
3. Round 10-11 **平行**:Phase 7 AST guard ↔ Phase 4 dispatcher
4. Round 12 Phase 5 audit chain
5. Round 13 Phase 8 canary + KILL
6. Round 14 1000 case 跑模擬
7. Round 15+ 觀察 + 修

### Q4 完美 KPI(5 個)

| # | 指標 | 閾值 |
|---|---|---|
| K1 | LINE inbound → 隔天 09:00 Telegram 推 | 95% 在 3 分鐘內完成 |
| K2 | Gary 按核准 → sandbox replay + patch + canary 完成 | 95% 在 15 分鐘內,不含人工等待 |
| K3 | 1000 case false-positive(Gary 按 ✅ 但 replay 證明 bot 變笨) | < 1% |
| K4 | approved patch canary auto-revert rate | < 5%(高於 = 審核或 replay 太鬆) |
| K5 | gemma4 學習品質 — approve rate 連 3 輪上升或持平 + duplicate suggestion | duplicate < 15% |

**DB 自動整理**:不只現有 30d retention prune,還要加:
- candidate dedupe(同 payload_hash 已 applied 不重建)
- orphan artifact cleanup(replay 跑完的 sandbox snapshot)
- sandbox run purge(>7d sandbox events)
- failed replay compaction(>30d failed replay row)

## 3. Codex 確認的 5 個 implicit assumption

| ID | 假設 | codex 拍板 |
|---|---|---|
| A | sandbox gemma4 vs production gemma4 | 共用本機 model,**必記 model digest**(不只 name) |
| B | sandbox Telegram 真打? | **必 fake client**;真 Telegram 跑 5 筆 smoke test 收場 |
| C | 1000 case 跑時間 | LLM 7 小時不可接受 → cache curate output,full LLM 只 sample / nightly |
| D | 「自動整理小腳本」 | 需要新的,不只現有 retention |
| E | 失敗樣本比例 | **至少 30%** — Guardrail 看不到壞路徑就沒用 |

## 4. Codex 補的 3 個 architectural question 我漏了

| # | 議題 | 為什麼重要 |
|---|---|---|
| New 1 | **PII 匿名化** | production 真實訊息含同事/客戶 LINE user_id,進 sandbox 不能直接用,要先 hash 偽名化 |
| New 2 | **Reviewer separation 強化**(Round 1 U35 重申) | propose patch 的 profile 不能自己 approve;Phase 4 dispatcher 不能跑 propose,gemma4 不能跑 dispatch |
| New 3 | **Reject 後 Telegram UI** | Gary 按 ❌ 後不能只回「rejected」,要顯示「返回後 candidate.status 變什麼、replay corpus 怎麼處理」 |

→ 全進 Round 7 contract design。

## 5. 3 個 trade-off 我直接拍(不 surface Gary,因為已 implicit decided)

| trade-off | 我的拍板 | 為什麼不問 Gary |
|---|---|---|
| Sandbox 隔離級別 | Option A 新 PG DB 同 container | Gary 沒 explicit 拍但 codex 推 + 我同意,中等成本 / 中等隔離,可後續升 Option C |
| LLM 成本/速度(1000 case 全打 gemma4 vs cache) | cache curate output + sample LLM 模式 | 7 小時不可接受,deterministic 也要 cache support |
| auto-apply 停在 Telegram 還是 canary 後自動 ship | canary 後自動全切 | Gary 5/29 上午**已拍 dial D4=1**,無新 decision |

## 6. Round 7-15 路線圖

| Round | 目標 | Output |
|---|---|---|
| **7** | 鎖 4 contracts | 4 個 markdown spec in `docs/contracts/op_assistant_v0.3/` |
| 8 | Phase 6 sandbox replay MVP | `scripts/op_assistant/op_assistant_sandbox_replay.py` + 4 metric |
| 8' (parallel) | Phase 3 Telegram fake client + inline keyboard | `op_assistant_daily_curate.py` 加 keyboard render |
| 9-10 | Phase 7 AST guard + Phase 4 dispatcher | `op_assistant_patch_emitter.py` + `telegram-op-control/dispatcher.py` |
| 11 | Phase 5 audit chain | `approvals` 表 ALTER + dispatcher 寫入邏輯 |
| 12 | Phase 8 canary + KILL | `op_assistant_canary_judge.py` + LineRouter bucket |
| 13 | sandbox DB scaffold + 1000 case generator | `op_assistant_sandbox_kernel` DB + `scripts/op_assistant/op_assistant_sandbox_seed.py` |
| 14 | 真跑 1000 case | 5 KPI 量出來 |
| 15+ | 觀察 + 修 + DB 自動整理 cron | 直到 5 KPI 全綠 |

## 7. Karpathy lens

- **#1 Think Before Coding**:codex 抓 PII 匿名化 + reviewer separation + reject UI 三個我漏了,Round 7 contract 起就要 build in
- **#2 Simplicity First**:codex 把 LLM cache + fake clock + fake Telegram 三個簡化決定都給了,不會無謂打真實 Telegram / 跑 7 小時 LLM
- **#3 Surgical Changes**:Phase 3-8 平行做不亂改既有 Phase 1+2,新檔多放 `scripts/op_assistant/` 跟 `docs/contracts/op_assistant_v0.3/`,既有 Phase 2 `_persist_candidates` 不動
- **#4 Goal-Driven Execution**:5 KPI 明確,「完美」可 measure,Round 15+ 達 KPI 才算 ship

## 8. Artifacts

- Round 6 prompt:`.claude/jobs/1d06a75b/round06_prompt.md`(含現狀 dump + 4 信念 + 4 Q + 5 implicit assumption)
- Round 6 codex output:`.claude/jobs/1d06a75b/round06_output.md`
- session id:`019e7341-741e-73c3-bbfa-d06ab2a0ca75`
