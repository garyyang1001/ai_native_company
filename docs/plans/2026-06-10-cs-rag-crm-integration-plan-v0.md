# 客服 RAG 接 CRM — 規劃 v0(暫停待辦)

> 2026-06-10 建立。Gary 指示:**先做內部助理(OP Assistant)那條線,客服端先寫成文件擱置**。
> 等內部助理整合完,回來從這份文件接續。對齊框架見 [`AI_NATIVE_COMPANY_北極星.md`](../../AI_NATIVE_COMPANY_北極星.md)。

---

## 一句話目標(草稿,措辭待 Gary 確認)

> 讓 CRM 客服對話跑起來——對話存本機、AI 出草稿、人批准才送、每次人工修改都被記錄並回頭改善 AI。

---

## 兩條線,別搞混(2026-06-10 Gary 更正)

| | 線 A:內部助理(已上線,本次優先) | 線 B:客服 CS(本文件,擱置中) |
|---|---|---|
| 服務誰 | 公司同仁 | 客人 |
| 入口 | 「小弟」LINE OA → Hermes op-assistant gateway | CRM 對話頁(未來才接客服 LINE OA) |
| 性質 | 秒查訂單、內部知識 | AI 草稿 → 客服改 → 客服送 |

小弟 **不是** 客服沙箱——它是內部助理本體。兩條線唯一共用的是同一顆知識腦(本機知識庫 + 本地模型)。

---

## 已拍板的決定

1. **CRM 對話儲存 = DGX 本機 PostgreSQL**(對話功能未上線,直接實作,不用遷移)。
   - 推論:**熱資料同步 Supabase 大概率不需要**——CRM 後端就跑在 DGX 上,直讀本機 PG。Supabase 續留訂單/客戶資料(現況不動)。
2. **CRM repo 搬家**:`garyyang1001/wannavegtourcrm`(私有)已建立;本地 remote 已切(origin=garyyang1001、upstream=inventra)。⚠️ push 尚未完成(待 Gary 親推或確認)。
3. **路由層 = 待辦,先不做**:過渡期訊息進來一律先丟 LLM 產草稿(草稿不會自動送出,安全);之後再補 Code-is-Law 規則分流(省算力 + 分流訂單操作類)。
4. **測試策略**:Phase 0 在 CRM 對話頁灌模擬對話測,不碰任何真實 LINE;要端到端測試時再開**全新**測試 LINE OA(免費)。
5. **模型**:直接接本地模型(Gemma4 → 終局微調版),不做 MCP——用例是「每題必檢索」的確定性流程,不需要讓 LLM 自選工具。
6. **行程來源雙連接器**:WooCommerce + Payload 都要抓(WooCommerce 會被 Payload 慢慢淘汰,但現階段兩邊都要)。

## 鐵則(不可違反)

- AI **絕不**自動回覆客人——只有建議模式,客服按了才送。
- **Code is Law**:控制流是確定性程式;LLM 只產草稿、不主宰流程。
- **不可接真實客戶 LINE OA 開發**——CRM 的 auto-trigger(強制綁定等狀態機)會全部跑出來。
- 獨立 branch 開發,測試驗證過才併回。
- 憑證一律放 `~/.hermes/credentials/`,不進 repo。

---

## 工作流程(目標形態)

```
客人訊息(未來:客服 LINE OA;現在:模擬資料)
   ↓
本機真相庫(PostgreSQL,只增不改)── 對話第一落點在本機
   ↓
〔路由層:待辦。過渡期 = 全部往下走〕
   ↓
知識腦(本機):Qdrant 檢索 + Gemma4 草擬 → 建議回覆 + 引用了哪幾筆知識
   ↓
CRM 對話頁薄面板:顯示建議 → 客服 照送 / 改送 / 不用 + 填理由
   ↓(人按了才發出)
記錄三件套:① AI 原建議+引用 ② 客服最終版 ③ 差異+理由 → 入本機真相庫
   ↓
改善迴圈(全走人批准,接 closed-loop kernel):
   a) 知識錯 → 修知識庫該筆
   b) 答法不好 → 變 few-shot 範例進提示
   c) 量夠了 → 微調 Gemma 的訓練資料
```

## 改善機制(「被調整」→ 真的變聰明)的三條路

| 路 | 觸發 | 動作 | 批准 |
|---|---|---|---|
| 修知識 | 客服改的是「事實」 | 更新知識庫該筆(留舊版軌跡) | 沙盒驗證 → Telegram 人批准 |
| 教範例 | 客服改的是「口氣/格式」 | 收進 few-shot 範例庫,進系統提示 | 同上 |
| 微調 | 累積數百筆修正 | 整理成訓練資料,微調本地模型 | 人工發起 + 驗收 |

---

## 還沒收斂、回來要先討論的

1. **真相庫串接細節**:本機 PG 開新 database 還是跟知識庫(:5436)同庫不同 schema?表結構(conversations / messages / suggestions / feedback)?CRM 後端怎麼連(docker 容器 → host PG)?
2. **規則路由設計**(待辦):哪些意圖走程式直接處理(查訂單/改人數)、哪些進知識腦、哪些直升真人。
3. **客戶提問範圍**:草稿只管知識題,還是操作題(改人數/取消)也出草稿?
4. **薄面板設計**:Gary 說「還要再改」——具體長相待討論(顯示什麼、改稿介面、理由欄位必填與否)。
5. **送出+記錄+改善的細部 spec**:回饋表 schema、與 closed-loop kernel 的 improvement_candidates 怎麼接、批准 UI 用 Telegram 還是 CRM 內。
6. **行程連接器怎麼抓**:WooCommerce API 被 Cloudflare 擋(403)、Payload `/api/products` 之前 404 — 兩個都要先打通。
7. **Gemma4 12B**:Ollama 需先升級(sudo,Gary 自跑 `curl -fsSL https://ollama.com/install.sh | sh`)才能 pull。

## 分期(維持原案)

- **Phase 0**:本機對話庫 + 知識腦最小版,CRM 內模擬對話測,不碰 CRM 主線、不碰 LINE。
- **Phase 1**:增量知識管線 + 兩個行程連接器。
- **Phase 2**:CRM 薄面板 + 回饋表(獨立 branch,測完才併)。
- **Phase 3**:回饋接 closed-loop kernel,開始「人改 → AI 變好」循環。

## 相關資產

- 知識庫:本機 PostgreSQL :5436(canonical 三層)+ Qdrant(49,781 筆,bge-m3),pipeline 在 `Gary/wannavegtour-knowledge/`(branch `feat/knowledge-pipeline`)。
- CRM:`/home/wannavegtour/clients/wannavegtourcrm`(DGX docker-compose,deploy.sh 重建)。
- 死掉的 clawdbot(:18789)= 要被本機知識腦取代的位置。
