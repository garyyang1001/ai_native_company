# wannavegtour_knowledge — 維護手冊

客服對話知識庫的維護做法。任何人(或 agent)接手都先讀這份。

---

## 1. 這是什麼 / 為什麼這樣設計

把官方 LINE 客戶對話(匯出 CSV)**清洗 + 全面去識別 + 標記意圖**,變成一個
**獨立、共用、可讀**的 PostgreSQL 知識庫。它是**唯一真相來源(canonical)**,
未來餵 RAG、微調、ElevenLabs、其他 agent 都從它匯出。

設計成**三層(medallion)**,直接對應「可維護 / 可整理 / 可清洗」:

| 層 | 表 | 內容 | PII | 誰能讀 |
|---|---|---|---|---|
| **bronze** 原始 | `source_files` / `raw_turns` | 原封不動匯入,immutable | ⚠️ 含 PII | 僅 owner(本機) |
| **silver** 清洗 | `clean_turns` | 清洗+去識別,帶版本 | ✅ 已去識別 | owner |
| **gold** 知識 | `knowledge_units` | 問答+意圖,canonical | ✅ 已去識別 | **所有 agent(唯讀)** |
| 稽核 | `pipeline_runs` | 每次跑的帳 | — | owner |

**核心原則:PII 只存在 bronze(本機受限);silver/gold 一律去識別,可安全共用/匯出。**

---

## 2. 連線資訊

- DB:`wannavegtour_knowledge` @ `wannaveg-dev-pg`(PostgreSQL 18,`127.0.0.1:5436`)
- 跟正在跑的 op-assistant 營運庫(:5434)**完全分開**,動這裡不影響線上 bot。
- 憑證:`~/.hermes/credentials/wannavegtour/knowledge_db.env`(chmod 600,**不在專案/repo**)。
- 程式 venv:`./.venv`(已裝 psycopg)。

---

## 3. 日常操作(都用 `run.py`)

```bash
cd "~/Desktop/AI Native Company/wannavegtour-knowledge"
./.venv/bin/python run.py stats              # 看現況
./.venv/bin/python run.py ingest             # 匯入所有對話檔 → bronze
./.venv/bin/python run.py clean              # 清洗+去識別 → silver
./.venv/bin/python run.py label              # 配問答+標意圖 → gold(用 gpt-oss,慢)
./.venv/bin/python run.py all                # 三階段依序
# 加 --limit N 只處理 N 個對話檔(測試/分批用)
```

**冪等保證**:每階段重跑只處理「還沒處理的」——
- ingest 用檔案 SHA256 去重(同檔不重收)
- clean 用 `(raw_turn_id, pipeline_version)` 唯一鍵
- label 用 `content_hash` 唯一鍵

所以可以隨時中斷、隨時續跑、重跑也不會產生重複。

---

## 4. 加新資料(新的 LINE 匯出)

1. 把新 zip 放好,設環境變數指它:`export KNOWLEDGE_ZIP=/path/to/new.zip`
2. `run.py all`。舊的不動,只新增新對話(SHA256 去重)。

---

## 5. 重洗 / 改規則(關鍵維護動作)

清洗規則(`clean.py`)、去識別規則(`redact.py`)或意圖分類(`labeler.py`)改了之後,
要讓**舊資料套用新規則**:

1. 把 `config.py` 的 `PIPELINE_VERSION` +1(例 `v1` → `v2`)。
2. `run.py clean` → silver 會用新版重洗(舊版資料保留,可比對)。
3. `run.py label` → gold 重建。
4. 確認新版沒問題後,清掉舊版 silver(可選):
   ```sql
   DELETE FROM clean_turns WHERE pipeline_version = 'v1';
   ```

**bronze 永遠不動**,所以任何時候都能用新規則從原始資料重來,不會遺失原料。

---

## 6. 其他 agent 怎麼讀(共用)

gold 層開了唯讀角色 `wv_knowledge_reader`,只看得到 `knowledge_units`(看不到 bronze PII)。
給某個 agent 一個能登入的帳號:

```sql
CREATE ROLE op_reader LOGIN PASSWORD '...';
GRANT wv_knowledge_reader TO op_reader;
```

之後 op-assistant / marketing-agent / 官網 agent 後端就能用它連 `:5436` 查 gold。
**新增要共用的表時,記得手動 `GRANT SELECT ... TO wv_knowledge_reader`**(刻意不自動授權,防 PII 外洩)。

---

## 7. canonical → 各匯出器(通用化)

gold 是唯一真相,各目標格式都從它匯出(匯出器之後一個個加,放 `exporters/`):

| 目標 | 格式 | 做法 |
|---|---|---|
| 我們自己的 RAG | chunk + bge-m3 向量 + metadata | 讀 gold → 切塊 → 嵌入 → 存向量庫(Qdrant) |
| 微調(SFT) | 對話 JSONL(user/assistant) | 讀 gold 的 question/answer → 輸出 JSONL |
| ElevenLabs KB | 乾淨 Markdown / text | 讀 gold → 依行程/意圖聚合成文件 → POST `/v1/convai/knowledge-base/text` |
| ElevenLabs Tests | 測試題 | 讀 gold 抽樣 → 轉測試格式 |

換掉任何下游工具,gold 一行都不用改,只換匯出器。

---

## 8. 備份

```bash
# gold + silver 邏輯備份(canonical 真相)
docker exec wannaveg-dev-pg pg_dump -U wv -Fc wannavegtour_knowledge \
  > ~/.hermes/profiles/op-assistant/backups/knowledge-$(date +%Y%m%d).dump
```
bronze 含 PII,備份檔請存本機受限位置,勿上雲。

---

## 9. 監控 / 稽核

```sql
SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT 10;   -- 每次跑的帳
SELECT intent, count(*) FROM knowledge_units GROUP BY intent;     -- 意圖分布
SELECT avg(redaction_count) FROM clean_turns;                     -- 去識別密度
```

---

## 10. 已知限制 + 下一步強化

- **去識別(人名)**:結構化 PII(電話/身分證/護照/卡號/email)正則可靠攔截;
  人名靠「客人傳送者名 + 檔名客名」逐字遮蔽,**主帳號客人名覆蓋良好**,但
  **同行旅客的名字若只出現在文字中(非傳送者)可能漏**。
  → **強化路徑**:加一個 `redact.py` 的 LLM/NER pass(用本機模型掃人名),
  當 `PIPELINE_VERSION` v2 的一部分重洗。**正式對外匯出前務必先補這塊。**
- **行程資訊抽取**:`tour_destination/date` 目前用關鍵字 best-effort,可改成 LLM 抽取。
- **問答配對**:目前「客人問→下一則客服答」簡單配對;多輪複雜對話可再強化。
- **full run**:測試用 `--limit`;正式跑拿掉 `--limit` 即可(label 階段慢,11k 對話建議分批或背景跑)。
