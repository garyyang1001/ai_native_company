# LINE Messaging API 串接設定（wannavegtour OP 群）

這份文件給 Gary 一人看。教你怎麼在 LINE 平台拿到串接 wannavegtour OP 群所需的 credentials，放到 Hermes 約定位置。**你自己操作 LINE 後台、自己填 credentials 檔案，我不需要看到任何 secret**。

---

## 你需要拿到的四個值

| 值 | 來源 | 範例 | 何時用 |
|---|---|---|---|
| **Channel ID** | LINE Developers Console → 你的 channel → Basic settings | `1234567890`（10 位數字） | 識別 channel 用 |
| **Channel Secret** | 同上 | 32 字 hex（範例略 — 不放範本避免被誤認 secret） | 驗證 webhook 簽章用 |
| **Channel Access Token** | LINE Developers Console → 你的 channel → Messaging API → Issue | 一長串 base64-ish 字串 | 呼叫 LINE API（推送訊息）用 |
| **Bot Basic ID** | 同上 Messaging API tab | `@850abcdef`（含 @） | 顯示 / debug 用 |

---

## Step 1：建 Channel（10 分鐘）

1. 開 https://developers.line.biz/console/
2. 登入（用你既有的 LINE 帳號）
3. 如果還沒 Provider：**Create Provider** → 名稱「wannavegtour」或「阿玩」皆可
4. 在 Provider 底下 **Create a Messaging API channel**
   - Channel name: `wannavegtour-op-bot`
   - Channel description: `Internal OP group automation for wannavegtour`
   - Category / Subcategory: 隨意填（行銷 / 旅遊）
   - Company name: 玩素食旅行社股份有限公司
   - 同意 Terms

5. 建好後 → 進入 channel → **Basic settings** tab
   - **Channel ID**：複製
   - **Channel secret**：複製（按 Issue 才會顯示）
   - 滾到最下面 → Delete channel 旁邊那個 **「Disable use of OAuth 2.0 for v2.1 endpoints」** 可以留預設

---

## Step 2：拿 Channel Access Token（2 分鐘）

1. 同一個 channel → 切到 **Messaging API** tab
2. 滾到 **Channel access token** 區
3. 選 **Long-lived**（沒到期日，省得每月換）
   - 如果你公司政策要求 token 有到期日，選 **Stateless** 然後在 credentials 裡填 `expires_at`
4. **Issue** → 複製整個 token

⚠️ **這個 token = 你 channel 的萬能鑰匙**：能讀全部 webhook、能 push 任何訊息、能加好友、能撤好友。**洩漏 = LINE 帳號被別人接管**。

---

## Step 3：設應答模式（必做，不然 webhook 不會觸發）

切換到 **LINE Official Account Manager**（不同網站）：https://manager.line.biz/

1. 登入 → 選 wannavegtour-op-bot
2. 左側 **設定** → **應答設定**
3. **應答模式** 改成 **聊天機器人**（不是「聊天」）
4. **自動回應訊息** 改成 **停用**（否則 LINE 內建回覆會跟我們的 bot 互踩）
5. **Webhook** 改成 **啟用**
6. 暫時不填 webhook URL（之後接 LINE listener 服務時再填）

回到 **設定** → **帳號設定**
1. **接受邀請加入群組或多人聊天室** 改成 **接受**（預設可能是「拒絕」）

---

## Step 4：申請藍盾（認證帳號，可選但建議）

藍盾讓 LINE 帳號可被搜尋 + 看起來更專業 + 之後上廣告需要。

- 路徑：LINE Official Account Manager → 設定 → 認證帳號 → 申請
- 費用：NT$720/年（電腦 / Android 申請）
- 文件：商業登記證明（玩素食旅行社的）

**Type 1 worker 不需要藍盾就能跑**。等之後對外正式上線時再辦也可以。

---

## Step 5：填 credentials 檔案

我已經幫你建好 template：

```
~/.hermes/credentials/wannavegtour/line-bot.json
```

權限已鎖 mode 600（只有你能讀）。打開編輯：

```bash
chmod 644 ~/.hermes/credentials/wannavegtour/line-bot.json   # 暫時開放編輯
$EDITOR ~/.hermes/credentials/wannavegtour/line-bot.json
chmod 600 ~/.hermes/credentials/wannavegtour/line-bot.json   # 編輯完再鎖回去
```

把 Step 1-2 拿到的 4 個值貼到對應欄位。改成 `"filled": true`，`"issued_at"` 填當下 ISO8601 時間：

```json
{
  "site": "wannavegtour",
  "platform": "line",
  "channel_id": "<10-digit numeric from Basic settings>",
  "channel_secret": "<32-char hex from Basic settings>",
  "channel_access_token": "<long token from Messaging API tab>",
  "bot_basic_id": "@<your bot id>",
  "bot_user_id": null,
  "target_groups": [],
  "webhook_url": null,
  "filled": true,
  "issued_at": "2026-05-25T13:30:00+08:00",
  "expires_at": null,
  "notes": [ ... ]
}
```

`bot_user_id` / `target_groups` / `webhook_url` 留 null / `[]` 就好，會在之後自動填。

---

## Step 6：驗證 credentials 真的能用

填好後，用這個 curl 驗證 channel access token 有效：

```bash
TOKEN=$(jq -r .channel_access_token ~/.hermes/credentials/wannavegtour/line-bot.json)

curl -sS -H "Authorization: Bearer $TOKEN" \
  https://api.line.me/v2/bot/info | jq .
```

預期輸出：

```json
{
  "userId": "U1234567890abcdef1234567890abcdef",
  "basicId": "@850abcdef",
  "displayName": "wannavegtour-op-bot",
  "pictureUrl": "https://...",
  "chatMode": "bot",
  "markAsReadMode": "manual"
}
```

→ 看到 `chatMode: bot` 代表 Step 3 設定對了。複製 `userId` 那個 `U...` 字串回 line-bot.json 的 `bot_user_id` 欄位。

如果回 401 / 400：token 沒貼對，或 Step 3 應答模式沒切。

---

## 我做完之後，下一步要蓋的東西（不是現在）

`line-bot.json` 填好之後，第二輪工作會蓋：

1. **LINE listener 服務（webhook receiver）** — 跑在你機器或 VPS，接 LINE webhook，把 OP 群訊息送進 Hermes Kanban
2. **Hermes profile：`line-gateway`** — 接 webhook → router → 已有的 wannavegtour worker
3. **Webhook URL 寫回 LINE Developers Console** — Step 3 那個現在空著的欄位
4. **Bot 加入 OP 群實測** — 用 bot_basic_id (`@850abcdef`) 在 LINE App 加好友，再邀進 OP 群

那輪我會在新 worktree 上做，不會動到目前已 commit 的 wannavegtour package。

---

## 安全提醒（讀一次就好）

- **Channel access token 洩漏的傷害**：別人可以用你的 bot 推訊息給所有加入的群組 / 好友。對你而言：聲譽傷害、可能被 LINE 停權、客戶混淆
- **這個 token 沒辦法看舊訊息**：LINE 不允許 bot retrieve 歷史訊息，只能收 join 之後的新訊息。所以洩漏不會洩露舊對話
- **撤銷 token 的方法**：LINE Developers Console → channel → Messaging API → Reissue（會立即作廢舊 token，所有用舊 token 的服務會 401）
- **Channel secret 洩漏的傷害**：別人可以偽造 webhook 騙你 server 處理假訊息。所以 webhook server 必須驗證 `x-line-signature` header（之後 LINE listener 服務會做）
- **跟 WC API credentials 一樣的硬性 dependency**：升 macOS Keychain 那條 TODO 也包含這檔案

---

## 給未來的我看的對照表

| 平台 | 你給 bot 什麼權限 | bot 能做什麼 |
|---|---|---|
| LINE 群組裡的 bot | 預設無權限 | 收 webhook、push message 到該群、reply 限 30 秒內 |
| 群組中已 @mention | 同上 + 知道自己被叫到 | 觸發 message event 的 mention.isSelf=true |
| 1:1 chat with bot | 同上 + 可看 user profile | 可用 push / multicast 給該 user |
| Channel access token | 萬能 | 上述全部 |

換句話說：**這個 token 等同於這個 LINE 帳號的全部 API 能力**，妥善保管。
