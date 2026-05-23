# Antigravity Supervision Workflow

This document defines how Codex should use Google Antigravity as an execution assistant for this repository.

Antigravity is useful because it can run a parent agent with parallel subagents. In this repo, that capability should be used for bounded execution and review, not for uncontrolled architecture expansion.

## 1. Role Split

```text
Codex
  Plans the work, writes the checklist, limits scope, monitors Antigravity, reviews output, runs verification, and commits.

Antigravity
  Executes the specific task brief given by Codex. It may use subagents for isolated research, mapping, and review.
```

Codex remains responsible for final acceptance. Antigravity reports are evidence, not completion proof.

## 2. Default Task Shape

Codex should give Antigravity a task brief with:

- working repo path
- files it may read
- files it may edit
- files it must not touch
- whether commits are allowed
- expected output format
- required subagent roles
- verification it should run

Antigravity should read `AGENTS.md` first in every new repo conversation.

## 3. Subagent Usage

For architecture and documentation work, Antigravity subagents should usually be read-only reviewers:

```text
Contract Mapper
  Reads canonical source documents and extracts fields, enums, and constraints.

Structure Reviewer
  Checks whether a proposed document structure matches the repo direction and boundaries.

Risk Gate Reviewer
  Checks review, sandbox, human approval, retention, cleanup, and failure-update rules.

Consistency Reviewer
  Compares a draft against source docs and flags contradictions or missing requirements.
```

Do not ask multiple Antigravity subagents to edit the same file in the same working tree. Use one writer plus read-only reviewers. If real parallel edits are required, use isolated worktrees or separate files with a later integration pass.

## 4. Memory And Trace Policy

Antigravity conversation history is not a source of truth for the company operating system.

Important durable knowledge must be promoted into repo-controlled artifacts:

- `AGENTS.md` for repo-level agent operating rules
- `docs/*.md` for architecture contracts and workflow decisions
- `tracking/*.md` for implementation state
- commits for accepted changes

Subagent outputs should be summarized into the controlling Codex review or a repo document only when they affect future work. Raw Antigravity chats, temporary subagent logs, and one-off analysis should not be treated as long-term memory.

If an Antigravity finding changes how agents should operate, capture it as one of:

- an update to `AGENTS.md`
- a new or updated architecture document
- a future Memory Candidate once the Memory & Cleanup Kernel exists

## 5. Verification Rules

After Antigravity reports completion, Codex must independently verify:

```bash
git status --short
git diff
```

For code changes, run the relevant tests before accepting the result. For documentation-only changes, inspect the diff and check consistency with `docs/company-data-contract-v0.md`.

Antigravity should not commit. Codex commits after review.

## 6. Prompt Template

```text
Read `AGENTS.md` first.

You are the executor. Codex is the controller and reviewer.

Working repo: `/Volumes/Hermes System/HermesArchive/Gary`

Task:
<specific task>

Scope:
- May read: <files>
- May edit: <files>
- Must not touch: credentials, auth files, runtime logs, production DBs, unrelated files
- Do not commit.

Subagents:
<role list and whether each is read-only>

Return:
- changed files
- subagent names/ids/states if visible
- summary of work
- verification performed
- blockers
```

