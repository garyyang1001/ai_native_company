# Handoff: Private Development Continues In Gary

Date: 2026-05-23

## Current Decision

Continue active development in the private repository:

```text
/Volumes/Hermes System/HermesArchive/Gary
git@github.com:garyyang1001/Gary.git
visibility: PRIVATE
```

Use the public repository only as a clean publication surface:

```text
/Volumes/Hermes System/HermesArchive/AI-Native-Company
git@github.com:garyyang1001/ai-native-company.git
visibility: PUBLIC
```

## What Happened

- The old `Gary` repository was temporarily public, scanned, cleaned, and then set back to private.
- A new clean public repository was created at `garyyang1001/ai-native-company`.
- The public repository was created from a curated file snapshot, not by copying old Git history.
- The old `Gary` repository remains the source for private development and historical context.
- The public `ai-native-company` repository is for redacted, public-safe releases.

## Important Commits And URLs

Private repository:

- `d56d34c Launch AI Native Company public kernel`
- GitHub: `https://github.com/garyyang1001/Gary`

Public repository:

- `ff83fe8 Initial AI Native Company public kernel`
- GitHub: `https://github.com/garyyang1001/ai-native-company`

## Public Repo Contents

The public repository intentionally includes only the clean core:

- `README.md`
- `AGENTS.md`
- `closed_loop_kernel/`
- `tests/`
- `spec/`
- `data/agent-profile-registry-v0.json`
- `docs/company-data-contract-v0.md`
- `docs/agent-profile-registry-v0.md`
- `references/ohya-seo-architecture/SNAPSHOT.md`
- `.gitleaks.toml`
- `.github/workflows/security-scan.yml`

It intentionally excludes local work summaries, Antigravity local prompts, internal bot names, local absolute paths, and operational/private research files.

## Security State

Both repositories have secret scanning and push protection enabled where GitHub supports it.

The public repository also has:

- protected `main`
- required `gitleaks` check
- force push disabled
- branch deletion disabled
- linear history enabled

The old private repository is not meant to be a public-safe history. Treat it as internal.

## Development Rule Going Forward

Use this split:

```text
Gary private repo
  real development, drafts, internal notes, work-in-progress architecture

ai-native-company public repo
  curated contracts, kernel prototype, tests, public-safe docs, redacted examples
```

Do not automatically mirror all private changes into the public repository. Publish only curated snapshots.

## Recommended Next Session

Start in:

```bash
cd "/Volumes/Hermes System/HermesArchive/Gary"
git status --short --branch
```

Then create a short-lived branch for the next development task:

```bash
git switch -c codex/<short-task-name>
```

Suggested skills for the next session:

- `handoff` if more context must be transferred again.
- `test-driven-development` for code or validator changes.
- `verification-before-completion` before any commit or merge.
- `receiving-code-review` if GitHub/Codex review comments appear.
- `antigravity-supervisor` only if Antigravity is used as a bounded executor.

## Open Questions

- Whether the private repo should keep all internal docs as-is or get a private-only cleanup pass.
- Whether future public releases should be manual snapshots or scripted exports.
- Whether `ai-native-company` should receive a `PUBLICATION_POLICY.md` that defines what can be copied from private to public.
