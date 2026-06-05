# wannavegtour-knowledge

把官方 LINE 客戶對話 → 清洗 + 全面去識別 + 標記意圖 → 存進一個**獨立、共用、可讀**的
PostgreSQL 知識庫(canonical 唯一真相),供 RAG / 微調 / ElevenLabs / 其他 agent 共用。

## 快速開始

```bash
cd "~/Desktop/AI Native Company/wannavegtour-knowledge"
./.venv/bin/python run.py all --limit 30   # 試跑 30 個對話
./.venv/bin/python run.py stats            # 看結果
```

## 架構(三層 medallion)

```
LINE 匯出 zip ──ingest──▶ bronze(原始,含PII,本機受限)
                          raw_turns / source_files
                ──clean──▶ silver(清洗+去識別,帶版本)
                          clean_turns
                ──label──▶ gold(問答+意圖,canonical,對外共用唯讀)
                          knowledge_units  ◀── 其他 agent 讀這層
                                  │
                                  └─exporters/─▶ RAG / SFT / ElevenLabs
```

## 檔案

| 檔 | 作用 |
|---|---|
| `schema.sql` | DB schema(三層 + 稽核表 + 唯讀角色) |
| `config.py` | 設定 + 憑證載入(憑證在 ~/.hermes/credentials) |
| `db.py` | PostgreSQL 連線 + run 紀錄 |
| `clean.py` | 清洗判準(deterministic) |
| `redact.py` | 全面去識別(PII) |
| `labeler.py` | 意圖標記(本機 gpt-oss:120b) |
| `pipeline.py` | 三階段管線 |
| `run.py` | CLI |
| **`MAINTENANCE.md`** | **維護手冊 — 接手必讀** |

## 維護 / 重洗 / 共用 / 限制

全部見 **[MAINTENANCE.md](MAINTENANCE.md)**。重點:
- 冪等,可隨時中斷續跑;
- 改規則 → `config.PIPELINE_VERSION` +1 即可重洗,bronze 永不丟;
- gold 用唯讀角色 `wv_knowledge_reader` 給其他 agent 讀;
- ⚠️ 人名去識別主帳號覆蓋良好,但同行旅客名可能漏 → 正式對外前先補 LLM/NER pass(見維護文件 §10)。
