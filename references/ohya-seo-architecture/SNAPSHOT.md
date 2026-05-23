# OHYA SEO Architecture Snapshot

Redacted on: 2026-05-23

This reference is intentionally reduced to a public-safe architecture note.
The original executable snapshot was removed from this public repository because
it contained local paths, tool names, credential filenames, and operational
details that are not needed for the Gary company kernel.

## Public-Safe Reference

This file records only the reusable pattern:

- A department coordinator assigns bounded work to profile-specific agents.
- Profile agents produce durable task records, source references, artifact
  references, and reviewable machine records.
- Human approval gates sit before publishing, production writes, account changes,
  or profile updates.
- Generated artifacts and operational logs are not company memory by default.
  They become memory candidates only after review, deduplication, scope
  assignment, and cleanup eligibility checks.
- Local paths, credential filenames, platform secrets, runtime databases, and
  client-specific implementation details do not belong in a public reference.

## Removed From Git Tracking

The public repo no longer tracks the previous executable snapshot contents:

- command scripts
- profile SOUL files
- schema migrations
- workflow templates
- helper libraries
- local runbooks
- environment variable names
- credential file paths
- runtime database references

## Notes For Adaptation

- Use this only as a pattern note.
- Do not restore client-specific files into this public repository.
- If a richer reference is needed, keep it in a private workspace and publish only
  redacted contracts or diagrams.
