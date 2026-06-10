# LT-A — wannavegtour kernel 基礎(rename + 多 agent 註冊)

**狀態**:spec ready,等 Codex 執行
**設計 anchor**:[2026-05-28-op-assistant-v0.3-design.md](2026-05-28-op-assistant-v0.3-design.md)、ohya brand pattern(`closed_loop_kernel/ohya_seed.py`)
**Telegram approval**:過 V0.3 Phase 5 機制(沒 Phase 5 就**走人工 + commit 證跡審**)
**並行對象**:[LT-D](2026-05-30-LT-D-v03-phase-2-3.md)(改不同檔案,無衝突)
**Blast radius**:中(動 op-assistant 還在跑的 kernel,但 < 30 秒停機)
**估時**:1 小時(codex 半小時 + 驗 半小時)

---

## 1. 目標(一句)

把現有 `op_assistant_kernel` DB rename 成品牌全域的 `wannavegtour_kernel`,在 `agents` / `teams` 表幫 marketing-agent + customer-service 登錄好 row,讓**之後三個 agent 共用同一個 kernel,用 `agent_id` 區分 row**,跟 ohya brand 同 pattern(11 agents 共用 `ohya_kernel`)。

---

## 2. 背景(Codex 必讀的 5 條)

1. **ohya brand pattern** = 1 brand 1 個 kernel DB,內含 `agents` + `teams` 表,所有 agent 共用 events/attempts/decisions/tool_calls/improvement_candidates。Agent 之間用 `agent_id` 區分,**不**用 schema-per-agent。實證:`closed_loop_kernel/ohya_seed.py` 把 11 個 ohya agent 全塞進同一張 `ohya_kernel.agents` 表。
2. **wannavegtour brand** 現在只有 op-assistant 一個 agent 在 kernel 裡跑;marketing-agent + 未來 customer-service 都要加進去。DB 名 `op_assistant_kernel` 跟「整個品牌共用」語意不符,要 rename。
3. **op-assistant 不能掉資料**。Rename 過程必須**短暫停機 + 寫入 retry-buffer**,確保進行中的 LINE 事件 retry 後有地方落地。
4. **V0.3 Phase 4-8 還沒上線**,所以本 LT-A 上線後寫入 path 還是只有 op-assistant 在用;marketing-agent 寫入要等 LT-B(它的 listener 跟 schema 填好)。
5. **不要碰 op-assistant 的 14 表 schema**(events / attempts / 等)— 它們**已經是 brand-level**,只要 row 帶 agent_id 就分得開。

---

## 3. 動作清單(Codex 照這個跑)

### Step 1 — 備份

```bash
# 在 DGX 上跑(連 op-assistant-kernel container)
PG_USER=op_kernel
docker exec op-assistant-kernel \
  pg_dump -U "$PG_USER" -Fc -Z 6 op_assistant_kernel \
  > ~/.hermes/profiles/op-assistant/backups/pre-LT-A-$(date +%Y%m%d-%H%M%S).dump
ls -lh ~/.hermes/profiles/op-assistant/backups/pre-LT-A-*.dump
# 預期 ≥ 1 MB,< 50 MB
```

### Step 2 — DB rename(原子化)

```bash
# 停 op-assistant 寫入端(讓 in-flight 寫入完成 + 之後 retry)
sudo systemctl stop hermes-op-assistant   # 或對應 service name; 找 systemctl list-units | grep hermes
sleep 3

# 改 DB 名(只能在沒人連的時候 SET)
docker exec op-assistant-kernel \
  psql -U "$PG_USER" -d postgres -c \
  "ALTER DATABASE op_assistant_kernel RENAME TO wannavegtour_kernel;"

# 改 user 名(語意 op_kernel → wannavegtour_kernel_writer 太長,改成 wv_kernel)
docker exec op-assistant-kernel \
  psql -U "$PG_USER" -d wannavegtour_kernel -c \
  "ALTER ROLE op_kernel RENAME TO wv_kernel;"
# 注意:ALTER ROLE RENAME 會清掉密碼,要重新 set
# 從 /run/secrets/db_password 讀新密碼 → ALTER ROLE wv_kernel WITH PASSWORD '<new>';

# 改 container 名(docker rename 即時生效,連線中斷但 volume 不動)
docker rename op-assistant-kernel wannavegtour-kernel
```

### Step 3 — 連線字串改

在 op-assistant 的 .env 改:

```diff
- KERNEL_DATABASE_URL=postgresql://op_kernel:<pwd>@127.0.0.1:5434/op_assistant_kernel
+ KERNEL_DATABASE_URL=postgresql://wv_kernel:<pwd>@127.0.0.1:5434/wannavegtour_kernel
```

文件路徑:`/home/wannavegtour/.hermes/profiles/op-assistant/.env`

### Step 4 — agents + teams 表灌入

```sql
-- 確保 wannavegtour team 存在(if 已存在直接 skip)
INSERT INTO teams (id, name, description, created_at)
VALUES (gen_random_uuid(), 'wannavegtour', '阿玩旅遊 — 旅行社 AI Native team', now())
ON CONFLICT (name) DO NOTHING;

-- 註冊 marketing-agent(LINE channel: @479lcuhp)
INSERT INTO agents (id, name, team_id, role, description, profile_path, created_at)
VALUES (
  gen_random_uuid(),
  'marketing-agent',
  (SELECT id FROM teams WHERE name='wannavegtour'),
  'marketing-bot',
  '行銷 + 行程上架 LINE bot',
  '/home/wannavegtour/.hermes/profiles/marketing-agent',
  now()
) ON CONFLICT (name) DO NOTHING;

-- 註冊 customer-service(資料來源是 CRM REST,不是自己 LINE)
INSERT INTO agents (id, name, team_id, role, description, profile_path, created_at)
VALUES (
  gen_random_uuid(),
  'customer-service',
  (SELECT id FROM teams WHERE name='wannavegtour'),
  'customer-service-bot',
  '客服 bot,站在 wannavegtourcrm-backend REST 上的 agent',
  '/home/wannavegtour/.hermes/profiles/customer-service',
  now()
) ON CONFLICT (name) DO NOTHING;

-- 把 op-assistant 既有 agent row(如果有)也指到 wannavegtour team
UPDATE agents
SET team_id = (SELECT id FROM teams WHERE name='wannavegtour')
WHERE name = 'op-assistant' AND team_id IS DISTINCT FROM (SELECT id FROM teams WHERE name='wannavegtour');
```

⚠ 如果 op-assistant agent row 還不存在(`SELECT * FROM agents WHERE name='op-assistant'` 是 0 row),補一條:

```sql
INSERT INTO agents (id, name, team_id, role, description, profile_path, created_at)
VALUES (
  gen_random_uuid(),
  'op-assistant',
  (SELECT id FROM teams WHERE name='wannavegtour'),
  'op-bot',
  'OP 客服查詢 LINE bot(被動)',
  '/home/wannavegtour/.hermes/profiles/op-assistant',
  now()
) ON CONFLICT (name) DO NOTHING;
```

### Step 5 — 加 v0.3 提的 `domain` 欄(denormalized)

依 v0.3 design §3 + 附錄 B:

```sql
ALTER TABLE improvement_candidates
  ADD COLUMN IF NOT EXISTS domain text;

-- backfill 既有 row 為 'op-assistant'(它們都是 op-assistant 的 candidate)
UPDATE improvement_candidates SET domain = 'op-assistant' WHERE domain IS NULL;

-- 設成 NOT NULL,寫入 path 必須帶
ALTER TABLE improvement_candidates ALTER COLUMN domain SET NOT NULL;

-- 加 index 給 dispatcher
CREATE INDEX IF NOT EXISTS improvement_candidates_domain_idx
  ON improvement_candidates(domain, created_at DESC);
```

### Step 6 — op-assistant 重啟

```bash
sudo systemctl start hermes-op-assistant
sleep 5
sudo systemctl status hermes-op-assistant --no-pager
# 預期 active (running),沒有 connection error log
```

### Step 7 — 驗證

```bash
docker exec wannavegtour-kernel \
  psql -U wv_kernel -d wannavegtour_kernel -c "
    SELECT t.name AS team, a.name AS agent, a.role
    FROM teams t JOIN agents a ON a.team_id = t.id
    ORDER BY t.name, a.name;"
# 預期至少 3 行:op-assistant / marketing-agent / customer-service 都在 wannavegtour team

docker exec wannavegtour-kernel \
  psql -U wv_kernel -d wannavegtour_kernel -c "
    SELECT COUNT(*) FROM events WHERE created_at > now() - interval '5 minutes';"
# 預期 > 0(代表 op-assistant restart 後有新事件進來)

# 在你自己 LINE 對 op-assistant 發測試訊息,30 秒內 events 應該多一條
```

---

## 4. 驗收 checklist(Claude review)

- [ ] `docker ps` 顯示 `wannavegtour-kernel`,沒有 `op-assistant-kernel`
- [ ] DB rename 後 op-assistant 寫入沒 error(查 `~/.hermes/profiles/op-assistant/logs/`)
- [ ] `agents` 表 3 row(op-assistant, marketing-agent, customer-service),都指 wannavegtour team
- [ ] `improvement_candidates.domain` 是 NOT NULL 欄,既有 row backfill 為 'op-assistant'
- [ ] backup .dump 檔存在 `~/.hermes/profiles/op-assistant/backups/`,size ≥ 1 MB
- [ ] op-assistant `.env` 更新成 `wannavegtour_kernel` connection string
- [ ] 真實 LINE 訊息打進 op-assistant 後,events 表新 row 還是進得去

---

## 5. Rollback

```bash
# 1. 停服務
sudo systemctl stop hermes-op-assistant

# 2. DB 名改回
docker rename wannavegtour-kernel op-assistant-kernel
docker exec op-assistant-kernel psql -U wv_kernel -d postgres -c \
  "ALTER DATABASE wannavegtour_kernel RENAME TO op_assistant_kernel;"
docker exec op-assistant-kernel psql -U wv_kernel -d op_assistant_kernel -c \
  "ALTER ROLE wv_kernel RENAME TO op_kernel;"

# 3. .env 改回
# 4. 還原 schema(刪 domain 欄、刪 marketing-agent/customer-service agent row、刪 wannavegtour team row)
# 5. 重啟 op-assistant

# 若 step 4 還原失敗:
docker exec op-assistant-kernel \
  pg_restore -U op_kernel -d op_assistant_kernel --clean --if-exists \
  ~/.hermes/profiles/op-assistant/backups/pre-LT-A-*.dump
```

---

## 6. Codex prompt template(paste-ready)

```
You are Codex executing LT-A per spec at:
~/Desktop/AI Native Company/Gary/docs/plans/2026-05-30-LT-A-wannavegtour-kernel-foundation.md

Constraint: code-is-law. NO LLM in control flow. Every step's command must be deterministic.

Execute Steps 1-7 in order. After each step, verify the expected state matches before continuing. If any step fails, STOP and execute the Rollback section. Do NOT improvise SQL or container ops.

Acceptance: Section 4 checklist all checked.
Output: A patch file diff for the .env change + a `LT-A-execution-log.txt` capturing every command's stdout/stderr + the final SELECT from Step 7.

Note: hermes-op-assistant service name might not match exactly — use `systemctl list-units --type=service | grep -i hermes` to find correct name before stopping it. If you can't find a managed service, fall back to `pgrep -af op-assistant | head` to locate the process and use kill -TERM + retry-buffer (the process writes to JSONL fallback, so 30s downtime is safe).
```

---

## 7. 結束後解鎖了什麼

- LT-B 可以開跑(marketing-agent listener 寫入有 agent_id='marketing-agent' 的 row 進 wannavegtour_kernel)
- LT-D 可以開跑(improvement_candidates 寫入有 domain 欄)
- v0.3 Phase 2-8 後續實作有對的表結構
- CS bot 將來起來時 agent row 已經在了,直接 fill profile dir 即可
