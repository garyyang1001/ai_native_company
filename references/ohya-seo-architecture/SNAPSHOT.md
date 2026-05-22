# OHYA SEO Architecture Snapshot

Copied on: 2026-05-22

Source:

```text
/Volumes/Hermes System/HermesArchive/HermesRuntime/clients/ohya
```

This folder is a reference snapshot of OHYA's SEO agent architecture. It is here so the Gary repo can study and adapt the pattern for an AI-native SEO department.

It is not a data migration and it is not meant to be executed directly.

## Included

- Root agent instructions: `AGENT.md`, `SOUL.md`, `CLAUDE.md`, `README.md`
- SEO swarm roster: `docs/swarm-roster.md`
- Kanban workflow templates:
  - `kanban/templates/new-article-swarm.template.md`
  - `kanban/templates/audit-swarm.template.md`
- SEO OS schema migrations: `data/seo-os/migrations/`
- Shared helper code: `lib/`
- SEO command scripts: `bin/`
- Profile definitions only: `profiles/*/SOUL.md`

## Excluded

- Runtime sessions, logs, caches, profile homes, and memories
- Kanban database files and generated task data
- Credentials, auth files, tokens, and environment files
- Generated SEO reports, article outputs, media assets, and backups
- Virtual environments, package caches, and repository checkouts

## Notes For Adaptation

- OHYA-specific names, paths, WordPress details, and environment variable names remain in the copied files as reference material.
- Before using this for Gary or 好事發生處, adapt the profiles, paths, policies, and database ownership model.
- The useful pattern is the department shape: one coordinator, multiple profile workers, Kanban tasks, audit events, approval gates, and durable artifacts.
