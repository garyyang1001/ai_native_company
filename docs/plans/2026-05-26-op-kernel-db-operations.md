# OP Assistant 資料層 + Kernel DB 完整操作文件

**狀態**: DRAFT(等 Gary 確認後動工)
**日期**: 2026-05-26
**作者**: Claude(based on Gary 2026-05-26 對話釐清)
**Cross-refs**:
- `docs/plans/2026-05-26-wannavegtour-full-company-bot-map-v2.md` § Option E
- `docs/plans/2026-05-26-op-bot-hermes-harness-spec.md` § 6 tools
- `docs/handoffs/2026-05-25-wannavegtour-session-context.md` § P4 P5 (Code is Law + Stage 順序)
- `EN7frwQIbKc-transcript.txt` line 41-67(Diana「make organization queryable」)
- `X_JsIHUfUjc-transcript.txt`(Gary「record everything」)
- `closed_loop_kernel/`(既有 generic kernel,OHYA demo 跑通過)

---

## 為什麼有這份

之前的 spec 講「op-assistant 怎麼接 LINE + 怎麼回應」,但**沒講底下的資料層**。

Gary 2026-05-26 釐清:**「對話、學習、每個關卡與流程,都需要回存到資料庫,這才符合 AI Native Company 的 structure」**。對照 Diana 逐字稿(line 41-67):

> "make your entire company queryable. In other words, the whole organization should be legible to AI. Every important action should produce an artifact that the intelligence at the center of the company can learn from and use to self-improve."

**沒資料庫 = 不是 AI native company,只是有個 bot**。這份文件補上整個資料層 — 怎麼存、怎麼讀、怎麼清洗、怎麼備份、怎麼還原。

---

## 整體資料層(一張圖)

```mermaid
flowchart TB
    LINE[OP LINE 群組<br/>C24cf0311116b96f22aced7cc2f7cac8d] -->|webhook| HP[Hermes LINE plugin<br/>1638 行 adapter.py]
    HP --> Agent[op-assistant AIAgent<br/>GPT-5.5 / Codex OAuth]

    Agent <--> SDB[(Hermes session.db<br/>SQLite,raw 對話 log)]
    Agent -->|tool-calling| Tools[6 個 deterministic tool<br/>code-is-law guardrail]

    Tools -->|每次 call 寫一筆| KDB[(closed_loop_kernel<br/>PostgreSQL @ Docker<br/>port 5434,獨立)]
    SDB -->|每小時 ETL cron| KDB

    KDB -->|每日 LLM 整理| Cand[candidates 表<br/>AI 提的改進建議]
    Cand -->|push 摘要| TG[Gary Telegram<br/>@skimm3r918_bot<br/>via default profile]

    TG -->|你批准/駁回| App[approvals 表]
    App --> Art[artifacts 表<br/>版本化「學進去的東西」]
    Art -->|更新| Agent

    KDB -.->|daily pg_dump| Backup[備份三層<br/>daily/weekly/monthly]
    Backup -.->|未來決定| Remote[異地備份<br/>S3 / restic / 第二台機]

    style KDB fill:#9fc5e8
    style SDB fill:#cfe2f3
    style Tools fill:#ffd966
    style TG fill:#ea9999
    style Backup fill:#b6d7a8
```

**怎麼讀**:
- 🔵 **藍**:資料儲存層 — SDB 是 raw,KDB 是結構化
- 🟡 **黃**:Code is Law 工具層 — 寫操作都在這收口
- 🔴 **紅**:Gary 跟系統互動的窗口
- 🟢 **綠**:備份

---

## Hermes session.db 跟 PostgreSQL kernel 的分工(誰存什麼)

| | **Hermes session.db (SQLite)** | **closed_loop_kernel (PostgreSQL)** |
|---|---|---|
| 位置 | `~/.hermes/profiles/op-assistant/state.db` | Docker `127.0.0.1:5434` |
| 內容 | OP 群每一筆訊息原文、bot 每一筆回應、agent 內部 turn-by-turn | events / attempts / failures / candidates / replays / approvals / artifacts(11 表) |
| 寫者 | Hermes runtime(自動) | 我們寫的 6 tool + cron job + Gary 批准 |
| 讀者 | Hermes agent(對話 context)、Hermes search | cron job(整理)、Gary 手動 psql query、未來 Default supervisor |
| 寫密度 | 高(每 turn)但 single-threaded | 中(每 tool call 一筆)multi-writer |
| 結構化程度 | 半結構(JSON-in-text) | 完全結構化(11 表 schema) |
| 跨時間 query 性能 | 差(SQLite 沒分散索引) | 好(PG B-tree + GIN index) |
| 可備份性 | 檔複製 OK | pg_dump 標準流程 |
| 跨 process 共用 | 麻煩(SQLite 寫鎖) | 容易(PG TCP) |
| **角色定位** | **raw log**(原汁原味,debug 用) | **公司大腦的記憶**(學習用) |

**為什麼兩個都要**:Diana 講「record everything」不能光靠 raw log — raw log 跨時間 query 不出 pattern。要 ETL 進結構化表才能做「過去 30 天客訴 top 5」這種分析。SQLite 留 raw 是因為 Hermes 本來就用它跑 agent context,我們順手讀;PG 是「整理過」的版本。

---

## Closed Loop Kernel 是什麼(澄清)

**Closed Loop Kernel** = `closed_loop_kernel/` Python package,**generic** 的閉環學習基礎建設。

**11 張表**(`spec/schema-v0.md`):

| 表 | 內容 | 對 op-assistant 來說裝什麼 |
|---|---|---|
| `events` | append-only sensor 資料 | 每筆 LINE 訊息 + 每筆 bot 回應 |
| `attempts` | 每次 agent 工作的 lifecycle | OP 問 → agent 想 → tool calls → 回 |
| `attempt_lifecycle_events` | attempts 中間狀態(running / completed / failed) | 細粒度追蹤 |
| `failures` | 失敗紀錄(timeout / wrong answer / OP 抱怨) | 「日本團我問了 3 次都答錯」這種 |
| `improvement_candidates` | AI 提的改進(新 keyword / 新規則 / 修 prompt) | 「建議加 keyword『賣得好嗎』to aggregate intent」 |
| `replays` | sandbox 驗證 candidate | 拿過去 7 天 audit log 試新規則,看會不會 regression |
| `approvals` | Gary 批准紀錄 | 「Gary 在 Telegram 按了 ✓」 |
| `artifacts` | 版本化資產 | 每次 SOUL.md / MEMORY.md / tool 規則的版本 |
| `validation_assertions` | replay 通過條件 | 「row_count >= 1 AND error_code IS NULL」 |
| `lifecycle` | 整體狀態流轉 | 從 sensor → candidate → approved → applied 全鏈 |
| `kanban_sync_checkpoint` | 跨來源同步點 | (OHYA pattern 用,op-assistant 暫不用) |

**OHYA 是什麼**(Gary 問):**OHYA = 「好事發生」**(數位有限公司,你另一個專案 / 公司)。`closed_loop_kernel/` 之前用 OHYA 跑端到端 demo(commit `2cebb1a` 「OHYA self-healing loop」)— 證明 kernel 端到端可運作。

**OHYA-specific 檔案**(`closed_loop_kernel/ohya_demo.py` / `ohya_seed.py` / `ohya_approval_bot.py` / `event_reporter.py`)**我們不 import 也不依賴**。我們只用 kernel 主幹(`store.py` / `engine.py` / `sandbox.py` / `sql_sandbox.py`),自己寫一份 `op_assistant_seed.py` + op-assistant 專用 cron job。

**結論**:kernel 程式碼通用,跟「排除其他專案資料」精神不衝突 — 我們重用基礎建設,自己長 op-assistant-specific 的種子資料 + cron 邏輯。

---

## Infrastructure:PostgreSQL Docker container

### 為什麼開新 container(不用既有的)

| 既有 container | 為什麼不用 |
|---|---|
| `wannavegtourcrm-postgres-audit-1` (127.0.0.1:5433) | **CRM 專用,不能碰**(Gary 明確指示) |
| 系統 PG(uid 70 process) | 沒對外 listen,沒設密碼,綁 OS 太緊 |

**獨立新開**:port `127.0.0.1:5434`(不衝突),獨立 data volume,獨立 credentials,獨立 backup。

### docker-compose.yml(放 `~/.hermes/credentials/wannavegtour/op_kernel/`)

```yaml
# ~/.hermes/credentials/wannavegtour/op_kernel/docker-compose.yml
services:
  op-assistant-kernel:
    image: postgres:16-alpine
    container_name: op-assistant-kernel
    restart: unless-stopped
    ports:
      - "127.0.0.1:5434:5432"           # 只 bind localhost
    environment:
      POSTGRES_DB: op_assistant_kernel
      POSTGRES_USER: op_kernel
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    secrets:
      - db_password
    volumes:
      - op-assistant-kernel-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U op_kernel -d op_assistant_kernel"]
      interval: 30s
      timeout: 5s
      retries: 5

secrets:
  db_password:
    file: ./db_password.txt              # mode 600,只 op_kernel 用

volumes:
  op-assistant-kernel-data:
    name: op-assistant-kernel-data
```

### Credentials 檔案

```
~/.hermes/credentials/wannavegtour/op_kernel/
├── docker-compose.yml          (上面這份)
├── db_password.txt             (mode 600,隨機 32 字)
├── kernel-db.json              (mode 600,連線 URL + 給 Python 用)
└── backup/                     (備份輸出位置,見下)
```

`kernel-db.json` 格式:
```json
{
  "host": "127.0.0.1",
  "port": 5434,
  "database": "op_assistant_kernel",
  "user": "op_kernel",
  "password_file": "/home/wannavegtour/.hermes/credentials/wannavegtour/op_kernel/db_password.txt",
  "url_template": "postgresql://op_kernel:{password}@127.0.0.1:5434/op_assistant_kernel"
}
```

### 啟動順序(第一次)

```bash
# 1. 建目錄 + 生密碼
mkdir -p ~/.hermes/credentials/wannavegtour/op_kernel/{backup/daily,backup/weekly,backup/monthly,backup/volume}
chmod 700 ~/.hermes/credentials/wannavegtour/op_kernel/
openssl rand -base64 32 > ~/.hermes/credentials/wannavegtour/op_kernel/db_password.txt
chmod 600 ~/.hermes/credentials/wannavegtour/op_kernel/db_password.txt

# 2. 寫 docker-compose.yml(內容如上)
# 3. 啟動
cd ~/.hermes/credentials/wannavegtour/op_kernel/
docker compose up -d
docker compose ps                      # 看 healthy

# 4. 安裝 psql client(方便 Gary 手動查)
sudo apt install -y postgresql-client

# 5. 測連線
PGPASSWORD=$(cat db_password.txt) psql -h 127.0.0.1 -p 5434 -U op_kernel -d op_assistant_kernel -c "SELECT version();"

# 6. 初始化 11 張表
KERNEL_DATABASE_URL="postgresql://op_kernel:$(cat db_password.txt)@127.0.0.1:5434/op_assistant_kernel" \
  python3 -c "from closed_loop_kernel.store import KernelStore; KernelStore.from_url(KERNEL_DATABASE_URL).initialize()"
# 預期輸出:11 張表 + prevent_mutation trigger 建好

# 7. 把 KERNEL_DATABASE_URL 寫進 op-assistant profile 的 .env(mode 600)
echo "KERNEL_DATABASE_URL=postgresql://op_kernel:$(cat db_password.txt)@127.0.0.1:5434/op_assistant_kernel" \
  >> ~/.hermes/profiles/op-assistant/.env
chmod 600 ~/.hermes/profiles/op-assistant/.env
```

---

## 存取流程(誰怎麼讀寫)

### 寫:6 tool 內每次 call 結束都寫一筆 events

```python
# 在 op-assistant 的 tool wrapper 內(例如 query_intent / fetch_wc_data 等)
from closed_loop_kernel.store import KernelStore
import os, json, uuid, hashlib
from datetime import datetime, timezone

_KERNEL_URL = os.getenv("KERNEL_DATABASE_URL")

def _log_event(event_type: str, payload: dict):
    if not _KERNEL_URL:
        return  # graceful no-op,沒設 URL 不擋運作
    store = KernelStore.from_url(_KERNEL_URL)
    try:
        store.execute(
            "INSERT INTO events (id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()),
             event_type,
             json.dumps(payload, ensure_ascii=False),
             datetime.now(timezone.utc).isoformat()),
        )
    finally:
        store.close()
```

### 讀:Gary 手動查(debug / 報告)

```bash
# 進 PG shell
PGPASSWORD=$(cat ~/.hermes/credentials/wannavegtour/op_kernel/db_password.txt) \
  psql -h 127.0.0.1 -p 5434 -U op_kernel -d op_assistant_kernel

# 內部範例查詢
op_assistant_kernel=> SELECT event_type, COUNT(*) FROM events
                       WHERE created_at > NOW() - INTERVAL '24 hours'
                       GROUP BY event_type;

# 看最近 candidates
op_assistant_kernel=> SELECT id, candidate_type, created_at, status FROM improvement_candidates
                       ORDER BY created_at DESC LIMIT 10;

# 看 Gary 批准歷史
op_assistant_kernel=> SELECT id, candidate_id, approved_by, decided_at FROM approvals
                       ORDER BY decided_at DESC LIMIT 20;
```

### 讀:cron job(整理用,見下節)

### 讀:Default supervisor(未來,deferred)

當 Default profile 之後要當 supervisor 讀 op-assistant 資料時:
- 同樣設 `KERNEL_DATABASE_URL` 在 default profile 的 `.env`
- 用 `KernelStore.from_url()` 讀 events / candidates / artifacts
- (這對應 v2 plan 「Default 讀 sub-profile」的 β 路徑)

---

## 4 條 Cron Job(清洗 / 整理 / 週報 / 月維護)

### Cron 1:每小時 ETL(把 session.db raw → kernel events)

```python
# ~/.hermes/profiles/op-assistant/cron/hourly_etl.py
"""每小時:把 Hermes session.db 過去 1 小時新訊息 → kernel events"""
import sqlite3, json, uuid, os
from datetime import datetime, timezone, timedelta
from closed_loop_kernel.store import KernelStore

SESSION_DB = os.path.expanduser("~/.hermes/profiles/op-assistant/state.db")
KERNEL_URL = os.environ["KERNEL_DATABASE_URL"]

def run():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    # 讀 session.db(唯讀)
    conn = sqlite3.connect(f"file:{SESSION_DB}?mode=ro&immutable=1", uri=True)
    rows = conn.execute(
        "SELECT id, role, content, ts FROM messages WHERE ts > ? ORDER BY ts",
        (cutoff.isoformat(),)
    ).fetchall()
    conn.close()
    if not rows:
        return

    # 增量寫進 kernel events,checkpoint 自帶(events.id unique)
    store = KernelStore.from_url(KERNEL_URL)
    try:
        for msg_id, role, content, ts in rows:
            event_id = f"line_{msg_id}"  # 用 source id deduplicate
            store.execute(
                "INSERT INTO events (id, event_type, payload, created_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT (id) DO NOTHING",
                (event_id,
                 "op_assistant_line_message",
                 json.dumps({"role": role, "content": content, "source": "line"}),
                 ts)
            )
    finally:
        store.close()

if __name__ == "__main__":
    run()
```

**排程**(Hermes cron 或 crontab):每小時 `:05`(避開整點 traffic spike)

### Cron 2:每日 03:00 整理 + 提 candidates + push Telegram

```python
# ~/.hermes/profiles/op-assistant/cron/daily_curate.py
"""每天 03:00:LLM 整理過去 24hr events,找 pattern,提 candidates,push Gary"""
import os, json, uuid
from datetime import datetime, timezone, timedelta
from closed_loop_kernel.store import KernelStore
# (Hermes 內呼叫 LLM 用 hermes_cli 的 helper,這裡 pseudo-code)
from hermes_cli.runtime_provider import call_auxiliary  # 用 Ollama gemma4:e4b 走 auxiliary 路徑

KERNEL_URL = os.environ["KERNEL_DATABASE_URL"]

def run():
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    store = KernelStore.from_url(KERNEL_URL)
    try:
        events = store.fetch_all(
            "SELECT payload FROM events WHERE event_type = ? AND created_at > ? "
            "ORDER BY created_at",
            ("op_assistant_line_message", cutoff)
        )
        if not events:
            return

        # 用 gemma4:e4b(便宜,本地)做 first-pass 分類
        # 找:重複問句 / 客訴關鍵字 / 未涵蓋意圖
        prompt = build_curation_prompt(events)  # 給 LLM 條目化的 JSON
        result = call_auxiliary("compression", prompt)  # 已設定 ollama gemma4:e4b
        patterns = json.loads(result)  # 強制 JSON output

        # 每個 pattern 寫進 candidates
        for p in patterns:
            store.execute(
                "INSERT INTO improvement_candidates "
                "(id, candidate_type, payload, status, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()),
                 p["type"],     # e.g. "new_intent_keyword"
                 json.dumps(p),
                 "pending_approval",
                 datetime.now(timezone.utc).isoformat())
            )

        # Push Telegram(走 default profile)— 這部分依靠 Hermes 跨 platform delivery
        send_telegram_summary(patterns)
    finally:
        store.close()

# (build_curation_prompt / send_telegram_summary 細節在實作時補)
```

**排程**:每日 `03:00`(OP 睡了,traffic 低,DB load 小)

### Cron 3:每週日 04:00 週報

```python
# ~/.hermes/profiles/op-assistant/cron/weekly_report.py
"""每週日 04:00:過去 7 天 candidates + approvals,生週報推 Telegram + 寫 artifact"""
# 細節:
# - 統計 candidates by type(新意圖 X 個、客訴 Y 個、規則 gap Z 個)
# - 統計 approvals(批了 N 個、駁回 M 個)
# - 列「Gary 批的趨勢」(你最常批准什麼類型 → 學進去)
# - 摘要寫進 artifacts table(weekly_report_YYYY-WW)
# - push 摘要進 Telegram
```

**排程**:每週日 `04:00`

### Cron 4:每月 1 日 05:00 維護

```python
# ~/.hermes/profiles/op-assistant/cron/monthly_maintenance.py
"""每月 1 日 05:00:archive 30 天前 events / vacuum / 觸發備份"""
# 細節:
# - 把 30 天前 events 壓進 events_archive 表(冷儲存,讀慢但省空間)
# - VACUUM ANALYZE 全 DB
# - 觸發 monthly pg_dump(見備份節)
# - 檢查 backup 鏈完整性,如果某天 daily 缺,寫 alert 進 Telegram
```

**排程**:每月 1 日 `05:00`

### Cron 註冊

兩種方式選一:

**選 A:Hermes 內建 cron**(`~/.hermes/profiles/op-assistant/cron/*.py` 自動掃描)
- 在 cron 檔頂端寫 metadata `# @schedule: 0 3 * * *`
- Hermes gateway 跑 dispatcher 會自動執行

**選 B:系統 crontab + venv**
- 純 OS cron 跑 python script
- 更熟悉、更可控

**推薦 A**(走 Hermes 原生,跟其他 profile 統一管理)。

---

## 備份(三層 + Restore)

### 為什麼三層

- **L1 daily** — 抓「上一筆好的」,recover from yesterday
- **L2 weekly** — 跨週 recovery,保留比 daily 久
- **L3 monthly** — 跨月 archive,合規 / 長期追溯

### Backup script

```bash
#!/bin/bash
# ~/.hermes/credentials/wannavegtour/op_kernel/backup.sh
# 用法:bash backup.sh daily|weekly|monthly

set -euo pipefail
TYPE="${1:?usage: backup.sh daily|weekly|monthly}"
BASE="$HOME/.hermes/credentials/wannavegtour/op_kernel"
DIR="$BASE/backup/$TYPE"
mkdir -p "$DIR"
chmod 700 "$DIR"

case "$TYPE" in
  daily)   FNAME="$(date +%Y-%m-%d).sql.gz" ;;
  weekly)  FNAME="$(date +%Y-W%V).sql.gz" ;;
  monthly) FNAME="$(date +%Y-%m).sql.gz" ;;
  *) echo "bad type"; exit 1 ;;
esac

OUT="$DIR/$FNAME"
PASSWORD=$(cat "$BASE/db_password.txt")

docker exec op-assistant-kernel pg_dump \
  -U op_kernel -d op_assistant_kernel \
  --no-owner --no-acl \
  | gzip > "$OUT"

chmod 600 "$OUT"

# Retention
case "$TYPE" in
  daily)   find "$DIR" -name "*.sql.gz" -mtime +14 -delete ;;     # 留 14 天
  weekly)  find "$DIR" -name "*.sql.gz" -mtime +90 -delete ;;     # 留 ~12 週
  monthly) find "$DIR" -name "*.sql.gz" -mtime +400 -delete ;;    # 留 ~12 個月
esac

# 結束時報自己的健康(write events,給 cron 4 月度檢查讀)
echo "[$(date -Iseconds)] backup ${TYPE}: $FNAME ($(du -h "$OUT" | cut -f1))" >> "$BASE/backup/backup.log"
```

### Backup 排程(crontab,系統層)

```cron
# crontab -e
0 2 * * *     bash ~/.hermes/credentials/wannavegtour/op_kernel/backup.sh daily
30 2 * * 0    bash ~/.hermes/credentials/wannavegtour/op_kernel/backup.sh weekly
0 3 1 * *     bash ~/.hermes/credentials/wannavegtour/op_kernel/backup.sh monthly
```

### Volume backup(每月 1 次)

整個 Docker volume 打包加密:

```bash
# ~/.hermes/credentials/wannavegtour/op_kernel/backup_volume.sh
docker compose down  # 確保 consistent snapshot
sudo tar czf "backup/volume/$(date +%Y-%m).tar.gz" \
  /var/lib/docker/volumes/op-assistant-kernel-data/
docker compose up -d
```

(這是「打包整個 PG 資料夾」的方式,跟 pg_dump 互補:pg_dump 是邏輯備份可跨版本,volume 是物理備份可整套搬。)

### Restore runbook

**場景 A:DB 壞了 / 想 rollback 到昨天**

```bash
cd ~/.hermes/credentials/wannavegtour/op_kernel/
docker compose down
docker volume rm op-assistant-kernel-data    # ⚠️ 確認你真的要重置
docker compose up -d
sleep 10  # 等 PG 起來
gunzip < backup/daily/2026-05-25.sql.gz | \
  docker exec -i op-assistant-kernel \
    psql -U op_kernel -d op_assistant_kernel
```

**場景 B:整台機壞了,新機重建**

```bash
# 1. 新機安裝 docker
# 2. git clone Gary repo
# 3. 從備份移植 credentials + backup 檔到新機
# 4. 同上 restore 流程
```

### Monitoring(怎麼知道 DB 健康)

簡單 monitoring(寫進 Cron 4):

```python
# 每月維護時檢查:
# 1. 最新 daily backup 是不是 <24hr
# 2. 最新 weekly backup 是不是 <8 天
# 3. PG container is healthy (docker inspect)
# 4. DB size growth rate(events 表 row count 異常嗎)
# 5. backup.log 有沒有失敗紀錄

# 不健康 → 寫進 events table 一筆 "kernel_health_warning" + push Telegram
```

更完整的 monitoring(Prometheus + Grafana)等之後流量大再上,現在先以 cron-based 簡單檢查為主。

---

## 異地備份(未來決定 — 不在本份 scope)

選項:
- **rsync to 第二台機**(最簡單,需要有第二台)
- **restic + S3 / B2 / wasabi**(de-dupe,加密,雲端)
- **borg + 自架 backup server**(self-hosted,功能強)

**現階段不做**,但本份 backup 結構(`~/.hermes/credentials/wannavegtour/op_kernel/backup/`)是固定路徑,將來起異地備份直接掛上去。

---

## 跟 Hermes session.db 的具體分工(再次強調)

| 場景 | 去 session.db 拿 | 去 kernel 拿 |
|---|---|---|
| 「上次 OP 同事問什麼」 | ✅ raw 全文 | ⚠️ 結構化但摘要過 |
| 「過去 30 天客訴有幾筆」 | ❌ 跨時間 query 慢 | ✅ `SELECT COUNT(*) FROM events WHERE ...` |
| 「Agent 跑某筆訊息的完整 trace」 | ✅ 對話 turn-by-turn | ✅ attempt + tool calls |
| 「Gary 上個月批准什麼」 | ❌ Telegram 對話不在 session.db | ✅ `approvals` table |
| 「op-assistant SOUL.md 過去版本」 | ❌ 不存 | ✅ `artifacts` table |
| Debug 一筆訊息為什麼回錯 | ✅ 看 session 上下文 | ✅ 看 failures table + replay |

**心法**:session.db 是「**現場錄影**」,kernel 是「**事後整理過的檔案**」。兩個都要,角色不同。

---

## NOT in scope(明確排除)

- ❌ **OHYA 的 demo / seed / approval bot** — 不 import 也不 reuse(只用 kernel 主幹)
- ❌ **wannavegtourcrm-postgres-audit container** — 完全不碰
- ❌ **既有系統 PG(uid 70)** — 不啟用、不設定
- ❌ **異地備份** — 留待之後決定(rsync / restic / borg 任選)
- ❌ **Prometheus / Grafana 監控** — 等流量大再上,現在 cron 檢查夠
- ❌ **跨 profile read 機制(α/β/γ)** — Default supervisor 暫緩
- ❌ **多 tenant** — 單 wannavegtour,不做 tenant 隔離 schema
- ❌ **PII 去識別化 / GDPR-grade 加密** — 留待之後決定(現階段 mode 600 + container 內網)

---

## 在新機重建的 12 步(將來用得到)

1. 裝 Docker + docker-compose plugin
2. `sudo apt install postgresql-client`
3. `git clone git@github.com:garyyang1001/Gary.git`(本 repo)
4. 把 `~/.hermes/credentials/wannavegtour/op_kernel/` 整個移植過來(含 `db_password.txt`, `docker-compose.yml`, `backup/`)
5. 確認 `chmod 700` 目錄 + `chmod 600` 密碼檔
6. `cd ~/.hermes/credentials/wannavegtour/op_kernel/ && docker compose up -d`
7. `docker compose ps` 看 healthy
8. 找最新 daily backup 還原(見 Restore runbook 場景 B)
9. 寫 `KERNEL_DATABASE_URL` 進 `~/.hermes/profiles/op-assistant/.env`(mode 600)
10. `systemctl --user restart hermes-gateway.service`
11. 驗證:`PGPASSWORD=... psql ... -c "SELECT COUNT(*) FROM events;"` 應跟備份時一致
12. 加 crontab 4 條(見 Cron 註冊節)

---

## 跟其他文件的關係

| 本文件 ↔ | 對應 doc | 關係 |
|---|---|---|
| 11 表 schema | `spec/schema-v0.md` | 我引用,不修改 |
| 6 tool 設計 | `2026-05-26-op-bot-hermes-harness-spec.md` | tool 寫到 kernel 是兩邊都要看 |
| 整體 bot map | `2026-05-26-wannavegtour-full-company-bot-map-v2.md` | 本文件是 v2 plan 的「資料層細節」展開 |
| Code is Law 原則 | `spec/code-is-law-v0.md` | Cron job 也走 Code is Law(寫成 Python 不是 prompt) |
| Diana / Gary 逐字稿 | `EN7frwQIbKc-transcript.txt` / `X_JsIHUfUjc-transcript.txt` | 「record everything / queryable」直接 anchor 在這 |
| OHYA demo | `closed_loop_kernel/ohya_demo.py` | 範例,不 reuse,但證明 kernel 可運作 |

---

## 開放問題(Gary 之後拍板)

1. **Cron 註冊走 Hermes 還是系統 crontab**(推薦 Hermes)
2. **每日 curation 用 gemma4:e4b 還是 GPT-5.5**(推薦 gemma4 — 便宜 + 本地 + 寫進 auxiliary 已設好)
3. **Telegram 推週報的頻率上限**(別變垃圾,推薦每日 1 則摘要 + 重大事件即時)
4. **異地備份**(現在不做,但要不要先預留 rsync target 路徑)
5. **Retention 政策**(預設 14d/12w/12mo,要不要更長 / 更短)
6. **PII 處理**(OP 對話可能含同事姓名 / 客戶資訊 — 要不要在 ETL 階段 redact)
7. **Backup 加密**(目前 mode 600,要不要再 gpg 加密一層 — 異地備份才需要)

---

## 動工順序(確認後)

1. ✅ 本份 doc commit + push(現在做)
2. ⏳ Gary review
3. ⏳ 動工:寫 Codex brief,讓 Codex 執行 PG container 啟動 + schema initialize + env 設定,Claude 驗證
4. ⏳ 寫 SOUL.md / MEMORY.md / USER.md(基本架構)
5. ⏳ 寫 6 個 tool(把 kernel write 嵌進每個 tool)
6. ⏳ 寫 4 條 cron job
7. ⏳ 寫 backup script + crontab
8. ⏳ 整套 smoke test(端到端跑一次)
9. ⏳ Cutover(切 LINE webhook → Hermes,停舊 listener)
