# Creative Brain

A repo your agent can run to build your personal creative brain.

Clone this repo, give it to Claude Code / Hermes / Cursor / OpenClaw, and tell it:

```txt
Use this repo to interview me and build my creative brain.
```

The agent will interview you about your taste, voice, references, work, and creative instincts, then create a structured markdown brain it can use before writing, designing, brainstorming, or planning for you.

## Why this exists

Most people ask AI to create from zero.

That is why the output feels generic.

A creative brain gives your agent context before it starts making things:

- what you make
- what you sound like
- what feels corny to you
- what references shape your taste
- what kind of output feels alive vs dead
- what you are building right now
- what feedback should change next time

The point is not more prompts.

The point is giving your agent a brain to work from.

## Who this is for

This is for creatives, builders, creators, designers, editors, writers, operators, and internet people who want AI to understand their taste instead of sounding like a random productivity account.


## Install / quickstart

If you just want to use it, read [`INSTALL.md`](INSTALL.md).

Fastest prompt after cloning:

```txt
help me install this and build my creative brain
```

## How to use

### Option 1 — with Claude Code / Cursor / OpenClaw

1. Clone or download this repo.
2. Open it in your coding agent.
3. Paste this:

```txt
Read README.md and AGENTS.md. Follow the protocol and interview me to build my creative brain inside outputs/creative-brain/.
```

### Option 2 — with Hermes or any chat agent that can edit files

Give the agent this repo and say:

```txt
Use the prompts in this repo to interview me. Build my creative brain using the templates. Save the final files under outputs/creative-brain/.
```

## What gets created

Your agent should create:

```txt
outputs/creative-brain/
  README.md
  identity.md
  voice.md
  taste.md
  anti-slop.md
  references.md
  content-system.md
  ideas.md
  current-state.md
  feedback-memory.md
```

## The loop

```txt
interview → draft brain → feedback → update memory → use brain for future work
```

The first version will not be perfect.

That is the point.

Every time you approve, reject, or edit output, your agent should update `feedback-memory.md` so your creative brain gets sharper.

## Repo structure

```txt
prompts/       agent prompts and run instructions
templates/     blank files the agent copies/fills
examples/      example creative brain fragments
outputs/       where your generated creative brain lives
```

## Important rule

Do not let the agent skip the interview.

If it writes before understanding your taste, it will probably produce slop.
