# OP Assistant 資料層 + Kernel DB 完整操作文件 v2

**Supersedes**: `docs/plans/2026-05-26-op-kernel-db-operations.md` (commit `0d21527`)
**狀態**: DRAFT — 等 Gary 確認 → 交 Codex review → Codex 執行
**日期**: 2026-05-26
**作者**: Claude(based on Gary 2026-05-26 修訂指示 + kernel schema 真實對照)
**Cross-refs**:
- v1 doc(本份取代它,但保留 audit findings)
- `closed_loop_kernel/postgres.py`(14 表真實 schema 來源)
- `closed_loop_kernel/store.py`(`json_param()` helper)
- `closed_loop_kernel/ohya_demo.py` / `event_reporter.py`(實際 INSERT 範例)
- `spec/schema-v0.md` / `spec/code-is-law-v0.md`
- `docs/plans/2026-05-26-wannavegtour-full-company-bot-map-v2.md`
- `docs/plans/2026-05-26-op-bot-hermes-harness-spec.md`

---

## v2.1 修訂(2026-05-26,Codex review 後)

Codex review 找出 2 BLOCKER + 3 HIGH + 8 MEDIUM,本份逐條修正:

| Codex 發現 | 修在哪 | 修法 |
|---|---|---|
| **B1**:cron `--script` 路徑必須相對 + 放 profile 內 | Cron 1/2/3/4 + register 段 | `--script op_assistant_etl.py`(不是絕對路徑);scripts 放 `~/.hermes/profiles/op-assistant/scripts/` |
| **B2**:`--no-agent` cron 不會 auto-load profile .env | 每個 cron script 頂端 | 加 `_load_profile_env()` helper 手動載 |
| **H1**:Schema init NameError + password URL-unsafe | 啟動順序 Step 6 | `os.environ['...']` + `openssl rand -hex 24`(不是 base64) |
| **H2**:cron timeout default 120s < Ollama 300s | 註冊段 | 加 `hermes config set cron.script_timeout_seconds 300` |
| **H3**:SQLite `immutable=1` WAL 不安全 | Cron 1 ETL | `mode=ro` + `PRAGMA busy_timeout=30000` |
| **M1**:11 表 → 14 表 + 6 trigger | 全文 | 已 replace_all |
| **M2**:summary jobs uuid4 不 idempotent | Cron 2/3 | `uuid5(NAMESPACE, period_key)` + `ON CONFLICT DO NOTHING` |
| **M3**:weekly `_push_weekly_report() = pass` | Cron 3 | 實作完整 push,不留假動作 |
| **M4**:monthly subprocess fail 丟失 alert | Cron 4 | try/except 包,還是要寫健康事件 |
| **M5**:mapping JSONDecodeError 不處理 | Cron 1 ETL | catch + 寫 health event,繼續跑 |
| **L1**:Telegram exception 可能洩 token URL | Cron 2/3 helpers | catch RequestException,只記 status code,寫 health event |
| **L2**:event_type `artifact_applied` → `candidate_applied` | Lifecycle 表 | 已改(per `engine.py:429`) |
| **L3**:backup cron PATH 不全 | backup.sh | `/usr/bin/docker` 絕對路徑 + stderr 進 log |
| **F1**:Pre-launch replay scripts 沒寫 | Pre-launch test 段 | 加 3 個 script spec(replay_audit / replay_through / diff_replies) |

**未在本 doc 修(留 Codex execute 階段或更後面)**:
- 多 PG container 之間的 port 登記表(LOW,先放沒事)
- multi-tenant governance 規則(STRATEGIC,目前單公司不需要)

---

## 變更摘要(對照 v1)

Gary 2026-05-26 給 v1 review,5 大類修訂 + 我做的 schema audit 修正:

| # | 類別 | v1 | v2 |
|---|---|---|---|
| 1 | Cron 1 ETL 頻率 | 每 1 hr | **每 4 hr**(降密度) |
| 2 | Cron 2 daily curation | 03:00 | **09:00**(早上產出給你早會看) |
| 3 | Cron 3 weekly | Sun 04:00 | **Mon 09:00**(週一早上看週報) |
| 4 | Cron 4 monthly | 1 日 05:00 | 同(維持) |
| 5 | Cron 註冊方式 | A/B 二選一 | **走 Hermes 內建** |
| 6 | Daily curation 模型 | gemma4:e4b(臨時) | **gemma4:e4b(維持,本機已有,跟 compression 共用)** |
| 7 | 異地備份 | 待後話 | **明確暫緩,不做** |
| 8 | 備份加密 | 待後話 | **明確不做** |
| 9 | PII 處理 | 開放問題 | **NEW:OP 對話確認含同事姓名 + 客戶資料,須 user_id→name mapping** |
| 10 | Pre-launch test | 沒提 | **NEW:拉舊 LINE 對話 replay + 出 test report** |
| 11 | Multi-PG container 支援 | 沒提 | **NEW:未來別部門可開獨立 PG container** |
| 12 | Kernel candidate 策略 | LLM 直接寫(錯) | **修正:LLM 寫 events,真實 failure 才生 candidate** |
| 13 | improvement_candidates schema | 寫錯 5 個欄位 | **修正:照 kernel 真實 schema 寫(失敗 FK / artifact FK / patch_type / etc.)** |
| 14 | JSON 寫入 | `json.dumps()` | **修正:用 `closed_loop_kernel.store.json_param()`** |

---

## 重要 Audit 發現(v1 doc 有真實 schema drift,留檔教訓)

我對照 `closed_loop_kernel/postgres.py` 真實 `CREATE TABLE`,v1 有 3 個 drift:

### Drift A:`improvement_candidates` 欄位寫錯

```python
# v1 寫的(❌ 跑不起來)
INSERT INTO improvement_candidates 
  (id, candidate_type, payload, status, created_at)
VALUES (?, 'new_intent_keyword', '...', 'pending_approval', NOW())
```

**真實 schema**(`postgres.py:120-135`):
```sql
CREATE TABLE improvement_candidates (
    id UUID PRIMARY KEY,
    failure_id UUID NOT NULL REFERENCES failures(id),
    target_artifact_id UUID NOT NULL REFERENCES artifacts(id),
    target_artifact_name VARCHAR(255) NOT NULL,
    target_artifact_type VARCHAR(100) NOT NULL,
    target_artifact_version INT NOT NULL,
    base_artifact_hash VARCHAR(64) NOT NULL,
    patch_type VARCHAR(100) NOT NULL,
    proposed_content TEXT NOT NULL,
    validation_assertions JSONB NOT NULL,
    rollback_plan JSONB NOT NULL,
    status VARCHAR(50) CHECK (status IN ('draft','sandbox_verified','approved','rejected','applied')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

❌ 沒 `candidate_type`(實際叫 `patch_type`)
❌ 沒 `payload`(被拆 `proposed_content` / `validation_assertions` / `rollback_plan`)
❌ `status='pending_approval'` 違反 CHECK(只准 5 個值,初始是 `draft`)
❌ 缺 6 個 NOT NULL 必填欄位(`failure_id`、`target_artifact_*` 等)

### Drift B:語意層級錯(更嚴重)

`improvement_candidates` **不是「AI 整理出的客訴/建議」這種摘要** — 它是「**把 artifact X 從 v1 改成 v2**」的工程級補丁。要先有具體 `failure` + 具體 `artifact`。

v1 寫「daily curation → LLM 直接生 candidates」走不了 kernel 流程。**正確分層**(下面 Lifecycle 表會講)。

### Drift C:JSON 寫入沒用 `json_param()`

```python
# v1 寫的(JSONB 可能不認識)
json.dumps(payload, ensure_ascii=False)

# 正確(kernel canonical pattern,見 event_reporter.py:117)
from closed_loop_kernel.store import json_param
json_param(payload)
```

`json_param` 內部還是 `json.dumps`,但 wrap 成 `JsonParam` 型別讓 psycopg 認識 → 進 JSONB。直接 dumps 字串會被 PG 當 TEXT,JSONB query 吃不到。

---

## 整體資料層(Mermaid v2,refined,無顏色)

```mermaid
flowchart TB
    LINE[OP LINE 群組] -->|webhook| HP[Hermes LINE plugin]
    HP --> Agent[op-assistant AIAgent<br/>GPT-5.5 / Codex OAuth]

    Agent <--> SDB[(Hermes session.db<br/>SQLite,raw 對話 log)]
    Agent -->|每次 tool call| Tools[6 個 deterministic tool]

    Tools -->|寫 attempts + tool_calls| KDB[(closed_loop_kernel<br/>PostgreSQL @ Docker 5434)]
    SDB -->|Cron 1<br/>每 4 hr ETL| KDB
    Tools -->|失敗時 寫 failures| KDB

    KDB -->|Cron 2 每日 09:00<br/>gemma4:e4b 整理| Sum[event_type=<br/>daily_curation_summary]
    Sum -->|push 摘要| TG[Gary Telegram<br/>@skimm3r918_bot]

    TG -->|你標記 要修| Mark[event_type=<br/>gary_marked_for_fix]
    Mark -->|AI 看 failure +<br/>提具體補丁| Cand[improvement_candidates<br/>含 failure_id + target_artifact +<br/>patch_type + proposed_content +<br/>validation_assertions + rollback_plan]

    Cand -->|sandbox replay| Rep[replays]
    Rep -->|過了 推 Telegram| TG
    TG -->|你按 ✓| App[approvals]
    App -->|apply_candidate<br/>4 點指紋防線| Art[artifacts<br/>version+1]
    Art -->|hot reload| Agent

    KDB -.->|Cron 4 backup<br/>pg_dump| Backup[三層備份<br/>daily 14d / weekly 12w / monthly 12mo<br/>無加密 無異地]
```

**怎麼讀**:
- 上半(LINE → Hermes → tools → kernel) = 即時路徑
- 中段(events / attempts / failures) = 自然累積
- 下半(curation → 你標記 → candidate → replay → approval → apply) = **完整 kernel 工程級 self-improvement loop**(只在「真要改 artifact」時才走)

---

## 完整 Lifecycle 表(每筆 LINE 訊息一路到 SOUL.md 更新)

| 階段 | 寫去 | 何時 | 誰 | 範例內容 |
|---|---|---|---|---|
| 1 | `events` (`event_type='op_line_message'`) | OP 講話即時 | Hermes LINE plugin → ETL cron | `{user_id, group_id, text, ts}` |
| 2 | `attempts` | agent 開始回應 | op-assistant tool wrapper | `{event_id, input={query}, output={reply,intent}, status='success'|'failed'}` |
| 3 | `tool_calls`(每 tool call 一筆) | agent 內每次 call | tool wrapper | `{attempt_id, tool_name, arguments, result, status}` |
| 4 | `failures`(僅當 agent 答錯 / OP 抱怨) | validator 偵測 OR Gary 標 | tool wrapper / 你 | `{attempt_id, failure_type='wrong_answer', context}` |
| 5 | `events` (`event_type='daily_curation_summary'`) | 每日 09:00 | Cron 2 + gemma4:e4b | `{period: '2026-05-26', patterns: [...], counts: {...}}` |
| 6 | Telegram push | 同上 | Cron 2 | 摘要 + 你可回「這個要修」 |
| 7 | `events` (`event_type='gary_marked_for_fix'`) | 你 Telegram 回覆 | Gary | `{summary_event_id, marked_failures: [ids], note}` |
| 8 | `improvement_candidates`(真要改 artifact 才生) | Hermes 主 Agent 或你手動 | AI proposer | 完整 12 欄(見上 schema) |
| 9 | `replays` | candidate 寫完即跑 | sandbox runner | `{candidate_id, validation_results, sandbox_schema}` |
| 10 | Telegram push「ready to approve」 | replay 過 | Cron 3 / runner | 等你按 ✓ |
| 11 | `approvals` | 你 Telegram 回 ✓ | Gary | `{candidate_id, approved_by='gary', decision='approved'}` |
| 12 | `artifacts` (version+1) + `is_active=true` | approval 過 | apply_candidate() | 新 SOUL.md / 新 query_parser regex / etc. |
| 13 | `events` (`event_type='candidate_applied'`) | apply 完 | apply_candidate() | `{candidate_id, artifact_id, new_version}`(per `engine.py:429`) |
| 14 | Agent hot reload 新 artifact | 立刻 | Hermes runtime | 之後行為照新版 |

**關鍵**:**只有第 8-13 步走 kernel 工程級流程**,前面 1-7 步是「累積 + curation + 你標記」的輕量資料層。多數時候 1-7 在跑,8-13 一週可能只動 1-2 次。

---

## Infrastructure:PostgreSQL Docker container(同 v1,保留)

### 為什麼開新 container

| 既有 container | 為什麼不用 |
|---|---|
| `wannavegtourcrm-postgres-audit-1` (127.0.0.1:5433) | CRM 專用,**Gary 明確不能碰** |
| 系統 PG(uid 70 process) | 沒對外 listen,綁 OS,跨機麻煩 |

**獨立新開**:port `127.0.0.1:5434`,獨立 volume,獨立 credentials,獨立 backup。

### Multi-PG 未來支援(NEW)

Gary 提:**未來如果有新部門 / 新資料,可開多個 Docker PostgreSQL**(eg 行銷 bot 用 `5435`、客戶監聽 bot 用 `5436`)。本份 spec 為 op-assistant 設 5434,**保留 5435+ 給之後別部門開**。命名規則:`<dept>-kernel` container,DB 名 `<dept>_kernel`,user `<dept>_kernel`。

### docker-compose.yml

```yaml
# ~/.hermes/credentials/wannavegtour/op_kernel/docker-compose.yml
services:
  op-assistant-kernel:
    image: postgres:16-alpine
    container_name: op-assistant-kernel
    restart: unless-stopped
    ports:
      - "127.0.0.1:5434:5432"
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
    file: ./db_password.txt

volumes:
  op-assistant-kernel-data:
    name: op-assistant-kernel-data
```

### Credentials 結構

```
~/.hermes/credentials/wannavegtour/op_kernel/   (mode 700)
├── docker-compose.yml
├── db_password.txt                              (mode 600, 32 字隨機)
├── kernel-db.json                               (mode 600, 連線設定 metadata)
├── op_mapping.json                              (mode 600, NEW — 見下節 PII)
└── backup/
    ├── daily/   (mode 700, 內 .sql.gz mode 600)
    ├── weekly/
    ├── monthly/
    └── backup.log
```

`kernel-db.json`:
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

### 啟動順序(Codex 執行階段做)

```bash
# 1. 建目錄 + 生密碼
mkdir -p ~/.hermes/credentials/wannavegtour/op_kernel/{backup/daily,backup/weekly,backup/monthly}
chmod 700 ~/.hermes/credentials/wannavegtour/op_kernel/
openssl rand -hex 24 > ~/.hermes/credentials/wannavegtour/op_kernel/db_password.txt   # hex(URL-safe);base64 含 /+= 會炸 PG URI
chmod 600 ~/.hermes/credentials/wannavegtour/op_kernel/db_password.txt

# 2. 寫 docker-compose.yml(上面 YAML)

# 3. 啟動
cd ~/.hermes/credentials/wannavegtour/op_kernel/
docker compose up -d
sleep 10
docker compose ps    # 確認 healthy

# 4. 裝 psql client(Gary 手動查 + backup script 用)
sudo apt install -y postgresql-client

# 5. 測連線
PGPASSWORD=$(cat db_password.txt) psql -h 127.0.0.1 -p 5434 \
  -U op_kernel -d op_assistant_kernel \
  -c "SELECT version();"

# 6. 初始化 schema(14 表 + prevent_mutation triggers)
cd "/home/wannavegtour/Desktop/AI Native Company/Gary"
KERNEL_DATABASE_URL="postgresql://op_kernel:$(cat ~/.hermes/credentials/wannavegtour/op_kernel/db_password.txt)@127.0.0.1:5434/op_assistant_kernel" \
  python3 -c "import os; from closed_loop_kernel.store import KernelStore; KernelStore.from_url(os.environ['KERNEL_DATABASE_URL']).initialize()"
# 預期:14 表 + 6 個 prevent_mutation trigger 建好 (append-only: events / attempts /
# attempt_lifecycle_events / tool_calls / decisions / approvals)

# 7. 把 KERNEL_DATABASE_URL 寫進 op-assistant profile .env
KERNEL_URL="postgresql://op_kernel:$(cat ~/.hermes/credentials/wannavegtour/op_kernel/db_password.txt)@127.0.0.1:5434/op_assistant_kernel"
echo "KERNEL_DATABASE_URL=$KERNEL_URL" >> ~/.hermes/profiles/op-assistant/.env
chmod 600 ~/.hermes/profiles/op-assistant/.env

# 8. 驗證:Hermes 看得到
hermes -p op-assistant config show | grep KERNEL || echo "(env not loaded yet, restart needed)"
```

---

## 存取流程(正確 — 含 v1 修正)

### 寫入 events(canonical pattern)

```python
# 在 op-assistant 的 tool wrapper 內(將來實作 6 tool 會用到)
from closed_loop_kernel.store import KernelStore, json_param   # ← 用 json_param,不要 json.dumps
import os, uuid
from datetime import datetime, timezone

_KERNEL_URL = os.environ["KERNEL_DATABASE_URL"]   # 沒設就讓它 crash(嚴格,不要 silent fallback)

def _log_event(event_type: str, payload: dict) -> str:
    """寫一筆 events,return id 供 attempts 引用"""
    eid = str(uuid.uuid4())
    store = KernelStore.from_url(_KERNEL_URL)
    try:
        store.execute(
            "INSERT INTO events (id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
            [eid, event_type, json_param(payload), datetime.now(timezone.utc).isoformat()]
        )
    finally:
        store.close()
    return eid
```

### 寫入 attempts(每個 OP 訊息一筆)

```python
def _record_attempt(event_id: str, input_data: dict, output_data: dict, status: str, err: str = None) -> str:
    aid = str(uuid.uuid4())
    store = KernelStore.from_url(_KERNEL_URL)
    try:
        store.execute(
            "INSERT INTO attempts (id, event_id, status, input, output, error_message, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [aid, event_id, status,
             json_param(input_data),
             json_param(output_data) if output_data else None,
             err,
             datetime.now(timezone.utc).isoformat()]
        )
    finally:
        store.close()
    return aid
```

### 寫入 failures(僅當答錯)

```python
def _record_failure(attempt_id: str, failure_type: str, context: dict) -> str:
    fid = str(uuid.uuid4())
    store = KernelStore.from_url(_KERNEL_URL)
    try:
        store.execute(
            "INSERT INTO failures (id, attempt_id, failure_type, context, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [fid, attempt_id, failure_type, json_param(context), 'open',
             datetime.now(timezone.utc).isoformat()]
        )
    finally:
        store.close()
    return fid
```

### 讀(Gary 手動查)

```bash
PGPASSWORD=$(cat ~/.hermes/credentials/wannavegtour/op_kernel/db_password.txt) \
  psql -h 127.0.0.1 -p 5434 -U op_kernel -d op_assistant_kernel

# 過去 24hr 訊息數
=> SELECT event_type, COUNT(*) FROM events
   WHERE created_at > NOW() - INTERVAL '24 hours'
   GROUP BY event_type;

# 過去 7 天失敗
=> SELECT failure_type, COUNT(*) FROM failures
   WHERE status='open' AND created_at > NOW() - INTERVAL '7 days'
   GROUP BY failure_type;

# 待你批准的 candidates
=> SELECT id, target_artifact_name, patch_type, status, created_at FROM improvement_candidates
   WHERE status='sandbox_verified'
   ORDER BY created_at DESC;

# 你過去批准了什麼
=> SELECT a.created_at, a.decision, c.target_artifact_name, c.patch_type
   FROM approvals a JOIN improvement_candidates c ON a.candidate_id = c.id
   ORDER BY a.created_at DESC LIMIT 20;
```

---

## PII 處理 + User ID 對應(NEW,Gary 2026-05-26 要求)

Gary 確認:**OP 對話確實包含同事姓名 + 客戶資料**。不能假裝沒有。

### User ID → 同事名稱對應表(2026-05-26 已 seed)

實檔 `~/.hermes/credentials/wannavegtour/op_mapping.json`(mode 600,已寫入)。

**真實群組**:`玩素食旅行社OP Team`(group_id `C24cf0311116b96f22aced7cc2f7cac8d`),total members 13 人。

**已知 9 人**(2026-05-26 13:20 push 系統測試訊息後增量更新):

| User ID | 暱稱(LINE displayName) | 取得來源 |
|---|---|---|
| `Ufd364c78f6041ab4e30d37e804017b7a` | Gary | audit log(自己) |
| `Uec2911424093f80c1533579150ac80c3` | 洪先生 | audit log |
| `U366928d65b6287063b4592e32c5a9f05` | Mickey廖美怡 | audit log |
| `Uee711d925e84c66126bd65c99ad5de45` | 蔡妙齡 | audit log + 主動回「收到」 |
| `U3227b5769b3f246ffb30b1718704e6ac` | 姿婕❤️ | audit log |
| `Uf702ff1addffe56caee7cd632bf3d1cd` | **雅虎Joy** | push 測試後回「收到」 |
| `Uef4903526cede89ff74b1a82fbf966f4` | **Sin mei** | push 測試後回「收到」 |
| `U<...>eb98e7d541da` | **Allen** | push 測試後回「收到」 |
| `U<...>19b18a9966e1` | **weiru** | push 測試後回「收到」 |

**未知 4 人**:群裡共 13 人,9 個已 resolve,**4 個還沒在 audit log 發過言 → user_id 未知**。

LINE API `/v2/bot/group/{id}/members/ids` 回 HTTP 403(需要 LINE OA 升級成「認證帳號」)。

**剩 6 人增量補完策略**(已在 mapping JSON 標註):
- ETL Cron 1 跑時遇到 mapping 沒有的 user_id → 自動 query Profile API → 寫回 mapping
- 任何時間有同事在群裡發第一句話 → 同上自動 resolve
- Gary 可選擇升級 LINE OA 認證帳號 → 一次拿 13 人(免費,1-2 週審核)

**補完策略**(已在 mapping JSON 的 `resolution_method.auto_update` 標註):
- 增量補:Cron 1 ETL 遇到 mapping 沒有的 user_id → 自動 query `/v2/bot/group/{group_id}/member/{user_id}` → 寫回 mapping(需加 file lock)
- 一次補:Gary 把 OA 升級成認證帳號(免費,需審核 1-2 週,提供統編 / 公司資料)→ 用 `/members/ids` 一次拿 13 人

**完整 schema**(已寫入檔案):

```json
{
  "schema_version": 1,
  "generated_at": "2026-05-26T13:12:35",
  "company": "wannavegtour / 阿玩旅遊",
  "groups": {
    "C24cf0311116b96f22aced7cc2f7cac8d": {
      "name": "玩素食旅行社OP Team",
      "purpose": "OP 部門內部群,小弟服務對象",
      "total_members_in_line": 13,
      "members_known_count": 5,
      "members_unknown_count": 8,
      "members_unknown_reason": "需 LINE OA 認證帳號才能 enumerate all member ids (API 403)"
    }
  },
  "user_id_to_name": {
    "Ufd364c78f6041ab4e30d37e804017b7a": "Gary",
    "Uec2911424093f80c1533579150ac80c3": "洪先生",
    "U366928d65b6287063b4592e32c5a9f05": "Mickey廖美怡",
    "Uee711d925e84c66126bd65c99ad5de45": "蔡妙齡",
    "U3227b5769b3f246ffb30b1718704e6ac": "姿婕❤️"
  },
  "resolution_method": {...},
  "notes": [...]
}
```

### ETL 階段 resolve user_id → name

Cron 1 ETL 寫進 events 時自動 resolve:

```python
import json
_MAPPING = json.load(open("/home/wannavegtour/.hermes/credentials/wannavegtour/op_mapping.json"))
_USER_MAP = _MAPPING["user_id_to_name"]
_GROUP_MAP = _MAPPING["group_id_to_name"]

def _resolve_payload(raw: dict) -> dict:
    return {
        **raw,
        "user_name": _USER_MAP.get(raw.get("user_id"), "未知 OP"),
        "group_name": _GROUP_MAP.get(raw.get("group_id"), "未知群"),
    }
```

`events.payload` 同時保留 `user_id`(原始)+ `user_name`(可讀)— 你 psql 查就看到名字,debug 也找得到 raw id。

### 客戶資料 redaction(初版策略,可疊代)

**目前不做主動 redact**,理由:
- OP 對話討論客戶都是內部需要(訂位 / 行程細節)
- 機器在 mode 600 file,Tailscale 內網,DGX 本機 — 不對外
- 異地備份未開,無洩漏面

**未來考慮 redact 的場景**:
- 啟用異地備份 → 備份時跑 redact filter(姓名 / 電話 / 護照號等 regex)
- Default supervisor 跨 profile 讀 → 視 supervisor 角色,可能要遮蔽
- 開發測試環境匯出 → 強制 redact

**初版只做**:in-memory 處理時提醒自己「這裡有 PII」,不存進外部任何地方。

---

## 4 條 Cron Job(修訂時間 + 改用 Hermes 內建)

### Cron 1:每 4 小時 ETL

```python
# 放這:~/.hermes/profiles/op-assistant/scripts/op_assistant_etl.py
# (NOT ~/.hermes/scripts/ — hermes cron --profile 解析在 profile 內 scripts/)
"""每 4 hr:Hermes session.db 新訊息 → kernel events(含 user_id resolve + UUID dedup)

session.db 真實 schema(verified 2026-05-26):
  CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,             -- 'user' / 'assistant' / 'tool' / 'system'
    content TEXT,
    tool_call_id TEXT,
    tool_calls TEXT,
    tool_name TEXT,
    timestamp REAL NOT NULL,        -- ★ Unix epoch(不是 ISO string)
    token_count INTEGER,
    finish_reason TEXT,
    platform_message_id TEXT,       -- ★ LINE 用這欄 dedup
    observed INTEGER DEFAULT 0
  );
  CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,           -- 'line' / 'telegram' / 'cli' etc.
    user_id TEXT,
    started_at REAL NOT NULL,
    ...
  );

★ Codex review 修正(v2.1):
- B2:--no-agent cron 不會 auto-load profile .env,手動 dotenv 載
- H3:SQLite WAL 模式不可 immutable=1(可能讀不到最新 WAL frame),
       改 mode=ro + busy_timeout
"""
import sqlite3, os, json, uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta

# ★ B2 修正:手動載入 profile .env(--no-agent cron 不會自動載)
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

# 用絕對路徑(--no-agent script 的 $HOME 被 scheduler 改成 profile home,
# 用 ~/... 可能展開到 profile dir 而非 user home)
SESSION_DB = "/home/wannavegtour/.hermes/profiles/op-assistant/state.db"
MAPPING_PATH = "/home/wannavegtour/.hermes/credentials/wannavegtour/op_mapping.json"
KERNEL_URL = os.environ["KERNEL_DATABASE_URL"]   # 沒設 = crash(嚴格,不要 silent fallback)

# UUID5 namespace 用 op-assistant 固定 UUID(避免每次跑 dedup 失敗)
ETL_NAMESPACE = uuid.UUID("a1b2c3d4-0000-0000-0000-000000000001")

def _load_mapping():
    """缺檔 → 空 dict;檔壞 → 寫健康事件後也回空 dict,不擋 ETL"""
    if not os.path.exists(MAPPING_PATH):
        return {"user_id_to_name": {}, "group_id_to_name": {}}
    try:
        with open(MAPPING_PATH) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        # ★ Codex review M1 修正:malformed JSON 寫健康事件而非 silent crash
        try:
            store = KernelStore.from_url(KERNEL_URL)
            store.execute(
                "INSERT INTO events (id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
                [str(uuid.uuid4()), "op_mapping_load_failure",
                 json_param({"path": MAPPING_PATH, "error": str(e)}),
                 datetime.now(timezone.utc).isoformat()]
            )
            store.close()
        except Exception:
            pass
        return {"user_id_to_name": {}, "group_id_to_name": {}}

def run():
    mapping = _load_mapping()
    user_map = mapping.get("user_id_to_name", {})
    group_map = mapping.get("group_id_to_name", {})

    # ★ timestamp 是 Unix epoch REAL,要 epoch 不是 ISO
    cutoff_epoch = (datetime.now(timezone.utc) - timedelta(hours=4)).timestamp()

    # ★ H3 修正:WAL 模式 immutable=1 不安全;改 mode=ro + busy_timeout
    conn = sqlite3.connect(
        f"file:{SESSION_DB}?mode=ro", uri=True,
        timeout=30.0,          # busy_timeout 30s(等 Hermes 寫完)
    )
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT m.id, m.session_id, m.role, m.content,
               m.tool_calls, m.tool_name, m.timestamp,
               m.platform_message_id,
               s.source, s.user_id
        FROM messages m
        JOIN sessions s ON m.session_id = s.id
        WHERE m.timestamp > ?
          AND s.source = 'line'
        ORDER BY m.timestamp
    """, (cutoff_epoch,)).fetchall()
    conn.close()

    if not rows:
        return

    store = KernelStore.from_url(KERNEL_URL)
    try:
        for r in rows:
            # ★ 用 uuid5 + platform_message_id (LINE) 或 fallback msg_id 做 deterministic UUID
            dedup_key = r["platform_message_id"] or f"hermes_msg_{r['id']}"
            event_id = str(uuid.uuid5(ETL_NAMESPACE, dedup_key))

            uid = r["user_id"]
            payload = {
                "role": r["role"],
                "content": r["content"],
                "tool_calls": json.loads(r["tool_calls"]) if r["tool_calls"] else None,
                "tool_name": r["tool_name"],
                "platform_message_id": r["platform_message_id"],
                "session_id": r["session_id"],
                "user_id": uid,
                "user_name": user_map.get(uid, "未知 OP"),
                "group_name": group_map.get(r["session_id"], "未知群"),  # session.id 對 group 看實際情況
                "source": r["source"],
            }
            # ★ timestamp 從 REAL 轉成 ISO 給 PG TIMESTAMPTZ
            created_iso = datetime.fromtimestamp(r["timestamp"], tz=timezone.utc).isoformat()

            store.execute(
                "INSERT INTO events (id, event_type, payload, created_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT (id) DO NOTHING",
                [event_id, "op_assistant_line_message", json_param(payload), created_iso]
            )
    finally:
        store.close()

if __name__ == "__main__":
    run()
```

**Schedule**: `0 */4 * * *`(每 4 hr 整點)
**Hermes cron 註冊**(✱ Codex 抓出 v1 路徑寫錯 — 必須相對):
```bash
hermes cron create '0 */4 * * *' \
  --name op-etl \
  --script op_assistant_etl.py \
  --no-agent \
  --profile op-assistant
```
script 檔放 `~/.hermes/profiles/op-assistant/scripts/op_assistant_etl.py`(不是 root 的 `~/.hermes/scripts/`)。`--no-agent` = script 直接跑,不經 LLM agent。

**Timeout 限制**(H2):Hermes cron `--no-agent` 預設 timeout 120s。ETL 通常 1-5s 完成,在限內。如果未來資料量大,改 `hermes config set cron.script_timeout_seconds 300`。

### Cron 2:每日 09:00 curation(寫 events,不寫 candidates)

```python
# 放這:~/.hermes/profiles/op-assistant/scripts/op_assistant_daily_curate.py
"""每日 09:00:讀過去 24hr events,gemma4:e4b 整理,寫 summary event,push Telegram

模型呼叫:用 OpenAI 相容 endpoint 直接打 Ollama(localhost:11434/v1)
原因:Hermes auxiliary_client 內部 API(`call_llm`)可選,但直接 HTTP 控制力更大,
fail 模式也清楚。如果之後要切走 Hermes 統一路徑,改 `from agent.auxiliary_client
import call_llm` 即可(API 在 `~/.hermes/hermes-agent/agent/auxiliary_client.py`)。

★ Codex review 修正(v2.1):
- B2:--no-agent cron 不會 auto-load profile .env,手動 dotenv 載
- M2:summary uuid 改 uuid5(period) 確保 idempotent,cron 重跑不會生重複 summary
- M4:Telegram push 失敗的 exception 不能含 token URL,catch RequestException sanitize
- L1:把 event_count / open_failure_count 也 merge 進 summary dict(否則 push 顯 ?)
"""
import os, json, uuid, requests
from pathlib import Path
from datetime import datetime, timezone, timedelta

# ★ B2 修正(同 ETL)
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

# ★ M2 修正:uuid5 namespace(daily 跟 weekly 各用一個)
DAILY_NAMESPACE = uuid.UUID("a1b2c3d4-0000-0000-0000-000000000002")

# 直接打 Ollama OpenAI-compatible endpoint(跟 Hermes auxiliary.compression 共用模型)
OLLAMA_URL = "http://127.0.0.1:11434/v1/chat/completions"
CURATION_MODEL = "gemma4:e4b"  # 跟 auxiliary.compression 同一個 — 不需額外 pull

def run():
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    store = KernelStore.from_url(KERNEL_URL)
    try:
        events = store.fetch_all(
            "SELECT id, payload, created_at FROM events "
            "WHERE event_type = ? AND created_at > ? ORDER BY created_at",
            ["op_assistant_line_message", cutoff_iso]
        )
        failures = store.fetch_all(
            "SELECT id, attempt_id, failure_type, context FROM failures "
            "WHERE status='open' AND created_at > ?",
            [cutoff_iso]
        )

        if not events and not failures:
            return

        # 用 gemma4:e4b 整理(直接 HTTP)
        prompt = _build_curation_prompt(events, failures)
        resp = requests.post(OLLAMA_URL, json={
            "model": CURATION_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,    # 整理任務求穩
        }, timeout=300)
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        summary = json.loads(raw)

        # 把 metrics merge 進 summary(L1 修正)
        summary["event_count"] = len(events)
        summary["open_failure_count"] = len(failures)

        # ★ M2 修正:uuid5(period) 確保同一天重跑不會生重複 summary
        period_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        sid = str(uuid.uuid5(DAILY_NAMESPACE, period_key))

        # 寫進 events table(不是 candidates!) — ON CONFLICT 保證 idempotent
        store.execute(
            "INSERT INTO events (id, event_type, payload, created_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT (id) DO NOTHING",
            [sid, "daily_curation_summary",
             json_param({
                 "period_start": cutoff_iso,
                 "period_end": datetime.now(timezone.utc).isoformat(),
                 "period_key": period_key,
                 "event_count": len(events),
                 "open_failure_count": len(failures),
                 "model": CURATION_MODEL,
                 "patterns": summary.get("patterns", []),
                 "intent_gaps": summary.get("intent_gaps", []),
                 "customer_complaints": summary.get("complaints", []),
                 "actionable_items": summary.get("actionable", []),
             }),
             datetime.now(timezone.utc).isoformat()]
        )
        # Push Telegram(走 Hermes Bot API 直接送 Gary chat)
        _push_telegram_summary(sid, summary)
    finally:
        store.close()

def _build_curation_prompt(events, failures):
    sample = []
    for e in events[:50]:   # 控制 token
        p = e['payload'] if isinstance(e['payload'], dict) else json.loads(e['payload'])
        sample.append({
            "role": p.get('role'),
            "name": p.get('user_name'),
            "text": (p.get('content') or '')[:200]
        })
    fail_list = [{"type": f["failure_type"], "context": f["context"]} for f in failures]
    return f"""你是 wannavegtour OP 助理的「整理員」。讀過去 24hr 對話 + 失敗紀錄,找出:
- patterns: 重複出現的問句或話題
- intent_gaps: 我們的規則表沒抓到的意圖(列原文)
- complaints: 疑似客訴或不滿(列原文)
- actionable: 你建議要修的事(具體建議)

對話:{json.dumps(sample, ensure_ascii=False)}
失敗:{json.dumps(fail_list, ensure_ascii=False)}

只回 JSON,key: patterns / intent_gaps / complaints / actionable,值為陣列。"""

def _push_telegram_summary(summary_event_id, summary):
    """直接打 Telegram Bot API,不需要走 Hermes gateway(這是後台 script)。

    ★ M4 修正:catch RequestException,sanitize 不洩 token URL。
    """
    bot_token = _get_telegram_bot_token()
    chat_id = _get_telegram_home_channel()
    if not bot_token or not chat_id:
        # graceful no-op:也寫 health event 讓 Gary 知道為何沒收到通知
        try:
            store = KernelStore.from_url(KERNEL_URL)
            store.execute(
                "INSERT INTO events (id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
                [str(uuid.uuid4()), "telegram_push_skipped",
                 json_param({"reason": "missing token or chat_id",
                             "has_token": bool(bot_token), "has_chat": bool(chat_id),
                             "summary_event_id": summary_event_id}),
                 datetime.now(timezone.utc).isoformat()]
            )
            store.close()
        except Exception:
            pass
        return

    text = (
        f"📋 OP 對話日整理 ({datetime.now().strftime('%Y-%m-%d')})\n"
        f"事件數: {summary.get('event_count', 0)} / 待修 failures: {summary.get('open_failure_count', 0)}\n\n"
        f"🔁 重複 pattern: {len(summary.get('patterns', []))} 筆\n"
        f"❓ 意圖 gap: {len(summary.get('intent_gaps', []))} 筆\n"
        f"📣 客訴: {len(summary.get('customer_complaints', []))} 筆\n"
        f"💡 我建議: {len(summary.get('actionable_items', []))} 筆\n\n"
        f"細節查 events.id={summary_event_id}"
    )
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        # ★ M4:exception message 可能含 token URL,只 log status code + message preview
        status = getattr(e.response, "status_code", None) if hasattr(e, "response") and e.response else None
        sanitized = f"telegram push failed: status={status}, type={type(e).__name__}"
        try:
            store = KernelStore.from_url(KERNEL_URL)
            store.execute(
                "INSERT INTO events (id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
                [str(uuid.uuid4()), "telegram_push_failure",
                 json_param({"summary_event_id": summary_event_id, "error": sanitized}),
                 datetime.now(timezone.utc).isoformat()]
            )
            store.close()
        except Exception:
            pass

def _get_telegram_bot_token():
    """從 default profile 的 .env 讀(or 從 op-assistant 設定的 escalate token)"""
    # Codex 階段確認讀法
    env_path = os.path.expanduser("~/.hermes/.env")
    if not os.path.exists(env_path):
        return None
    for line in open(env_path):
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None

def _get_telegram_home_channel():
    env_path = os.path.expanduser("~/.hermes/.env")
    if not os.path.exists(env_path):
        return None
    for line in open(env_path):
        if line.startswith("TELEGRAM_HOME_CHANNEL="):
            return line.split("=", 1)[1].strip()
    return None

if __name__ == "__main__":
    run()
```

**Schedule**: `0 9 * * *`(每日 09:00)
**模型**:**gemma4:e4b**(本機已有,跟 auxiliary.compression 共用)
**Hermes cron 註冊**(✱ Codex B1 修正 — 路徑相對):
```bash
hermes cron create '0 9 * * *' \
  --name op-daily-curate \
  --script op_assistant_daily_curate.py \
  --no-agent \
  --profile op-assistant
```

**Timeout 重要**(H2):curation 內含 Ollama call,gemma4:e4b 24hr 對話摘要可能 30-60s,加上 cold start 可能 60-90s。Hermes cron `--no-agent` 預設 timeout 120s **不夠**。**必須調**:
```bash
hermes config set cron.script_timeout_seconds 300
```
(這設定影響全部 cron script,設一次即可。)

### Cron 3:每週一 09:00 週報

```python
# 放這:~/.hermes/profiles/op-assistant/scripts/op_assistant_weekly_report.py
"""每週一 09:00:過去 7 天統計 + Gary 批准趨勢 + 推 Telegram

★ Codex review 修正(v2.1):
- B2:手動載 profile .env
- M2:weekly summary uuid 改 uuid5(week_key) 確保 idempotent
- M3:_push_weekly_report 完整實作(不留 pass,避免 cron 假動作)
"""
import os, json, uuid, requests
from pathlib import Path
from datetime import datetime, timezone, timedelta

# B2 修正
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

# M2 修正
WEEKLY_NAMESPACE = uuid.UUID("a1b2c3d4-0000-0000-0000-000000000003")

def run():
    week_start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    store = KernelStore.from_url(KERNEL_URL)
    try:
        # 1. 訊息總數 / 各意圖分佈
        intent_dist = store.fetch_all(
            "SELECT payload->>'intent' AS intent, COUNT(*) AS n "
            "FROM events JOIN attempts ON attempts.event_id = events.id "
            "WHERE events.created_at > ? GROUP BY payload->>'intent' "
            "ORDER BY n DESC",
            [week_start]
        )
        # 2. 失敗 top types
        fail_top = store.fetch_all(
            "SELECT failure_type, COUNT(*) AS n FROM failures "
            "WHERE created_at > ? GROUP BY failure_type ORDER BY n DESC LIMIT 10",
            [week_start]
        )
        # 3. Gary 批准了多少 / 駁回多少
        approvals = store.fetch_all(
            "SELECT decision, COUNT(*) AS n FROM approvals "
            "WHERE created_at > ? GROUP BY decision",
            [week_start]
        )
        # 4. Gary 最常批准什麼 patch_type(學進去的方向)
        approved_types = store.fetch_all(
            "SELECT c.patch_type, COUNT(*) AS n FROM approvals a "
            "JOIN improvement_candidates c ON a.candidate_id = c.id "
            "WHERE a.decision='approved' AND a.created_at > ? "
            "GROUP BY c.patch_type ORDER BY n DESC",
            [week_start]
        )

        # ★ M2 修正:uuid5(week_key) idempotent
        week_key = datetime.now(timezone.utc).strftime("%G-W%V")   # ISO week
        wid = str(uuid.uuid5(WEEKLY_NAMESPACE, week_key))
        payload = {
            "period_start": week_start,
            "period_key": week_key,
            "intent_distribution": [dict(r) for r in intent_dist],
            "top_failures": [dict(r) for r in fail_top],
            "approvals": [dict(r) for r in approvals],
            "approved_patch_types": [dict(r) for r in approved_types],
        }
        store.execute(
            "INSERT INTO events (id, event_type, payload, created_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT (id) DO NOTHING",
            [wid, "weekly_report", json_param(payload),
             datetime.now(timezone.utc).isoformat()]
        )
        _push_weekly_report(wid, payload)
    finally:
        store.close()

def _push_weekly_report(weekly_event_id, payload):
    """★ M3 修正:real push,not pass。同 daily,sanitize exception。"""
    bot_token = _get_telegram_bot_token()
    chat_id = _get_telegram_home_channel()
    if not bot_token or not chat_id:
        return

    intents = payload["intent_distribution"][:5]
    intents_str = "\n  ".join(f"- {i['intent']}: {i['n']}" for i in intents) or "(無)"
    fails = payload["top_failures"][:5]
    fails_str = "\n  ".join(f"- {f['failure_type']}: {f['n']}" for f in fails) or "(無)"
    apps = {a["decision"]: a["n"] for a in payload["approvals"]}

    text = (
        f"📊 OP 週報 ({payload['period_key']})\n\n"
        f"訊息意圖 TOP5:\n  {intents_str}\n\n"
        f"失敗類型 TOP5:\n  {fails_str}\n\n"
        f"你批准了 {apps.get('approved', 0)} 筆,駁回 {apps.get('rejected', 0)} 筆\n\n"
        f"細節 events.id={weekly_event_id}"
    )
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        status = getattr(e.response, "status_code", None) if hasattr(e, "response") and e.response else None
        store = KernelStore.from_url(KERNEL_URL)
        try:
            store.execute(
                "INSERT INTO events (id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
                [str(uuid.uuid4()), "telegram_push_failure",
                 json_param({"weekly_event_id": weekly_event_id,
                             "error": f"weekly push failed status={status} type={type(e).__name__}"}),
                 datetime.now(timezone.utc).isoformat()]
            )
        finally:
            store.close()

# 共用 Telegram helpers(同 daily_curate.py)
def _get_telegram_bot_token():
    p = "/home/wannavegtour/.hermes/.env"
    if not os.path.exists(p): return None
    for line in open(p):
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None

def _get_telegram_home_channel():
    p = "/home/wannavegtour/.hermes/.env"
    if not os.path.exists(p): return None
    for line in open(p):
        if line.startswith("TELEGRAM_HOME_CHANNEL="):
            return line.split("=", 1)[1].strip()
    return None

if __name__ == "__main__":
    run()
```

**Schedule**: `0 9 * * 1`(每週一 09:00)

### Cron 4:每月 1 日 05:00 維護

```python
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
```

**Schedule**: `0 5 1 * *`(每月 1 日 05:00)

### Cron 註冊方式:Hermes 內建(✱ 正確命令)

**驗證 2026-05-26**:Hermes cron 用 CLI 註冊。**★ Codex B1 修正**:`--script` 路徑 **必須相對**,檔放在 **profile 內** scripts 目錄(不是 root)。

```bash
# Scripts 放這:profile-local,不是 ~/.hermes/scripts/
mkdir -p ~/.hermes/profiles/op-assistant/scripts
ls ~/.hermes/profiles/op-assistant/scripts/
  op_assistant_etl.py
  op_assistant_daily_curate.py
  op_assistant_weekly_report.py
  op_assistant_monthly_maintenance.py

# 設 cron script timeout(★ H2:gemma4:e4b cold start + 摘要可能 > 120s 預設)
hermes config set cron.script_timeout_seconds 300

# 4 條 job 註冊 — script 名相對,不是絕對路徑
hermes cron create '0 */4 * * *' --name op-etl              --script op_assistant_etl.py              --no-agent --profile op-assistant
hermes cron create '0 9 * * *'   --name op-daily-curate     --script op_assistant_daily_curate.py     --no-agent --profile op-assistant
hermes cron create '0 9 * * 1'   --name op-weekly-report    --script op_assistant_weekly_report.py    --no-agent --profile op-assistant
hermes cron create '0 5 1 * *'   --name op-monthly-maint    --script op_assistant_monthly_maintenance.py --no-agent --profile op-assistant
```

`--no-agent` = script 直接執行,stdout 不丟給 LLM agent(deterministic 後台任務)。

**★ B2 重要**:`--no-agent` 模式 **不會自動 load profile .env**。每個 script 頂端**必須手動 `_load_profile_env()`** 把 `KERNEL_DATABASE_URL` 等讀進來(已包進上面 4 個 script 範本)。

**驗證**:
```bash
hermes -p op-assistant cron list
# 預期顯示 4 條 job + 各自下次執行時間

# 手動跑一次 ETL 確認 .env 載得到
hermes -p op-assistant cron run op-etl
# 預期:無 KeyError,events 表多幾筆 row
```

---

## 備份(三層,**無加密 無異地**)

### Backup script

```bash
#!/bin/bash
# ~/.hermes/credentials/wannavegtour/op_kernel/backup.sh
# 用法:bash backup.sh daily|weekly|monthly

set -euo pipefail
TYPE="${1:?usage: backup.sh daily|weekly|monthly}"
BASE="$HOME/.hermes/credentials/wannavegtour/op_kernel"
DIR="$BASE/backup/$TYPE"
mkdir -p "$DIR" && chmod 700 "$DIR"

case "$TYPE" in
  daily)   FNAME="$(date +%Y-%m-%d).sql.gz" ;;
  weekly)  FNAME="$(date +%Y-W%V).sql.gz" ;;
  monthly) FNAME="$(date +%Y-%m).sql.gz" ;;
  *) echo "bad type"; exit 1 ;;
esac

OUT="$DIR/$FNAME"
# ★ L: 絕對路徑(crontab 的 PATH 不全)
/usr/bin/docker exec op-assistant-kernel pg_dump \
  -U op_kernel -d op_assistant_kernel \
  --no-owner --no-acl \
  2>> "$BASE/backup/backup.log" \
  | gzip > "$OUT"

chmod 600 "$OUT"

# Retention
case "$TYPE" in
  daily)   find "$DIR" -name "*.sql.gz" -mtime +14 -delete ;;
  weekly)  find "$DIR" -name "*.sql.gz" -mtime +90 -delete ;;
  monthly) find "$DIR" -name "*.sql.gz" -mtime +400 -delete ;;
esac

echo "[$(date -Iseconds)] backup ${TYPE}: $FNAME ($(du -h "$OUT" | cut -f1))" >> "$BASE/backup/backup.log"
```

### Cron(系統 crontab,不是 Hermes 內)

```cron
# crontab -e
0 2 * * *     bash ~/.hermes/credentials/wannavegtour/op_kernel/backup.sh daily
30 2 * * 0    bash ~/.hermes/credentials/wannavegtour/op_kernel/backup.sh weekly
0 3 1 * *     bash ~/.hermes/credentials/wannavegtour/op_kernel/backup.sh monthly
```

(backup 走系統 crontab 因為它不該綁 Hermes — Hermes 掛了 backup 仍要跑)

### Restore runbook(同 v1)

```bash
# 場景 A:DB 壞了 / 想 rollback 到昨天
cd ~/.hermes/credentials/wannavegtour/op_kernel/
docker compose down
docker volume rm op-assistant-kernel-data    # ⚠️ 確認你真的要 reset
docker compose up -d
sleep 10
gunzip < backup/daily/2026-05-25.sql.gz | \
  docker exec -i op-assistant-kernel psql -U op_kernel -d op_assistant_kernel
```

---

## Pre-Launch Test Plan(NEW,Gary 2026-05-26 要求)

### 測試輸入:過去真實 LINE 對話

兩個來源:
1. `~/.hermes/line_events/wannavegtour.jsonl`(舊 standalone listener 寫的,DGX 上有今天 audit)
2. (若需要)從 Mac 撈過去歷史(目前 Mac 已退場,只能挖 git history 找 commit `b24c927` 之前的 test fixture)

### 測試 procedure

```bash
# 1. 把舊 audit log 灌進 op-assistant kernel events 表(以模擬 ETL)
python3 scripts/replay_audit_to_kernel.py \
  --input ~/.hermes/line_events/wannavegtour.jsonl \
  --kernel-url "$KERNEL_DATABASE_URL" \
  --dry-run                              # 先 dry-run 看會寫進什麼

# 2. 真正寫入(--apply)

# 3. op-assistant agent 一筆一筆 replay(假設 6 tool 已實作)
python3 scripts/replay_through_op_assistant.py \
  --since "2026-05-25T00:00:00" \
  --until "2026-05-26T00:00:00" \
  --output reports/pre-launch-test-$(date +%Y-%m-%d).json

# 4. 比對 bot reply vs 舊 listener 歷史 reply
python3 scripts/diff_replies.py \
  --report reports/pre-launch-test-...json \
  --output reports/pre-launch-test-diff.md
```

### 3 個 Replay Script 的 spec(★ Codex 指出 v1 沒寫,Codex execute 階段要實作)

**scripts/replay_audit_to_kernel.py**(放 Gary repo 內 scripts/ 子目錄):
- 讀 `~/.hermes/line_events/wannavegtour.jsonl`(舊 listener audit)
- 每行 parse 成 dict
- 對每筆,用 `uuid5(ETL_NAMESPACE, line_event_id)` 算 deterministic id
- ON CONFLICT DO NOTHING insert 進 kernel events(event_type=`op_assistant_line_message_replay`,跟 live ETL 區隔)
- payload 含 user_name resolve(透過 op_mapping.json)
- 支援 `--dry-run`(只 print,不寫)/ `--apply`(寫)/ `--since` `--until` 過濾

**scripts/replay_through_op_assistant.py**:
- 讀 kernel events(replay 來源)
- 每筆呼叫 op-assistant 的 6 tool flow(在 6 tool 實作後,**現在 spec 階段這 script 寫不了**)
- 比對 reply 跟原 audit log 裡的 listener reply
- 輸出 JSON 報告:每筆 `{event_id, original_reply, new_reply, match: bool, diff: str}`
- **本 script 必須等 6 tool 實作完成才能寫**(Phase 順序見 v2 plan)

**scripts/diff_replies.py**:
- 吃 replay_through 的 JSON 報告
- 算 match rate / 列 ❌ 個別案例 / 算嚴重度(用 validator 規則 + Gary 手動標)
- 出 markdown 報告(模板見上「Test report 內容」段)
- 含 user_id → name resolve

**這 3 script 暫不在本 v2 doc 內附,在 Codex execute 階段寫入 Gary repo 的 `scripts/` 目錄(或併進 `closed_loop_kernel/`)**。

### Test report 內容(自動產生)

```markdown
# OP Assistant Pre-Launch Test Report

## Summary
- 測試期間: 2026-05-25 ~ 2026-05-26
- 訊息總數: 52 筆
- bot 該回應: 18 筆(prefix 觸發)
- 新版回應: ✅ 17 / ❌ 1 / ⚠️ 0
  - ✅ 17 = 跟舊 listener 一致(語意)
  - ❌ 1 = 偏離舊行為(列細節 + 評估嚴重度)
  - ⚠️ 0 = 完全沒回(漏接)

## 個別案例
### Case 1: ❌ 偏離
- 原始: "小弟 日本團 7月還有位嗎"
- 舊 listener: "日本京阪七日 (7/12) 還有 8 位..."
- 新 op-assistant: [新版回應]
- diff: ...
- 嚴重度: low / med / high
- 建議: ...

### Case 2..N: ✅
- 略

## 驗收標準(Gary 設)
- ❌ 數 < 5% → PASS,可 cutover
- ❌ 數 5-15% → 需 Gary 個案 review 決定
- ❌ 數 > 15% → BLOCK cutover,回頭修
- ⚠️ 數 > 0 → 都要查(可能是 SOUL.md / parser 漏)

## 同事身分對應(從測試發現)
- User ID Ufd...7a → 美鳳(從訊息上下文推斷,Gary 確認)
- User ID Uec...c3 → Gary
- (其他 N 個 user_id,你補上對應)
```

### 測試什麼時候做

**cutover 之前**(LINE webhook 還沒切換時)— 純 replay,不影響生產 listener。

---

## 跟 Hermes session.db 分工(同 v1,確認)

| 場景 | 去 session.db 拿 | 去 kernel 拿 |
|---|---|---|
| 「上次 OP 問什麼」 | ✅ raw 全文 + 對話 turn | ⚠️ 結構化但摘要 |
| 「過去 30 天客訴 top 5」 | ❌ 跨時間 query 慢 | ✅ `SELECT ... GROUP BY failure_type` |
| 「Gary 上個月批准什麼」 | ❌ 不在 session | ✅ `approvals` JOIN `candidates` |
| 「op-assistant SOUL.md v3 是什麼樣子」 | ❌ 不存 | ✅ `artifacts WHERE name='op-soul' AND version=3` |
| Debug 一筆訊息為什麼回錯 | ✅ 對話 turn 細節 | ✅ `attempts` + `tool_calls` + `failures` |

---

## NOT in Scope(明確排除)

- ❌ **OHYA demo / seed / approval bot** — 不 import(只用 kernel 主幹)
- ❌ **wannavegtourcrm-postgres-audit container** — 完全不碰
- ❌ **異地備份** — 暫緩(Gary 2026-05-26)
- ❌ **備份加密** — 不做(Gary 2026-05-26)
- ❌ **PII 主動 redact** — 初版不做(理由見 PII 段)
- ❌ **Prometheus / Grafana** — 流量大再上
- ❌ **跨 profile read** — Default supervisor 暫緩
- ❌ **多 tenant** — 單 wannavegtour
- ❌ **multi-region / HA** — 單機

---

## 開放問題(narrowed)

| # | 問題 | v1 → v2 變化 |
|---|---|---|
| 1 | Cron 註冊 | ✅ 解:Hermes 內建 |
| 2 | Curation 模型 | ✅ 解:gemma4:e4b(本機已有) |
| 3 | 異地備份 | ✅ 解:暫緩 |
| 4 | 備份加密 | ✅ 解:不做 |
| 5 | PII 主動 redact | ✅ 解:初版不做(僅 in-memory) |
| 6 | Retention 政策 | 維持 14d/12w/12mo(沒新指示) |
| 7 | Telegram 推週報頻率 | 維持每日摘要 + 重大事件即時 |
| 8 | Kernel candidate 策略(LLM 直接 vs 真實 failure) | **修正:真實 failure 才生 candidate**(見 audit) |
| **新 9** | OP user_id → 同事名稱對應表初始種子怎麼填 | **等 Gary 補**(我可以挖 audit log 列已知 user_id,你對應名字) |
| **新 10** | Pre-launch test 通過標準 | 建議:< 5% diff → PASS / 5-15% → review / > 15% → BLOCK(Gary 確認) |
| **新 11** | 失敗了 attempt 怎麼自動標 failure(or 等 Gary 看 Telegram 標) | 建議:validator 認得出來的 → 自動;模糊的 → Gary 看 daily summary 標 |

---

## 動工順序(Gary 確認後)

1. ✅ 本 v2 doc commit + push(現在做)
2. ⏳ **Gary review**(看 GitHub 頁面 → 給意見 / OK)
3. ⏳ **Codex review**(把 doc 路徑給 Codex,跑 `codex review` 抓邏輯 / 安全 / drift)
4. ⏳ Claude + Gary 看 Codex review feedback,改 doc
5. ⏳ 寫 **Codex execute brief**(從 doc 拆出可執行步驟)
6. ⏳ Codex 執行 infra(依序):
   1. 建 `~/.hermes/credentials/wannavegtour/op_kernel/`(mode 700)+ 隨機密碼
   2. 寫 `docker-compose.yml`
   3. `docker compose up -d` → 等 healthy
   4. `sudo apt install postgresql-client`(裝 psql)
   5. `KernelStore.from_url(...).initialize()` 建 14 表 + trigger
   6. 寫 `KERNEL_DATABASE_URL` 進 `~/.hermes/profiles/op-assistant/.env`
   7. 寫 4 個 cron script 進 `~/.hermes/scripts/`
   8. 4 條 `hermes cron create ...` 註冊
   9. 寫 `op_mapping.json` 框架(Gary 之後填內容)
   10. 寫 `backup.sh` + crontab 3 條
7. ⏳ Claude 驗證每一步(對照 self-audit checklist)
8. ⏳ Gary 填 `op_mapping.json` user_id → 同事名稱
9. ⏳ Pre-launch test(用過去 audit log 跑 replay → test report)
10. ⏳ Gary review test report → 決定 cutover 或回頭修
11. ⏳ Cutover(LINE webhook 切 Hermes:8646,Tailscale Funnel 切 port,停舊 listener)

---

## Self-Audit 結果(verified 2026-05-26)

### ✅ 已 verified(對照真實 file / API)

- [x] `events / failures / attempts / improvement_candidates / approvals / artifacts` 欄位名跟 `closed_loop_kernel/postgres.py:31-156` 一致
- [x] CHECK 約束值(`status` 等)正確列出可用 enum
- [x] 所有 JSON 寫入用 `json_param()` from `closed_loop_kernel.store`
- [x] `improvement_candidates` 不在 daily curation 寫入路徑(改寫進 events.daily_curation_summary)
- [x] Mermaid 圖無顏色 fill
- [x] Cron 時間表對齊 Gary 指示(`0 */4` / `0 9` / `0 9 * * 1` / `0 5 1 * *`)
- [x] 模型統一 `gemma4:e4b`(本機已有,16GB GPU loaded)
- [x] 備份段無加密 / 無異地
- [x] PII / user_id mapping 段完整
- [x] Pre-launch test 段有驗收標準(< 5% / 5-15% / > 15%)
- [x] NOT in scope 段明確
- [x] 11 個 open question 都有狀態
- [x] **Hermes cron 註冊用 `hermes cron create` CLI**(不是 `@schedule:` decorator)
- [x] **Scripts 放 `~/.hermes/scripts/`**(不是 profile cron 目錄)
- [x] **ETL UUID 用 `uuid.uuid5(NAMESPACE, platform_message_id)`** 確保 deterministic dedup
- [x] **session.db schema 真實對照過**:column 是 `timestamp` (REAL Unix epoch),不是 `ts` (ISO);有 `platform_message_id` 可 dedup;有 `sessions` 表 JOIN 篩 `source='line'`

### ⚠️ 待 Codex 階段驗證(API 細節)— v2.1 重新整理

| # | 假設 | 狀態 | 備註 |
|---|---|---|---|
| 1 | `hermes cron create --no-agent --profile` syntax | ✅ Codex review 驗 | CLI help + Codex 實測過,但路徑要相對(已修) |
| 2 | scripts 放 `~/.hermes/profiles/op-assistant/scripts/` | ✅ Codex review 驗 | 已改成 profile-local 路徑 |
| 3 | Telegram bot token 從 `~/.hermes/.env` 直接讀 | ⚠️ 中 | Codex 建議改用 Hermes-native API,但目前 grep 也 work |
| 4 | Ollama `localhost:11434/v1/chat/completions` 直打 | ✅ Verified | smoke test 過,curl 200,模型已 pulled |
| 5 | `KernelStore.from_url().initialize()` 建 14 表 + 6 trigger | ✅ Verified | Codex 確認 postgres.py 14 表 |
| 6 | `prevent_mutation` trigger 自動 attach 在 APPEND_ONLY_TABLES | ✅ Verified | postgres.py:8-15 直接看 |
| 7 | session.db `messages.platform_message_id` 對 LINE 一定填 | ⚠️ 中 | Hermes LINE plugin 應該填,但要 cutover 後實測才確定 |
| 8 | `hermes config set cron.script_timeout_seconds` 真的能調 | ⚠️ 待 Codex 執行階段確認 | Codex review 推測有此設,執行階段如失敗改 env var |
| 9 | profile scripts 目錄真的會被 `--no-agent` 解析 | ✅ Codex review 驗 | scheduler 路徑解析確認 |

**處理原則**:Codex 在執行階段碰到 ⚠️ 任一條失敗 → STOP + report 給 Claude → Claude 找正確 API → 改 doc → 重 push。

---

## Codex Review Checklist(交給 Codex 看的時候用)

Codex 看 doc 時請至少 cross-check 這些:

- [ ] schema 對得起 `closed_loop_kernel/postgres.py`(每個 INSERT 範例)
- [ ] `improvement_candidates` 的「fully populated INSERT」範例(我在 doc 沒給,Codex 補一份)
- [ ] `apply_candidate` 流程細節(看 `closed_loop_kernel/engine.py`)— doc 內描述跟程式是否一致
- [ ] backup script 在 Hermes 環境裡權限正確(docker exec 需要 user 在 docker group)
- [ ] cron script 路徑、執行身分、stdout/stderr 落地位置(會落到哪?journal?)
- [ ] ETL 對 session.db 唯讀 (`mode=ro&immutable=1`) 不會卡 Hermes 自己寫入
- [ ] PII mapping file 缺失時的 graceful fallback 行為
- [ ] Telegram bot token 讀取路徑跟 Hermes 規範一致(或建議改 hermes-native API)
- [ ] 各 cron 重複執行(如機器重啟錯過)的處理:寫成 idempotent(`ON CONFLICT DO NOTHING` 已用 in ETL,curation 是時段性,週月報是 snapshot 行為 — 都安全)
- [ ] 任何 hardcoded path 是否該抽出成 config

---
