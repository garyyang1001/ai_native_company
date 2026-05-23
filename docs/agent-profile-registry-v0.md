# Agent Profile Registry v0

本文件定義 Gary / 好事發生數位有限公司 AI 原生公司框架的第二層合約：**Agent Profile 註冊表 (Agent Profile Registry)**。

本註冊表的目的在於規範所有在系統中運行的 AI 代理人（Agent Profiles）的身份、職能邊界、工具權限、資料流合約與生命週期，防止代理人越權、避免記憶污染，並嚴格杜絕自我審查與自我更新的共謀風險（Collusion）。

---

## 1. 目的 (Purpose)

在 Agent-first 架構中，Hermes 引擎作為執行期運行環境（Agent Runtime），為每個 Profile 提供獨立的狀態目錄、`SOUL.md` 指令集與會話資料。然而，執行環境本身並不限制檔案存取，亦不具備跨代理人的安全稽核機制。

本註冊表作為**唯讀安全原則與資料流契約的宣告層**。Closed Loop Kernel 與任務調度器（Kanban Dispatcher）必須在任務派發前、執行中與結束後，依據本註冊表載明的規則對 Agent Profile 進行靜態 Linting 與動態沙盒權限驗證，確保所有工作留下可審核、可回溯、可清洗的軌跡。

---

## 2. AI 原生公司資料原則 (AI-Native Data Principle)

為確保公司資料的可用性與安全性，好事發生數位有限公司確立以下核心資料原則：

> **核心原則：**
> 所有具備業務意義的公司資料輸入與輸出，必須做到「代理人可讀（Readable by Agents）」、「系統可記錄（Recordable by System）」、「人類或驗證代理人可審核（Reviewable by Humans/Verifiers）」、「具備記憶候選資格（Eligible for Memory Candidates）」，以及「後續可安全清洗（Cleanable Later）」。

這項原則是判斷一家公司是否真正 AI-native 的最低條件：資料進來時，系統要知道它從哪裡來、誰使用它、如何驗證它；資料出去時，系統要知道它產生了什麼、引用了哪些來源、是否能被後續任務接手。

這項原則**並不代表**所有原始數據（Raw Data）都應直接塞入大腦或 context window 中。「可被記憶」的意思是具備進入 Memory Candidate 流程的資格，而不是原始資料自動升級為公司記憶。原始數據往往充斥著低價值的雜訊，直接寫入會造成記憶污染、脈絡窗爆量與 AI 幻覺。

公司資料的精煉與升級流向如下：

```text
[原始輸入/輸出資料 (Data In/Out)]
       │ (經過過濾與結構化包裝)
       ▼
[機器可讀封包 (Machine-Readable Record)]
       │ (加上執行 ID、雜湊指紋與關聯證據)
       ▼
[證據/產物/決策軌跡 (Source/Artifact/Decision Trace)]
       │ (進行自動沙盒驗證與 Reviewer 審查)
       ▼
[記憶候選者 (Memory Candidate)] (僅保留具長期價值之 SOP 或事實)
       │ (經人類簽署批准)
       ▼
[批准的記憶 (Approved Memory)] 或 [歸檔的唯讀證據 (Archived Evidence)]
```

---

## 3. 註冊表條目綱要 (Registry Entry Schema)

所有在中央註冊表中登記的 Profile，其定義區塊必須嚴格遵循以下 YAML/JSON 結構，由驗證器在載入時執行 Schema 校驗：

```yaml
profile_id: "string (全域唯一 ID，如 gsc-analyst)"
display_name: "string (繁體中文顯示名稱)"
permanence_level: "string (permanent | dynamic)"
department: "string (所屬部門)"
description: "string (職責描述)"

# =========================================================================
# [未來/v1 設計意圖與延伸合約層]
# (以下三個區塊在 v0 核心驗證器中暫不強制執行，亦不在 v0 JSON 註冊表種子中出現)
# =========================================================================
security_policy:
  privilege_level: "string (low | medium | high)"
  allowed_tools: ["string (允許調用的工具 Schema 名稱)"]
  denied_tools: ["string (明確禁止調用的工具 Schema 名稱)"]
  working_directory_template: "string (限制的檔案存取根目錄，如 workspace/{task_id}/)"
  sandbox_policy: "string (AST 限制級別或資料庫專屬低權限角色)"

governance_rules:
  requires_peer_review: boolean
  peer_reviewer_profiles: ["string (合法的審核者 Profile ID)"]
  requires_sandbox_verification: boolean
  verification_types: ["string (如 schema_contract_check)"]
  requires_human_approval: boolean

update_policy:
  requires_sandbox_regression: boolean
  allowed_update_proposers: ["string (有權提出此 Profile 更新案的 Profile)"]

# =========================================================================
# [v0 資料流原則欄位 (Data Flow Policy - v0 核心校驗強制欄位)]
# =========================================================================
data_flow_policy:
  readable_inputs: ["string (此 Profile 可讀取的 Source Type 或 Record Type)"]
  writable_outputs: ["string (此 Profile 可產出的 Artifact Type 或 Envelope Type)"]
  record_required: true
  machine_record_required: true
  source_refs_required: true
  artifact_refs_required: true
  memory_candidate_allowed: true
  promoted_memory_allowed: false
  cleanup_required: true
  required_fields:
    task_id: "string (關聯的 Task ID)"
    run_id: "string (關聯的 Run ID)"
    profile_id: "string (執行此任務的 Profile ID)"
    source_refs: "array (輸入證據來源定位，必須指向 Source Reference)"
    artifact_refs: "array (輸出產物路徑與定位，必須指向 Artifact Record)"
    content_hash: "string (產物與程式碼之 SHA-256 雜湊值)"
    created_at: "string (任務或產出時間戳記)"
    sensitivity: "string (資料敏感度等級)"
    retention_policy: "string (資料保存與保留策略)"
    machine_record: "object (機器可讀之關鍵決策/證據中繼紀錄)"
  sensitivity_level: "string (public | internal | confidential | restricted)"
  retention_policy: "string (資料保存期限策略)"
  cleanup_lifecycle_state: "string (active | warm | cold | archived | deleted)"
```

`memory_candidate_allowed: true` 只表示該 Profile 的產出可以被送進記憶候選流程；是否成為 Company Memory，仍必須由 `memory-curator` 整理、`reviewer` 審查，並視風險由 Gary 或指定 DRI 批准。

---

## 4. 常駐系統角色 (Permanent Profiles)

常駐系統角色是好事發生數位有限公司「公司核心內核」與「部門應用層」中的長期守門人。這些角色具備持久性的狀態（State Directories）、獨立的會話資料庫（`state.db`），並且其行為歷史會永久寫入 append-only audit logs。

> [!IMPORTANT]
> **憑證與密鑰邊界說明：**
> 本 repo 文件不涉及任何明文憑證、API 密鑰或存取權杖（Credentials are out of scope for this repository document）。常駐系統角色**並不直接擁有** API 密鑰。所有敏感 API（如 GSC、GA4）之存取，必須由執行期運行環境（Runtime Environment）進行密鑰注入，且 Profile 僅能透過經註冊批准的**執行期工具（Approved Runtime Tools）**間接存取。

### 4.1 `growth-coordinator` (成長協調員)
*   **職責**：作為人機協同的總入口。負責接收 Gary 交付的任務、解析任務意圖、建立標準 Task Record、指派合適的工作 Profile、追蹤 Kanban 狀態，並在需要審批時，向外部 HTTP 審批 UI 遞交請求。
*   **工具限制**：僅能使用任務指派、看板讀寫、訊息分發工具。禁止直接存取分析 API，禁止直接編輯代碼。
*   **資料流邊界**：負責建立 Task Record。其產出均為 `Task` 級別與 `Department` 級別的路由追蹤。

### 4.2 `gsc-analyst` (GSC 數據分析師)
*   **職責**：專門讀取 Google Search Console 資料，針對網頁曝光量、點擊率、關鍵字排名進行統計與趨勢分析，產出機會點報告。
*   **工具限制**：僅能透過經過授權的 `gsc_retriever_tool` 讀取資料。無 CMS 發布權限，無程式碼修改權限。
*   **資料流邊界**：產出 `gsc_opportunity_report` 產物，且必須完整標註 GSC 的 `source_refs`（如查詢維度、日期區間與 locator）。

### 4.3 `ga4-analyst` (GA4 流量分析師)
*   **職責**：專門讀取 Google Analytics 4 資料，追蹤網站流量來源、落地頁跳出率、轉化漏斗，評估既有內容成效。
*   **工具限制**：僅能使用 `ga4_retriever_tool`。禁止任何寫入生產端網站或變更 DNS 的工具。
*   **資料流邊界**：產出 `ga4_traffic_analysis` 產物，必須引用 GA4 報表雜湊作為 `source_refs`。

### 4.4 `seo-content-strategist` (SEO 內容規劃師)
*   **職責**：接收分析師報告，設計關鍵字覆蓋策略、規劃文章結構大綱、撰寫 SEO 內容 Brief，維護全站 Brand Voice 與 Brand Rules。
*   **工具限制**：擁有讀取機會報告與歷史 Content Brief 的權限。禁止操作發布與調試代碼工具。
*   **資料流邊界**：產出 `seo_content_strategy` 與 `content_brief`，其 `data_flow_policy.memory_candidate_allowed` 可設為 `true`（SOP 規則類別）。

### 4.5 `reviewer` (內容與合規審核員)
*   **職責**：作為一等公民的防禦角色。對分析報告、代碼補丁、文案草稿進行事實核對（Fact Check）、風險評估與 Brand Voice 對齊。
*   **工具限制**：唯讀存取當次 Task 產生的所有 Envelope 與 Artifact。
*   **資料流邊界**：產出 `review_report`。

### 4.6 `sandbox-verifier` (沙盒驗證器)
*   **職責**：負責自動化安全核對。執行 schema 合規檢查、死連結核對、AST 語法 Linting，並在隔離子進程沙盒中跑模擬測試。
*   **工具限制**：擁有調用 AST parser 與低權限子進程的權限。禁止存取生產端資料庫，無網絡寫入權限。
*   **資料流邊界**：產出 `sandbox_verification_report`。

### 4.7 `memory-curator` (公司記憶管理員)
*   **職責**：定時掃描任務軌跡與 artifacts。將通過審查與驗證的 SOP、規則、統計洞察整理為 `Memory Candidate`，並定期執行過期記憶的清洗與壓縮。
*   **工具限制**：僅能使用 Memory DB 讀寫與 deduplication 分析工具。
*   **資料流邊界**：負責將 `memory_candidate` 寫入審批隊列，其產出影響 `company` 與 `department` 記憶層。

### 4.8 `profile-maintainer` (代理人維護工程師)
*   **職責**：分析 Failure Records。當發現執行失敗的原因需要修改 Profile 的 `SOUL.md` 或 Skill 程式碼時，負責撰寫 `Profile Update Candidate`（即 Diff patch），並交由 `sandbox-verifier` 重播。
*   **工具限制**：唯讀存取失敗軌跡與 Profile 設定檔。禁止直接套用變更至 active profile，必須產出 Patch 檔案。
*   **資料流邊界**：產出 `profile_update_proposal`。

### 4.9 `outcome-monitor` (成效監控員)
*   **職責**：異步追蹤任務落地後的數據反饋。例如在內容更新 14 天與 30 天後，自動拉取 GSC 數據核對點擊數是否顯著改善，若成效衰退則自動拋出 `outcome_failure` 紀錄。
*   **工具限制**：擁有 GSC/GA4 定時唯讀查詢權限。
*   **資料流邊界**：產出 `outcome_report`。

---

## 5. 動態輔助角色 (Dynamic Sub-agents)

動態輔助角色並非公司內核的長期守門人。這些角色代表的是**無狀態、拋棄式、單次執行的特定技能（Stateless Skills）**。它們在執行期由 `growth-coordinator` 或 `seo-content-strategist` 透過 `delegate_task` 工具調用，執行完畢即行釋放。

> **關於註冊表種子 (JSON Registry) 之設計邊界說明：**
> 為了實現嚴格的執行安全，**動態輔助角色仍會被條列並登記於本中央 JSON 註冊表中**。這使得系統能在執行期，針對動態角色的 `readable_inputs` 與 `writable_outputs` 進行靜態 Linting 與合規檢驗，確保其輸入/輸出不越界。
>
> 然而，與常駐系統角色 (Permanent Profiles) 相比，動態輔助角色具備以下嚴格邊界限制：
> 1. **無持久狀態**：不擁有獨立、持久的狀態目錄或狀態資料庫 (`state.db`)。
> 2. **無獨立靈魂**：不具備獨立、受版本控管的 `SOUL.md` 指令與生命週期，其指令完全繼承自主調用者的 Tools 與 Skills 定義。
> 3. **無自我決策與審批權**：不具備獨立的審批權限，且其產出也必須直接包裝在主調用者的 `Agent Output Envelope` 中交付，避免系統狀態失控與註冊表臃腫。
> 4. **無全域記憶權限**：不允許直接推選、申請或變更公司全域記憶 (`promoted_memory_allowed: false`)。

### 5.1 `social-listener` (社群聆聽工具)
*   **定位**：短期 API 抓取工具。抓取特定社群論壇有關關鍵字的討論，輸出必須包成 Source Reference 與 Machine Record，抓取完畢即釋放。

### 5.2 `competitor-monitor` (競品觀測器)
*   **定位**：網頁爬蟲技能。對指定競品網站進行單次 HTML 抓取與變更對比，產出差異報告後釋放。

### 5.3 `research-analyst` (主題研究員)
*   **定位**：單次檢索與綜述技能。針對特定專業領域進行 Google Search 檢索，產出摘要。

### 5.4 `youtube-transcript-agent` (影片逐字稿解析器)
*   **定位**：文件處理器。下載指定 YouTube URL 的字幕或呼叫 Whisper API 轉譯，產出逐字稿 Markdown 檔案。

### 5.5 `content-producer` (內容撰寫器)
*   **定位**：大語言模型寫作技能。依據 Content Brief 產生文章草稿。其生成過程高度依賴 prompt 樣板，不具有自主決策權限。

### 5.6 `social-operator` (社群發文小幫手)
*   **定位**：格式化包裝工具。將文章草稿轉化為適合 Facebook、Threads 或 LINE 的貼文格式。

---

## 6. 角色隔離與防共謀規則 (Role Isolation Rules)

為確保 AI 原生公司的安全性，註冊表強制執行以下**職能分離（Separation of Duties）**矩陣：

1.  **無自我批准 (No Self-Approval)**：
    任何 Profile 產出的產物，若涉及外部發布（風險等級 Medium 以上）或系統核心變更（如修改 Profile 指令），其產出者、審查者與最終批准者**必須為互斥的實體**。
2.  **變更隔離鏈 (Change Isolation Loop)**：
    當 `gsc-analyst` 發生合約失效（contract_violation）時：
    *   `gsc-analyst` (執行者)：僅能申報 Failure，無權修改自己。
    *   `profile-maintainer` (修改提案者)：撰寫變更 patch，但無權執行與驗證。
    *   `sandbox-verifier` (驗證者)：在隔離沙盒中重播，產出 verification report，若通過則標註 `sandbox_verified`，無權批准。
    *   `reviewer` (審查者)：唯讀比對 Diff 變更，產出審查報告。
    *   **Gary (人類 DRI)**：在本地 `/approvals` UI 中進行人工審查，點擊「批准並套用」，寫入 immutable `approvals` 資料表。
    *   **內核引擎 (Kernel Engine)**：偵測到 Human Approved 且 Sandbox Verified 後，自動以原子操作（Atomic Transaction）套用 patch 並封存舊版本。

### 職責矩陣限制表

| 動作 \ Profile | `Executor` | `Maintainer` | `Verifier` | `Reviewer` | `Gary (Human)` |
| :--- | :---: | :---: | :---: | :---: | :---: |
| 執行任務 / 拋出錯誤 | **YES** | No | No | No | No |
| 撰寫更新 Patch | No | **YES** | No | No | No |
| 跑自動化沙盒重播 | No | No | **YES** | No | No |
| 審查變更 Diff | No | No | No | **YES** | No |
| 最終批准 (DB Write) | No | No | No | No | **YES** |

---

## 7. Profile 更新生命週期 (Profile Update Lifecycle)

所有常駐 System Profile 的配置與 `SOUL.md` 指令變更，必須歷經以下狀態機，嚴格禁止任何越級跳躍：

```text
[草稿狀態 (draft)]
       │ (由 profile-maintainer 建立)
       ▼
[沙盒驗證通過 (sandbox_verified)]
       │ (由 sandbox-verifier 自動執行 AST Lint 與 regression replay)
       ▼
[人類批准 (approved)]
       │ (由 Gary 在 HTTP /approvals 點擊確認，寫入不可變 table)
       ▼
[已套用 (applied)]
       │ (內核執行原子升級，將舊版 artifact 搬移至 archived，更新 hash)
       ▼
[回滾中 (rolled_back)] (若新版發生嚴重 Failure，觸發回滾機制)
```

---

## 8. 記憶邊界與資料流向 (Memory Scope & Data Flow)

本註冊表依據資料契約，強制實施四層記憶隔離，避免上下文溢出與數據干擾：

1.  **Company (公司全域記憶)**：
    *   *內容*：公司核心 Brand Rules、核心客戶事實、標準工作 SOP、已修復之 Failure 模式。
    *   *流向限制*：唯讀。僅有 `memory-curator` 在人類簽署批准後，方可將 `Memory Candidate` 升級至此層。
2.  **Department (部門局部記憶)**：
    *   *內容*：特定部門（如 Growth Intelligence）的共用知識、累積的機會點報告目錄。
    *   *流向限制*：限該部門之 permanent profiles 可讀。
3.  **Profile (角色私有記憶)**：
    *   *內容*：該角色專屬的會話歷史、執行偏好、工具回饋。
    *   *流向限制*：僅該 Profile 可讀寫，避免跨角色干擾。
4.  **Task (任務臨時記憶)**：
    *   *內容*：當次任務的 Ephemeral Context Pack（如當次 GSC 導出的 CSV 資料與臨時分析 monologue）。
    *   *流向限制*：任務結束後**即刻銷毀**。精煉後的結論必須寫入 Artifact Envelope，嚴禁將未經整理的 Raw data 留在系統記憶中。

### 8.1 資料進出最低條件

任何 Profile 只要讀取或產生具業務意義的資料，都必須滿足以下條件，否則該任務不得被標記為完成：

- **Readable**：資料不能只存在於人腦、聊天室片段、截圖或不可定位的 terminal output。它必須能被後續 agent 透過 Source Reference、Artifact Record 或 Machine Record 重新讀取。
- **Recordable**：輸入與輸出都必須帶有 `task_id`、`run_id`、`profile_id`、`source_refs`、`artifact_refs`、`content_hash`、`created_at`、`sensitivity` 與 `retention_policy`。
- **Reviewable**：任何會影響外部發布、公司記憶、profile 更新或決策建議的產物，都必須能被 reviewer 或 sandbox-verifier 重新檢查。
- **Memorable**：重要資料可以被提名為 `Memory Candidate`；但 candidate 不是 memory，必須經整理、去重、審查與批准後才可升級。
- **Cleanable**：每一筆資料都必須有 lifecycle state 與 retention policy，能被標記為 `active`、`warm`、`cold`、`archived` 或 `deleted`。

### 8.2 輸出封包機密憑證與金鑰掃描 (Secret/Credential Scanning)

為了杜絕敏感金鑰、API Tokens 或私鑰明文外洩至 Append-Only 系統日誌或 Company Brain 中，v0 核心驗證器在載入與核對任何 Agent 產出的 `Agent Output Envelope` 時，強制執行**機密憑證與金鑰掃描 (Secret/Credential Scanning) 靜態檢驗**。

1. **正則表達式匹配 (Pattern Regex Check)**：
   核心驗證器會針對輸出的所有字串欄位進行敏感特徵過濾，特徵包含但不限於：
   * Google API Keys (`AIzaSy...`)
   * OpenAI API Keys (`sk-proj-...` / `sk-...`)
   * GitHub Access Tokens (`ghp_...` / `github_pat_...`)
   * Slack OAuth Tokens / Webhooks
   * 私鑰標頭 (RSA/OPENSSH/EC/DSA Private Key Headers)
2. **高熵隨機字串校驗 (Shannon Entropy Check)**：
   針對長度 $\geq 32$ 字元且疑似隨機雜湊的字串，驗證器會執行 Shannon 熵估算（安全閥值為 $\geq 4.2$）。若熵值高於閥值，將判定為潛在的隨機私鑰或 Token 洩漏並強制阻斷。
3. **白名單豁免欄位 (Scan Exemptions)**：
   為了避免安全機制誤判，以下特定 metadata / 指紋雜湊欄位被列為白名單，不計入金鑰靜態掃描範圍：
   * `content_hash` (輸出產物的 SHA-256 指紋)
   * 明確列名的時間戳記欄位：`created_at`, `updated_at`, `reviewed_at`, `verified_at`, `approved_at`

---

## 9. 保存策略與清洗生命週期 (Retention & Cleanup)

為維持 context window 的高效運作並符合審計需求，註冊表套用以下保存與清洗時效：

### 9.1 保存時效 (Retention Policies)
*   `raw_evidence_90d`：大型原始日誌、API 導出原始檔，於 90 天後自動刪除，僅保留 Metadata Hash 以供未來校驗。
*   `task_worklog_30d`：代理人執行時的臨時工作紀錄與 terminal traces，保留 30 天以供 debug，逾期清理。
*   `task_summary_long_term`：任務的核心 envelope 資訊與機器可讀記錄，永久保留於 PostgreSQL 以供歷史回溯。
*   `promoted_memory_long_term`：升級至公司記憶庫的 SOP 與品牌規則，除非被新版 `superseded`，否則永久保留。

### 9.2 清洗狀態機 (Cleanup Lifecycle States)
所有資料實體必須被標註以下五種狀態之一，由清理引擎（Cleanup Engine）執行對應操作：
*   **`active`**：處於活躍期，系統自動載入至關聯 Agent 的 context 中。
*   **`warm`**：可供搜尋（Searchable），但不自動注入 context。
*   **`cold`**：不再進索引，僅供人類審計與 forensic 回放。
*   **`archived`**：實體內容移出主資料庫，僅保留雜湊值與中繼資料。
*   **`deleted`**：徹底清除實體檔案，僅在不可變日誌中留下一行刪除事件。

---

## 10. 非目標 (Non-Goals)

本註冊表 v0 合約**不處理**以下範疇：
*   **明文憑證與金鑰管理**：API 密鑰、密碼與存取權杖嚴格排除在 repo 之外。
*   **外部參考平台細節**：不包含任何參考快照中的平台 API 路徑、CMS 假設、部署設定或 runtime 憑證。
*   **高風險自動發布**：v0 階段任何涉及外部發布（如文案上架、網站結構變更）的任務，均不開放自動執行，必須設置 Human Approval Gate。

---

## 11. 開放問題與 v0 預設值 (Open Questions & v0 Defaults)

為確保系統可落地性，v0 階段實施以下預設技術路徑：

1.  **沙盒執行預設**：
    v0 階段之 `sandbox-verifier` 採用**本地 Python 子進程 + 靜態 AST Linting** 作為驗證環境。此預設僅能阻擋常見的語法錯誤與低階危險指令，**不應視為 production 級別的安全硬邊界**。更高級別的 OS 容器隔離（如 Docker）留待未來版本實作。
2.  **審核者角色預設**：
    v0 階段僅註冊單一 permanent profile `reviewer` 負責所有事實核對與品質審查。不針對技術與文案作進一步的 Reviewer 角色細分。
3.  **審核通道預設**：
    v0 階段的所有人機協同審批（Human Approvals）**完全在本地 HTTP UI `/approvals` 介面中進行**。外部訊息平台按鈕或 callback 簽署批准的機制，列為未來版本開發項目。
4.  **未決合約與資料分類學問題 (Unresolved Contract & Taxonomy Questions)**：
    v0 階段在 JSON 註冊表種子與 `docs/company-data-contract-v0.md` 之間存在以下未決的分類邊界問題，目前在 v0 中作為「特例」暫行容忍，留待未來 v1 版本收斂：
    *   **Source Type 與 Writable Output 混淆**：`research-analyst` 的輸出被標記為 `web_research`。然而在資料合約中，`web_research` 屬於 Source Type (原始來源)，並非標準的 Artifact Type (產物)。這在未來應被收斂至如 `web_research_report` 或 `research_summary`。
    *   **非標準產物輸出**：`growth-coordinator` 的輸出包含 `task_record` 與 `route_status_summary`。這兩個類型在 canonical Artifact Types (合約第 8 節) 中並未被條列。
    我們選擇僅對 `company-data-contract-v0.md` 做必要的對齊性修補，不擅自發明新型態；其餘未決分類邊界在此清晰記錄，留待 v1 收斂。
