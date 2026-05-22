# Antigravity Continuous Tracking Goal：Closed Loop Kernel v0

這份 goal 用來要求 Antigravity 不只「產出文件」，而是持續追蹤 Closed Loop Kernel v0 規格是否真的收斂到可開工。

## Goal

持續追蹤、審查、修正 `/Volumes/Hermes System/HermesArchive/Gary/` 內的 Closed Loop Kernel v0 規格，直到所有 v0 acceptance criteria 都具備清楚、可測、可實作的文件依據。

## 不可犯的錯

- 不要回到 `employees` / 員工資料庫 demo。
- 不要把 `typeless` 當前提，這是誤打。
- 不要把 JSONL 當 source of truth；PostgreSQL 才是主資料層。
- 不要竄改歷史紀錄；失敗 attempt 永遠保留為 failed。
- 不要讓 LLM 自動套用 code patch / DDL；必須走 proposal → sandbox/replay → approval → apply。
- 不要在 attempts append-only 的同時又設計 UPDATE attempts。
- 不要只做 SQL query scenario；至少要保留非 SQL scenario 證明 kernel 泛用。

## 持續追蹤輸出

請建立並持續更新以下檔案：

```text
/Volumes/Hermes System/HermesArchive/Gary/tracking/status.md
/Volumes/Hermes System/HermesArchive/Gary/tracking/open-issues.md
/Volumes/Hermes System/HermesArchive/Gary/tracking/verification-log.md
/Volumes/Hermes System/HermesArchive/Gary/tracking/next-actions.md
```

### `tracking/status.md`

每次工作後更新：

- 目前整體狀態：draft / reviewed / ready-for-build / blocked
- 已完成文件清單
- 最近一次修改時間
- 目前還剩幾個 open issue
- 是否符合 Gary 的硬性要求

### `tracking/open-issues.md`

列出未解問題，不准用泛泛而談：

- issue id
- 問題描述
- 影響文件
- 嚴重度：blocker / high / medium / low
- 建議修正
- 狀態：open / fixed / deferred

### `tracking/verification-log.md`

每次自我驗證都要記：

- 驗證時間
- 檢查項目
- 使用的搜尋 / grep / browser research / 檔案閱讀證據
- 結果
- 後續修正

### `tracking/next-actions.md`

只列真正下一步，不要列大話：

- 下一個要修的文件
- 下一個要驗證的矛盾
- 是否需要 Gary 決策
- 是否可以進入實作

## 每輪必做檢查

每輪至少做以下檢查，並把結果寫入 `tracking/verification-log.md`：

1. 搜尋是否還有 `employees` / 員工 demo 痕跡。
2. 搜尋是否還有 `logs.jsonl` 被當 source of truth 的描述。
3. 搜尋是否還有 `UPDATE attempts` 或 running→success/failed 的矛盾。
4. 搜尋 schema 是否包含：`events`、`attempt_lifecycle_events`、`attempts`、`tool_calls`、`decisions`、`policy_gates`、`artifacts`、`failures`、`improvement_candidates`、`replays`、`approvals`。
5. 檢查 `pgcrypto` / `gen_random_uuid()` 是否一致。
6. 檢查 approval 部署條件是否包含：latest approved approval、candidate sandbox_verified、replay success、artifact hash 未變。
7. 檢查 sandbox guardrail 是否包含 static lint、least-privilege role、DB sandbox 與 code patch sandbox 分離。
8. 檢查 self-review 是否務實，不使用「完美」「工業級」等過度包裝詞。
9. 檢查是否至少有一個 SQL scenario 與一個非 SQL scenario。
10. 檢查 acceptance criteria 是否能對應到測試或 SQL/Python assertion。

## 完成標準

只有同時符合以下條件，才可以把狀態標成 `ready-for-build`：

- `tracking/open-issues.md` 沒有 blocker / high issue。
- 所有 v0 必要規格文件存在。
- `tracking/verification-log.md` 有至少兩輪檢查紀錄。
- 搜尋不到 employees demo 回歸。
- 搜尋不到 attempts append-only vs UPDATE attempts 的矛盾。
- Scenario 1 被明確標成 verification scenario，而不是底層本身。
- 非 SQL scenario 存在且能對應同一套 kernel model。
- 文件中明確寫出 v0 仍需實作驗證的風險。

## 若仍未達標

不要回報完成。請直接：

1. 把問題加入 `tracking/open-issues.md`。
2. 修相關 spec / scenario / self-review。
3. 更新 `tracking/verification-log.md`。
4. 再跑一次檢查。

## 回報格式

每次回報請只回：

- 目前狀態
- 修了哪些文件
- 還剩哪些 blocker / high issue
- 下一步要做什麼
