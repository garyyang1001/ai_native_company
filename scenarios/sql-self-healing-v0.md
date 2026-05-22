# Scenario 1: SQL Self-Healing 驗證流程 (Loop 3 - Fixed)

本情境設計作為 **Closed Loop Kernel v0** 的第一個自癒驗證場景（Scenario 1）。本場景的目的是驗證內核在發生資料庫查詢錯誤時，如何不污染歷史、使用生命週期事件追蹤、在 SQL 沙盒中重播，並在通過四層安全部署校驗與人類 DRI 審批後原子性部署生效。

> [!IMPORTANT]
> **本場景不涉及任何「員工查詢（Employees Table）」玩具 Demo。**
> 我們使用中性的「企業數位文件庫 (`documents`)」與「標籤關聯庫 (`document_tags_mapping`)」作為業務查詢模型。

---

## 1. 驗證環境之資料庫結構 (Neutral Domain Schema)

在生產環境的 `public` schema 中，存在以下兩張業務資料表：

```sql
-- 企業文件表
CREATE TABLE public.documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 文件標籤關聯表 (使用複數命名以區隔，為 Scenario 設計之衝突點)
CREATE TABLE public.document_tags_mapping (
    document_id UUID REFERENCES public.documents(id),
    tag_name VARCHAR(100) NOT NULL,
    PRIMARY KEY (document_id, tag_name)
);
```

---

## 2. 完整驗證演練步驟 (Step-by-Step Execution)

### 步驟一：使用者發起查詢與生命週期啟動 (User Action & Lifecycle Started)
*   **輸入**：使用者輸入：*"幫我找出所有標記為 'Important' 的文件標題。"*
*   **觸發事件**：
    1.  引擎於記憶體中預先生成 `attempt_uuid = '9e02c673-dbbf-4886-905e-f00de93246bc'`。
    2.  引擎向 `events` 寫入啟動日誌。
    3.  引擎向 `attempt_lifecycle_events` 寫入啟動狀態，完全不寫入 attempts 表：
        ```sql
        INSERT INTO attempt_lifecycle_events (attempt_id, state, metadata)
        VALUES ('9e02c673-dbbf-4886-905e-f00de93246bc', 'started', '{"query": "找出標記為 Important 的文件標題"}');
        
        INSERT INTO attempt_lifecycle_events (attempt_id, state)
        VALUES ('9e02c673-dbbf-4886-905e-f00de93246bc', 'running');
        ```

---

### 步驟二：Text-to-SQL 翻譯與執行失敗 (Failure Isolation & Single INSERT)
*   **核心引擎行為**：`query.py` 載入當前 active 的 `artifacts`（Prompt version 1，其 `content_hash = '8af73d9...'`），LLM 根據 Prompt 生成以下 SQL：
    ```sql
    SELECT title FROM public.documents d
    JOIN public.document_tags t ON d.id = t.document_id
    WHERE t.tag_name = 'Important';
    ```
*   **失敗原因**：LLM 誤以為關聯表名稱是 `document_tags`，但實際生產環境是 `document_tags_mapping`。
*   **執行報報錯**：PostgreSQL 回傳錯誤 `ERROR: relation "public.document_tags" does not exist`。
*   **一次性批次提交（Batch Trace Transaction，不包含任何 UPDATE）**：
    系統開啟單次寫入交易，將所有 trace 與最終 failed outcome 寫入資料庫：
    ```sql
    BEGIN;
    
    -- 1. 寫入 attempts 表（狀態為 failed，單次寫入，永不更新）
    INSERT INTO attempts (id, status, input, output, error_message)
    VALUES ('9e02c673-dbbf-4886-905e-f00de93246bc', 'failed', '{"query": "找出標記為 Important 的文件標題"}', NULL, 'ERROR: relation "public.document_tags" does not exist');

    -- 2. 寫入 tool_calls 與 decisions 軌跡 (FK 關聯)
    INSERT INTO tool_calls (attempt_id, tool_name, arguments, result, status, error_message)
    VALUES ('9e02c673-dbbf-4886-905e-f00de93246bc', 'text_to_sql_executor', '{"sql": "SELECT title FROM public.document_tags..."}', NULL, 'failed', 'ERROR: relation "public.document_tags" does not exist');
    
    -- 3. 寫入生命週期結束事件
    INSERT INTO attempt_lifecycle_events (attempt_id, state)
    VALUES ('9e02c673-dbbf-4886-905e-f00de93246bc', 'finished');

    -- 4. 建立失敗追蹤
    INSERT INTO failures (attempt_id, failure_type, context, status)
    VALUES ('9e02c673-dbbf-4886-905e-f00de93246bc', 'syntax_error', '{"active_prompt_id": "prompt_v1_id", "schema_snapshot": "..."}', 'open');

    COMMIT;
    ```
    這徹底保證了歷史不可篡改防線，`attempts` 中此 `attempt_id` 只有一筆 `failed` 記錄，且完全無 `UPDATE` 操作。

---

### 步驟三：Supervisor 根因分析與 SQL 沙盒重播 (RCA & Replay)
*   **診斷**：`auto_improve.py` 偵測到失敗，Supervisor LLM 分析指出關聯表名稱錯誤。
*   **生成修正案**：AI 決定修改 Text-to-SQL 提示詞（Prompt），增加對 `document_tags_mapping` 結構的明確宣告。
*   **建立變更候選 (精細化 Candidate 欄位)**：
    ```sql
    INSERT INTO improvement_candidates (
        failure_id, target_artifact_id, target_artifact_version, base_artifact_hash, proposed_by, 
        description, patch_type, artifact_diff, proposed_content, content_hash, risk_level, 
        rollback_plan, validation_assertions, status
    ) VALUES (
        'failure_uuid', 'artifact_prompt_uuid', 1, '8af73d9...', 'supervisor_agent', 
        'Fix table mapping error for tag relationship', 'prompt_update', 
        '- JOIN public.document_tags \n + JOIN public.document_tags_mapping', 
        'New Prompt Content...', '9bf15e2...', 'low', 
        'UPDATE public.artifacts SET is_active = TRUE WHERE version = 1;', 
        '[{"type": "no_error"}, {"type": "output_contains", "val": "title"}]'::jsonb, 'draft'
    );
    ```
*   **SQL 沙盒重播隔離驗證**：
    1.  進行 **Static SQL DDL Linting**：過濾 SQL 補丁，確保無任何 `DROP`（臨時 sandbox schema 內除外）、`TRUNCATE` 或 `public.` 的惡意前綴。
    2.  建立臨時隔離 Schema：`CREATE SCHEMA sandbox_temp_9f2a;`。
    3.  在臨時 Schema 下複製關聯表結構，並將連線切換至低權限角色 `sandbox_runner`。
    4.  重播查詢：
        ```sql
        SET search_path = sandbox_temp_9f2a, public;
        -- 由 sandbox_runner 執行驗證 SQL
        SELECT title FROM sandbox_temp_9f2a.documents d
        JOIN sandbox_temp_9f2a.document_tags_mapping t ON d.id = t.document_id
        WHERE t.tag_name = 'Important';
        ```
    5.  執行成功（回傳 0 筆，無報錯），符合 `validation_assertions`。
*   **寫入重播結果**：
    *   建立 `replays` 紀錄 (status='success', sandbox_schema='sandbox_temp_9f2a')。
    *   更新 candidate 狀態為 `sandbox_verified`。

---

### 步驟四：人類審批阻斷安全線 (Human Gate)
*   **UI 展現**：Gary 登入控制台 `/approvals` 頁面：
    *   看見 Pending 項目。
    *   審閱精確的 Diff 以及 sandbox 重播成功的報告 `[ SUCCESS ] (sandbox_temp_9f2a)`。
    *   由於候選方案狀態為 `sandbox_verified`，Approve 按鈕解鎖可用。
*   **審批決策**：Gary 點擊 **"Approve & Deploy"**。
*   **寫入唯增 approvals 表**：
    ```sql
    INSERT INTO approvals (candidate_id, approved_by, decision, comments)
    VALUES ('candidate_uuid', 'human_dri:gary', 'approved', 'Verified. Please deploy.');
    ```

---

### 步驟五：原子部署與生產重播驗證 (Four-tier Deploy & Prod Retry)
*   **原子交易四層部署驗收**：
    引擎發起部署交易，並在單一鎖定中進行防禦校驗：
    ```sql
    BEGIN;
    
    -- 1. 鎖定當前生產 Prompt 資源行，防並發覆蓋
    SELECT content_hash FROM public.artifacts 
    WHERE id = 'artifact_prompt_uuid' AND is_active = TRUE FOR UPDATE;
    
    -- [四層指紋防線校驗]
    -- 校驗一：最新 approvals.decision 必須為 'approved'
    -- 校驗二：candidate.status 必須為 'sandbox_verified'
    -- 校驗三：replays.status 必須為 'success'
    -- 校驗四：artifacts.content_hash ('8af73d9...') 必須等於 candidate.base_artifact_hash ('8af73d9...')
    -- 校驗通過，繼續執行！

    -- 2. 升級 Prompt 版本為 2，並切換 is_active
    INSERT INTO public.artifacts (name, artifact_type, content, content_hash, version, is_active)
    VALUES ('text_to_sql_prompt', 'prompt', 'New Prompt Content...', '9bf15e2...', 2, TRUE);
    
    UPDATE public.artifacts SET is_active = FALSE 
    WHERE id = 'artifact_prompt_uuid' AND version = 1;

    -- 3. 變更狀態
    UPDATE public.improvement_candidates SET status = 'applied' WHERE id = 'candidate_uuid';
    UPDATE public.failures SET status = 'resolved' WHERE attempt_id = '9e02c673-dbbf-4886-905e-f00de93246bc';

    COMMIT;
    ```
*   **生產重播驗證 (Production Replay)**：
    *   內核使用當前 active 的 Prompt v2 重新翻譯並發起使用者原先的查詢。
    *   產生正確 SQL 並執行成功，建立**新**的 `attempts` 紀錄 (status='success')，將生命週期設為 finished。
    *   使用者順利拿到資料。
*   **審計狀態結果**：此時 attempts 歷史有兩筆紀錄：`attempt_1` (failed，歷史事實原封不動)，`attempt_2` (success，代表問題已透過閉環修復)。這證明了最底層閉環內核的自癒與高安全性特質。
