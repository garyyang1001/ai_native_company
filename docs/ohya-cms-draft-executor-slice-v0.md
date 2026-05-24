# OHYA cms-draft-executor Slice v0

本文件定義 OHYA 第一個可控驗證切片：只驗證 `cms-draft-executor` 這一個 profile，不整理整個 OHYA。

## 白話目標

OHYA 資料很多，也很髒。第一步不能把整個 OHYA 都丟進 Gary kernel，否則 kernel 會被壞資料、舊任務、混雜 profile、破損 kanban.db 拖垮。

本切片只回答一個問題：

```text
Gary kernel 能不能管住一個真實 OHYA profile 的失敗、修正、沙盒試跑、Gary 批准與套用？
```

若這一條跑不通，就不要擴到整個 OHYA。

## 驗證對象

- Profile：`cms-draft-executor`
- 來源：OHYA kanban.db 的 `tasks`、`task_runs`、`task_events`
- 目標：`ohya_kernel` PostgreSQL database
- 同步方向：只允許 kanban.db -> ohya_kernel
- 禁止事項：不反寫 kanban.db，不修改 HermesRuntime live state，不碰 credentials

## 程式位置與白話註解

- [closed_loop_kernel/event_reporter.py](/Volumes/Hermes%20System/HermesArchive/Gary/closed_loop_kernel/event_reporter.py)
  - 這是什麼：OHYA kanban.db 到 Gary kernel 的同步器。
  - 白話功能：把指定 profile 的任務執行紀錄搬到 kernel，其他 profile 先跳過。

- [closed_loop_kernel/ohya_demo.py](/Volumes/Hermes%20System/HermesArchive/Gary/closed_loop_kernel/ohya_demo.py)
  - 這是什麼：OHYA 端到端驗證流程。
  - 白話功能：把同步、失敗分析、修正案、批准通知串起來；預設不再寫入傳入的 kanban.db。

- [closed_loop_kernel/failure_analyzer.py](/Volumes/Hermes%20System/HermesArchive/Gary/closed_loop_kernel/failure_analyzer.py)
  - 這是什麼：把 failure 轉成 improvement candidate 的分析器。
  - 白話功能：目前只讓 `crash` 這種可測試失敗走真 sandbox；其他模糊錯誤不能假裝修好了。

## 髒資料隔離規則

`EventReporter` 會把不能安全匯入的資料放進 `skipped_rows`，並標原因。

| reason | 白話意思 | 結果 |
|---|---|---|
| `profile_mismatch` | 不是 `cms-draft-executor` 的資料 | 跳過 |
| `missing_required_field` | 缺 task id、profile、時間或結果欄位 | 跳過 |
| `bad_json` | payload 或 metadata 不是有效 JSON | 跳過 |
| `unsupported_outcome` | outcome 不是目前支援的成功/失敗狀態 | 跳過 |
| `corrupt_source_table` | SQLite 來源表讀取失敗或損毀 | 記錄後繼續同步其他表 |
| `unexpected_error` | 單筆資料發生未預期錯誤 | 跳過該筆 |

白話判斷：髒資料可以存在，但不能污染 kernel 的正式 attempts / failures。

## 通過標準

本切片通過，必須同時符合：

1. 只匯入 `cms-draft-executor` 的 task runs。
2. 其他 profile 的紀錄只進 skipped，不進 attempts。
3. 壞 JSON、缺欄位、未完成 run、不支援 outcome 不會中斷同步。
4. `crashed` / `timed_out` / `failed` 類型會轉成 `failures.status='open'`。
5. `crash` failure 可產生 candidate 並跑 code sandbox replay。
6. 未通過 sandbox 的 candidate 不會進入可批准狀態。
7. demo 預設不寫入 live kanban.db。

## 非目標

- 不清理整個 OHYA。
- 不代表整個 HermesRuntime 已完成整合。
- 不把 OHYA 全部 profile 一次接進 kernel。
- 不處理 production deploy、launchd、Telegram token 或 credentials。
