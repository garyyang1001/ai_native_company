# Gary

Gary is a working repository for turning an AI-native company operating model
into a small, durable, and verifiable local system.

The goal is not to build a generic SEO agent, a large company brain, or a
collection of disconnected automations. The goal is to define a company kernel
where real agents can do work, leave structured records, and make their inputs,
outputs, sources, artifacts, failures, reviews, approvals, and cleanup state
available for later inspection.

## Core Direction

This repository starts from a simple principle:

> Raw data is not company memory.

An AI-native company needs every meaningful data input and output to be
readable, recordable, reviewable, memory-candidate eligible, and cleanable.
That does not mean every raw log, draft, export, or transcript becomes memory.
It means agent work must leave records that can be verified, deduplicated,
scoped, approved, retained, or removed.

The current kernel is organized around four concerns:

- **Company data contracts**: common record shapes for tasks, source references,
  artifacts, output envelopes, failures, verification reports, memory
  candidates, and profile update candidates.
- **Agent profile registry**: a machine-readable registry of permanent and
  dynamic profiles, including what they can read, write, remember, and clean up.
- **Closed loop kernel prototype**: a local Python prototype for append-only
  lifecycle events, failures, candidates, sandbox replay, approval, and apply
  flows.
- **Public repository guardrails**: secret scanning, branch protection, and
  local output-envelope checks that reduce the chance of publishing credentials
  or operational details.

## Current Status

The repository currently includes:

- A Python closed-loop kernel prototype under `closed_loop_kernel/`
- Unit tests for the kernel, HTTP views, sandbox, PostgreSQL schema rendering,
  and agent profile registry
- A company data contract v0
- An agent profile registry v0
- A redacted public reference note for the previous OHYA SEO architecture
- Gitleaks configuration and a GitHub Actions security scan workflow

This is still a local prototype and contract layer. It is not a production
agent runtime, not a production database integration, and not a production
publishing system.

## Repository Map

- `closed_loop_kernel/` - Python prototype for lifecycle events, approvals,
  sandbox replay, profile registry validation, and local HTTP views
- `data/agent-profile-registry-v0.json` - machine-readable profile registry seed
- `docs/company-data-contract-v0.md` - source contract for company data records
- `docs/agent-profile-registry-v0.md` - profile registry contract and governance
- `docs/antigravity-supervision-workflow.md` - Codex/Antigravity supervision
  workflow
- `spec/` - closed-loop kernel specifications and acceptance criteria
- `tests/` - unit tests for the current prototype and contracts
- `references/ohya-seo-architecture/SNAPSHOT.md` - redacted public-safe
  architecture pattern note
- `.gitleaks.toml` - local and CI secret scanning configuration
- `.github/workflows/security-scan.yml` - GitHub Actions Gitleaks workflow

## Local Verification

Run the unit test suite:

```bash
python3 -m unittest discover -s tests
```

Run the local demo:

```bash
python3 -m closed_loop_kernel.demo
```

Run the local HTTP prototype:

```bash
python3 -m closed_loop_kernel.http_app
```

Then open:

```text
http://127.0.0.1:8765/events
```

## Security Guardrails

This repository is intended to be public-safe. Current guardrails include:

- Gitleaks configuration in `.gitleaks.toml`
- GitHub Actions secret scanning on push and pull request
- GitHub native secret scanning and push protection
- Protected `main` branch with pull-request review required
- Local credential-leak detection inside `validate_output_envelope`

The local output-envelope guardrail scans agent payloads and machine records for
common credential patterns before accepting an output envelope. It intentionally
ignores known metadata fields such as content hashes and timestamps.

## Boundaries

- Do not commit credentials, auth files, runtime logs, production databases, or
  local runtime state.
- Do not treat raw exports, transcripts, logs, or generated artifacts as company
  memory.
- Do not let one profile execute, review, approve, and apply its own work.
- Do not restore private executable reference snapshots into this public
  repository.
- Do not copy client-specific paths, tokens, platform details, or deployment
  assumptions into public architecture documents.

## Design Principle

The durable unit of work is not a chat response. It is a reviewable record:

```text
task -> source evidence -> agent output envelope -> artifact -> verification
     -> review -> approval -> memory candidate -> cleanup or retention
```

That loop is the company kernel. Agents can change, tools can change, and
department applications can be added later, but the record contract should stay
small, explicit, and auditable.
