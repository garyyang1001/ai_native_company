# Handoff: wannavegtour OP Bot — Ready for New-Machine Migration

Date: 2026-05-25

## Current Decision

Prepare the `Gary` private repository so the wannavegtour OP bot and the AI Native Company kernel can move to a new development / deployment machine, likely NVIDIA DGX Spark.

Current source worktree:

```text
/Volumes/Hermes System/HermesArchive/Gary/.claude/worktrees/wannavegtour-availability-checker
git@github.com:garyyang1001/Gary.git
observed branch: worktree-wannavegtour-availability-checker
base: main
state: 10 commits ahead of main, not pushed from this handoff commit
```

This handoff is for code migration and continuation. It does not move secrets, local runtime logs, production databases, or Hermes runtime state.

## Migration Status

- 2026-05-25: Migrated to NVIDIA DGX Spark (`spark-8035`, Linux).
- Public webhook (Tailscale Funnel): `https://spark-8035.tailb40323.ts.net/wannavegtour/line/webhook`
- LINE webhook endpoint set via Messaging API (`PUT /v2/bot/channel/webhook/endpoint`), test reply `success:true / 200`.
- Linux launcher added: `bin/wannavegtour-line-up-linux` (macOS launcher kept as-is).

## What Was Built

- `6459b75 Add wannavegtour Type 1/3/4 workers (LINE OP -> WC REST)`:
  Added the `wannavegtour/` Python package: deterministic parser, WooCommerce client, Type 1 availability checker, historical / lifecycle lookup, LINE-style response formatting, CLI, package exports, tests, and package README.
- `1a807bd Add LINE Messaging API credential setup guide for wannavegtour OP bot`:
  Added `docs/line-credentials-setup.md` for Gary-side LINE channel setup and secret placement. No secrets are stored in the repo.
- `653d18b Add LINE webhook listener (L1) + Tailscale Funnel launcher`:
  Added `line_client.py`, `line_router.py`, `line_listener.py`, `bin/wannavegtour-line-up`, `bin/wannavegtour-line-down`, LINE signature verification, threaded webhook handling, JSONL audit log, and Tailscale Funnel exposure.
- `679b587 Fix launcher: replace Unicode ellipsis adjacent to shell var`:
  Fixed shell parsing in the launcher so the runtime script stays portable across local shells.
- `8807e10 Switch to passive listening mode: bot stays silent unless @mentioned`:
  Changed group behavior to silent observer by default. Messages are classified for audit, but the bot replies only when invoked.
- `a1c831d Add text-prefix invocation: works on desktop LINE (no @autocomplete needed)`:
  Added prefix triggers such as `小弟`, `@小弟`, and `/小弟` so desktop LINE users can invoke the bot without mobile @mention support.
- `a60125f Add help command (小弟 ?) returning plain-Chinese functionality summary`:
  Added a shipped-feature help response for OP users, including availability, historical lookup, ranking, and Type 2 refusal boundaries.
- `58f8527 Speed up aggregate ranking + show total_sales in availability replies`:
  Improved historical aggregate ranking performance and exposed WooCommerce `total_sales` in relevant replies.
- `4034da7 Fix 成團了嗎/額滿了嗎 fallback for publish tours (no lifecycle marker yet)`:
  Added fallback behavior for currently published tours that have no lifecycle marker but are asked about as if historical.
- `f643aa3 Parser: catch "賣的最好" / "賣得最好" + "最近" as aggregate signals`:
  Broadened aggregate-query parsing for natural OP phrasing and recent-period questions.

## Architecture Snapshot

```text
LINE webhook
  -> wannavegtour.line_listener (Python stdlib ThreadingHTTPServer)
  -> x-line-signature verification
  -> wannavegtour.line_client.parse_events
  -> wannavegtour.line_router
  -> wannavegtour.query_parser
  -> workers:
       - availability_checker
       - historical_lookup
  -> response_formatter
  -> LINE reply API first, push API fallback
  -> append-only JSONL audit record
```

Runtime endpoint paths:

```text
POST /wannavegtour/line/webhook
GET  /healthz
GET  /
```

The bot is deterministic in control flow. There is no LLM classifier in the current route.

## Files / Modules Map

`wannavegtour/` package:

- `wannavegtour/__init__.py` - package exports for configs, parser, WC client, workers, and formatters.
- `wannavegtour/config.py` - loads WC and LINE credentials from `~/.hermes/credentials/wannavegtour/`, enforces mode `600`, and defines invocation prefixes.
- `wannavegtour/wc_client.py` - thin synchronous WooCommerce REST client with BasicAuth, product dataclass, stock buckets, and API error wrapper.
- `wannavegtour/query_parser.py` - deterministic LINE-message parser for availability, historical, aggregate, and Type 2 price-edit hints.
- `wannavegtour/availability_checker.py` - Type 1 read-only availability worker: search WC, match departure date, bucket result.
- `wannavegtour/historical_lookup.py` - historical / lifecycle / aggregate worker across publish, private, and draft products.
- `wannavegtour/response_formatter.py` - formats worker results into short LINE-readable Traditional Chinese replies.
- `wannavegtour/cli.py` - local REPL dry-run entry point: `python3 -m wannavegtour.cli`.
- `wannavegtour/line_client.py` - LINE HMAC signature verification, webhook event parsing, reply / push API client.
- `wannavegtour/line_router.py` - passive-listening dispatcher, invocation detection, help command, worker routing, Type 2 refusal.
- `wannavegtour/line_listener.py` - stdlib threaded HTTP listener, `/healthz`, webhook endpoint, async dispatch, JSONL audit logging.

Other runtime files:

- `bin/wannavegtour-line-up` - starts caffeinate, Python listener on `127.0.0.1:8765`, and Tailscale Funnel.
- `bin/wannavegtour-line-down` - stops Tailscale Funnel, listener, and caffeinate with PID command-line safety checks.
- `docs/line-credentials-setup.md` - LINE channel setup and local credential instructions.
- `wannavegtour/tests/` - unit and live integration tests for parser, formatter, workers, LINE client/router/listener, pagination, and credential security.

## Dependencies

Python:

- Current launcher uses `python3`.
- Code uses modern type syntax (`|` unions), so use Python 3.10+.
- Recommended for the new machine: Python 3.11+ in a virtualenv.

Python packages from `requirements.txt`:

```text
psycopg[binary]>=3.2
requests>=2.31
```

System tools:

- `tailscale` CLI - required by `bin/wannavegtour-line-up` for Funnel.
- `caffeinate` - macOS sleep prevention used by `bin/wannavegtour-line-up`.
- `curl` - used by launcher health checks.
- `chmod`, `mkdir`, `tail`, `ps`, `grep` - standard shell tools used by setup / launcher / stop flow.
- On Linux / DGX Spark, replace `caffeinate` with `systemd-inhibit` or run under a service manager. The current launcher is macOS-first.

Third-party services:

- LINE Messaging API - receives OP group webhooks and sends replies.
- WooCommerce REST API - reads products, stock, prices, metadata, lifecycle title markers, and `total_sales`.
- Tailscale Funnel - exposes the local webhook listener to LINE over HTTPS.

## Credentials Required

Credentials live outside the repo and must not be committed.

Directory:

```text
~/.hermes/credentials/wannavegtour/
```

Required permissions:

```bash
mkdir -p ~/.hermes/credentials/wannavegtour
chmod 700 ~/.hermes/credentials
chmod 700 ~/.hermes/credentials/wannavegtour
chmod 600 ~/.hermes/credentials/wannavegtour/wc-api.json
chmod 600 ~/.hermes/credentials/wannavegtour/line-bot.json
```

`wannavegtour.config.load_config()` and `load_line_config()` fail closed if POSIX credential files have group/world permission bits. Required file mode is `600` or stricter.

### WooCommerce Credential Schema

Path:

```text
~/.hermes/credentials/wannavegtour/wc-api.json
```

Schema:

```json
{
  "site": "wannavegtour",
  "base_url": "https://wannavegtour.com",
  "api_namespace": "wc/v3",
  "consumer_key": "<WC consumer key or WP username>",
  "consumer_secret": "<WC consumer secret or WP application password>",
  "auth_method": "header",
  "permissions": "read"
}
```

Only key names and placeholders belong in docs. Never paste actual `consumer_key` or `consumer_secret` into the repo.

### LINE Bot Credential Schema

Path:

```text
~/.hermes/credentials/wannavegtour/line-bot.json
```

Schema:

```json
{
  "site": "wannavegtour",
  "platform": "line",
  "channel_id": "<LINE channel id>",
  "channel_secret": "<LINE channel secret>",
  "channel_access_token": "<LINE channel access token>",
  "bot_basic_id": "@<LINE bot basic id>",
  "bot_user_id": "<LINE bot user id or null>",
  "target_groups": [],
  "webhook_url": null,
  "invocation_prefixes": ["小弟", "@小弟", "/小弟"],
  "filled": true,
  "issued_at": "<ISO8601 timestamp>",
  "expires_at": null,
  "notes": []
}
```

`target_groups: []` means accept any group. Set specific LINE group IDs before broader rollout if the bot must be limited to one OP group.

Never paste actual `channel_secret`, `channel_access_token`, group IDs, or user IDs into the repo.

## Bootstrap On New Machine

Clone the private repo:

```bash
mkdir -p "/Volumes/Hermes System/HermesArchive"
cd "/Volumes/Hermes System/HermesArchive"
git clone git@github.com:garyyang1001/Gary.git
cd Gary
git status --short --branch
```

If this OP bot branch has not been merged to `main`, fetch and check out the branch that contains the 10 commits:

```bash
git fetch origin
git switch worktree-wannavegtour-availability-checker
git log --oneline main..HEAD
```

Create Python virtualenv and install dependencies:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Create credential directory and files:

```bash
mkdir -p ~/.hermes/credentials/wannavegtour
chmod 700 ~/.hermes
chmod 700 ~/.hermes/credentials
chmod 700 ~/.hermes/credentials/wannavegtour
$EDITOR ~/.hermes/credentials/wannavegtour/wc-api.json
$EDITOR ~/.hermes/credentials/wannavegtour/line-bot.json
chmod 600 ~/.hermes/credentials/wannavegtour/wc-api.json
chmod 600 ~/.hermes/credentials/wannavegtour/line-bot.json
```

Create audit-log directory:

```bash
mkdir -p ~/.hermes/line_events
chmod 700 ~/.hermes/line_events
```

Install and authenticate Tailscale:

```bash
tailscale version
tailscale up
tailscale status
```

Join the existing `garymac-mini` tailnet if that is still the deployment tailnet, or use the new DGX / production tailnet decided by Gary. Confirm Tailscale Funnel is enabled for the node ACL.

Confirm sleep prevention:

```bash
command -v caffeinate
```

On Linux / DGX Spark, either ignore this for dev runs or use `systemd-inhibit` / a real systemd unit later. Do not edit the macOS launcher until the deployment target is known.

Run local dry run:

```bash
python3 -m wannavegtour.cli
```

Start listener + Tailscale Funnel:

```bash
bin/wannavegtour-line-up
```

Copy the public webhook URL printed by the launcher and set it in LINE Developers Console:

```text
https://<tailscale-dns-name>/wannavegtour/line/webhook
```

Then in LINE Developers Console / Official Account Manager, ensure:

- Webhook is enabled.
- Auto-reply is disabled.
- Bot can join groups.
- Webhook URL points to the new machine's Funnel URL.

## Run / Stop Commands

Start:

```bash
cd "/Volumes/Hermes System/HermesArchive/Gary"
bin/wannavegtour-line-up
```

Stop:

```bash
cd "/Volumes/Hermes System/HermesArchive/Gary"
bin/wannavegtour-line-down
```

Tail runtime log:

```bash
tail -F ~/.hermes/run/wannavegtour/listener.log
```

Local health check:

```bash
curl -sS http://127.0.0.1:8765/healthz
```

## Audit Log Location

Append-only LINE event audit log:

```text
~/.hermes/line_events/wannavegtour.jsonl
```

Each line is one JSON record containing event metadata, dispatch action, classified intent, worker, skip reason, extras, timing, and raw text. This is local runtime data and must not be committed.

The listener creates the parent directory if missing, but on a new machine create it during bootstrap so permissions are explicit:

```bash
mkdir -p ~/.hermes/line_events
chmod 700 ~/.hermes/line_events
```

## Testing

Current test files are under `wannavegtour/tests/`.

Run all wannavegtour tests with stdlib unittest:

```bash
python3 -m unittest discover -s wannavegtour/tests
```

If `pytest` is installed in the new environment, this should also work:

```bash
pytest wannavegtour/tests/
```

Run live WooCommerce API tests only when credentials are present and the target site can be hit:

```bash
HERMES_WANNAVEG_LIVE=1 python3 -m unittest wannavegtour.tests.test_availability_checker_live -v
```

Pytest equivalent:

```bash
HERMES_WANNAVEG_LIVE=1 pytest wannavegtour/tests/test_availability_checker_live.py
```

Run broader AI Native Company kernel checks separately, because they need `KERNEL_DATABASE_URL` and a throwaway PostgreSQL database:

```bash
python3 -m unittest discover -s tests
python3 -m closed_loop_kernel.demo
python3 -m closed_loop_kernel.http_app
```

## Known Limitations / Pending

- No `launchd` plist or systemd unit exists. A Mac reboot will not automatically restart the listener.
- Current launcher is macOS-first because it uses `caffeinate`.
- A basic `/healthz` liveness endpoint exists. There is no richer readiness / metrics endpoint yet.
- Type 2 price / page editing worker is not implemented. Current behavior is explicit refusal.
- Hybrid LLM classifier is not implemented. Routing is deterministic rules only.
- LINE listener writes local JSONL audit records, but there is no retention / cleanup job yet.
- DGX Spark with a Hermes-native LINE plugin is a separate migration path. Do not mix that with this L1 stdlib listener unless Gary decides to replace the current launcher/runtime.
- Type 1 currently reads WooCommerce directly. It does not write to `closed_loop_kernel` yet; business events should be imported later once the event-store contract is decided.

## Cross-References

- `README.md` - top-level AI Native Company repo overview and verification commands.
- `PROTOTYPE.md` - current Closed Loop Kernel prototype status and local run commands.
- `tracking/status.md` - current tracked status.
- `tracking/next-actions.md` - current implementation roadmap.
- `tracking/verification-log.md` - kernel verification history.
- `closed_loop_kernel/` - AI Native Company closed-loop kernel code.
- `wannavegtour/README.md` - package-level OP bot design, CLI use, credentials, tests, and roadmap.
- `docs/line-credentials-setup.md` - LINE Messaging API setup guide.
- `docs/hermes-integration-assessment-v0.md` - Hermes / kernel integration assessment and multi-tenant context.
- `docs/hermes-agent-first-architecture.md` - Hermes runtime / profile / Kanban architecture context.
- `docs/handoffs/2026-05-23-private-dev-handoff.md` - previous handoff style and private/public repo split.
