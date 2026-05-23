# Install

This repo is not a normal app.

You do not install it like software.

You give it to an AI agent, and the agent uses the files here to interview you and build your creative brain.

## Fastest way

Clone the repo:

```bash
git clone https://github.com/prathamcreates/creative-brain.git
cd creative-brain
```

Then open this folder in your agent and say:

```txt
help me install this and build my creative brain
```

The agent should read `README.md` and `AGENTS.md`, then start interviewing you.

## If you use Claude Code

Clone the repo:

```bash
git clone https://github.com/prathamcreates/creative-brain.git
cd creative-brain
```

Start Claude Code in the folder:

```bash
claude
```

Then paste:

```txt
Read README.md and AGENTS.md. Help me install this and build my creative brain.
```

## If you use Cursor

1. Clone or download this repo.
2. Open the folder in Cursor.
3. Open Cursor chat.
4. Paste:

```txt
Read README.md and AGENTS.md. Help me install this and build my creative brain.
```

## If you use Hermes

Point Hermes at this folder or ask it to work inside the folder, then say:

```txt
Read README.md and AGENTS.md. Interview me and build my creative brain.
```

## If you do not use coding agents

You can still use the repo manually:

1. Open `prompts/01-interview-user.md`.
2. Answer the interview questions.
3. Copy the files from `templates/creative-brain/` into `outputs/creative-brain/`.
4. Fill them in from your answers.
5. Use `feedback-memory.md` to keep improving the brain.

## What should happen after install

The agent should create:

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

Then it should ask you what felt right/wrong and update the brain from your feedback.

## Troubleshooting

### The agent starts writing content immediately

Stop it and say:

```txt
Do not generate content yet. First interview me and build my creative brain using AGENTS.md.
```

### The output sounds generic

Tell it:

```txt
This sounds generic. Ask me more specific questions about my taste, references, voice, and what I hate.
```

### The agent does not create files

Tell it:

```txt
Create the files under outputs/creative-brain/ using the templates in templates/creative-brain/.
```
