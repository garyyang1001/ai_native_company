# Scenario 2: Agent Skill Code Patching 驗證流程 (Loop 3 - New)

本情境為 **Closed Loop Kernel v0** 的第二個驗證場景（Scenario 2），專注於**非 SQL 類型**的代碼級自癒。本場景旨在驗證內核在 Agent 執行 Python 技能（Skills）或輔助模組（Helpers）拋出執行期例外（Runtime Exception）時，如何使用唯增生命週期紀錄、雙沙盒（Python AST Lint 與 Subprocess 隔離）進行重播、並經過人類 DRI 審批與四層部署指紋防線，原子性升級生產環境的代碼檔案資產。

---

## 1. 驗證環境之代碼資產結構 (Versioned Code Artifact)

在生產環境的 `skills/` 目錄中，存在一個用於處理數據對齊計算的輔助函數。在系統底層，該 Python 檔案作為受版本管理的 `artifacts` 資產進行儲存：

*   **資產名稱**：`helper_skill_calc.py`
*   **資產類型**：`code`
*   **基準版本**：`version = 1`
*   **基準指紋 (Hash)**：`e7f9a1b...` (SHA256)
*   **代碼內容 (Prompt v1)**：
    ```python
    # helper_skill_calc.py (Version 1)
    def calculate_adjusted_score(raw_score, bonus_points):
        # 缺陷：如果 bonus_points 為 None，將直接拋出 TypeError 致命崩潰
        return raw_score + bonus_points
    ```

---

## 2. 完整驗證演練步驟 (Step-by-Step Execution)

### 步驟一：外部呼叫與生命週期啟動 (Agent Execution & Lifecycle Started)
*   **輸入**：Agent 呼叫 `calculate_adjusted_score(85, None)` 來處理一個帶有缺失資料的評分任務。
*   **觸發事件**：
    1.  引擎於記憶體中預先生成 `attempt_uuid = '3bcf44c0-5a3d-4c55-b441-2a6d4d12a6cb'`。
    2.  引擎向 `attempt_lifecycle_events` 中寫入 `started` 與 `running` 狀態，完全不寫入 attempts 表。
        ```sql
        INSERT INTO attempt_lifecycle_events (attempt_id, state)
        VALUES ('3bcf44c0-5a3d-4c55-b441-2a6d4d12a6cb', 'started');
        ```

---

### 步驟二：執行期崩潰與單次寫入交易 (Runtime Exception & Single INSERT Trace)
*   **失敗原因**：由於 `bonus_points` 為 `None`，Python 解釋器拋出 `TypeError: unsupported operand type(s) for +: 'int' and 'NoneType'`。
*   **原子批次提交（Batch Trace Transaction，無任何 UPDATE）**：
    核心引擎攔截該 Runtime Error，開啟短暫且原子性的交易，將執行軌跡一次性 INSERT 到 PostgreSQL：
    ```sql
    BEGIN;

    -- 1. 寫入 attempts 表 (狀態為 failed，單次寫入，不允許 UPDATE)
    INSERT INTO attempts (id, status, input, output, error_message)
    VALUES ('3bcf44c0-5a3d-4c55-b441-2a6d4d12a6cb', 'failed', '{"raw_score": 85, "bonus_points": null}', NULL, 'TypeError: unsupported operand type(s) for +: ''int'' and ''NoneType''');

    -- 2. 寫入 tool_calls 與 decisions 軌跡 (FK 關聯)
    INSERT INTO tool_calls (attempt_id, tool_name, arguments, result, status, error_message)
    VALUES ('3bcf44c0-5a3d-4c55-b441-2a6d4d12a6cb', 'helper_skill_calc', '{"raw_score": 85, "bonus_points": null}', NULL, 'failed', 'TypeError: ...');

    -- 3. 寫入生命週期結束事件
    INSERT INTO attempt_lifecycle_events (attempt_id, state)
    VALUES ('3bcf44c0-5a3d-4c55-b441-2a6d4d12a6cb', 'finished');

    -- 4. 建立失敗追蹤
    INSERT INTO failures (attempt_id, failure_type, context, status)
    VALUES ('3bcf44c0-5a3d-4c55-b441-2a6d4d12a6cb', 'runtime_exception', '{"target_artifact_name": "helper_skill_calc.py", "active_version": 1}', 'open');

    COMMIT;
    ```
    資料庫層 `trg_protect_attempts` 觸發器會鎖死該 ID，任何對此 `attempts` 紀錄的 `UPDATE` 都將直接被拒絕。

---

### 步驟三：Supervisor 診斷與 Python 代碼沙盒重播 (RCA & Python AST Sandbox)
*   **診斷**：Supervisor Agent 讀取 failures 紀錄與錯誤日誌，診斷出 `helper_skill_calc.py` 缺乏對 `None` 型態的邊界條件安全防禦。
*   **生成修正代碼與 Candidate (結構化補丁欄位)**：
    Supervisor 自動生成修正後的完整新代碼，並在資料庫中建立 Candidate 紀錄：
    *   `patch_type` = `code_patch`
    *   `proposed_content`：
        ```python
        # helper_skill_calc.py (Version 2)
        def calculate_adjusted_score(raw_score, bonus_points):
            # 新增防禦：若 bonus_points 為 None，則自動視為 0
            safe_bonus = bonus_points if bonus_points is not None else 0
            return raw_score + safe_bonus
        ```
    *   `artifact_diff` = `-[bonus_points] \n +[safe_bonus = bonus_points if bonus_points is not None else 0 \n return raw_score + safe_bonus]`
    *   `content_hash` = `3df18c5...` (修正後完整代碼之 SHA256)
    *   `base_artifact_hash` = `e7f9a1b...` (基礎代碼 Version 1 之 Hash)
    *   `risk_level` = `low`
    *   `rollback_plan` = `UPDATE public.artifacts SET is_active = TRUE WHERE name = 'helper_skill_calc.py' AND version = 1;`
    *   `validation_assertions` = `[{"type": "no_exception"}, {"type": "output_equals", "val": 85}]`::jsonb
*   **Python 雙沙盒隔離驗證**：
    1.  **AST Static Linting (前置語法樹過濾)**：
        系統調用 `ast.parse()` 解析新代碼，檢查 `Import` 與 `Call` 節點。確保無調用 `os`, `sys`, `subprocess`, `socket`, `builtins.__import__` 等敏感 API 的意圖，防止沙盒越權。
    2.  **子進程隔離沙盒 (Subprocess Exec Sandbox)**：
        - 系統啟動一個獨立的作業系統級子進程（Subprocess），並限制其在臨時虛擬目錄（Ephemeral Virtual Directory）下執行。
        - 將修正後的 `helper_skill_calc.py` 載入沙盒，重播原先失敗的參數 `(85, None)`。
        - 執行順利通過，回傳結果為 `85`，符合 `validation_assertions` 斷言。
    3.  **寫入重播結果**：
        - 寫入 `replays` (status='success', sandbox_env='{"python_version": "3.11", "sandbox_type": "subprocess"}')。
        - 將 candidate 狀態設為 `sandbox_verified`。

---

### 步驟四：人類審批阻斷安全線 (Human Gate)
*   **DRI 審核**：Gary 登入控制台 `/approvals` 頁面：
    *   檢視 Pending 變更（Type: `code_patch`，對象：`helper_skill_calc.py`）。
    *   比對代碼 Diff，看見安全防禦語句。
    *   檢視沙盒重播：`[ SUCCESS ] (Python Subprocess)`。Gary 點擊 **"Approve & Deploy"**。
*   **寫入 approvals 表**：
    ```sql
    INSERT INTO approvals (candidate_id, approved_by, decision, comments)
    VALUES ('code_candidate_uuid', 'human_dri:gary', 'approved', 'Code patch verified in sandbox. Deploy to prod.');
    ```

---

### 步驟五：四層部署防線原子套用與生產驗證 (Four-tier Deploy & Prod Retry)
*   **原子交易四層部署驗收**：
    套用引擎啟動部署交易，在 artifacts 行級鎖定中執行四層校驗：
    ```sql
    BEGIN;

    -- 1. 鎖定當前 active artifact 行，確保部署期間沒有其他 Agent 修改過它
    SELECT content_hash FROM public.artifacts 
    WHERE name = 'helper_skill_calc.py' AND is_active = TRUE FOR UPDATE;

    -- [四層指紋防線校驗]
    -- 校驗一：最新 approvals.decision 必須為 'approved'
    -- 校驗二：candidate.status 必須為 'sandbox_verified'
    -- 校驗三：replays.status 必須為 'success'
    -- 校驗四：artifacts.content_hash ('e7f9a1b...') 必須等於 candidate.base_artifact_hash ('e7f9a1b...')
    -- 校驗通過，繼續執行！

    -- 2. 寫入新 version 2 代碼 Artifact，並失效舊版本
    INSERT INTO public.artifacts (name, artifact_type, content, content_hash, version, is_active)
    VALUES ('helper_skill_calc.py', 'code', 'def calculate_adjusted_score(raw_score, bonus_points):...', '3df18c5...', 2, TRUE);

    UPDATE public.artifacts SET is_active = FALSE 
    WHERE name = 'helper_skill_calc.py' AND version = 1;

    -- 3. 變更狀態
    UPDATE public.improvement_candidates SET status = 'applied' WHERE id = 'code_candidate_uuid';
    UPDATE public.failures SET status = 'resolved' WHERE attempt_id = '3bcf44c0-5a3d-4c55-b441-2a6d4d12a6cb';

    COMMIT;
    ```

*   **生產重播驗證 (Production Replay)**：
    *   核心引擎載入生產環境最新生效的 `helper_skill_calc.py` (Version 2)。
    *   重新發起原先失敗的任務 `calculate_adjusted_score(85, None)`。
    *   執行成功並回傳結果 `85`，引擎一次性 `INSERT` 新 `attempts` 紀錄 (status='success')，並更新 lifecycle 為 finished。
    *   問題成功自癒，且保留了完整的 failed 與 success 的歷史審計軌跡，無任何 DDL 或 Python 狀態被隨意污染。這證明了本內核非 SQL 代碼修補功能的健全性與泛用性。
