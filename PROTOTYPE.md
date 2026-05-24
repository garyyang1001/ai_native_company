# Closed Loop Kernel v0 Prototype

本 prototype 是文件規格的第一個本地可跑版本。它以 PostgreSQL 作為 source-of-truth，先驗證核心資料流與約束，不碰 production DB、不部署真實代碼、不發外部通知。

## 已實作

- `KernelStore`：PostgreSQL schema、外鍵、append-only trigger（透過 `psycopg` 與 `KERNEL_DATABASE_URL` 連線）。
- `KernelEngine`：attempt lifecycle、單次 finish insert、failure tracking。
- improvement flow：failure -> candidate -> replay -> approval -> apply。
- 四層 apply gate：approval、candidate `sandbox_verified`、replay success、artifact hash match。
- orphan lifecycle reconciliation。
- SQL lint 與 Python AST lint 的第一版安全阻斷。
- Python subprocess sandbox：候選 code patch 會在暫存目錄內由獨立 Python process（`python -I` isolated mode + 空 PATH 環境）執行指定函式並回傳 JSON replay 結果；POSIX 平台再經 `preexec_fn` 套用 `RLIMIT_CPU` / `RLIMIT_AS` / `RLIMIT_DATA` / `RLIMIT_FSIZE` / `RLIMIT_NPROC` / `RLIMIT_CORE`，並以 `setsid()` 切到獨立 process group 以便整組終止；外層另有 wall-clock timeout 防止 hang 死。
- PostgreSQL DDL renderer：輸出 `pgcrypto`、核心 FK、append-only trigger、orphan view。
- 最小 HTML UI：`/events`、`/events/:id`、`/improvements`、`/approvals` 已可透過本地 HTTP server 開啟。
- `/approvals` 支援本地 `批准並套用` / `拒絕` POST action；approve 會套用 candidate，reject 會留下 rejected approval。
- `closed_loop_kernel.demo`：可跑出 Scenario 2 類型的本地閉環 demo。

## 驗證命令

```bash
python3 -m pip install -r requirements.txt
export KERNEL_DATABASE_URL='postgresql://USER@HOST:PORT/DBNAME'
python3 -m unittest discover -s tests

export KERNEL_ALLOW_DESTRUCTIVE_RESET=1   # 必填；demo/http_app 啟動會重置目標 DB
python3 -m closed_loop_kernel.demo
python3 -m closed_loop_kernel.http_app
```

執行 PostgreSQL-backed suite、demo 與 http_app 都需要 `KERNEL_DATABASE_URL`，且只能指向一次性測試資料庫；缺 `KERNEL_ALLOW_DESTRUCTIVE_RESET=1` 時 demo 與 http_app 會直接 abort。

## 邊界

- 本 prototype 已用 PostgreSQL 作為 source-of-truth；尚未硬化成 production runtime（單一連線 + 程序內 RLock 序列化所有查詢）。
- demo 與 http_app 啟動會 `DROP SCHEMA public CASCADE` 並重建表，僅能指向一次性測試資料庫。
- Python sandbox 已套用 POSIX `resource` 模組的 CPU / 記憶體 / 檔案寫入 / process 數 / core dump rlimit、isolated Python 模式與最小化環境變數；尚未引入 OS-level sandbox（如 macOS `sandbox-exec`、Linux seccomp / namespaces），跨平台 OS hardening 留待後續。
- SQL sandbox 目前只做 static lint，尚未建立 `sandbox_runner` role 或動態 schema。
- HTML views 已接本地 HTTP server 與本地 approve/reject action；持久化由 PostgreSQL 提供，但 demo seed 路徑會重置目標 DB。
- 任何 production DB、真實檔案部署、launchd、外部通知仍需 Gary 明確批准。
