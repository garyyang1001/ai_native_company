# Round 01 — Architectural unknowns enumeration

**Date**:2026-05-29
**Participants**:Claude Opus 4.7 (1M context, extended thinking max) ↔ codex `gpt-5.5` (`model_reasoning_effort=xhigh`)
**Round 1 status**:collapsed — enumeration complete, priority + Round 2 plan locked
**Duration**:~15 min (codex xhigh response + Claude integration)

---

## 1. Why this iteration loop exists

Gary 2026-05-29 mandate(原話):

> 「你把你的思考模式拉到最高然後呢再去找 codex 也是拉到最高去討論接續的設計你們可以做最多 100 輪一直持續的檢查修改」

After karpathy-guidelines lens review([[karpathy_pushback]]):Plan A 純 100 輪 design discussion 違反 simplicity-first + goal-driven。Adopted **Plan B**:

```
Round 1   : enumerate Phase 2-8 + AI Native Company architectural unknowns
Round 2-K : per p0 spike 1-2 rounds collapse spec
Round K+  : implement Phase N → codex review → ship → repeat
Max budget: 100 rounds (expect 5-15 to converge)
Capture   : each round = one commit in docs/plans/v0.3-iteration-log/
```

Gary chose "**both**":process value (case study) **and** outcome (Phase 2-8 production ship).

## 2. Starting state

- Phase 1 ship complete:5 commit chain on `plugins/telegram-op-control/` (44/44 pytest pass)
- V0.3 design doc:`docs/plans/2026-05-28-op-assistant-v0.3-design.md` (491 行 / 16 risks R1-R16)
- Claude enumerated 33 architectural unknowns spanning Phase 2-8 + cross-phase / AI Native Company
- Codex prompt:`.claude/jobs/1d06a75b/round01_prompt.md`(~1500 行 含 full enumeration)

## 3. Codex Round 1 output summary

Full codex output:`.claude/jobs/1d06a75b/round01_output.md`

### 3.1 Codex added 8 new unknowns

| ID | unknown | priority | strategy |
|---|---|---|---|
| **U34** | **candidate lifecycle 狀態機** — created → pushed → approved/rejected → replayed → patched → canary → killed/applied 必須唯一合法流向 | **p0** | decide-now |
| **U35** | **reviewer separation rule** — 同一個 AI 不能 propose + review + apply 同條改善;違反 human quality gate | **p0** | decide-now |
| U36 | failed candidate retention(replay-fail / AST-fail / canary-fail 保留多久,誰清) | p1 | spike |
| **U37** | **prompt/version pinning** — gemma4 每天產 candidate 時 prompt 版本 + model 名 + 輸入 corpus 版本必須入庫,否則事後不可重現 | **p0** | decide-now |
| U38 | approval identity proof(Telegram callback 的 actor 對到真實 approver) | p1 | decide-now |
| **U39** | **observation-to-candidate trace** — 每條 candidate 能回指哪些 inbound messages 觸發了它(否則 closed loop 變 loose suggestion) | **p0** | decide-now |
| U40 | partial rollout target(canary 對全流量 / chat / shadow mode) | p2 | spike |
| U41 | manual override path(Gary 不用 AI 直接 create/reject/kill candidate) | p1 | decide-now |

### 3.2 Codex re-prioritized 4 of Claude's enumeration

| 我原列 | codex 調整 | 理由 |
|---|---|---|
| U30 marketing-agent handler(我原 p2 delegate) | **defer 不寫 handler,只留 domain 欄位** | 不為不存在的第二個 app 寫 handler |
| U31 V0.4 升級路徑(我原 defer) | **強化 defer** | V0.3 先證明 closed loop 跑完一次,不要同時設計 new_intent / prompt patch / LLM AST fence |
| U23 patch 作者標籤 | **delegate** | commit message 後補規範,不影響 Phase 7 safety |
| U8 keyboard layout | **delegate** | U6/U7/U9 定了 UI 排版 Phase 3 收斂 |

### 3.3 全 41 條 priority 分布

```
p0 (Phase 2 blocker): 15 條
  U1 U2 U3 U4 U5 U10 U11 U14 U17 U21 U29 U34 U35 U37 U39
p1 (Phase 3/4 blocker): 22 條
  U6 U7 U9 U12 U13 U15 U16 U18 U19 U22 U24 U25 U26 U27 U28
  U32 U33 U36 U38 U41 (+ U8 U20 delegate)
p2: 3 條 — U23, U30, U40
defer: 1 條 — U31
```

### 3.4 Codex 整體建議 — 一句話 framing(本輪最強 takeaway)

> **「V0.3 不是『AI 自動改規則』,是『AI 提案,人批准,系統可重播、可驗證、可回滾』。」**

這句話 codex 提的位置上層 framing,可以壓住 Phase 2-8 所有設計選擇。Round 2 結算時寫進 V0.3 doc 開頭。

## 4. Round 2 工作清單(8 條,N ≤ 8 per karpathy)

依 codex 推薦的優先序攻 8 條 p0(+1 條 p1 spike):

| ID | 議題 | 為什麼最先 |
|---|---|---|
| U34 | candidate lifecycle 狀態機 | Phase 2 寫入格式漂移源頭 |
| U1 | payload_hash 演算法 | approval / replay / audit chain 錨點 |
| U2 | idempotency(`source_event_id + proposal_index UNIQUE`) | daily job 重跑不污染 single source of truth |
| U3 | typed_payload schema enforcement | 資料品質的 Python / PG / 雙層 邊界 |
| U37 | prompt/model/input version pinning | replay 不可重現問題 |
| U39 | observation→candidate trace | closed loop 跟 loose suggestion 的分界 |
| U10 | actor × chat 雙重 allowlist | Phase 4 權限邊界 + 誤按防線 |
| U11 | transactional claim SQL(spike) | approval race / 雙寫 / 重入 |

Round 2 expected:每條 decide-now → 直接拍 spec;U11 spike(可能再分 Round 2.5);結算時整批 patch 進 V0.3 doc + 把 codex 那句話加進 doc 開頭。

## 5. Karpathy lens reflection

- **#1 Think Before Coding**:enumeration 強迫展開所有假設,U35(reviewer separation)是 codex 抓我 silently 假設「同一個 LLM 流程沒問題」
- **#2 Simplicity First**:已剔除 U30 / U31 / U23 / U8(它們會把 V0.3 scope 拉大)
- **#3 Surgical Changes**:Round 1 commit 只動 log file,不動 V0.3 doc(等 Round 2 collapse 完一次性 patch)
- **#4 Goal-Driven Execution**:Round 2 success criteria = 8 條 decide-now 全有 spec + V0.3 doc 對應 patch + codex 二次 review 過

## 6. Artifacts

- Round 1 prompt:`.claude/jobs/1d06a75b/round01_prompt.md`(1500+ 行)
- Round 1 codex output:`.claude/jobs/1d06a75b/round01_output.md`(完整 review)
- codex session(`codex exec` `-c model_reasoning_effort=xhigh`)
- Round 2 prompt 將由本 round-01.md 衍生
