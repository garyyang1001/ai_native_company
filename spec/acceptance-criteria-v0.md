# Acceptance Criteria Specification (Loop 3 - Fixed)

本文件定義 **Closed Loop Kernel v0** 的工程驗收標準（Acceptance Criteria）。任何實作版本必須通過以下 6 項原型驗收指標與測試斷言，方可進行閉環原型對齊。

---

## 1. 指標一：資料庫持久化、UUID 支援與防篡改驗證 (Database Immutability)

### 驗收標準
*   [ ] 使用 PostgreSQL 原生的 `pgcrypto` 啟用 `gen_random_uuid()`，且各表主鍵 UUID 生成正常，不依賴非原生的 `uuid-ossp`。
*   [ ] `events`、`attempt_lifecycle_events`、`attempts`、`tool_calls` 與 `decisions` 紀錄在寫入後，資料庫層必須藉由 DDL 觸發器阻斷任何 `UPDATE` 或 `DELETE` 的請求，拋出防篡改 Exception。
*   [ ] 狀態變更紀錄（如 `failures`, `replays`, `improvement_candidates`）必須在 PostgreSQL 實體表中持久化，重啟服務後資料不得丟失。

### 測試斷言 (Assertion SQL)
```sql
-- 測試 1：嘗試修改 attempts 紀錄應被觸發器阻斷
-- 預期結果：ERROR: IMPERMISSIBLE ACTION: Table attempts is append-only...
UPDATE public.attempts SET status = 'success' WHERE id = 'some-uuid';

-- 測試 2：嘗試刪除 attempt_lifecycle_events 紀錄應被阻斷
-- 預期結果：ERROR: IMPERMISSIBLE ACTION: Table attempt_lifecycle_events is append-only...
DELETE FROM public.attempt_lifecycle_events WHERE attempt_id = 'some-uuid';

-- 測試 3：嘗試刪除 tool_calls 紀錄應被阻斷
-- 預期結果：ERROR: IMPERMISSIBLE ACTION: Table tool_calls is append-only...
DELETE FROM public.tool_calls WHERE id = 'some-uuid';
```

---

## 2. 指標二：不吞錯失敗隔離與單次寫入驗證 (Failure Isolation & Single INSERT)

### 驗收標準
*   [ ] 任務執行期間，引擎不得對 `attempts` 執行任何 `UPDATE`，也不得將未完結的 attempt 提早插入資料庫。
*   [ ] 任務啟動與運作時，僅唯增寫入 `attempt_lifecycle_events` (狀態為 `started`、`running`) 作為即時狀態監控。
*   [ ] 任務完結時，執行一個原子交易以**單次寫入 (Single INSERT) 且狀態為 `failed` 或 `success`** 的方式新增 `attempts`，並將記憶體緩衝的 `tool_calls` 與 `decisions` 一次性 INSERT 提交。
*   [ ] `attempts.error_message` 必須包含完整的 Python Exception 堆疊 (Stack Trace) 字串，不可被隱藏。
*   [ ] 系統必須在 `failures` 資料表中建立一筆 `status='open'` 且帶有當下 Schema Snapshots 與 Prompts 的 Failure 紀錄。

### 測試斷言 (Assertion PyTest / SQL)
```python
def test_failure_isolation_and_single_insert(db_connection):
    # 1. 預先生成 UUID
    attempt_id = generate_uuid()
    
    # 2. 模擬啟動，此時僅在 lifecycle 表中插入 started 與 running 狀態，attempts 表尚無此 id
    db_connection.execute(
        "INSERT INTO attempt_lifecycle_events (attempt_id, state) VALUES (%s, 'started')", (attempt_id,)
    )
    db_connection.execute(
        "INSERT INTO attempt_lifecycle_events (attempt_id, state) VALUES (%s, 'running')", (attempt_id,)
    )
    
    attempts_exist = db_connection.query("SELECT * FROM attempts WHERE id = %s", (attempt_id,))
    assert len(attempts_exist) == 0  # 核心保證：執行中 attempts 表無紀錄
    
    # 3. 執行一個故意拋出 Exception 的任務，引擎應將錯誤攔截並一次性寫入
    execute_faulty_task_and_batch_commit(attempt_id)
    
    # 4. 驗證：查詢 attempts 資料表，該 ID 應只有一筆紀錄，且狀態為 failed，絕無 UPDATE
    attempts = db_connection.query("SELECT * FROM attempts WHERE id = %s", (attempt_id,))
    assert len(attempts) == 1
    assert attempts[0]['status'] == 'failed'
    assert "TypeError" in attempts[0]['error_message']  # 確保沒有吞錯
    
    # 5. 驗證：對該 attempts 執行 UPDATE 必須觸發 DB 觸發器報錯
    with pytest.raises(Exception, match="Table attempts is append-only"):
        db_connection.execute("UPDATE attempts SET status='success' WHERE id = %s", (attempt_id,))
```

---

## 3. 指標三：雙沙盒隔離與靜態安全 Lints 驗證 (Sandbox Security & AST Lint)

### 驗收標準
*   [ ] **SQL 沙盒**：AI 生成的 SQL/DDL 補丁如果含有 `DROP TABLE`（臨時沙盒 DDL 除外）、`TRUNCATE` 或任何 `public.` 等前綴字串，靜態 SQL DDL Linting 必須在執行前直接拋出 `SecurityError` 進行阻斷。
*   [ ] SQL 沙盒重播時，由獨立極小權限 Role `sandbox_runner` 進行連線，該角色嘗試存取 `public` 表或進行非授權 schema 建立時必須被 PostgreSQL 強制阻斷。
*   [ ] **Code 沙盒**：AI 生成的 Python 代碼補丁在進入子進程執行前，必須進行 **AST Static Linting**。若代碼包含調用 `os`、`sys`、`subprocess`、`socket` 或試圖寫入非指定虛擬目錄之檔案，必須直接拋出 `SecurityError` 阻斷。
*   [ ] 重播驗證結果必須寫入 `replays` 表，且只有在 `replays.status = 'success'` 且通過 `validation_assertions` 時，Candidate 才能變為 `sandbox_verified`。

### 測試斷言 (Security Test)
```python
def test_sandbox_security_defenses(sandbox_runner_connection):
    # 1. 測試 SQL Lint 阻斷
    faulty_ddl = "DROP TABLE public.attempts;"
    with pytest.raises(SecurityError, match="SQL Lint Blocked: Forbidden keyword"):
        validate_and_lint_sql(faulty_ddl)
        
    # 2. 測試 SQL least-privilege 角色阻斷
    # 即使繞過了 Lint，sandbox_runner 連線嘗試存取 public 也必須被資料庫阻斷
    with pytest.raises(Exception, match="permission denied for schema public"):
        sandbox_runner_connection.execute("SELECT * FROM public.attempts")

    # 3. 測試 Python AST Lint 阻斷
    faulty_code = "import os; os.system('rm -rf /')"
    with pytest.raises(SecurityError, match="Python AST Lint Blocked: Forbidden module import"):
        validate_and_lint_python_ast(faulty_code)
```

---

## 4. 指標四：四層部署防線與防 Race Condition 驗證 (Deployment Verification)

### 驗收標準
*   [ ] 部署（Deploy）時，系統會啟動一個資料庫交易，強制校驗以下**四項部署指紋防線**：
    1.  最新審批記錄 `decision = 'approved'`。
    2.  Candidate 狀態為 `status = 'sandbox_verified'`。
    3.  重播紀錄 `status = 'success'`。
    4.  目標資產在生產環境的當前 `content_hash` 等於 Candidate 保存的基底指紋 `base_artifact_hash`。
*   [ ] 如果上述任何一項不一致，部署交易必須自動 **ROLLBACK**，拒絕套用，並將 Candidate 狀態退回 `draft`。

### 測試斷言 (Race Condition Verification)
```python
def test_atomic_rollback_on_fingerprint_mismatch(db_connection):
    # 1. 建立一筆已驗證且審批通過的 Candidate，其 base_artifact_hash 紀錄為 'hash_v1'
    candidate_id = create_approved_candidate_for_prompt_v1() # status = 'sandbox_verified', approvals.decision = 'approved'
    
    # 2. 在部署發起前，另一個並行 Agent 搶先修改了生產環境的同名 Artifact 為 version 2，其 Hash 變為 'hash_v2'
    db_connection.execute("UPDATE artifacts SET content_hash = 'hash_v2', version = 2 WHERE name = 'prompt' AND is_active = TRUE")
    
    # 3. 執行部署交易（預期會因為當前 Hash 'hash_v2' 不匹配 candidate.base_artifact_hash 'hash_v1' 而拋出異常並自動 Rollback）
    with pytest.raises(Exception, match="Race condition detected: Artifact has changed"):
        execute_deploy_transaction(candidate_id)
        
    # 4. 驗證：檢查 artifacts 版本，生產環境必須維持 version 2 (Hash: 'hash_v2')，Candidate 狀態應退回 draft
    active_artifact = db_connection.query("SELECT * FROM artifacts WHERE name = 'prompt' AND is_active = TRUE")
    assert active_artifact[0]['content_hash'] == 'hash_v2'
    
    candidate = db_connection.query("SELECT status FROM improvement_candidates WHERE id = %s", (candidate_id,))
    assert candidate[0]['status'] == 'draft'
```

---

## 5. 指標五：原子性回滾與生產驗證 (Atomic Rollback & Prod Verification)

### 驗收標準
*   [ ] 當新變更套用至生產環境後，若生產環境隨後的首次執行嘗試仍失敗，系統必須能立刻提取 candidate 的 `rollback_plan`。
*   [ ] 對於 DDL 變更，能在單一事務中原子性執行回滾 SQL，將 active 指向舊版本 Artifact，不留任何中間狀態。
*   [ ] 新變更部署成功後，必須產生一筆 status = 'success' 的新 attempts 記錄以完成閉環。

---

## 6. 指標六：孤兒生命週期對賬與補償 (Orphan Lifecycle Reconciliation)

### 驗收標準
*   [ ] 原型系統必須能精確偵測因為硬體或行程崩潰導致有 `attempt_lifecycle_events` 但無 `attempts` 記錄的孤兒 ID（過期時間設為 5 分鐘以上）。
*   [ ] 執行 Reconciliation 時，必須向 `attempts` 原子性插入一筆失敗補償紀錄（status = 'failed'，描述為 crash timeout），並同時將 `attempt_lifecycle_events` 時間軸封閉（state = 'finished'）。
*   [ ] 此補償寫入完成後，該 attempt 紀錄必須同樣被 `attempts` 唯增防篡改觸發器鎖定，禁止任何隨後的 UPDATE。

### 測試斷言 (Orphan Reconciliation Verification)
```python
def test_orphan_lifecycle_reconciliation(db_connection):
    orphan_attempt_id = gen_random_uuid()
    
    # 1. 模擬任務中途崩潰：只寫入了生命週期，沒有來得及寫入 attempts 就中斷了
    db_connection.execute(
        "INSERT INTO attempt_lifecycle_events (attempt_id, state, created_at) VALUES (%s, 'started', NOW() - INTERVAL '6 minutes')", 
        (orphan_attempt_id,)
    )
    db_connection.execute(
        "INSERT INTO attempt_lifecycle_events (attempt_id, state, created_at) VALUES (%s, 'running', NOW() - INTERVAL '5 minutes' - INTERVAL '30 seconds')", 
        (orphan_attempt_id,)
    )
    
    # 2. 驗證：此時 attempts 表中沒有該 ID，且偵測視圖中可看見此孤兒
    attempts_exist = db_connection.query("SELECT * FROM attempts WHERE id = %s", (orphan_attempt_id,))
    assert len(attempts_exist) == 0
    
    orphans = db_connection.query("SELECT * FROM view_orphan_attempts WHERE attempt_id = %s", (orphan_attempt_id,))
    assert len(orphans) == 1
    
    # 3. 執行對賬修復
    run_orphan_reconciliation(db_connection)
    
    # 4. 驗證：attempts 表中已產生一筆補償失敗紀錄，且 lifecycle events 補上了 finished 狀態
    attempts_after = db_connection.query("SELECT * FROM attempts WHERE id = %s", (orphan_attempt_id,))
    assert len(attempts_after) == 1
    assert attempts_after[0]['status'] == 'failed'
    assert "Orphan attempt detected and auto-reconciled" in attempts_after[0]['error_message']
    
    events_after = db_connection.query("SELECT * FROM attempt_lifecycle_events WHERE attempt_id = %s ORDER BY created_at", (orphan_attempt_id,))
    assert events_after[-1]['state'] == 'finished'
    
    # 5. 驗證：補償寫入後的 attempts 依然被觸發器鎖死，禁止任何 UPDATE
    with pytest.raises(Exception, match="Table attempts is append-only"):
        db_connection.execute("UPDATE attempts SET status='success' WHERE id = %s", (orphan_attempt_id,))
```
