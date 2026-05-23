---
name: claude-review
description: Use when Gary asks Codex to get a second-opinion Claude review through Terminal or Claude Code before accepting, committing, or merging repo changes
---

# Claude Review

Use Claude as a second-opinion reviewer, not as the owner of the change. Codex remains responsible for deciding whether findings are valid.

## When to Use

- After Antigravity or another executor changes code, contracts, tests, or architecture docs.
- Before committing or merging substantial repo changes.
- When a diff may contradict the project contract, agent workflow, security boundary, or tests.
- When Gary explicitly asks for Claude review, Claude Code, `claude agents`, or Terminal-based second opinion.

## Preferred Terminal Flow

Gary's default workflow is terminal-first:

1. Start Claude agents in a terminal:

   ```bash
   claude agents --dangerously-skip-permissions
   ```

2. Wait until the Claude agents TUI is ready.
3. Enter the read-only review prompt into the running TUI.
4. Submit the task from inside the TUI.
5. Monitor status from another terminal when needed:

   ```bash
   claude agents --json --cwd "<repo-path>"
   ```

6. Attach through the TUI to inspect the result.

Do not pass `--model`; Gary expects the Claude Code default model to be Opus 4.7.

## Commands

Start the interactive/background agents TUI:

```bash
claude agents --dangerously-skip-permissions
```

Monitor live Claude agent sessions:

```bash
claude agents --json --cwd "<repo-path>"
```

Use this non-interactive form when Codex needs stable captured output:

```bash
claude --print --dangerously-skip-permissions "<read-only review prompt>"
```

This `--print` form is a fallback for machine-readable capture, not the default Gary workflow.

## Review Prompt Pattern

Keep Claude read-only and scoped:

```text
You are a read-only code reviewer. In <repo-path>, review the current uncommitted diff.
Do not edit files and do not commit.
Focus on bugs, contradictions with <contract/docs>, and missing tests.
Return findings only with file/line references if any; if none, say no findings.
```

For architecture docs, name the governing contract explicitly, for example `docs/company-data-contract-v0.md`.

## Operating Rules

- Do not let Claude edit, stage, commit, push, or merge during review.
- Do not pass `--model sonnet`. Use the Claude Code default model, which Gary expects to be Opus 4.7.
- Prefer the terminal-first `claude agents --dangerously-skip-permissions` flow for Gary's normal Claude review.
- Use `claude --print` only when the TUI output cannot be captured reliably or Codex needs deterministic text output for audit.
- In the agents TUI, submit a background task with Enter/carriage return; plain newline may only insert text.
- If a background session cannot be resumed with `--resume`, attach through the TUI or rerun the same review with `claude --print`.
- Close the interactive TUI before finishing the Codex turn.
- Do not kill unrelated Claude agents. Check `claude agents --json --cwd "<repo-path>"` or `ps` before terminating anything.

## Codex Acceptance Gate

Treat Claude output as evidence, not authority:

1. Re-check every finding against `git diff`, file contents, and the governing docs.
2. Classify each item as valid, invalid, already known, or out of scope.
3. Fix only valid in-scope issues, or report blockers clearly to Gary.
4. Run the relevant checks again before claiming the branch is ready.

Known behavior: `claude agents --json` is useful for session status, but background-agent output retrieval can be awkward. `claude --print` is the reliable path for machine-readable review output.
