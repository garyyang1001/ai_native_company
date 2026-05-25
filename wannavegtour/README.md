# wannavegtour — Type 1 availability checker

阿玩旅遊 OP 群的第一個 AI 工作切片（Type 1：查名額）。

讀內部同事在 LINE OP 群打的「3/5 江南還剩多少？」這種訊息，回去 wannavegtour.com 的 WooCommerce 查當天那團的名額、售價、出發機場，回一份 LINE 風格的答案。

不寫任何資料，純讀。

---

## 1. 這是什麼 / 不是什麼

**這是什麼：**

- 一個獨立 Python 套件，可從 CLI 直接跑、可被未來的 Hermes profile 引用
- 純讀 WooCommerce REST API（Application Password / consumer key 任一 BasicAuth 形式皆可）
- 純規則式（deterministic）— 沒有 LLM 在 control flow 裡（Code is Law 原則）

**這不是什麼（故意不做）：**

- ❌ LINE bot listener — 還沒接到 LINE webhook，現在純靠 CLI / Python import 餵訊息
- ❌ Telegram 批准通知 — Type 1 純讀無需批准；Type 2 才會用 `@skimm3r918_bot`
- ❌ Hermes profile scaffold — LINE webhook 接上之前先不蓋 profile，避免空殼
- ❌ Type 2 (改價/改網頁) — 偵測到 PRICE_EDIT_HINT 會明確拒絕，不會誤判
- ❌ Type 3 (客訴) / Type 4 (新企劃) — 範圍外
- ❌ 寫進 closed_loop_kernel 的 events / approvals — Type 1 純讀，不適合丟進為「修正案閉環」設計的 kernel schema

---

## 2. 快速試跑

```bash
# 1. 確認 credentials 已填好（檔案 owner 才能讀，mode 600）
ls -la ~/.hermes/credentials/wannavegtour/wc-api.json

# 2. CLI 互動 REPL
cd <repo-root>
python3 -m wannavegtour.cli

# 範例輸入：
#   12/27 江南還收嗎
#   9/15 韓國首爾還剩多少？
#   7/9 韓國首爾還有位嗎          ← 會回多筆（桃園+台中出發）
#   韓國 8/12 那團                ← 低庫存會跳 ⚠️
#   3/5 那團怎麼樣？              ← 缺目的地 → 會請你補
#   5/6 價格改80000              ← Type 2 → 會拒絕
#   ?12/27 江南                  ← 加 ? 前綴看 parser debug
```

範例輸出：
```
🎯 12/27【江南】烏鎮・西湖・蘇州・江南水鄉・夜宿烏鎮一晚・三船一秀｜文化考察交流團．無購物
✅ 名額：10 位
💰 售價：NT$48,900（原價 NT$50,900）
📅 6 天行程
✈️ 桃園出發
🔗 https://wannavegtour.com/product/12-27/

📌 數字來自 WC 系統；若有保留位 / 候補名單請以 OP 為準。
```

---

## 3. Credentials

檔案路徑（fixed by `wannavegtour.config.DEFAULT_CREDENTIAL_PATH`）：

```
~/.hermes/credentials/wannavegtour/wc-api.json
```

權限：`-rw-------`（mode 600），目錄 `drwx------`（mode 700）。

格式（任一種 BasicAuth 都能用）：

```json
{
  "site": "wannavegtour",
  "base_url": "https://wannavegtour.com",
  "api_namespace": "wc/v3",
  "consumer_key": "<ck_xxx... 或 WP 使用者名>",
  "consumer_secret": "<cs_xxx... 或 application password 24-char>",
  "auth_method": "header",
  "permissions": "read"
}
```

**注意（已知債務）：**
- 純 JSON + mode 600 對 solo dev 個人 Mac 可接受，但**防不住同 UID 程式 + Time Machine 備份明文洩漏**
- 升 Type 2（改價）之前必須升級到 macOS Keychain 或 1Password CLI（見 repo top-level credentials 討論）
- 本切片只用 read 權限，洩漏的最大傷害是「客戶可看的商品 + 訂單資料外流」，**還不會被改價、改網頁**

---

## 4. 架構

```
┌──────────────────────────────────────────────┐
│ cli.py                                        │
│  輸入文字 → parse → check → format → 印出     │
└──────────────────────────────────────────────┘
              │
              ▼
┌──────────────────────────────────────────────┐
│ query_parser.parse_query(text) → ParsedQuery │
│  • 半形/全形數字、中文數字、日期變體            │
│  • Type 2 (改價) 偵測 → PRICE_EDIT_HINT      │
│  • destination_hint 抽取 (strip filler)      │
└──────────────────────────────────────────────┘
              │
              ▼
┌──────────────────────────────────────────────┐
│ availability_checker.check(query)            │
│  → CheckResult (FOUND_ONE/MANY/NONE/...)     │
│  • 用 destination_hint 打 WC search           │
│  • 比對每個 product 的 departure-date meta   │
│  • Bucket: 0 / 1 / many / edge cases         │
└──────────────────────────────────────────────┘
              │           │
              ▼           ▼
┌─────────────────┐ ┌─────────────────────────┐
│ wc_client       │ │ response_formatter      │
│ thin REST + auth│ │ CheckResult → LINE text │
└─────────────────┘ └─────────────────────────┘
              │
              ▼
   ~/.hermes/credentials/wannavegtour/wc-api.json
   (config.load_config)
```

**模組職責：**

| 檔案 | 職責 |
|---|---|
| `config.py` | 載 credentials，dataclass，驗 placeholder |
| `wc_client.py` | requests.Session + BasicAuth + 取 product / search products；錯誤統一包成 `WCAPIError` |
| `query_parser.py` | 純規則 NLP，無網路、無 LLM，輸入 → `ParsedQuery` |
| `availability_checker.py` | 商業邏輯：搜尋 → 過濾 → bucketing |
| `response_formatter.py` | `CheckResult` → LINE 友善字串 |
| `cli.py` | 互動 REPL |
| `tests/test_query_parser.py` | 24 個 unit test，無網路 |
| `tests/test_response_formatter.py` | 16 個 unit test，用假 product |
| `tests/test_availability_checker_live.py` | 6 個 live test（需 `HERMES_WANNAVEG_LIVE=1`） |

---

## 5. 測試

```bash
# 純 unit (40 tests, ~6ms, 無網路)
python3 -m unittest wannavegtour.tests.test_query_parser \
                    wannavegtour.tests.test_response_formatter -v

# Live integration (6 tests, ~2.5s, 打 wannavegtour.com)
HERMES_WANNAVEG_LIVE=1 python3 -m unittest \
    wannavegtour.tests.test_availability_checker_live -v
```

Live tests pin 兩個已知商品（id 255634 = 12/27 江南，7/9 韓國首爾雙團）。
若這些商品被下架或日期改，需要更新測試 fixture。

---

## 6. 設計決策（給未來修改的人）

| 決策 | 為什麼 |
|---|---|
| `departure-date` JetEngine 自訂欄位當 PRIMARY date source | 100% 覆蓋 publish products，比 title regex 可靠（15% 標題不照 `M/D【...】` 模板） |
| WC API 而非 SQL/SSH 直接讀 | 標準介面、含 WC plugin hooks、auth 可獨立撤銷 |
| Type 2 早期拒絕（PRICE_EDIT_HINT） | 避免 worker 半懂半不懂去亂查；明確邊界比假裝聰明好 |
| Per-product re-fetch 取 meta_data | WC list endpoint 不一定吐 meta；單筆 GET 保證完整。10 筆內網路成本 < 1.5s |
| 純規則 + keyword（無 LLM） | 符合「Code is Law」；可 reproducible；可 sandbox replay；錯了好 debug |
| 年份推論：過去日期視為明年 | 旅行社問「3/5」基本指未來；若要查歷史團要另開 query 模式 |

---

## 7. 下一步 roadmap

優先序按 Gary 已敲定的方向：

1. **包成 Hermes profile 並接 LINE bot**
   - 建 `line-gateway` profile：收 LINE webhook，把訊息進 Hermes Kanban
   - 建 `request-router` profile：分類 Type 1-4，分派
   - 建 `availability-checker` profile：本套件當 worker
   - 整合到 HermesRuntime 的 `channel_directory.json`

2. **Type 2 worker（改價 / 改網頁）**
   - 新增 `wannavegtour/pricing_editor.py` + `wannavegtour/itinerary_editor.py`
   - WC API 升 read/write
   - 整合 closed_loop_kernel 的 4 層 apply gate（approval + dry_run_verified + replay + hash）
   - **走 pre-flight read → write → re-read verify → auto-rollback pattern**（非 Kinsta staging）

3. **自動進化（business judgement patch）**
   - 在 closed_loop_kernel 新增 `routing_patch` / `response_template_patch` candidate types
   - sandbox replay 對歷史對話跑過去，驗證新規則的路由 / 回應結果
   - 整合進既有 candidate → sandbox → approve → apply 流程

4. **Type 3 (客訴 drafter) / Type 4 (新企劃 multi-agent)** — 範圍更大，等 Type 1+2 跑穩

---

## 8. 跟既有 kernel 的關係

本套件**目前不寫**進 `closed_loop_kernel`，理由：

- Type 1 是純讀，沒有「修正案」概念，kernel schema 不合身
- 套件成熟前先讓它能獨立跑、獨立測，避免把實驗性程式碼塞進已穩定的 kernel
- 等 Hermes profile + LINE webhook 接上後，**業務事件**（同事 query → agent 回覆）才適合進 kernel `events` 表當稽核軌跡
- Type 2 啟用時，**寫操作的 candidate 必定走 kernel**（這是 kernel 設計的真正用武之地）

換句話說：**現階段 wannavegtour 是 kernel 的「未來客戶」，不是 kernel 的內部模組**。
