# System Verification Log

本檔案記錄 **Closed Loop Kernel v0** 的自我驗證歷程。本內核規格已完成多輪工程安全與資料流自檢，檢驗證據與結果詳列如下。

---

## 1. 第一輪驗證檢驗 (Round 1 Verification)

*   **驗證時間**：2026-05-22T12:15:00+08:00
*   **檢驗人**：Antigravity (AI Coding Assistant)
*   **檢查項目與實體證據**：
    
    1.  **搜尋 `employees` / 員工 Demo 殘留**：
        *   *搜尋方法*：執行全域搜尋 "employee" 關鍵字。
        *   *證據結果*：經確認，除對齊說明、逐字稿與指令外，9 個設計與場景檔案中未包含 any employees 業務資料表或相關查詢。業務模型已改為 `documents` 與 `tags`。 (結果：**PASS**)
    
    2.  **搜尋 `logs.jsonl` 是否被誤當 Source of Truth**：
        *   *搜尋方法*：執行全域搜尋 "logs.jsonl"。
        *   *證據結果*：確認 PostgreSQL 為 Single Source of Truth，JSONL 定位為 debug/export 紀錄。 (結果：**PASS**)
    
    3.  **搜尋 `UPDATE attempts` 或 running 狀態更新衝突**：
        *   *搜尋方法*：執行全域搜尋 "UPDATE attempts" 與 "running"。
        *   *證據結果*：確認 attempts 僅作一次性寫入，無執行中途 UPDATE 的矛盾。唯一的 `UPDATE attempts` 語句存在於 `spec/acceptance-criteria-v0.md` 中，其作為測試防篡改 Trigger 阻斷特性的測試斷言，邏輯正確。 (結果：**PASS**)
    
    4.  **檢查 11 張核心表是否完整包含**：
        *   *檢查方法*：搜尋 `spec/schema-v0.md` 中 "CREATE TABLE" 定義。
        *   *證據結果*：`events`、`artifacts`、`policy_gates`、`attempt_lifecycle_events`、`attempts`、`decisions`、`tool_calls`、`failures`、`improvement_candidates`、`replays`、`approvals` 等 11 張核心資料表皆已定義。 (結果：**PASS**)
    
    5.  **檢查 `pgcrypto` / `gen_random_uuid()` 一致性**：
        *   *檢查方法*：檢視 `spec/schema-v0.md` DDL。
        *   *證據結果*：確認使用 pgcrypto 的 `gen_random_uuid()`，未使用 `uuid-ossp`。 (結果：**PASS**)
    
    6.  **檢查部署四層指紋防線**：
        *   *檢查方法*：檢索 `spec/event-flow-v0.md` 變更套用。
        *   *證據結果*：部署包含 approvals 批准、sandbox 驗證、replay 成功與樂觀鎖雜湊校驗。 (結果：**PASS**)
    
    7.  **檢查沙盒隔離防線**：
        *   *檢查方法*：閱讀 `spec/event-flow-v0.md` 第 3 節沙盒機制。
        *   *證據結果*：規劃了 DDL 沙盒（Static DDL Lint、低權限 role、動態隔離 Schema）與 Code 沙盒（AST Lint、隔離子進程）之防禦。 (結果：**PASS**)
    
    8.  **檢查自評是否客觀**：
        *   *檢查方法*：搜尋誇飾包裝詞。
        *   *證據結果*：確認 `notes/self-review.md` 客觀列出 3 個殘留風險。 (結果：**PASS**)
    
    9.  **檢查是否有 SQL 與非 SQL 雙驗證場景**：
        *   *檢查方法*：檢查 scenarios/ 目錄。
        *   *證據結果*：`sql-self-healing-v0.md` (Scenario 1, SQL自癒) 與 `agent-skill-patch-v0.md` (Scenario 2, Python技能自癒) 均已建立，邏輯一致。 (結果：**PASS**)
    
    10. **檢查驗收指標是否對應 Assertion 測試**：
        *   *檢查方法*：檢視 `spec/acceptance-criteria-v0.md` 測試斷言。
        *   *證據結果*：各驗收指標已具備相應的測試斷言代碼。 (結果：**PASS**)

*   **第一輪結論**：**PASS**。無 Blocker 或 High 議題，各項規格大致對齊。

---

## 2. 第二輪驗證檢驗 (Round 2 Verification - Deep Transaction Audit)

*   **驗證時間**：2026-05-22T12:16:00+08:00
*   **檢驗人**：Antigravity (AI Coding Assistant)
*   **檢查項目與實體證據**：
    
    針對唯讀 attempts、批次單次寫入交易（Batch Trace Transaction）於高並發環境下的外鍵關聯 Timing 與交易鎖定順序進行審查：
    
    1.  **審查邏輯外鍵與 timing 衝突**：
        *   *檢查對象*：`spec/schema-v0.md` 中 `decisions`、`tool_calls` 與 `failures` 的關聯欄位。
        *   *審查設計*：確認先寫入 attempts 再寫入 decisions 與 tool_calls，外鍵約束可正常通過。 (結果：**PASS**)
    
    2.  **審查部署混合鎖定之順序防死鎖 (Anti-deadlock Lock Ordering)**：
        *   *檢查對象*：`spec/event-flow-v0.md` 第 4 節部署鎖定。
        *   *審查設計*：確認 artifacts 升級交易鎖定順序一致。
        *   *規格保障*：部署交易鎖定順序為 artifacts -> candidates -> failures，避開交叉鎖定死鎖風險。 (結果：**PASS**)

*   **第二輪結論**：**PASS**。資料庫交易與鎖定機制的潛在衝突已作處理。

---

## 3. 第三輪驗證檢驗 (Round 3 Verification - Word Review)

*   **驗證時間**：2026-05-22T12:17:30+08:00
*   **檢驗人**：Antigravity (AI Coding Assistant)
*   **檢查項目與實體證據**：
    
    為符合務實、客觀要求，本輪進行了自嗨詞彙清掃與 UI 規格核對：
    
    1.  **規格檔案誇飾字眼清查**：
        *   *檢索方法*：搜尋規格檔案中的誇飾字眼。
        *   *審查發現*：在 `notes/source-alignment.md` 發現誇飾描述。
        *   *修復證據*：將誇飾描述替換為客觀的「實際生產」與「具體工程」。 (結果：**PASS**)
    
    2.  **核對 UI 規格的狀態更新**：
        *   *檢索對象*：[spec/html-views-v0.md](spec/html-views-v0.md)。
        *   *證據結果*：Attempt 顯示節點定位為唯讀，新重試產生新 Attempt，無中途 UPDATE 衝突。 (結果：**PASS**)

*   **第三輪結論**：**PASS**。各工程文件字詞語意已調整為務實客觀。

---

## 4. 第四輪驗證檢驗 (Round 4 Verification - Global Consistency Check)

*   **驗證時間**：2026-05-22T12:20:00+08:00
*   **檢驗人**：Antigravity (AI Coding Assistant)
*   **檢查項目與實體證據**：

    本輪針對規格一致性進行自檢，並調整殘留的誇飾詞彙：

    1.  **誇飾詞彙調整**：
        *   *檢索方法*：檢視規格，發現在 html-views、scenarios 與 research-findings 中仍有部分誇飾形容詞。
        *   *修復*：
            - 修改 [spec/html-views-v0.md](spec/html-views-v0.md)：調整字詞使語意更為客觀。
            - 修改 [scenarios/agent-skill-patch-v0.md](scenarios/agent-skill-patch-v0.md)：調整測試語氣。
            - 修改 [notes/research-findings.md](notes/research-findings.md)：替換為實際生產實踐。 (結果：**PASS**)

    2.  **再次確認無 Employees 業務表**：
        *   *檢索對象*：9 個系統規格與場景檔案。
        *   *證據結果*：無業務邏輯涉及 employees，Scenario 1 與整個 v0 體系使用 documents 與 tags。 (結果：**PASS**)

    3.  **再次確認 attempts 唯增與 DDL 觸發器**：
        *   *檢索對象*：[spec/schema-v0.md](spec/schema-v0.md) 與 [spec/acceptance-criteria-v0.md](spec/acceptance-criteria-v0.md)。
        *   *證據結果*：attempts 設計為一次性批次寫入，無執行中途 UPDATE 的矛盾，且 `acceptance-criteria-v0.md` 設有阻斷測試。 (結果：**PASS**)

*   **第四輪結論**：**PASS**。系統規格在安全、資料流與防篡改機制上已對齊，具備原型搭建準備。

---

## 5. 第五輪驗證檢驗 (Round 5 Verification - FK Alignment & Reconciliation Audit)

*   **驗證時間**：2026-05-22T12:36:00+08:00
*   **檢驗人**：Antigravity (AI Coding Assistant)
*   **檢查項目與實體證據**：

    針對外鍵（FK）一致性、孤兒生命週期對賬機制、原型開發決策條件以及已知風險進行自檢：

    1.  **核對外鍵（FK）約束**：
        *   *審查對象*：`spec/schema-v0.md` 與先前描述。
        *   *發現問題*：schema-v0.md 內 decisions、tool_calls 與 failures 缺實體外鍵。
        *   *修復證據*：已於 `schema-v0.md` 補上實體 `REFERENCES attempts(id)` 約束，確保批次寫入能受外鍵校驗。 (結果：**PASS**)

    2.  **孤兒生命週期對賬機制與驗收指標**：
        *   *審查對象*：`attempt_lifecycle_events` 中無 attempts 實體的孤兒事件。
        *   *修復證據*：
            - 在 `schema-v0.md` 規劃 `view_orphan_attempts` 與處理設計。
            - 在 `acceptance-criteria-v0.md` 新增指標六與對應測試。 (結果：**PASS**)

    3.  **審批與決策條件**：
        *   *審查對象*：`tracking/next-actions.md` 中的決策條件。
        *   *修復證據*：明確界定原型開發期間，如涉及生產環境、檔案部署、系統服務配置或外部通知等，仍須經 Gary 審批。 (結果：**PASS**)

    4.  **已知風險與延期問題**：
        *   *審查對象*：`tracking/open-issues.md` 與 `tracking/status.md`。
        *   *修復證據*：
            - 將 `open-issues.md` 分為 Blocker/High 與 Deferred 兩類。
            - 修改 `tracking/status.md`，將整體狀態定位為 `ready-for-prototype-build`，並列明 3 個 Deferred Issues 為原型階段已知風險。 (結果：**PASS**)

    5.  **核對檢查項目**：
        - [x] 1. 無 employees demo。
        - [x] 2. PostgreSQL 為 source of truth，非 JSONL。
        - [x] 3. attempts 單次寫入，無 running->failed/success 的 UPDATE 矛盾。
        - [x] 4. 11 張核心表皆有 DDL 與外鍵防線。
        - [x] 5. 原生 pgcrypto 與 gen_random_uuid() 保持一致。
        - [x] 6. approvals 部署包含 approvals 最新批准、sandbox 驗證、replays 成功與樂觀鎖。
        - [x] 7. 雙沙盒隔離（Lints + sandbox_runner role + subprocess 隔離）各自分離。
        - [x] 8. 正式 spec/scenario/status 內不使用誇大詞；verification log 只保留必要審查紀錄，並避免使用那些詞本身。
        - [x] 9. 具備 SQL 與非 SQL（Python AST Skill）雙自癒驗證場景。
        - [x] 10. 驗收標準對應 PyTest 與 SQL assertion 斷言（已追加指標六）。

*   **第五輪結論**：**PASS**。無 Blocker/High 設計阻礙，3 項已知風險已登記並提供原型期緩解說明。規格在原型建置範疇上符合原型驗收標準，本專案設置為 `ready-for-prototype-build` 狀態。

---

## 6. 第六輪驗證檢驗 (Round 6 Verification - Humble Prose Alignment & Word Search Audit)

*   **驗證時間**：2026-05-22T12:43:00+08:00
*   **檢驗人**：Antigravity (AI Coding Assistant)
*   **檢查項目與實體證據**：

    本輪針對整體檔案中的字詞一致性、過度肯定語意進行清查與微調：

    1.  **規格檔案引用與語意修正**：
        *   *修復對象*：`tracking/verification-log.md`（本檔案）、`tracking/next-actions.md`、`tracking/status.md`、`spec/closed-loop-kernel-v0.md` 與 `ai_native_closed_loop_architecture.md`。
        *   *修改證據*：
            - 重寫 `tracking/verification-log.md` 歷史歷程以去除誇飾形容詞、過度肯定語氣與標籤；
            - 將 status、next-actions、closed-loop-kernel、architecture 各處文件中有關驗收指標的數量從原先指標調整為「6項原型驗收指標」；
            - 修正 next-actions.md 描述以避免過度肯定說法，明定原型實作準備就緒。 (結果：**PASS**)

    2.  **安全與字彙搜尋檢驗**：
        *   *搜尋方法*：執行全域搜尋以檢驗敏感與誇飾字詞之殘留。
        *   *搜尋結果*：目前在正式規格與追蹤文件中未發現上述殘留。 (結果：**PASS**)

*   **第六輪結論**：**PASS**。規格與追蹤文件的字意與指針已調整，語意較客觀。

---

## 7. 第七輪驗證檢驗 (Round 7 Verification - Local Prototype Baseline)

*   **驗證時間**：2026-05-22T13:26:05+08:00
*   **檢驗人**：Codex
*   **檢查項目與實體證據**：

    本輪開始將規格推進到本地可跑 prototype。採用 Python 標準函式庫與 SQLite adapter，先驗證資料流與約束，不接觸 production DB。

    1.  **本地測試建立與執行**：
        *   *測試檔案*：`tests/test_closed_loop_kernel.py`、`tests/test_demo.py`。
        *   *執行命令*：`python3 -m unittest discover -s tests`。
        *   *結果*：7 tests passed。 (結果：**PASS**)

    2.  **核心 prototype 檔案**：
        *   *實作檔案*：`closed_loop_kernel/store.py`、`closed_loop_kernel/engine.py`、`closed_loop_kernel/demo.py`。
        *   *覆蓋範圍*：append-only trigger、attempt lifecycle、failure、candidate、replay、approval、apply、hash mismatch rollback、orphan reconciliation、SQL/Python lint。 (結果：**PASS**)

    3.  **Demo run**：
        *   *執行命令*：`python3 -m closed_loop_kernel.demo`。
        *   *結果摘要*：failed attempt 保留為 `failed`；candidate 套用後為 `applied`；failure 轉為 `resolved`；active artifact 變成安全修正版。 (結果：**PASS**)

    4.  **仍未完成的 prototype gap**：
        *   PostgreSQL adapter 尚未實作。
        *   真實 `sandbox_runner` role 與動態 schema replay 尚未實作。
        *   Python subprocess sandbox 尚未實作。
        *   最小 HTML views 尚未實作。

*   **第七輪結論**：**PASS**。本地 prototype 已開始，第一批可重跑測試通過；下一步應聚焦 PostgreSQL adapter、真實 sandbox 與 HTML views。

---

## 8. 第八輪驗證檢驗 (Round 8 Verification - PostgreSQL DDL & HTML Renderer)

*   **驗證時間**：2026-05-22T13:29:23+08:00
*   **檢驗人**：Codex
*   **檢查項目與實體證據**：

    1.  **PostgreSQL DDL renderer**：
        *   *測試檔案*：`tests/test_postgres_schema.py`。
        *   *實作檔案*：`closed_loop_kernel/postgres.py`。
        *   *覆蓋範圍*：`pgcrypto`、`gen_random_uuid()`、核心 FK、append-only trigger、`view_orphan_attempts`。 (結果：**PASS**)

    2.  **HTML views renderer**：
        *   *測試檔案*：`tests/test_views.py`。
        *   *實作檔案*：`closed_loop_kernel/views.py`。
        *   *覆蓋範圍*：`/events`、`/events/:id`、`/improvements`、`/approvals` 的核心資訊；approval view 會依 `sandbox_verified` 與 successful replay 控制按鈕狀態。 (結果：**PASS**)

    3.  **完整測試**：
        *   *執行命令*：`python3 -m unittest discover -s tests`。
        *   *結果*：12 tests passed。 (結果：**PASS**)

*   **第八輪結論**：**PASS**。PostgreSQL DDL 與 HTML renderer 已有本地可驗證版本；下一步是接真實 PostgreSQL integration、subprocess sandbox 與 HTTP routes。

---

## 9. 第九輪驗證檢驗 (Round 9 Verification - Subprocess Sandbox & HTTP UI)

*   **驗證時間**：2026-05-22T13:36:32+08:00
*   **檢驗人**：Codex
*   **檢查項目與實體證據**：

    1.  **Python subprocess sandbox**：
        *   *測試檔案*：`tests/test_python_sandbox.py`。
        *   *實作檔案*：`closed_loop_kernel/sandbox.py`、`closed_loop_kernel/engine.py`。
        *   *覆蓋範圍*：安全函式在獨立 Python process 執行並回傳 JSON；危險 import 在執行前被 AST lint 阻斷；`replay_code_candidate` 會寫入 replay 並將 candidate 設為 `sandbox_verified`。 (結果：**PASS**)

    2.  **HTTP UI routes**：
        *   *測試檔案*：`tests/test_http_app.py`。
        *   *實作檔案*：`closed_loop_kernel/http_app.py`。
        *   *覆蓋範圍*：`/events`、`/events/:id`、`/improvements`、`/approvals`、`/favicon.ico`；實際 HTTP server 測試涵蓋 SQLite cross-thread access。 (結果：**PASS**)

    3.  **Browser/HTTP smoke test**：
        *   *執行狀態*：`python3 -m closed_loop_kernel.http_app` 啟動於 `http://127.0.0.1:8765/events`。
        *   *HTTP 驗證*：`curl` 對 `/events` 回 200；`/improvements` 顯示 `sandbox_verified`；`/approvals` 顯示 `Approve & Deploy`。
        *   *Browser 驗證*：Chrome DevTools 開啟 `/events`，document request 200，console 無錯誤。 (結果：**PASS**)

    4.  **完整測試**：
        *   *執行命令*：`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests`。
        *   *結果*：20 tests passed。 (結果：**PASS**)

*   **第九輪結論**：**PASS**。本地 prototype 已具備 subprocess code replay 與可瀏覽 HTTP UI；下一步應處理真實 PostgreSQL integration、SQL sandbox runner、Python sandbox hardening，以及本地 approve/reject action。

---

## 10. 第十輪驗證檢驗 (Round 10 Verification - Human-readable UI & Approval Actions)

*   **驗證時間**：2026-05-22T16:04:57+08:00
*   **檢驗人**：Codex
*   **檢查項目與實體證據**：

    1.  **人類可讀 UI 修正**：
        *   *實作檔案*：`closed_loop_kernel/views.py`。
        *   *修正內容*：`/events` 與 `/events/:id` 不再直接顯示 `attempt_lifecycle_events`、完整 UUID、`Status:`、`Tool Calls` 等工程欄位；改成「任務開始」「執行中」「任務完成」「等待審核」「執行失敗」「錯誤原因」等操作語言。 (結果：**PASS**)

    2.  **approve/reject action**：
        *   *實作檔案*：`closed_loop_kernel/http_app.py`、`closed_loop_kernel/engine.py`。
        *   *測試檔案*：`tests/test_http_app.py`。
        *   *覆蓋範圍*：POST `/approvals/:candidate_id/approve` 會寫入 approval、套用 candidate、將 failure 標為 resolved、在 events 補 `candidate_applied`；POST `/reject` 會寫入 rejected approval、candidate 變 rejected、failure 回到 open。 (結果：**PASS**)

    3.  **實際 HTTP 驗證**：
        *   *approve 結果*：POST approve 回 303；`/approvals` 顯示「目前沒有待審核修正案」；`/events` 顯示「已批准」與「已套用」。 (結果：**PASS**)

    4.  **完整測試**：
        *   *執行命令*：`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests`。
        *   *結果*：23 tests passed。 (結果：**PASS**)

*   **第十輪結論**：**PASS**。本地 prototype 已從 read-only 進入 interactive approval prototype；下一步是本地 SQLite 檔案持久化、PostgreSQL integration 與 sandbox hardening。

---

## 11. 第十一輪驗證檢驗 (Round 11 Verification - Python Sandbox Hardening)

*   **驗證時間**：2026-05-24T12:00:00+08:00
*   **檢驗人**：Claude (Opus 4.7) under Gary 自主開發授權
*   **檢查項目與實體證據**：

    本輪聚焦 Phase 3 之 Python subprocess sandbox hardening，補上資源限制、環境隔離與 timeout 後備防線。

    1.  **POSIX `resource` rlimit 套用**：
        *   *實作檔案*：`closed_loop_kernel/sandbox.py` 之 `_build_preexec` 工廠函式，以 `subprocess.Popen` 的 `preexec_fn` 在 child fork 後、exec 前套用。
        *   *涵蓋 rlimit*：`RLIMIT_CPU`（軟硬限制差 1 秒給 cleanup）、`RLIMIT_AS` + `RLIMIT_DATA`（記憶體上限）、`RLIMIT_FSIZE`（單檔寫入大小，預設 1 KB）、`RLIMIT_NPROC`（fork/spawn 子程序數，macOS 不支援則略過）、`RLIMIT_CORE = 0`（禁 core dump）。
        *   *Process group 隔離*：child 進入新 process group（`os.setsid()`），方便外層在 timeout 時整組終止。 (結果：**PASS**)

    2.  **Python isolated mode 與環境變數最小化**：
        *   *實作*：subprocess 啟動帶 `-I`（忽略 `PYTHON*` env vars、停用 user site）；env 改成顯式白名單（`PATH=/usr/bin:/bin`、`PYTHONDONTWRITEBYTECODE=1`、`PYTHONIOENCODING=utf-8`、`LC_ALL/LANG=C.UTF-8`、macOS 額外給 `HOME=/tmp`），不繼承呼叫者整個 `os.environ`。 (結果：**PASS**)

    3.  **Wall-clock timeout 後備**：
        *   *實作*：外層 `subprocess.run` 帶 `timeout = self.timeout_seconds + 2`；攔到 `TimeoutExpired` 後回傳 `SandboxResult(status="failed", error_message=...)`，不再讓例外往上炸到 engine。
        *   *動機*：rlimit CPU 應該先觸發，但若 child 卡在 syscall（如 I/O wait）CPU 計時不會累積；wall-clock 是第二道防線。 (結果：**PASS**)

    4.  **非零 returncode 解讀**：
        *   *實作*：`_interpret_nonzero_exit` 區分 SIGKILL（典型 OOM）、SIGXCPU（CPU rlimit）、其他 signal、`MemoryError` 等情況，回傳人類可讀的 error_message，便於 candidate 鏈接到 replay 失敗原因。 (結果：**PASS**)

    5.  **stdout 上限**：
        *   *實作*：parse JSON 前先檢查 `proc.stdout` 大小（預設 1 MB），超過直接回傳失敗，避免 candidate 透過 print 灌爆 capture buffer。 (結果：**PASS**)

    6.  **測試覆蓋**：
        *   *新增測試*：`tests/test_python_sandbox.py` 新增 `test_subprocess_sandbox_kills_infinite_loop_via_cpu_rlimit`（CPU 超時觸發）、`test_subprocess_sandbox_does_not_inherit_parent_environment`（即使透過 `eval("__import__('os').environ.get(...)")` 繞過 AST lint 仍讀不到父行程環境變數）、`test_subprocess_sandbox_blocks_memory_blowup_via_rlimit_as`（Linux-only，記憶體上限）。
        *   *既有測試擴充*：success 路徑增加對 `sandbox_env["isolated_mode"]` / `rlimit_cpu_seconds` / `rlimit_memory_mb` 欄位的斷言。
        *   *執行命令*：`KERNEL_DATABASE_URL='postgresql:///clk_test' KERNEL_ALLOW_DESTRUCTIVE_RESET=1 python3 -m unittest discover -s tests`。
        *   *結果*：44 tests run, 43 passed, 1 skipped（Linux-only 記憶體測試於 macOS 跳過）。 (結果：**PASS**)

*   **第十一輪結論**：**PASS**。Python sandbox 在現有 AST lint 之上加了 POSIX-level 資源/環境/時間防線，並補了測試證據。下一步聚焦 SQL sandbox runner（`sandbox_runner` role + 動態 schema）。OS-level sandbox（macOS `sandbox-exec` / Linux seccomp）暫不納入本階段。

---

## 12. 第十二輪驗證檢驗 (Round 12 Verification - SQL Sandbox Runner & Lint Hardening)

*   **驗證時間**：2026-05-24T13:00:00+08:00
*   **檢驗人**：Claude (Opus 4.7) under Gary 自主開發授權
*   **檢查項目與實體證據**：

    本輪聚焦 Phase 3 之 SQL 沙盒，補上 `event-flow-v0.md §3.1` 所要求的低權限角色 + 動態 schema 隔離，並擴充 SQL static lint 黑名單。

    1.  **SQL static lint 黑名單擴充**：
        *   *實作檔案*：`closed_loop_kernel/engine.py` 之 `_SQL_LINT_FORBIDDEN_PATTERNS` 與 `validate_sql_patch`。
        *   *覆蓋類別*：
            - 角色 / 授權切換：`SET/RESET ROLE`、`SET/RESET SESSION AUTHORIZATION`、`SECURITY DEFINER`；
            - 權限管理：`CREATE/ALTER/DROP ROLE|USER|GROUP`、`GRANT`、`REVOKE`；
            - Broad destruction：`DROP SCHEMA|DATABASE`、`TRUNCATE`、`ALTER SYSTEM`、原有的 `DROP TABLE`；
            - 宿主 I/O：statement-leading `COPY`、`pg_read_file`、`pg_read_binary_file`、`pg_ls_dir`、`lo_import`、`lo_export`；
            - 跨 schema：原有的 `public.` 前綴。
        *   *錯誤訊息*：每條規則回傳具體原因（如 `RESET ROLE could escape sandbox role`），便於 candidate 作者修正。 (結果：**PASS**)

    2.  **SqlSandbox primitive**：
        *   *實作檔案*：`closed_loop_kernel/sql_sandbox.py`，新增 `SqlSandbox` 類別與 `SqlSandboxResult` dataclass。
        *   *核心 API*：
            - `ensure_role()`：idempotent 建立 `sandbox_runner` 角色（NOLOGIN/NOINHERIT），REVOKE public schema 全部權限，GRANT 角色給當前 admin 以供 `SET ROLE`。
            - `temp_schema()`：context manager，產生 `sandbox_temp_<12-hex uuid>` schema，授予 runner `USAGE, CREATE`；離開時 finally 區塊 CASCADE 清理。
            - `run_as_runner(sql, schema)`：交易內依序 `SET LOCAL search_path = schema, public` → `SET LOCAL ROLE sandbox_runner` → execute，回傳 `SqlSandboxResult(status, schema, rows, error_message)`。 (結果：**PASS**)
        *   *Spec 偏離備案*：規格 (`event-flow-v0.md §3.1`) 寫的是「獨立資料庫連線帳號」。Prototype 走 `SET LOCAL ROLE`，privilege boundary 依然由 `sandbox_runner` 的 GRANT/REVOKE 強制，事務結束自動恢復；省去本機 trust auth 配置。產線需升級為獨立 `psycopg.connect(user=sandbox_runner, ...)` 物理連線。 (結果：**已於 `sql_sandbox.py` 與 `PROTOTYPE.md` 文件中明示**)

    3.  **安全邊界測試**：
        *   *測試檔案*：`tests/test_sql_sandbox.py`。
        *   *核心斷言*：
            - `test_run_as_runner_cannot_write_to_public_schema`：候選嘗試 `CREATE TABLE public.evil_table` 必須回 `permission denied`；
            - `test_run_as_runner_cannot_select_from_kernel_state_tables`：候選嘗試 `SELECT 1 FROM public.attempts` 必須回 `permission denied`。 (結果：**PASS**)

    4.  **並發測試**：
        *   *測試檔案*：`tests/test_sql_sandbox.py::test_concurrent_temp_schemas_get_distinct_names_and_clean_up`。
        *   *方法*：6 個 thread 同時各開一個 `temp_schema`，在自己的 schema 內 `CREATE TABLE local_t` + `INSERT` + `SELECT`，最後驗證所有 schema 名稱互不碰撞且沒有任何 schema 留在 DB。 (結果：**PASS**)

    5.  **生命週期清理測試**：
        *   `test_temp_schema_is_cleaned_up_even_if_caller_raises`：故意在 `with sandbox.temp_schema()` 內 raise，驗證 finally 仍會 DROP 該 schema。 (結果：**PASS**)

    6.  **完整測試**：
        *   *執行命令*：`KERNEL_DATABASE_URL='postgresql:///clk_test' KERNEL_ALLOW_DESTRUCTIVE_RESET=1 python3 -m unittest discover -s tests`。
        *   *結果*：54 tests run, 53 passed, 1 skipped（Linux-only 記憶體 rlimit 測試於 macOS 跳過）。 (結果：**PASS**)

*   **第十二輪結論**：**PASS**。Phase 3 沙盒（Python + SQL 雙路）已具備可重跑、可並發、可驗證權限邊界的 prototype；SQL static lint 涵蓋 spec 已知的 escape 路徑。下一步把 `SqlSandbox` 串入 `KernelEngine.replay_sql_candidate`，並把 `scenarios/sql-self-healing-v0.md` 轉成可重跑的 scenario script。物理獨立連線版本的 sandbox_runner 與 OS-level sandbox 留待產線階段。

---

## 13. 第十三輪驗證檢驗 (Round 13 Verification - SQL Replay Engine Wiring & Scenario 1 Demo)

*   **驗證時間**：2026-05-24T14:00:00+08:00
*   **檢驗人**：Claude (Opus 4.7) under Gary 自主開發授權
*   **檢查項目與實體證據**：

    本輪把 SqlSandbox 串入 KernelEngine，並把 `scenarios/sql-self-healing-v0.md` 轉成可重跑端到端 demo，使 Phase 5 兩個 scenario 都能在本地跑出實際輸出。

    1.  **`KernelEngine.replay_sql_candidate` 落地**：
        *   *實作檔案*：`closed_loop_kernel/engine.py` 之 `replay_sql_candidate` 與 `_check_sql_assertions`。
        *   *流程*：load candidate → 確認 patch_type == `sql_patch` → `validate_sql_patch(proposed_content)` → `sandbox.temp_schema()` → 可選 `run_as_runner(setup_sql, schema)` → `run_as_runner(proposed_content, schema)` → 比對 `expected_row_count` / `expected_result` → `record_replay` 寫 `replays.sandbox_schema`。
        *   *結果分支*：lint 違規 → SecurityError 不寫 replay；setup 失敗 → `replays(failed, phase=setup)`；replay 失敗 → `replays(failed)` 帶 DB 錯誤訊息；assertion 違規 → `replays(failed)` 帶具體期望值；全綠 → `replays(success)` 並 `candidate → sandbox_verified`。 (結果：**PASS**)
        *   *Trust 邊界*：`setup_sql` 不過 lint（caller-trusted 內部輸入，可能合法引用 `public.*` 以複製生產表）；`proposed_content` 必須過 lint。

    2.  **Scenario 1 可重跑 demo**：
        *   *實作檔案*：`closed_loop_kernel/sql_demo.py`。
        *   *劇本*：active artifact 用錯的 SQL（`public.document_tags`）→ 寫 failed attempt + open failure → 提 `sql_patch` candidate（修正為 `document_tags_mapping`）→ SqlSandbox replay（setup 在 temp schema 內建兩表 + 種一筆 Important seed，replay 跑修正 SQL，assertion `expected_row_count=1` + `expected_result=[["Q2 Strategy"]]`）→ approve → apply → retry attempt success。
        *   *最終狀態*：`attempts` 兩列（failed 不可篡改 + retry success），`candidate=applied`，`failure=resolved`，`replay=success`，`replays.sandbox_schema` 仍是 `sandbox_temp_*` 形式，`active artifact` 已換成修正版 SQL。 (結果：**PASS**)
        *   *執行命令*：`KERNEL_DATABASE_URL=postgresql:///clk_test KERNEL_ALLOW_DESTRUCTIVE_RESET=1 python3 -m closed_loop_kernel.sql_demo`。

    3.  **測試覆蓋**：
        *   `tests/test_sql_sandbox.py::ReplaySqlCandidateTests`（5 個）：success / assertion violation / replay error / lint rejection / wrong patch_type。
        *   `tests/test_sql_demo.py::SqlDemoTests`：完整 demo 端到端，校驗最終狀態。
        *   *完整測試*：`python3 -m unittest discover -s tests` → 60 tests run, 59 passed, 1 skipped（Linux-only 記憶體 rlimit）。 (結果：**PASS**)

*   **第十三輪結論**：**PASS**。Phase 3 與 Phase 5 完整收斂；兩個 scenario 皆可重跑並有測試守門。Phase 4 剩餘工作：(a) demo/http_app seed-once 拆分避免每次 reset；(b) HTTP UI 加 `sql_patch` 顯示路徑；(c) 產線階段把 SqlSandbox 升級成獨立物理連線（需 Gary 在配 trust auth / password 時參與）。

---

## 14. 第十四輪驗證檢驗 (Round 14 Verification - http_app Subcommand Split & Store TX Leak Fix)

*   **驗證時間**：2026-05-24T15:00:00+08:00
*   **檢驗人**：Claude (Opus 4.7) under Gary 自主開發授權
*   **檢查項目與實體證據**：

    本輪處理 Phase 4 (a)：把 `http_app` 拆成「不 reset」與「reset + seed」兩條路徑，讓 Gary 多次重啟瀏覽器不會把歷史砍掉。過程順手發現並修正 `KernelStore` 一個 pre-existing 連線洩漏 bug。

    1.  **`http_app` subcommand 拆分**：
        *   *實作檔案*：`closed_loop_kernel/http_app.py`。
        *   *新 API*：
            - `seed_demo_store()`（從 `build_demo_store` 改名）：reset + 種 Scenario 2 種子，需 `KERNEL_ALLOW_DESTRUCTIVE_RESET=1`。
            - `open_store()`：只連線、不 reset；`initialize()` 走 idempotent `CREATE TABLE IF NOT EXISTS`。
            - `serve(host, port, *, with_seed=False)`：預設 `with_seed=False`，呼叫 `open_store`；`with_seed=True` 才走 `seed_demo_store`。
        *   *CLI subcommand*：argparse 加 `mode` 位置參數，可選 `serve`（預設）/ `seed`（只重置不開 server）/ `seed-and-serve`（reset 後開 server，舊行為）。`--host` / `--port` 支援自訂。
        *   *手動驗證*：`python3 -m closed_loop_kernel.http_app --help` 顯示新說明；`http_app seed` 印出 "Seeded ..."；`http_app`（無 arg）開 server 後 `curl /events` 回 200 + "(DB state preserved)" 提示。 (結果：**PASS**)

    2.  **`KernelStore` 讀方法不再洩漏 idle 交易**：
        *   *問題*：`scalar` / `fetch_one` / `fetch_all` 在 psycopg `autocommit=False` 下會隱式啟動一筆 SELECT TX，但讀完從不 commit。每呼叫一次連線就停在 `idle in transaction`；多用幾條連線同時打 DB 後，後續任何要 exclusive lock 的 DDL（例如 `DROP SCHEMA public CASCADE`）就會永久卡住。
        *   *發現經緯*：新加的 `test_open_store_is_non_destructive` 同時用兩條連線 → 下一輪 `seed_demo_store` reset 被 lock 卡死；用 `pg_stat_activity` 看到 6 條 idle TX 連線。
        *   *修法*：`scalar` / `fetch_one` / `fetch_all` 三個讀方法的 `with self._lock` block 結尾加 `self.conn.commit()`，把隱式 TX 關掉。`transaction()` 路徑不受影響（它走 `_PostgresTransaction.execute`，由 context manager 在 scope 結束時統一 commit / rollback）。 (結果：**PASS**)

    3.  **測試覆蓋**：
        *   `tests/test_http_app.py` 新增 `test_serve_without_seed_preserves_existing_state` 與 `test_open_store_is_non_destructive`，連同既有 7 個路由 / approval / favicon / real-server 測試一起跑：9 tests passed。
        *   *完整測試*：`python3 -m unittest discover -s tests` → 62 tests run, 61 passed, 1 skipped（Linux-only 記憶體 rlimit）。 (結果：**PASS**)

*   **第十四輪結論**：**PASS**。Phase 4 (a) 已收斂；Gary 可以重複 `python3 -m closed_loop_kernel.http_app` 而不丟歷史，要重置時改用 `seed` 或 `seed-and-serve` 子命令。剩餘 Phase 4 (b)（UI 加 `sql_patch` 顯示路徑）與 (c)（SqlSandbox 物理連線升級）保留作為下一輪。
