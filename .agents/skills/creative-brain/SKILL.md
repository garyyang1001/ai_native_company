---
name: creative-brain
description: Use when the user wants to build, update, or use a personal creative brain for voice, taste, anti-slop rules, references, creative direction, writing style, or feedback memory.
---

# Creative Brain

Use this skill to interview the user and build a structured creative brain before writing, designing, brainstorming, or planning on their behalf.

This skill is adapted from `prathamcreates/creative-brain` at commit `663f92db3b5d52e7c0260a575f9a520a821175f9`.

## Core Rule

Do not skip the interview. Do not generate final creative content before understanding the user's taste, voice, references, anti-slop rules, and current work.

## Gary Style Overlay

When writing for Gary, default to Traditional Chinese with Taiwan business and consultant language.

Primary content types:

- presentations
- sales copy
- product planning
- teaching/explainer content
- social posts

Style:

- Keep paragraphs short and point-first.
- Prefer clear bullet structure.
- Use natural spoken phrasing when it improves clarity.
- Sound professional, friendly, logical, and easy to understand.
- Explain knowledge in a way that makes difficult ideas feel clear and usable.
- Present Gary as someone who interprets knowledge well: professional, concrete, approachable, and not trying to sound mysterious.

Important themes:

- AI-native company architecture, concepts, implementation, and validation.
- AI adoption consulting for marketing-led organizations.
- Gary's roles include consultant for 阿玩旅遊, partner with 相信旅遊, and consultant for Study Central.

Avoid:

- `這是...而不是...`
- `這不是...而是...`
- defensive contrast framing
- fake guru language
- long abstract paragraphs
- generic personal-brand wording
- over-polished corporate copy

## Workflow

1. Read `references/README.md` and `references/AGENTS.md` when starting a creative brain session.
2. Interview the user in small rounds. Ask 5-7 questions at a time, not a huge intake form.
3. Start with identity and current work, then cover taste, voice, references, anti-slop rules, workflow, and feedback.
4. Build the creative brain from `references/templates/creative-brain/`.
5. Save or draft the brain under the target project path the user chooses, commonly `outputs/creative-brain/`.
6. Ask for feedback using:

```text
Keep:
Cut:
Rewrite around:
More like:
Less like:
What feels wrong?
What feels most like you?
```

7. Update `feedback-memory.md` with approved lines, rejected patterns, phrases to preserve, phrases/styles to avoid, and what changed after feedback.

## Output Files

The complete creative brain usually includes:

```text
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

## Quality Check

Before finalizing, ask:

- Could this describe anyone?
- Is this grounded in what the user actually said?
- Would this help a future agent sound closer to the user?
- Does this include useful constraints, not just flattering adjectives?
- Did I capture what to avoid?

If the answer is weak, ask more questions instead of polishing generic text.
