# Company Data Contract v0

本文件定義 Gary / 好事發生數位 AI 原生公司框架的第一層資料契約。

這份契約的目的不是先設計很多 agent，而是先規定：任何 agent 只要替公司工作，就必須留下可讀、可審核、可驗證、可清洗、可接手的資料。

## 1. 設計前提

兩份最早逐字稿給出的共同方向是：

- 公司知識必須變成 agent 可讀的 context / skills / artifacts，而不是只留在人腦、Email、Slack、Notion 或零散檔案裡。
- 不能把所有 raw data 直接塞進 context window。資料必須被整理、聚合、萃取，然後以 breadcrumb 方式供 agent 使用。
- Agent experience 必須是一等公民，包含 CLI、API、docs、export、permissions、context format。
- Review、verification、sandbox、權限、任務管理、品質控管是 agent 化公司真正的瓶頸。
- 要習慣快速建立、快速驗證、快速刪除不再有用的東西。資料可以長大，但可被 agent 使用的記憶必須保持乾淨。

因此，v0 不先追求完整公司大腦，而是先建立所有 agent 都必須遵守的資料格式。

## 2. 核心原則

### 2.1 Raw Data 不等於 Memory

```text
Raw data
  只是原始證據，例如 GSC export、GA4 report、YouTube transcript、社群貼文、Email、agent logs。

Memory
  是經過整理、去重、分類、審核後，可以被未來任務安全引用的知識。

Context
  是某次任務臨時組出來的一包資料，用完即丟，不應永久膨脹。
```

### 2.2 每個 Agent 都產出兩種東西

```text
Human Artifact
  給人看的產物，例如報告、文章 brief、審核意見、社群貼文草稿。

Machine Record
  給系統看的紀錄，例如 JSON / DB row / metadata / evidence links / confidence / next action。
```

Agent 不可以只留下自然語言結論。自然語言可以存在，但必須被 machine record 包住。

### 2.3 先證據，再判斷，再記憶

```text
source evidence
  -> agent interpretation
  -> verification / review
  -> human approval if needed
  -> promoted memory
```

抓到資料不等於學到知識。Agent 分析過也不等於可以進 Company Brain。

## 3. 系統層級

這份資料契約是五層架構的第一層。

```text
1. Company Data Contract
   規定所有 agent 產物、證據、任務、failure、驗證報告、記憶候選的格式。

2. Agent Profile Registry
   登記每個 profile 是誰、能做什麼、不能做什麼、需要哪些工具、產出哪些格式。

3. Workflow / Orchestration Contract
   定義多個 agent 怎麼接力、誰審核誰、失敗怎麼轉交、什麼時候需要 Gary 批准。

4. Memory & Cleanup Kernel
   定義資料怎麼進來、怎麼壓縮、怎麼淘汰、什麼可以變成公司記憶。

5. Agent Maintenance Kernel
   定義 agent 自己怎麼被更新、測試、sandbox replay、審核、回滾。
```

本文件會預留後四層需要的欄位，但不在 v0 實作完整 orchestrator。

## 4. Canonical Records

v0 先定義 8 種核心 record：

```text
Task Record
Agent Output Envelope
Source Reference
Artifact Record
Failure Record
Verification Report
Memory Candidate
Profile Update Candidate
```

所有 record 都應該可被寫入 PostgreSQL，也可以被匯出成 JSONL / Markdown 做 debug 或 handoff。PostgreSQL 是 source of truth，JSONL 只能是 export/debug。

## 5. Task Record

Task Record 表示一件可被 agent 接手的工作。

```json
{
  "task_id": "task_...",
  "created_at": "2026-05-22T00:00:00+08:00",
  "created_by": "gary",
  "department": "growth-intelligence",
  "task_type": "gsc_opportunity_analysis",
  "title": "Find one page worth updating from GSC data",
  "description": "Use recent GSC data to identify one content update opportunity.",
  "input_refs": [],
  "assigned_profile": "gsc-analyst",
  "required_output_types": ["gsc_opportunity_report"],
  "risk_level": "medium",
  "requires_review": true,
  "requires_sandbox": false,
  "requires_human_approval": true,
  "retention_policy": "task_summary_long_term",
  "status": "queued"
}
```

### Required Fields

- `task_id`: 全域唯一 ID。
- `department`: 任務所屬部門。
- `task_type`: 任務類型，必須對應 workflow contract。
- `assigned_profile`: 負責 profile。
- `required_output_types`: 此任務允許或要求的 output type。
- `risk_level`: `low` / `medium` / `high`。
- `requires_review`: 是否需要 reviewer。
- `requires_sandbox`: 是否需要 sandbox 驗證。
- `requires_human_approval`: 是否需要 Gary 或指定 DRI 批准。
- `retention_policy`: 任務紀錄保存策略。

## 6. Agent Output Envelope

所有 agent 的輸出都必須包在同一個 envelope 裡。

```json
{
  "task_id": "task_...",
  "run_id": "run_...",
  "profile_id": "gsc-analyst",
  "agent_role": "query_drop_detector",
  "output_type": "gsc_opportunity_report",
  "created_at": "2026-05-22T00:00:00+08:00",
  "human_artifact_path": "artifacts/growth/task_.../gsc-opportunity.md",
  "machine_record": {},
  "source_refs": [],
  "assumptions": [],
  "open_questions": [],
  "risks": [],
  "confidence": "medium",
  "recommended_next_actions": [],
  "memory_candidates": [],
  "verification_required": true,
  "review_required": true,
  "retention_policy": "artifact_long_term"
}
```

### Required Fields

- `task_id`
- `run_id`
- `profile_id`
- `output_type`
- `human_artifact_path`
- `machine_record`
- `source_refs`
- `confidence`
- `recommended_next_actions`
- `verification_required`
- `review_required`
- `retention_policy`

### Confidence Values

```text
low
medium
high
unknown
```

`unknown` 不是失敗，但必須搭配 `open_questions` 或 `risks`。

## 7. Source Reference

Source Reference 指向 agent 使用的證據來源。

```json
{
  "source_ref_id": "src_...",
  "source_type": "google_search_console",
  "source_name": "GSC property: https://example.com",
  "captured_at": "2026-05-22T00:00:00+08:00",
  "date_range": "2026-04-22..2026-05-22",
  "locator": {
    "property": "https://example.com",
    "dimensions": ["page", "query"],
    "filters": []
  },
  "content_hash": "sha256...",
  "raw_artifact_path": "raw/gsc/2026-05-22/export.json",
  "sensitivity": "internal",
  "retention_policy": "raw_evidence_90d"
}
```

### Source Types

v0 預留以下來源：

```text
google_search_console
google_analytics_4
social_platform
competitor_site
youtube_transcript
email
telegram
line
manual_upload
local_file
agent_worklog
web_research
```

### Sensitivity Values

```text
public
internal
confidential
restricted
```

`restricted` 預設不進一般 context pack，除非 workflow 明確允許。

## 8. Artifact Record

Artifact 是可以被人類或後續 agent 接手的工作產物。

```json
{
  "artifact_id": "artifact_...",
  "task_id": "task_...",
  "run_id": "run_...",
  "artifact_type": "content_brief",
  "path": "artifacts/growth/task_.../brief.md",
  "title": "SEO update brief for /blog/example",
  "created_by_profile": "seo-content-strategist",
  "content_hash": "sha256...",
  "source_refs": [],
  "status": "draft",
  "review_status": "pending",
  "memory_status": "not_candidate",
  "retention_policy": "artifact_long_term"
}
```

### Artifact Status

```text
draft
reviewed
approved
rejected
superseded
archived
```

### Artifact Types

Growth Intelligence v0 預留：

```text
gsc_opportunity_report
ga4_traffic_analysis
social_listening_digest
social_patrol_report
brand_presence_signal
competitor_change_report
youtube_transcript_summary
ai_search_visibility_report
seo_content_strategy
content_brief
content_draft
social_post_draft
social_reply_recommendation
human_reply_handoff
review_report
sandbox_verification_report
memory_promotion_note
profile_update_proposal
outcome_report
```

## 9. Failure Detection Contract

這是 Agent Maintenance Kernel 的前置契約。沒有 Failure Detection Contract，就不能談自我修復。

### 9.1 什麼叫做做不好

Failure 分成 7 類：

```text
hard_failure
  任務失敗、工具錯誤、API error、timeout、例外。

contract_violation
  沒照 Agent Output Envelope 交付，缺 source_refs、缺 artifact、缺 confidence。

verification_failure
  sandbox / test / schema / link check / SEO check 沒過。

human_rejection
  Gary 或 reviewer 明確退回，原因可能是內容不對、不可用、風險太高。

quality_regression
  新版 agent 比舊版表現差，例如錯更多、漏資料、格式變亂。

stale_or_dirty_memory
  agent 引用了過期資料、重複資料、已廢棄 SOP、錯誤記憶。

outcome_failure
  任務表面完成，但後續數據證明沒有效果或造成負面結果。
```

### 9.2 什麼時候檢查

```text
pre_run
  任務開始前檢查工具權限、context pack 大小、資料是否過期。

during_run
  執行中檢查 timeout、API error、工具連續失敗、token 爆量。

post_run
  任務結束後檢查 output schema、source refs、artifact、風險欄位是否齊全。

review_time
  reviewer / Gary 審核時檢查內容品質、判斷是否合理、是否能用。

outcome_time
  任務完成一段時間後檢查 GSC / GA4 / 社群數據是否改善或變差。
```

### 9.3 誰發現

```text
self_reported_by_agent
contract_validator
sandbox_verifier
reviewer
human_approver
outcome_monitor
memory_cleaner
system_reconciler
```

### 9.4 Failure Record

```json
{
  "failure_id": "failure_...",
  "task_id": "task_...",
  "run_id": "run_...",
  "profile_id": "gsc-analyst",
  "detected_by": "contract_validator",
  "detected_at": "2026-05-22T00:00:00+08:00",
  "detection_timing": "post_run",
  "failure_type": "contract_violation",
  "severity": "medium",
  "evidence_refs": [],
  "expected": "Agent output must include source_refs and human_artifact_path.",
  "actual": "source_refs is empty.",
  "recommended_resolution_type": "artifact_revision",
  "requires_profile_update": false,
  "requires_sandbox": false,
  "requires_human_approval": false,
  "status": "open"
}
```

### 9.5 Severity Values

```text
low
medium
high
critical
```

`critical` 必須阻斷後續 workflow，並要求 human approval。

### 9.6 Resolution Types

不是每個 failure 都能或都應該修改 profile。

```text
task_retry
  單次工具錯誤，重跑即可。

data_fix
  資料來源錯、API 權限錯、GSC/GA4 設定錯。

artifact_revision
  內容或報告需要修改，但 agent 本身不用改。

workflow_fix
  派工順序錯、少了 reviewer、少了 sandbox。

profile_update
  agent 的 instruction / memory / skill / tool policy 需要修改。

system_bug
  內核或工具程式錯。
```

只有 `workflow_fix`、`profile_update`、`system_bug` 會進入較完整的 sandbox / approval / apply 流程。

## 10. Verification Report

Verification Report 是 sandbox 或檢查器的輸出。

```json
{
  "verification_id": "verify_...",
  "task_id": "task_...",
  "run_id": "run_...",
  "candidate_id": "candidate_...",
  "verified_by": "sandbox-verifier",
  "verification_type": "schema_contract_check",
  "environment": "sandbox",
  "checks": [
    {
      "check_name": "agent_output_envelope_required_fields",
      "status": "passed",
      "details": "All required fields are present."
    }
  ],
  "status": "passed",
  "failure_refs": [],
  "created_at": "2026-05-22T00:00:00+08:00"
}
```

### Verification Types

```text
schema_contract_check
source_ref_check
link_check
seo_metadata_check
ga4_query_check
gsc_query_check
content_quality_check
profile_regression_check
memory_contamination_check
security_policy_check
```

## 11. Memory Candidate

Memory Candidate 是「可能值得進公司大腦」的資料，但不是記憶本身。

```json
{
  "memory_candidate_id": "memcand_...",
  "task_id": "task_...",
  "run_id": "run_...",
  "proposed_by_profile": "memory-curator",
  "memory_type": "sop_update",
  "title": "GSC content refresh decision rule",
  "content": "When impressions rise but CTR drops for 14 days, create a title/meta review task.",
  "source_refs": [],
  "artifact_refs": [],
  "confidence": "medium",
  "scope": "department",
  "target_profiles": ["gsc-analyst", "seo-content-strategist"],
  "sensitivity": "internal",
  "retention_policy": "promoted_memory_long_term",
  "requires_human_approval": true,
  "status": "proposed"
}
```

### Memory Types

```text
sop_update
brand_rule
client_fact
market_insight
tool_usage_rule
known_failure
repair_record
workflow_rule
profile_instruction
```

### Memory Scope

```text
company
department
profile
task
```

`task` scope 不應進 promoted memory。它只能用於當次 context pack 或 task summary。

## 12. Profile Update Candidate

Profile Update Candidate 表示某個 profile 的 instructions、memory、skill 或 tool policy 需要修改。

```json
{
  "candidate_id": "candidate_...",
  "profile_id": "gsc-analyst",
  "proposed_by": "profile-maintainer",
  "trigger_failure_refs": ["failure_..."],
  "update_type": "instruction_update",
  "target_artifact": "profiles/gsc-analyst/SOUL.md",
  "base_artifact_hash": "sha256...",
  "proposed_content_hash": "sha256...",
  "diff_path": "artifacts/profile-updates/candidate_.../diff.patch",
  "reason": "Agent repeatedly omitted source_refs in GSC analysis tasks.",
  "minimum_repro_cases": ["task_001", "task_017", "task_021"],
  "validation_assertions": [
    {
      "type": "contract_check",
      "expected": "source_refs must be non-empty for gsc_opportunity_report"
    }
  ],
  "risk_level": "medium",
  "requires_sandbox": true,
  "requires_human_approval": true,
  "status": "draft"
}
```

### Update Types

```text
instruction_update
memory_cleanup
skill_update
tool_policy_update
workflow_rule_update
retention_policy_update
```

### Candidate Lifecycle

```text
draft
  Candidate proposed but not verified.

sandbox_verified
  Sandbox / regression tests passed.

approved
  Human DRI approved.

rejected
  Human DRI or reviewer rejected.

applied
  New profile artifact has been applied.

rolled_back
  Applied update was reverted by rollback policy.
```

## 13. Retention Policies

Retention policy 決定資料是否會持續被 agent 使用。

```text
raw_evidence_7d
raw_evidence_30d
raw_evidence_90d
raw_evidence_long_term

task_worklog_30d
task_summary_long_term
artifact_long_term

promoted_memory_long_term
known_failure_long_term
repair_record_long_term

delete_after_review
manual_review_required
```

v0 原則：

- Raw worklog 預設短期保留。
- Task summary 長期保留。
- Failure / repair record 長期保留。
- Promoted memory 長期保留，但必須可被 supersede。
- 未批准的 agent 自言自語不進長期記憶。

## 14. Cleanup Lifecycle

資料狀態分成：

```text
active
  正在被用，會進 context pack。

warm
  可查，但不主動塞給 agent。

cold
  只保留原始證據，不進一般檢索。

archived
  保留 hash / metadata，內容移出 active 系統。

deleted
  明確刪除，留下刪除事件紀錄。
```

Cleanup 不等於抹除歷史。對審計有價值的 metadata、hash、decision trace 應保留；對 context 造成污染的重複內容、過期摘要、失效規則應從 active memory 移除。

## 15. Growth Intelligence v0 Output Types

第一個使用這份契約的部門會是 Growth Intelligence Department。

預留 profile：

```text
growth-coordinator
gsc-analyst
ga4-analyst
social-listener
social-reply-advisor
competitor-monitor
research-analyst
youtube-transcript-agent
seo-content-strategist
content-producer
social-operator
reviewer
sandbox-verifier
memory-curator
profile-maintainer
outcome-monitor
```

每個 profile 可以有自己的 sub-agent role，但對外仍必須輸出標準 envelope。

範例：

```text
gsc-analyst
  output_type: gsc_opportunity_report

ga4-analyst
  output_type: ga4_traffic_analysis

social-listener
  output_type: social_listening_digest / social_patrol_report / brand_presence_signal

social-reply-advisor
  output_type: social_reply_recommendation

competitor-monitor
  output_type: competitor_change_report

youtube-transcript-agent
  output_type: youtube_transcript_summary

seo-content-strategist
  output_type: ai_search_visibility_report / seo_content_strategy / content_brief

content-producer
  output_type: content_draft / social_post_draft

social-operator
  output_type: social_post_draft / human_reply_handoff

reviewer
  output_type: review_report

sandbox-verifier
  output_type: sandbox_verification_report

memory-curator
  output_type: memory_promotion_note

profile-maintainer
  output_type: profile_update_proposal

outcome-monitor
  output_type: outcome_report
```

## 16. Minimal v0 Flow

第一個可驗證流程應該很小：

```text
Gary creates task
  -> Task Record
  -> gsc-analyst produces Agent Output Envelope
  -> contract-validator checks envelope
  -> reviewer produces review_report
  -> sandbox-verifier checks source refs / schema / links
  -> Gary approves or rejects
  -> memory-curator proposes Memory Candidate
  -> approved memory enters Company Brain
```

如果任一階段失敗：

```text
Failure Record
  -> resolution type
  -> retry / data fix / artifact revision / workflow fix / profile update / system bug
```

AI Native SEO 模組的第一個部門應用流程：

```text
Gary or intake channel creates SEO task
  -> growth-coordinator creates Task Record
  -> gsc-analyst produces gsc_opportunity_report
  -> ga4-analyst produces ga4_traffic_analysis
  -> social-listener produces social_patrol_report / brand_presence_signal
  -> competitor-monitor produces competitor_change_report
  -> seo-content-strategist produces ai_search_visibility_report / seo_content_strategy
  -> social-reply-advisor produces social_reply_recommendation
  -> reviewer produces review_report
  -> Gary approves or rejects
  -> social-operator produces human_reply_handoff only after approval
  -> outcome-monitor checks GSC / GA4 / social results
```

白話說：社群海巡與回文建議可以變成 SEO 模組的正式工作產物，但 v0 不允許 agent 自動發布或自動回覆。

只有真的需要修改 profile 時，才進：

```text
Profile Update Candidate
  -> sandbox regression check
  -> reviewer comparison
  -> human approval
  -> apply
  -> old version archived
```

## 17. Non-Goals for v0

v0 不處理：

- 完整多部門公司流程。
- 自動發布文章或社群貼文。
- 無人類審批的高風險修改。
- 直接把全部 raw data 丟進 vector DB。
- 直接沿用 OHYA 舊架構。
- 讓每個 sub-agent 都變成永久 profile。

## 18. 下一步

本契約通過後，下一份文件應該是：

```text
docs/agent-profile-registry-v0.md
```

它會定義每個 profile 的：

- 職責
- 工具權限
- 可讀 memory scope
- 可寫 artifact type
- 可提出的 failure / update candidate
- review / sandbox / human approval 規則
- cleanup policy

再下一步才是：

```text
docs/growth-intelligence-department-v0.md
```

部門設計必須建立在資料契約與 profile registry 之上。
