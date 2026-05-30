# Hermes / OHYA 整合評估 v0

**目的**：把 Gary kernel 跟 OHYA 的第一個真實 agent profile 對齊，確認 Closed Loop Kernel 能不能接住一條可驗證的真實工作流。

**目前決策**：本 repo 的第一個整合對象只保留 OHYA，不拿外部客戶資料當 proof target。

**白話說**：這份文件現在只回答一件事：OHYA 的 `cms-draft-executor` 失敗時，Gary kernel 能不能留下乾淨紀錄、產生修復候選、跑 sandbox、等 Gary 批准，再決定是否套用。

**評估日期**：2026-05-24；2026-05-30 清理為 OHYA-only 版本

---

## 1. 整合邊界

### 保留範圍

| 項目 | 白話意思 | 狀態 |
|---|---|---|
| `OHYA` | 第一個可控的自家 / 關係事業測試對象 | 保留 |
| `cms-draft-executor` | 第一個被 kernel 接住的 OHYA agent profile | 保留 |
| `ohya_kernel` | OHYA 專用 PostgreSQL kernel database | 保留 |
| `EventReporter(profile_filter="cms-draft-executor")` | 只匯入單一 profile 的同步器 | 保留 |
| dirty-row 隔離 | 壞 JSON、缺欄位、錯 profile 不進正式紀錄 | 保留 |

### 不保留範圍

| 項目 | 白話意思 | 原因 |
|---|---|---|
| 外部客戶資料 | 任何非 OHYA 的客戶工作區、網站、token、DB、runtime | 不適合作為第一個 proof target |
| 整個 HermesRuntime 搬遷 | 把所有 SQLite / sessions / clients 一次搬進 Gary kernel | 範圍太大，會污染判斷 |
| OHYA 全部 profiles | 一口氣吃下 OHYA 所有 agent | OHYA 資料多且髒，先切單一 profile |
| production writeback | 反寫 OHYA live `kanban.db` 或 HermesRuntime state | 風險高，第一階段禁止 |

---

## 2. 目前架構判斷

Gary kernel 不是要取代 OHYA 的 agent runtime。它現在扮演的是 OHYA 後面的「稽核與修復後端」。

```text
OHYA kanban.db
  -> EventReporter 只讀同步
  -> Gary kernel attempts / failures
  -> FailureAnalyzer 產生修復候選
  -> Sandbox replay 驗證
  -> Gary approval gate
  -> 之後才可能 apply
```

白話意思：

1. OHYA 繼續負責跑 agent。
2. Gary kernel 只接收紀錄，不直接干擾 OHYA live runtime。
3. 任務失敗後，kernel 要把失敗變成可審核、可重播、可批准的流程。
4. 在沒有 sandbox 證據與 Gary 批准前，不准假裝已修好。

---

## 3. 第一個切片：OHYA cms-draft-executor

選 `cms-draft-executor` 的原因：

| 原因 | 白話說法 |
|---|---|
| 工作內容具體 | 它跟 CMS 草稿發布有關，成功或失敗比較好判斷 |
| 容易留下證據 | 發布失敗、API timeout、payload 錯誤都能變成 failure |
| 範圍夠小 | 只看一個 profile，不會被整個 OHYA 髒資料拖垮 |
| 可測閉環 | 可以驗證 failure -> candidate -> sandbox -> approval |

程式位置：

- [closed_loop_kernel/event_reporter.py](/Volumes/Hermes%20System/HermesArchive/Gary/closed_loop_kernel/event_reporter.py)
  - 這是什麼：OHYA `kanban.db` 到 Gary kernel 的同步器。
  - 白話功能：唯讀打開 OHYA SQLite，只搬 `cms-draft-executor` 的紀錄，其他 profile 跳過。

- [closed_loop_kernel/failure_analyzer.py](/Volumes/Hermes%20System/HermesArchive/Gary/closed_loop_kernel/failure_analyzer.py)
  - 這是什麼：失敗分析器。
  - 白話功能：把已記錄的 failure 轉成修復候選；只有能 sandbox 驗證的候選才往下走。

- [closed_loop_kernel/ohya_demo.py](/Volumes/Hermes%20System/HermesArchive/Gary/closed_loop_kernel/ohya_demo.py)
  - 這是什麼：OHYA 端到端 demo 串接器。
  - 白話功能：把同步、失敗分析、修復候選、批准通知串成一條流程；預設不寫入 live `kanban.db`。

- [docs/ohya-cms-draft-executor-slice-v0.md](/Volumes/Hermes%20System/HermesArchive/Gary/docs/ohya-cms-draft-executor-slice-v0.md)
  - 這是什麼：第一個 OHYA 切片規格。
  - 白話功能：定義這條線怎樣才算乾淨、怎樣才算通過。

---

## 4. Dirty Data 策略

OHYA 資料很多，也不乾淨，所以第一步不是清完整個 OHYA，而是讓 kernel 有能力拒收髒資料。

| dirty reason | 白話意思 | kernel 行為 |
|---|---|---|
| `profile_mismatch` | 不是 `cms-draft-executor` 的資料 | 跳過 |
| `missing_required_field` | 缺 task id、profile、時間、結果等必要欄位 | 跳過 |
| `bad_json` | payload 或 metadata 不是合法 JSON | 跳過 |
| `unsupported_outcome` | outcome 不是目前 kernel 支援的狀態 | 跳過 |
| `corrupt_source_table` | SQLite 來源表讀取失敗或局部損毀 | 記錄後繼續其他表 |
| `unexpected_error` | 單筆資料發生未預期錯誤 | 跳過該筆 |

白話判斷：髒資料可以被看見，但不能被寫成正式 attempts / failures。

---

## 5. 下一步應該驗證什麼

下一個自主開發目標不應該再擴大範圍，而是把這條 OHYA slice 從「程式有」推進到「隔離資料跑得通」。

建議目標：

```text
建立 OHYA cms-draft-executor isolated snapshot runner
```

白話意思：複製一份 OHYA `kanban.db` 的安全快照，在隔離環境裡跑 `EventReporter(profile_filter="cms-draft-executor")`，產出一份同步報告，讓 Gary 可以看懂：

1. 匯入了幾筆 `cms-draft-executor` events / attempts / failures。
2. 跳過了幾筆髒資料，以及各自原因。
3. 是否產生可 sandbox 的修復候選。
4. 是否完全沒有寫回 OHYA live runtime。
5. 哪些資料品質問題會阻擋下一步擴 profile。

---

## 6. 通過標準

這個整合方向要算健康，至少要通過：

1. 只匯入 `cms-draft-executor`。
2. 其他 profile 不進正式 attempts。
3. 壞 JSON、缺欄位、不支援 outcome 不會中斷同步。
4. failure 會被保留為 `open`，不能直接被假修好。
5. candidate 必須跑 sandbox，沒有 sandbox 證據不能進入 approval。
6. demo / runner 預設不反寫 live `kanban.db`。
7. 報告要用白話列出「匯入、跳過、失敗、候選、下一步」。

---

## 7. 明確非目標

- 不整理整個 OHYA。
- 不接外部客戶資料。
- 不重構 HermesRuntime 主體。
- 不讀 credentials。
- 不發 Telegram / Slack / Email 等外部通知。
- 不設定 launchd 或 production service。
- 不把 snapshot runner 的結果當作正式 production migration。

---

## 8. 推薦開發順序

1. 清乾淨 repo 文件中容易誤導的外部客戶試點脈絡。
2. 建立 OHYA isolated snapshot runner。
3. 讓 runner 輸出 JSON + 白話 Markdown 報告。
4. 加測試：確認 runner 不寫 live DB、profile filter 正常、dirty rows 被統計。
5. Gary 看報告後，決定是否擴到第二個 OHYA profile。
