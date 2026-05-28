# telegram-op-control — V0.3 Phase 1

**Standalone control-plane service** for the wannavegtour OP Assistant. Runs as a separate aiohttp service, not as a Hermes platform plugin. It receives Telegram Bot API webhook updates, audits them into `op_assistant_kernel.events`, and (in later phases) dispatches Gary's approve/reject/KILL button presses.

## Why standalone, not a Hermes platform plugin

LINE is the **customer channel** (`plugins/op-assistant-line`). Telegram in this project is the **control channel** (Gary approves bot changes from his phone). Sharing a Hermes process would couple their failure domains — a LINE webhook bug would also take down the control plane. V0.3 design §5 Phase 1 explicitly mandates separation.

So:
- `plugin.yaml` declares `provides_tools: []` and does not export `register()` — Hermes plugin discovery skips this directory.
- `adapter.py` is a runnable standalone aiohttp app.
- Deployment is a separate systemd unit (added in a later phase).

## Run

```bash
# env file ~/.hermes/profiles/op-assistant/.env (and ~/.hermes/.env) is loaded
# automatically; required vars listed in plugin.yaml
/home/wannavegtour/.hermes/hermes-agent/venv/bin/python \
    plugins/telegram-op-control/adapter.py
```

## Test

```bash
/home/wannavegtour/.hermes/hermes-agent/venv/bin/python \
    -m pytest plugins/telegram-op-control/tests/ -v
```

## Scope walls (Code is Rule)

- No LLM is ever imported here. All routing is deterministic Python.
- The webhook only **records** updates into `events`. Dispatch (Phase 4) and approval writes (Phase 5) belong to later phases.
