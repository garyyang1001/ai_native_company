# Agent Instructions

This repository is the working space for turning 好事發生數位有限公司 into an AI-native company operating system.

The current priority is not to build a generic SEO agent and not to copy the OHYA architecture. The priority is to define a small, durable company kernel that lets real agents work while leaving structured records that can be reviewed, verified, cleaned, and reused.

## Current Direction

- Start from real agents and profiles, then collect their traces into the Closed Loop Kernel.
- Every task must preserve structured records for inputs, outputs, sources, artifacts, failures, review, verification, approval, repair, and retention.
- Raw data is not memory. Company memory must be curated, deduplicated, scoped, and eligible for cleanup.
- Profiles must be maintainable: failures can propose profile update candidates, candidates must be sandboxed, reviewed, approved, applied, and old versions archived.
- Growth, SEO, GSC, GA4, social listening, competitor monitoring, YouTube transcript work, and social operations are department applications. They must sit on top of the company contracts.

## Read First

Before changing architecture or docs, read the relevant current files:

- `README.md`
- `docs/company-data-contract-v0.md`
- `docs/hermes-agent-first-architecture.md`
- `docs/2026-05-22-work-summary.md`
- `ai_native_closed_loop_architecture.md`
- `references/ohya-seo-architecture/SNAPSHOT.md`

For the next contract layer, use:

- `docs/company-data-contract-v0.md` as the source contract.
- `docs/agent-profile-registry-v0.md` as the next intended document.

## Boundaries

- Do not treat `references/ohya-seo-architecture/` as code to run or migrate. It is a reference snapshot only.
- Do not import OHYA-specific names, paths, WordPress assumptions, tokens, or runtime data into this repo.
- Do not touch credentials, auth files, live runtime logs, production databases, or Hermes runtime state.
- Do not let one profile execute, review, approve, and apply its own work.
- Do not turn every sub-agent role into a permanent profile. Permanent profiles need a registry entry and clear responsibility.

## Documentation Workflow

- For new architecture documents, first propose design direction and section structure.
- Wait for Gary approval before writing the file.
- Keep documents practical: define records, fields, gates, ownership, lifecycle, and non-goals.
- Prefer small contracts that can later be implemented and tested over broad company-brain essays.
- Keep facts, assumptions, and future plans separate.

## Codex And Antigravity Workflow

- Codex is the controller, planner, reviewer, and committer.
- Antigravity is the bounded executor. It should follow Codex task briefs and should not expand scope by itself.
- Antigravity may use subagents for read-only mapping, review, and consistency checks.
- Do not run multiple Antigravity writers against the same file in the same working tree. Use one writer plus reviewer subagents, or use isolated worktrees when true parallel edits are required.
- Antigravity must not commit unless Gary explicitly asks for that.
- Codex must verify Antigravity output with `git status`, `git diff`, and relevant checks before accepting work.

Detailed operating rules live in `docs/antigravity-supervision-workflow.md`.

## Verification

When code or prototype behavior changes, run the relevant local checks before claiming completion:

```bash
python3 -m unittest discover -s tests
python3 -m closed_loop_kernel.demo
python3 -m closed_loop_kernel.http_app
```

For documentation-only changes, at minimum inspect the diff and verify that the document does not contradict `docs/company-data-contract-v0.md`.
