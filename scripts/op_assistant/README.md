# scripts/op_assistant/ — OP Assistant Hermes Cron Scripts + Backup

**Status**: 已 deploy 進 DGX spark-8035 — 對應 commit `c1-c4` 階段(2026-05-26)。
**Companion doc**: `docs/plans/2026-05-26-op-kernel-codex-execute-plan.md`

## 檔案清單

| 檔案 | 用途 | Deploy 到哪 | 註冊 |
|---|---|---|---|
| `op_assistant_etl.py` | 每 4hr ETL(session.db → kernel events) | `~/.hermes/profiles/op-assistant/scripts/` | `hermes cron create '0 */4 * * *' --name op-etl --script op_assistant_etl.py --no-agent --profile op-assistant` |
| `op_assistant_daily_curate.py` | 每日 09:00 curation(gemma4:e4b → daily_curation_summary event + Telegram push) | 同上 | `hermes cron create '0 9 * * *' --name op-daily-curate ...` |
| `op_assistant_weekly_report.py` | 每週一 09:00 週報 | 同上 | `hermes cron create '0 9 * * 1' --name op-weekly-report ...` |
| `op_assistant_monthly_maintenance.py` | 每月 1 日 05:00 VACUUM + backup 健康檢查 | 同上 | `hermes cron create '0 5 1 * *' --name op-monthly-maint ...` |
| `backup.sh` | pg_dump backup script(daily/weekly/monthly) | `~/.hermes/credentials/wannavegtour/op_kernel/` | 系統 crontab(不是 Hermes cron — backup 不應依賴 Hermes 跑著) |
| `docker-compose.example.yml` | PostgreSQL container 設定 範本 | `~/.hermes/credentials/wannavegtour/op_kernel/docker-compose.yml`(去掉 .example) | `docker compose up -d` |

## Deploy 流程(新機 / re-deploy)

完整步驟見 `docs/plans/2026-05-26-op-kernel-codex-execute-plan.md` 內 C1-C4 brief 全文。摘要:
1. 建 `~/.hermes/credentials/wannavegtour/op_kernel/`,生密碼,copy docker-compose,`docker compose up -d`
2. `KernelStore.from_url(...).initialize()` 建 14 表 + 6 trigger
3. 寫 `KERNEL_DATABASE_URL=...` 進 `~/.hermes/profiles/op-assistant/.env`
4. Copy 4 個 .py 到 profile scripts dir + symlink `closed_loop_kernel` 從 repo
5. `hermes cron create ...` 註冊 4 條
6. Copy `backup.sh` 到 op_kernel 目錄,加 crontab 3 條

## Dependencies(Python)

- `closed_loop_kernel.store.KernelStore` + `json_param`(from this repo,via symlink 或 PYTHONPATH)
- `psycopg`(installed in repo `.venv/`)
- `requests`(for daily/weekly Telegram push)
- 標準函式庫:`sqlite3`, `json`, `uuid`, `subprocess`, `datetime`, `pathlib`

## Run 各自手動

```bash
# 試 ETL 一次(會寫 events table)
hermes -p op-assistant cron run op-etl

# 試 daily curation(會打 Ollama gemma4:e4b)
hermes -p op-assistant cron run op-daily-curate

# 試 backup
bash ~/.hermes/credentials/wannavegtour/op_kernel/backup.sh daily
```

## Audit notes(v2.1 review fixes 已包含)

- **B2**:每個 .py 頂端有 `_load_profile_env()` 手動載 profile `.env`(`--no-agent` cron 不會自動載)
- **H3**:ETL 用 `mode=ro` + `PRAGMA busy_timeout=30000`(不用 `immutable=1` 因 WAL 模式不安全)
- **M2**:daily/weekly summary 用 `uuid5(NAMESPACE, period_key)` + `ON CONFLICT DO NOTHING` 確保 idempotent
- **M3**:weekly `_push_weekly_report()` 完整實作,不是 `pass`
- **M4**:monthly `subprocess.run` 包 try/except,失敗仍寫健康事件
- **L1**:Telegram exception catch `RequestException`,不洩 token URL
- **L3**:`backup.sh` 用 `/usr/bin/docker` 絕對路徑 + stderr → log

## 不入 repo 的東西(故意)

- `~/.hermes/credentials/wannavegtour/op_kernel/db_password.txt` — 機密
- `~/.hermes/credentials/wannavegtour/op_kernel/docker-compose.yml` — 含 secret reference(此 repo 留 .example.yml 不含密碼)
- `~/.hermes/credentials/wannavegtour/op_mapping.json` — 含 OP 同事姓名(PII)
- `~/.hermes/credentials/wannavegtour/op_kernel/backup/**` — backup 內含資料庫
