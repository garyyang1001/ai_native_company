# op-assistant-tools

這是阿玩旅遊 OP 部門助理「小弟」的 Hermes plugin skeleton。

它提供 6 個 deterministic harness tools,讓 OP LINE bot 之後可以照固定順序執行:

1. `query_intent`
2. `fetch_wc_data`
3. `compose_reply`
4. `validate_reply`
5. `send_reply`
6. `escalate_to_gary`

Phase D 只建立 plugin manifest、OpenAI-style tool schemas、以及 stub handlers。所有 handler 目前只回傳 `{"status": "stub", ...}`。不會呼叫 LINE API、WooCommerce REST API、GPT,也不會修改外部系統。

## 部署方式

從 repo source-of-truth 複製到 Hermes global plugin 目錄:

```bash
mkdir -p ~/.hermes/plugins/op-assistant-tools
cp -r "/home/wannavegtour/Desktop/AI Native Company/Gary/plugins/op-assistant-tools/"*.py \
  "/home/wannavegtour/Desktop/AI Native Company/Gary/plugins/op-assistant-tools/plugin.yaml" \
  ~/.hermes/plugins/op-assistant-tools/
chmod 600 ~/.hermes/plugins/op-assistant-tools/*
```

然後只在 `op-assistant` profile 的 `config.yaml` 啟用這個 plugin。其他 profile 不應啟用。

## 必要環境變數

- `KERNEL_DATABASE_URL`: closed_loop_kernel(op-assistant) PostgreSQL DSN
- `WANNAVEGTOUR_REPO_PATH`: Gary 的 wannavegtour repo 絕對路徑,之後用來重用 `wannavegtour` package

## 選用環境變數

- `TELEGRAM_BOT_TOKEN`: 之後 `escalate_to_gary` 推 Telegram 給 Gary 使用
- `TELEGRAM_HOME_CHANNEL`: Gary 的 Telegram chat_id

## Phase 狀態

- Phase D: skeleton stubs only
- Phase E: 補 query/fetch/compose/validate 的 deterministic Python logic
- Phase F: 補真實 LINE send / escalation bridge / replay verification
