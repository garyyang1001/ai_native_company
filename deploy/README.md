# deploy/

Production deployment artifacts for the wannavegtour OP Assistant on
the DGX Spark machine. The repo itself is the source of truth for these
files; the live copies under `~/.config/systemd/user/` are installed
via the steps below.

## V0.3 Phase 1+4 Telegram OP control plane

The `telegram-op-control` plugin runs as a standalone aiohttp service on
port `8647`, exposed publicly via the existing Tailscale Funnel under
`/telegram-op/*`. Telegram sends inline-keyboard `callback_query`
updates here; Phase 4 dispatcher writes approvals, triggers Phase 6
sandbox replay, and replies in Telegram.

### Files

| Path | Lives where in production | Purpose |
|---|---|---|
| [`systemd/hermes-telegram-op-control.service`](systemd/hermes-telegram-op-control.service) | `~/.config/systemd/user/` | systemd user unit that starts the plugin |

### Install

```bash
# 1. Sync plugin source into the runtime path the unit expects
rsync -a --delete \
    "/home/wannavegtour/Desktop/AI Native Company/Gary/plugins/telegram-op-control/" \
    ~/.hermes/plugins/telegram-op-control/

# 2. Install the systemd unit
cp deploy/systemd/hermes-telegram-op-control.service ~/.config/systemd/user/

# 3. Make sure ~/.hermes/.env carries:
#    TELEGRAM_BOT_TOKEN
#    TELEGRAM_HOME_CHANNEL
#    TELEGRAM_WEBHOOK_SECRET          (random 32-byte hex)
#    TELEGRAM_PUBLIC_URL              (e.g. https://<funnel>/telegram-op)
#    TELEGRAM_ALLOWED_CHATS           (= TELEGRAM_HOME_CHANNEL)
#    OP_PHASE3_INLINE_KEYBOARD=1

# 4. Tailscale funnel must mount /telegram-op → http://127.0.0.1:8647
#    (one-time, requires sudo):
#    sudo tailscale set --operator=$USER
#    tailscale serve --bg --set-path=/telegram-op http://127.0.0.1:8647

# 5. Start the service
systemctl --user daemon-reload
systemctl --user enable --now hermes-telegram-op-control.service
systemctl --user status hermes-telegram-op-control.service

# 6. Tell Telegram about the webhook
/home/wannavegtour/.hermes/hermes-agent/venv/bin/python \
    scripts/op_assistant/op_assistant_telegram_setwebhook.py
```

### Verify

```bash
# Service is up
systemctl --user is-active hermes-telegram-op-control.service

# Webhook is registered (no token in output)
/home/wannavegtour/.hermes/hermes-agent/venv/bin/python \
    scripts/op_assistant/op_assistant_telegram_setwebhook.py --verify-only
```

A real button tap from Gary's Telegram will land in
`events.telegram_inbound`, trigger `dispatch_callback`, and reply in
the same chat. Round 9's production smoke test exercises the same
chain without Telegram.

### Rotate the webhook secret

```bash
# Generate new
NEW_SECRET=$(python3 -c "import secrets;print(secrets.token_hex(32))")
# Edit ~/.hermes/.env: TELEGRAM_WEBHOOK_SECRET=$NEW_SECRET
# Then:
systemctl --user restart hermes-telegram-op-control.service
/home/wannavegtour/.hermes/hermes-agent/venv/bin/python \
    scripts/op_assistant/op_assistant_telegram_setwebhook.py --delete
/home/wannavegtour/.hermes/hermes-agent/venv/bin/python \
    scripts/op_assistant/op_assistant_telegram_setwebhook.py
```
