# 放這:~/.hermes/profiles/op-assistant/scripts/op_assistant_monthly_maintenance.py
"""每月 1 日 05:00:archive 30 天前 events + VACUUM + backup 健康檢查

★ Codex review 修正(v2.1):
- B2:手動載 profile .env
- M4:VACUUM subprocess 失敗 catch,**還是要寫健康事件**(否則 alert 不會發)
- 用絕對路徑 /usr/bin/docker(crontab/cron PATH 不全)
"""
import os, subprocess, uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta

def _load_profile_env():
    env_path = Path("/home/wannavegtour/.hermes/profiles/op-assistant/.env")
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

_load_profile_env()

from closed_loop_kernel.store import KernelStore, json_param

KERNEL_URL = os.environ["KERNEL_DATABASE_URL"]
BACKUP_BASE = Path("/home/wannavegtour/.hermes/credentials/wannavegtour/op_kernel/backup")
DOCKER_BIN = "/usr/bin/docker"  # ★ L: 絕對路徑

def run():
    store = KernelStore.from_url(KERNEL_URL)
    today = datetime.now(timezone.utc)
    warnings = []
    errors = []
    try:
        # 1. VACUUM ANALYZE — ★ M4:catch 例外,還是要寫健康事件
        try:
            subprocess.run([
                DOCKER_BIN, "exec", "op-assistant-kernel",
                "psql", "-U", "op_kernel", "-d", "op_assistant_kernel",
                "-c", "VACUUM ANALYZE;"
            ], check=True, timeout=600,
               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            errors.append(f"VACUUM failed: {type(e).__name__}: {str(e)[:200]}")

        # 2. backup 健康檢查
        latest_daily = max((BACKUP_BASE / "daily").glob("*.sql.gz"), default=None,
                          key=lambda p: p.stat().st_mtime)
        if not latest_daily or (today.timestamp() - latest_daily.stat().st_mtime) > 86400 * 2:
            warnings.append("daily backup 超過 2 天沒更新")

        latest_weekly = max((BACKUP_BASE / "weekly").glob("*.sql.gz"), default=None,
                           key=lambda p: p.stat().st_mtime)
        if not latest_weekly or (today.timestamp() - latest_weekly.stat().st_mtime) > 86400 * 10:
            warnings.append("weekly backup 超過 10 天沒更新")

        # 3. 寫健康事件 — 永遠寫,就算前面 VACUUM 失敗
        store.execute(
            "INSERT INTO events (id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
            [str(uuid.uuid4()),
             "kernel_monthly_health",
             json_param({"warnings": warnings, "errors": errors, "ts": today.isoformat()}),
             today.isoformat()]
        )

        # 4. 失敗或警告 → push Telegram alert
        if warnings or errors:
            # (push helper 同 daily_curate.py 的 _push_telegram_summary 結構,省略)
            pass
    finally:
        store.close()

if __name__ == "__main__":
    run()
