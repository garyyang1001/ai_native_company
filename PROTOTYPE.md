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
- SQL DDL sandbox（`closed_loop_kernel/sql_sandbox.py` 之 `SqlSandbox`）：每次 replay 建一個 `sandbox_temp_<uuid>` schema，由低權限角色 `sandbox_runner`（NOLOGIN/NOINHERIT、`public` schema 權限全數 REVOKE）以 `SET LOCAL ROLE` 在交易內執行候選 SQL；finally 區塊 `DROP SCHEMA ... CASCADE` 清理；並發 6 thread 測試已驗證 schema 名稱互不碰撞、無遺留。SQL static lint 已擴充黑名單：阻擋 `SET/RESET ROLE`、`SESSION AUTHORIZATION`、`SECURITY DEFINER`、`CREATE/ALTER/DROP ROLE|USER|GROUP`、`GRANT`/`REVOKE`、`DROP SCHEMA|DATABASE`、`ALTER SYSTEM`、statement-leading `COPY`、`pg_read_file`/`pg_ls_dir`/`lo_*` 等 escape 路徑。
- `KernelEngine.replay_sql_candidate`：將 `SqlSandbox` 串入閉環。讀 `sql_patch` candidate → lint → 開臨時 schema → 可選跑 setup_sql → 以 sandbox_runner 跑 proposed_content → 比對 `expected_row_count` / `expected_result` → 寫 `replays` 並把 candidate 標 `sandbox_verified` / `draft`。
- `closed_loop_kernel.sql_demo`：Scenario 1（SQL self-healing）可重跑端到端 demo。把錯的 SQL 失敗、提候選、sandbox replay、批准、套用、retry 成功完整跑一遍，輸出最終 attempts / candidate / failure / replay 狀態。
- PostgreSQL DDL renderer：輸出 `pgcrypto`、核心 FK、append-only trigger、orphan view。
- 最小 HTML UI：`/events`、`/events/:id`、`/improvements`、`/approvals` 已可透過本地 HTTP server 開啟。`/improvements` 表格已含「沙盒 schema」欄、`/approvals` 卡片會顯示候選的 patch_type 標籤（程式修正 / SQL 修正 / Prompt 修正）、隔離 schema 與 replay rows 樣本。
- `/approvals` 支援本地 `批准並套用` / `拒絕` POST action；approve 會套用 candidate，reject 會留下 rejected approval。
- `closed_loop_kernel.demo`：可跑出 Scenario 2（Python 技能 patch）類型的本地閉環 demo。
- `closed_loop_kernel.sql_demo`：可跑出 Scenario 1（SQL self-healing）類型的本地閉環 demo。

## 驗證命令

```bash
python3 -m pip install -r requirements.txt
export KERNEL_DATABASE_URL='postgresql://USER@HOST:PORT/DBNAME'
python3 -m unittest discover -s tests

export KERNEL_ALLOW_DESTRUCTIVE_RESET=1   # 必填；demo/http_app 啟動會重置目標 DB
python3 -m closed_loop_kernel.demo                 # Scenario 2 一次性 demo（會 reset）
python3 -m closed_loop_kernel.sql_demo             # Scenario 1 一次性 demo（會 reset）
python3 -m closed_loop_kernel.http_app             # 預設 serve；不 reset、保留歷史
python3 -m closed_loop_kernel.http_app seed        # 只 reset + 種 Scenario 2 種子，不啟 server
python3 -m closed_loop_kernel.http_app seed-and-serve   # reset + seed 再開 server（舊行為）
```

執行 PostgreSQL-backed suite、demo 與 http_app 都需要 `KERNEL_DATABASE_URL`，且只能指向一次性測試資料庫。`demo` / `sql_demo` / `http_app seed*` 模式都會 `DROP SCHEMA public CASCADE`，缺 `KERNEL_ALLOW_DESTRUCTIVE_RESET=1` 時會直接 abort；`http_app`（無 subcommand，預設 serve）不會 reset，可重複啟動而不丟歷史。

## 邊界

- 本 prototype 已用 PostgreSQL 作為 source-of-truth；尚未硬化成 production runtime（單一連線 + 程序內 RLock 序列化所有查詢）。
- `demo` / `sql_demo` 啟動會 `DROP SCHEMA public CASCADE` 並重建表，僅能指向一次性測試資料庫。
- `http_app` 預設改為 `serve` 模式（不 reset、保留歷史）；要重新種 demo 才需 `seed` 或 `seed-and-serve`（兩者均要求 `KERNEL_ALLOW_DESTRUCTIVE_RESET=1`）。
- Python sandbox 已套用 POSIX `resource` 模組的 CPU / 記憶體 / 檔案寫入 / process 數 / core dump rlimit、isolated Python 模式與最小化環境變數；尚未引入 OS-level sandbox（如 macOS `sandbox-exec`、Linux seccomp / namespaces），跨平台 OS hardening 留待後續。
- SQL sandbox 已具備 `sandbox_runner` 低權限角色與動態 `sandbox_temp_<uuid>` schema，並有 6 thread 並發測試覆蓋；`KernelEngine.replay_sql_candidate` 已串入，`closed_loop_kernel.sql_demo` 跑 Scenario 1 端到端通過。Prototype 沙盒走 `SET LOCAL ROLE` 隔離；產線階段建議升級為獨立 `psycopg.connect(user=sandbox_runner)` 物理連線。
- HTML views 已接本地 HTTP server 與本地 approve/reject action；持久化由 PostgreSQL 提供，但 demo seed 路徑會重置目標 DB。
- 任何 production DB、真實檔案部署、launchd、外部通知仍需 Gary 明確批准。
