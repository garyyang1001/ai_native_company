---
name: installing-antigravity-skills
description: Use when installing, moving, or verifying custom SKILL.md skills for Google Antigravity in a project or globally.
---

# Installing Antigravity Skills

Use this skill when a custom skill must be available to Antigravity through its actual skill discovery system.

## Core Rule

Do not accept "manually readable" as installed. A skill is installed only when Antigravity can discover it from a supported skill directory and a new conversation can load its `SKILL.md`.

## Supported Locations

Use the current Antigravity skill locations:

- Project scope: `<workspace-root>/.agents/skills/<skill-folder>/SKILL.md`
- Global scope: `~/.gemini/antigravity/skills/<skill-folder>/SKILL.md`

Prefer project scope for repo-specific workflows. It keeps the skill with the project and avoids relying on global discovery behavior.

## Install Checklist

1. Inspect the source skill shape first. Confirm it has a `SKILL.md` with YAML frontmatter and a clear `description`.
2. Copy the full skill folder, including `references/`, `scripts/`, `examples/`, or `assets/` if present.
3. For project installs, place it under `.agents/skills/<skill-folder>/`.
4. Verify with:

```bash
npx skills list -a antigravity --json
```

5. Confirm the output shows the expected skill with:

- `scope`: `project` or `global`
- `agents`: includes `Antigravity`
- `path`: points to the intended directory

6. Open a new Antigravity conversation in the target project and run a read-only capability check asking the agent to use the skill without a pasted filesystem path.
7. Accept the install only if Antigravity says the skill was available and loaded `SKILL.md`.

## Capability Check Prompt

```text
Capability check only. Do not edit files. Use the <skill-name> skill if it is available from this workspace skill context. Do not manually search the filesystem or use a pasted path. Reply in one line: whether <skill-name> was available as a skill, whether you loaded its SKILL.md, and one exact marker from that skill.
```

## Common Mistakes

- Putting a skill in a directory Antigravity does not scan.
- Testing by telling Antigravity the absolute path, which only proves the file is readable.
- Forgetting that existing conversations may not refresh the skill list.
- Copying only `SKILL.md` while leaving required references or templates behind.
- Treating `npx skills list -g` as project verification. Use project listing from the workspace when the skill is project-scoped.

