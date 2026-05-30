# AI Native SEO Module v0

本文件定義好事發生數位有限公司第一個部門應用層模組：`AI Native SEO`。

白話說：這不是傳統 SEO 代辦，也不是單一寫文章 agent。這是一組建立在 Company Data Contract、Agent Profile Registry、Closed Loop Kernel 與 Hermes runtime 之上的 SEO 工作流，目標是讓公司在 AI agent 會讀取、比較、引用與推薦的地方變得更可信。

## 1. 不可變基礎原則

本模組不得覆蓋或繞過以下底層原則：

1. **AI-native company** 是公司作業系統方向。
   - 白話：公司重要工作不能只留在人腦、聊天室或一次性檔案裡，必須能被 agent 查詢、接手、審核與清理。
2. **Code is Law** 是不可變原則。
   - 白話：retry、timeout、權限、審核、發布、寫入資料庫等流程控制，必須由程式規則決定，不能交給 prompt 自己想。
3. **所有 Agent 動作都要能被觀測、被記錄。**
   - 白話：Agent 做了什麼、看了哪些來源、產出什麼、是否失敗、誰審核，都要留下結構化紀錄。
4. **PostgreSQL / kernel database 是 source of truth。**
   - 白話：JSONL、Markdown、聊天紀錄可以當匯出或報告，但不能當公司正式狀態來源。
5. **回應與傳遞必須走審核閘門。**
   - 白話：Agent 可以建議怎麼回，但不能自己代表公司亂發文或亂回覆。

## 2. 服務定義

`AI Native SEO` 的服務範圍只包含以下工作：

```text
website visibility
  看官網、頁面、結構化內容、可爬行性與品牌敘事。

search visibility
  看 GSC、GA4、搜尋曝光、點擊、查詢意圖、內容機會。

social patrol
  看社群、論壇、新聞、公開討論、競品動態與品牌被提及情況。

reply recommendation
  針對值得回應的社群或公開討論，產生回文建議與風險說明。

human-approved handoff
  把通過審核的回覆建議整理成可交給人或外部系統執行的交付包。
```

白話說：AI Native SEO 是「讓 AI 和人都更容易相信你」的基礎設施。它不只檢查官網，也檢查社群足跡與公開討論，因為未來的搜尋與 AI agent 會同時參考多種公開來源。

## 3. 官方趨勢依據

本模組的外部方向參考：

- Google I/O 2026 官方整理：https://blog.google/innovation-and-ai/technology/ai/google-io-2026-all-our-announcements/
- Google Search Central AI features 文件：https://developers.google.com/search/docs/appearance/ai-features

白話解讀：AI 搜尋仍然依賴可爬行、可信、對使用者有幫助的公開內容；同時，AI 搜尋體驗正在把網站、新聞、部落格與社群訊號一起納入理解。公司不能只做官網 SEO，也要管理公開社群足跡。

## 4. 程式與文件位置

- [docs/company-data-contract-v0.md](/Volumes/Hermes%20System/HermesArchive/Gary/docs/company-data-contract-v0.md)
  - 這是什麼：公司資料合約。
  - 白話功能：規定 SEO 模組的每個輸入、輸出、來源、產物、審核與記憶候選要長什麼樣子。

- [docs/agent-profile-registry-v0.md](/Volumes/Hermes%20System/HermesArchive/Gary/docs/agent-profile-registry-v0.md)
  - 這是什麼：Agent 角色合約。
  - 白話功能：規定誰能看 GSC、誰能海巡、誰能產生回文建議、誰能審核。

- [data/agent-profile-registry-v0.json](/Volumes/Hermes%20System/HermesArchive/Gary/data/agent-profile-registry-v0.json)
  - 這是什麼：機器可讀的 Agent 名冊。
  - 白話功能：程式會用它檢查 Agent 交出來的東西有沒有越權。

- [closed_loop_kernel/profile_registry.py](/Volumes/Hermes%20System/HermesArchive/Gary/closed_loop_kernel/profile_registry.py)
  - 這是什麼：Agent 輸出檢查器。
  - 白話功能：擋掉缺欄位、亂產出、偷帶憑證或越權的 Agent output envelope。

- [docs/hermes-agent-first-architecture.md](/Volumes/Hermes%20System/HermesArchive/Gary/docs/hermes-agent-first-architecture.md)
  - 這是什麼：Hermes agent-first 架構文件。
  - 白話功能：說明 Hermes 負責 agent runtime / kanban / profiles，Closed Loop Kernel 負責稽核、驗證、審批與記憶。

## 5. 標準工作流

```text
Gary / LINE / Telegram / manual task
  -> growth-coordinator 建立 Task Record
  -> gsc-analyst 產出 gsc_opportunity_report
  -> ga4-analyst 產出 ga4_traffic_analysis
  -> social-listener 產出 social_patrol_report / brand_presence_signal
  -> competitor-monitor 產出 competitor_change_report
  -> seo-content-strategist 產出 ai_search_visibility_report / seo_content_strategy
  -> social-reply-advisor 產出 social_reply_recommendation
  -> reviewer 產出 review_report
  -> Gary / human DRI 批准或拒絕
  -> social-operator 只整理 human_reply_handoff，不直接發布
  -> outcome-monitor 追蹤 GSC / GA4 / 社群結果
  -> memory-curator 推選可長期保留的記憶候選
```

白話說：每一段都要有紀錄。海巡不是看完就算，回文建議不是寫完就能發，最後一定要有人審。

## 6. SEO 模組新增產物

```text
ai_search_visibility_report
  白話：整理公司在 AI 搜尋與傳統搜尋中是否容易被理解、引用與推薦。

brand_presence_signal
  白話：整理社群、論壇、新聞、競品頁面中對品牌或服務的公開訊號。

social_patrol_report
  白話：社群海巡報告，列出在哪裡看到什麼討論、風險、機會與來源。

social_reply_recommendation
  白話：回文建議。包含建議回不回、怎麼回、風險是什麼、需要誰批准。

human_reply_handoff
  白話：通過審核後整理給人或外部系統執行的交付包，不代表已經自動發布。
```

## 7. Agent 角色邊界

### `social-listener`

這是什麼：社群海巡工具。
白話功能：看公開社群、論壇、新聞與品牌提及，產出 `social_patrol_report` 與 `brand_presence_signal`。

限制：

- 只能讀公開或已授權來源。
- 必須留下 `source_refs`。
- 不能直接回覆、私訊、發文。

### `social-reply-advisor`

這是什麼：回文建議工具。
白話功能：根據海巡報告與品牌規則，產出 `social_reply_recommendation`。

限制：

- 只能建議，不得發布。
- 必須標註建議回覆的風險、依據與適用平台。
- 高風險內容必須要求 reviewer 與 Gary 批准。

### `social-operator`

這是什麼：通過審核後的交付包整理工具。
白話功能：把已批准的回文建議整理成 `human_reply_handoff`，給人或外部系統執行。

限制：

- 不擁有自動發布權限。
- 不得跳過 reviewer。
- 不得把未批准的建議包裝成可發布內容。

## 8. Hermes OHYA 清乾淨接法

OHYA 現有 runtime 很大，而且已知資料髒。AI Native SEO 模組不能直接把舊 OHYA 全部搬進 kernel。

乾淨接法：

1. 保留 Hermes 當 agent runtime。
   - 白話：Hermes 負責跑 agent、profiles、Kanban、sessions。
2. 保留 Closed Loop Kernel 當稽核與審批層。
   - 白話：kernel 負責記錄、驗證、審核、批准、記憶候選。
3. 舊 OHYA profile 只當參考，不直接沿用。
   - 白話：髒資料可以被看見，但不能直接變成正式公司記憶。
4. 新 OHYA SEO profile 要依本文件重建。
   - 白話：使用同一套模型設定與 Hermes profile 格式，但 SOUL、工具權限、輸出格式要乾淨重寫。
5. 先接單一乾淨切片，再擴大。
   - 白話：先讓一條 SEO 任務完整跑過記錄、審核、批准，再接更多 agent。

建議乾淨 profile 組：

```text
growth-coordinator
gsc-analyst
ga4-analyst
social-listener
social-reply-advisor
seo-content-strategist
reviewer
social-operator
outcome-monitor
memory-curator
```

## 9. 發布與回應安全閘門

以下行為在 v0 全部禁止自動執行：

- 自動發社群貼文。
- 自動回覆社群留言。
- 自動私訊客戶或陌生人。
- 自動修改客戶網站。
- 自動把海巡資料升級成公司長期記憶。

允許的 v0 行為：

- 產生報告。
- 產生回文建議。
- 產生交付包。
- 交給 reviewer / Gary 批准。
- 追蹤批准後的成效。

## 10. 非目標

v0 不處理：

- 不建立泛用 SEO agency agent。
- 不直接搬 OHYA 舊架構。
- 不讀 credentials。
- 不直接接 production 發布。
- 不把 Typeless 當 source of truth。
- 不讓單一 agent 同時負責執行、審查、批准與發布。

## 11. 通過標準

本模組要算進入可實作狀態，至少要滿足：

1. 新增產物已寫入 Company Data Contract。
2. 新增 role / output 已寫入 Agent Profile Registry。
3. JSON seed 允許正確 Agent 產出正確 output type。
4. 測試確認回文建議可以產出，但不能被未授權 profile 當作發布。
5. Hermes OHYA 清乾淨接法不直接碰 live runtime、不碰 credentials、不整包搬髒資料。
6. 所有 output envelope 都仍必須有 `source_refs`、`artifact_refs`、`machine_record` 與 `content_hash`。
