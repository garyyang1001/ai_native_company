# Closed Loop Kernel v0 Prototype

本 prototype 是文件規格的第一個本地可跑版本。它用 SQLite adapter 模擬 PostgreSQL 行為，先驗證核心資料流與約束，不碰 production DB、不部署真實代碼、不發外部通知。

## 已實作

- `KernelStore`：本地 SQLite schema、外鍵、append-only trigger。
- `KernelEngine`：attempt lifecycle、單次 finish insert、failure tracking。
- improvement flow：failure -> candidate -> replay -> approval -> apply。
- 四層 apply gate：approval、candidate `sandbox_verified`、replay success、artifact hash match。
- orphan lifecycle reconciliation。
- SQL lint 與 Python AST lint 的第一版安全阻斷。
- Python subprocess sandbox：候選 code patch 會在暫存目錄內由獨立 Python process 執行指定函式並回傳 JSON replay 結果。
- PostgreSQL DDL renderer：輸出 `pgcrypto`、核心 FK、append-only trigger、orphan view。
- 最小 HTML UI：`/events`、`/events/:id`、`/improvements`、`/approvals` 已可透過本地 HTTP server 開啟。
- `/approvals` 支援本地 `批准並套用` / `拒絕` POST action；approve 會套用 candidate，reject 會留下 rejected approval。
- `closed_loop_kernel.demo`：可跑出 Scenario 2 類型的本地閉環 demo。

## 驗證命令

```bash
python3 -m unittest discover -s tests
python3 -m closed_loop_kernel.demo
python3 -m closed_loop_kernel.http_app
python3 - <<'PY'
from closed_loop_kernel.postgres import render_postgres_schema
print(render_postgres_schema()[:500])
PY
```

目前測試不需要安裝第三方套件。

## 邊界

- SQLite adapter 是本地 prototype，不等於 PostgreSQL production adapter。
- PostgreSQL DDL 目前可輸出與測試，但尚未在真實 PostgreSQL instance 跑 integration test。
- Python sandbox 已啟動 subprocess replay，但尚未加上 OS sandbox、資源限制或更細的檔案系統 policy。
- SQL sandbox 目前只做 static lint，尚未建立 `sandbox_runner` role 或動態 schema。
- HTML views 已接本地 HTTP server 與本地 approve/reject action；尚未支援持久化 DB 檔案。
- 任何 production DB、真實檔案部署、launchd、外部通知仍需 Gary 明確批准。
