# PostgreSQL Schema Specification (Loop 3 - Fixed)

本文件定義 **Closed Loop Kernel v0** 的核心資料模型（Schema）。各實體均為抽象的系統元件，支援唯增（Append-Only）歷史審計，並引入動態政策、工具軌跡與安全的變更防護欄。

---

## 1. PostgreSQL DDL 定義

```sql
-- 確保 pgcrypto 擴充套件已啟用以支援 gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =========================================================================
-- 1. 系統事件紀錄表 (events) - 唯增 (Append-Only)
-- =========================================================================
CREATE TABLE events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source VARCHAR(100) NOT NULL, -- e.g., 'user_ui', 'agent_supervisor', 'deterministic_tool'
    event_type VARCHAR(100) NOT NULL, -- e.g., 'query_received', 'attempt_started', 'attempt_failed', 'approval_granted'
    payload JSONB NOT NULL         -- 彈性事件資料（Metadata, session_id 等）
);

-- =========================================================================
-- 2. 系統資產版本表 (artifacts) - 狀態可更新，主要為唯增版本控制
-- =========================================================================
CREATE TABLE artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,           -- 資產名稱 (e.g. 'query_prompt_main', 'helper_skill_calc')
    artifact_type VARCHAR(50) NOT NULL CHECK (artifact_type IN ('prompt', 'db_schema', 'code')),
    content TEXT NOT NULL,                -- 資產內容 (如 Prompt 範本、DDL 結構或 Python 代碼)
    content_hash VARCHAR(64) NOT NULL,    -- Content 的 SHA256 指紋 (防 Race Condition)
    version INT NOT NULL,                 -- 版本號 (唯增)
    is_active BOOLEAN NOT NULL DEFAULT TRUE, -- 是否為當前生產環境生效版本
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(name, version)
);

-- =========================================================================
-- 3. 政策規則定義表 (policy_gates) - 狀態可更新
-- =========================================================================
CREATE TABLE policy_gates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,     -- 規則名稱 (e.g. 'max_token_limit', 'sandbox_required')
    rule_definition JSONB NOT NULL,        -- 規則細節與參數限制
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =========================================================================
-- 4. 嘗試生命週期事件表 (attempt_lifecycle_events) - 唯增 (Append-Only)
-- =========================================================================
CREATE TABLE attempt_lifecycle_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id UUID NOT NULL,             -- 關聯的嘗試 ID（由客戶端預先生成，為邏輯關聯，避免在 attempts 寫入前產生 FK 衝突）
    state VARCHAR(50) NOT NULL CHECK (state IN ('started', 'running', 'finished')),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =========================================================================
-- 5. 執行嘗試紀錄表 (attempts) - 唯增 (Append-Only, 單次寫入，永不更新)
-- =========================================================================
CREATE TABLE attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(), -- ID 於客戶端/引擎啟動時預先生成，作為與生命週期及軌跡關聯之關鍵
    event_id UUID REFERENCES events(id),
    status VARCHAR(50) NOT NULL CHECK (status IN ('success', 'failed')),
    input JSONB NOT NULL,                 -- 原始輸入（例如用戶查詢、API 參數）
    output JSONB,                        -- 執行成功時的輸出
    error_message TEXT,                  -- 執行失敗時的詳細錯誤堆疊
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =========================================================================
-- 6. 決策紀錄表 (decisions) - 唯增 (Append-Only)
-- =========================================================================
CREATE TABLE decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id UUID REFERENCES attempts(id) NOT NULL, -- 關聯的嘗試 ID (在 final Batch Trace Transaction 內 attempts insert 後寫入，建立實體外鍵約束)
    gate_id UUID REFERENCES policy_gates(id),
    decision_maker VARCHAR(100) NOT NULL, -- e.g. 'policy_engine', 'human_dri:gary'
    action_taken VARCHAR(50) NOT NULL CHECK (action_taken IN ('allowed', 'blocked', 'approval_requested')),
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =========================================================================
-- 7. 工具細粒度呼叫紀錄表 (tool_calls) - 唯增 (Append-Only)
-- =========================================================================
CREATE TABLE tool_calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id UUID REFERENCES attempts(id) NOT NULL, -- 關聯的嘗試 ID (在 final Batch Trace Transaction 內建立實體外鍵約束)
    tool_name VARCHAR(100) NOT NULL,
    arguments JSONB NOT NULL,
    result JSONB,
    status VARCHAR(50) NOT NULL CHECK (status IN ('success', 'failed')),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =========================================================================
-- 8. 失敗事件追蹤表 (failures) - 狀態可更新，歷史不可改
-- =========================================================================
CREATE TABLE failures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id UUID REFERENCES attempts(id) NOT NULL, -- 關聯的嘗試 ID (建立實體外鍵約束)
    failure_type VARCHAR(100) NOT NULL,   -- e.g., 'syntax_error', 'runtime_exception', 'logic_fault'
    context JSONB NOT NULL,               -- 失敗時的系統上下文（如當前 Artifacts 版本、環境變數）
    status VARCHAR(50) NOT NULL CHECK (status IN ('open', 'analyzing', 'proposed', 'resolved', 'ignored')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =========================================================================
-- 9. 改進候選方案表 (improvement_candidates) - 狀態可更新，防止並行部署衝突
-- =========================================================================
CREATE TABLE improvement_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    failure_id UUID REFERENCES failures(id),
    target_artifact_id UUID REFERENCES artifacts(id), -- 目標資產 ID
    target_artifact_version INT NOT NULL,              -- 候選方案所基於的基礎 Artifact 版本 (防 Race Condition 校驗用)
    base_artifact_hash VARCHAR(64) NOT NULL,          -- 當初分析時 active artifacts 的 SHA256 指紋 (部署時校驗用)
    proposed_by VARCHAR(100) NOT NULL,    -- 提出改進的 Agent 識別
    description TEXT NOT NULL,            -- 修正的口語化描述
    patch_type VARCHAR(50) NOT NULL CHECK (patch_type IN ('prompt_update', 'db_migration', 'code_patch')),
    artifact_diff TEXT NOT NULL,          -- 補丁或 DDL 遷移的精確 Diff 內容
    proposed_content TEXT NOT NULL,       -- 修正後的完整新內容
    content_hash VARCHAR(64) NOT NULL,    -- 新內容的 SHA256 指紋 (部署時校驗防 Race Condition)
    risk_level VARCHAR(50) NOT NULL CHECK (risk_level IN ('low', 'medium', 'high')),
    rollback_plan TEXT NOT NULL,          -- 發生異常時之原子性回滾 SQL 或代碼復原指令
    validation_assertions JSONB NOT NULL, -- 沙盒驗證斷言清單 (e.g. [{"type": "no_error"}, {"type": "output_contains", "val": "Important"}])
    status VARCHAR(50) NOT NULL CHECK (status IN ('draft', 'sandbox_verified', 'approved', 'rejected', 'applied')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =========================================================================
-- 10. 沙盒重播驗證表 (replays)
-- =========================================================================
CREATE TABLE replays (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id UUID REFERENCES improvement_candidates(id),
    sandbox_schema VARCHAR(100) NOT NULL,  -- 執行的隔離 Schema 名稱 (適用於 DB DDL patch)
    sandbox_env JSONB,                    -- 執行的隔離 Python/代碼環境配置 (適用於 code patch)
    status VARCHAR(50) NOT NULL CHECK (status IN ('success', 'failed')),
    run_output JSONB,                      -- 重播後的輸出紀錄
    error_message TEXT,                    -- 若重播失敗，記錄報錯
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =========================================================================
-- 11. 人類審批紀錄表 (approvals) - 唯增 (Append-Only)
-- =========================================================================
CREATE TABLE approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id UUID REFERENCES improvement_candidates(id),
    approved_by VARCHAR(100) NOT NULL,    -- 人類 DRI 識別
    approved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decision VARCHAR(50) NOT NULL CHECK (decision IN ('approved', 'rejected')),
    comments TEXT                          -- 審批註記
);
```

---

## 2. 新增與細化欄位之設計理由

### 1. 解決 Attempts 唯讀卻更新的致命矛盾
舊版本在 Schema 中宣稱 `attempts` 唯讀防篡改，卻在事件流與實踐中將 attempt 標記為 `running` 後更新為 `success/failed`，這將直接導致資料庫觸發器攔截而拋出錯誤崩潰。
*   **新機制設計**：引入 `attempt_lifecycle_events`（嘗試生命週期事件表），任務啟動、執行與完結的生命週期進度均以**唯增方式**寫入此表，不對 `attempts` 進行修改。
*   **一次性寫入**：`attempts` 僅在任務完成時（不論成功或失敗），伴隨 `tool_calls` 與 `decisions` 以 Batch Trace Transaction 的形式**單次寫入**最終結果，藉此避免 `UPDATE` 操作。

### 2. 補完 v0 三張核心表
*   **`policy_gates`**：系統必須有預設的執行安全邊界與防護欄（例如：最大 token 預算限制、特定高風險工具需要審批的標記）。
*   **`decisions`**：記錄每一筆 tool_call 是否被 policy_gate 攔截或放行。這解決了「AI 行為是否受限於規則」的透明審計問題。
*   **`tool_calls`**：一筆 `attempt` 通常由多個細粒度工具呼叫組成。獨立出來能精確追蹤是「哪一個工具」在「哪一步驟」失敗。

### 3. `improvement_candidates` 指紋與斷言欄位擴充
*   **`target_artifact_version` & `base_artifact_hash`**：明確記錄 AI supervisor 進行根因分析時，該 Artifact 的基準版本與 Hash。在部署時，系統會比對生產環境最新版本的 `content_hash` 是否等於 `base_artifact_hash`。若已被其他 Agent 修改，交易將自動 rollback，避免覆蓋與並行 race condition。
*   **`content_hash` & `proposed_content`**：新代碼的 SHA256。在 Gary 點擊部署時，交易會比對 `artifacts` 當前 active 的 Hash 是否與當初 sandbox 驗證時所基於的舊 Hash 一致，防止並發 race condition。
*   **`validation_assertions` & `rollback_plan`**：定義沙盒 Replay 必須通過的硬性測試條件；附帶回滾方案，保證萬一部署出錯能原子性復原。

---

## 3. 唯增（Append-Only）防篡改觸發器實作

為了維護歷史真實性，我們在 PostgreSQL 中對核心審計表實施 `BEFORE UPDATE OR DELETE` 的觸發器硬性阻斷：

```sql
CREATE OR REPLACE FUNCTION prevent_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'IMPERMISSIBLE ACTION: Table % is append-only. UPDATE or DELETE operations are strictly prohibited.', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

-- 1. events 防篡改
CREATE TRIGGER trg_protect_events
BEFORE UPDATE OR DELETE ON events
FOR EACH ROW EXECUTE FUNCTION prevent_mutation();

-- 2. attempt_lifecycle_events 防篡改
CREATE TRIGGER trg_protect_attempt_lifecycle_events
BEFORE UPDATE OR DELETE ON attempt_lifecycle_events
FOR EACH ROW EXECUTE FUNCTION prevent_mutation();

-- 3. attempts 防篡改 (不進行 UPDATE，僅一次性寫入最終結果)
CREATE TRIGGER trg_protect_attempts
BEFORE UPDATE OR DELETE ON attempts
FOR EACH ROW EXECUTE FUNCTION prevent_mutation();

-- 4. tool_calls 防篡改
CREATE TRIGGER trg_protect_tool_calls
BEFORE UPDATE OR DELETE ON tool_calls
FOR EACH ROW EXECUTE FUNCTION prevent_mutation();

-- 5. decisions 防篡改
CREATE TRIGGER trg_protect_decisions
BEFORE UPDATE OR DELETE ON decisions
FOR EACH ROW EXECUTE FUNCTION prevent_mutation();

-- 6. approvals 防篡改
CREATE TRIGGER trg_protect_approvals
BEFORE UPDATE OR DELETE ON approvals
FOR EACH ROW EXECUTE FUNCTION prevent_mutation();
```

---

## 4. 孤兒生命週期對齊對賬機制 (Orphan Lifecycle Reconciliation Mechanism)

由於 `attempt_lifecycle_events.attempt_id` 採用邏輯外鍵（Logical FK），在任務運行中途如果系統因硬體崩潰、斷電、外部行程遭 Kill 等異常導致「未能成功寫入最終批次交易（Batch Trace Transaction）」，則會產生孤兒生命週期日誌（Orphan Lifecycle Events）。

為保證資料庫狀態審計的真實性與完整性，系統設計了以下**對齊對賬機制**：

### 1. 孤兒嘗試偵測視圖 (Orphan Detection View)
建立一個唯讀視圖，自動找出生命週期已過期（例如大於 5 分鐘前建立）但 `attempts` 資料表沒有對應 ID 紀錄的嘗試：
```sql
CREATE OR REPLACE VIEW view_orphan_attempts AS
SELECT 
    le.attempt_id,
    MAX(le.created_at) AS last_active_at,
    ARRAY_AGG(le.state ORDER BY le.created_at) AS lifecycle_history
FROM attempt_lifecycle_events le
LEFT JOIN attempts a ON le.attempt_id = a.id
WHERE a.id IS NULL
GROUP BY le.attempt_id
HAVING MAX(le.created_at) < NOW() - INTERVAL '5 minutes';
```

### 2. 原型自動對齊處理行程 (Reconciliation Engine)
系統的背景服務（或 Cron 任務）會定期拉取該視圖，並執行以下原子修復交易：
1. **補償插入 attempts 崩潰紀錄**：
   對每個孤兒嘗試，在 `attempts` 表中插入一筆 `status = 'failed'` 紀錄，並將錯誤訊息標記為 `'System aborted: Orphan attempt detected and auto-reconciled (execution crashed or timed out before Batch Trace Transaction commit)'`。
2. **寫入 lifecycle 結束標記**：
   向 `attempt_lifecycle_events` 中插入一筆 `state = 'finished'` 的狀態，確保時間軸鏈路可讀且完結。
3. **安全防護**：
   此補償插入仍遵守 `attempts` 唯增防篡改觸發器，保證該 attempt 寫入後即不再受任何 UPDATE。

---
