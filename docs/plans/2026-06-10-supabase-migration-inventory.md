# Supabase 搬家盤點報告(第一步,2026-06-10)

> 目的:評估把 CRM 的雲端 Supabase(`ngxcpgnbstacxhkzxfen`)搬到 DGX 本地的風險與工程量。
> 方法:全機程式碼/設定/容器掃描 + Zeabur API 盤查。**全程唯讀,未改任何東西。**
> 結論先講:**可行,走「本地自架 Supabase + 單向鏡像備份」路線;但比「搬一顆資料庫」厚——CRM 用掉 Supabase 四個子系統。工程量估 3-5 個工作天 + 切換後 2-4 週觀察期。**

## 一、好消息(讓搬家可行的事實)

1. **所有連線都從 DGX 出發**:backend、admin、frontend 三個容器都在 DGX;Zeabur 官網(Real 三服務)零 Supabase 連線;主機 crontab、systemd、Hermes、知識管線全部乾淨。**沒有任何外部服務直連這顆資料庫。**
2. **寫入全部經過 DGX 後端**:WooCommerce webhook、新官網訂單同步、CRM 排程(5 個任務)都在後端容器內——切換點集中。
3. **護照照片在本機磁碟**(`data/passports/`,docker volume),不用搬。
4. **沒用 RPC / Edge Functions**(全 repo 零命中)——少兩個要替代的東西。

## 二、複雜點(「不只是一顆 Postgres」)

CRM 實際用了 Supabase 的**四個子系統**,自架時都要起:

| 子系統 | 用在哪 | 搬家動作 |
|---|---|---|
| DB(PostgREST) | backend 87 個檔案走 `.table()` API | 自架 stack 就不用改程式,只換連線 env |
| Auth(GoTrue) | 邀請/建帳號走 admin API;**JWT 簽章金鑰綁定**(backend 用 `SUPABASE_JWT_SECRET` 自簽 LINE 登入 token,PostgREST/Realtime 靠它驗) | 自架 stack 的 JWT secret 要與簽發端一致 |
| Storage 3 buckets | `chat-files`(LINE 聊天圖/語音)、`payment-screenshots`(付款截圖)、`avatars`(頭像,前端直傳) | 搬 bucket 物件 + **DB 列內嵌的 public URL 要改寫**(如 `payments.screenshot_url`) |
| Realtime | 前端聊天介面三個即時訂閱(對話/會話列表/通知) | 自架 stack 含 Realtime,否則聊天即時更新會壞 |

另外兩個工程點:

5. **前端是瀏覽器直連 Supabase**,且網址在 build 時烤進 JS bundle → 切換時**前端必須重 build**;而且同仁從外面用 crm.lazyoffice.app,所以**本地 Supabase 也要有對外網址**(走現成的 Cloudflare tunnel 加一個子網域即可,如 supabase.lazyoffice.app)。
6. **舊專案地雷清理**:legacy 腳本硬編碼舊 Supabase 專案(`omhddlplqyjbfcccerwm`,如 `backend/scripts/migrate_pinned.py`),誤跑會打錯資料庫;`.env` 備份檔含舊憑證。搬家時一併作廢/清除。

## 三、建議路線(維持上次討論的單向架構)

```
1. DGX 起官方 self-host Supabase(docker:PG + PostgREST + GoTrue + Storage + Realtime + Kong)
2. Cloudflare tunnel 加子網域指到本地 Supabase(給瀏覽器直連用)
3. 資料遷移:pg_dump 倒庫 + 下載 3 個 bucket + 改寫列內 storage URL + 對齊 JWT secret
4. 前端用新網址重 build;backend/admin 換 env → 離峰重啟(中斷約 1 分鐘)
5. 雲端凍結唯讀 2-4 週當後悔藥;每日自動備份(本地 → 雲端儲存/QNAP)上線
6. 清理:作廢舊專案腳本、刪含憑證的 .env 備份檔
```

**雙向同步維持不做**(衝突地獄);雲端只當備份鏡像。

## 四、待辦/待驗證

- [x] **線上 DB 體積與各表筆數**(2026-06-10 Gary 授權唯讀查詢,實測):
  - DB 總大小 **20 MB**,public 51 表,auth.users 1 筆
  - 最大表:orders 1,355 列 / customers 1,009 / tour_groups 260 / payload_products 134 / messages 89(對話功能未上線,幾乎空)
- [x] **Storage 實測**:共 **65 個檔案 / 20 MB**(payment-screenshots 46 檔 18 MB、chat-files 19 檔 2.4 MB、avatars 0)
  - → URL 改寫範圍極小(65 個檔案的連結)
  - → **全部搬家資料量 ≈ 40 MB**,倒資料和搬檔案都是分鐘級操作
- [ ] `wannavegtour-creter`(Zeabur 舊版官網部署)環境變數未能用 API 驗證——同套 Payload 程式,風險極低,切換前再人工看一眼
- [ ] `crm-api.lazyoffice.app` 的 route 確認(應為 DGX cloudflared,切換前驗證)
- [ ] 對齊文件:`2026-06-10-cs-rag-crm-integration-plan-v0.md` 寫「Supabase 續留訂單/客戶」——本報告方向已升級為「整顆搬本地」,以本報告為準
- [ ] intent-labeler 的 sources.py 規劃寫著要直連 Supabase(stub 未實作),搬家後更新

## 五、複雜度總評

| 方案 | 複雜度 | 評語 |
|---|---|---|
| 自架 Supabase 整套 + 單向備份(建議) | **中** | 程式幾乎不用改;工夫在 storage URL 改寫、JWT 對齊、前端重 build、對外網址 |
| 改寫程式接普通 PostgreSQL | 高 | 87 個 backend 檔 + 前端直連邏輯 + Realtime 替代品,不划算 |
| 雙向同步 | 很高 | 不做 |
