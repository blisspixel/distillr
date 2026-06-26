# Briefing Context Template

This file is the **input prompt** for `distill research-brief` or `distill synthesize`.
Copy it to a new path, edit it to describe your audience and goal, and pass that
path to `--context-file`.

The conventional place for your own context files is under [`private/`](../../private/)
(e.g. `private/acme-pitch.md`). That folder is git-ignored, so personal or
client-specific contexts never ship. The `--context-file` flag accepts any path,
so you can also keep them elsewhere on disk.

Delete the guidance blockquotes below and replace the placeholders with your
actual content.

---

## Who this briefing is for

> Identify the primary reader. A product manager making a vendor selection? A researcher
> preparing a grant? A solutions architect briefing a customer? The model shapes tone,
> depth, and vocabulary based on this.

**Primary reader:** <who - role, domain expertise, what they already know>

**Goal of the briefing:** <what decision or action this briefing should support>

## Context the model needs to know

> Background the model cannot infer from the corpus alone. Prior decisions, constraints,
> existing architecture, deadlines, stakeholders, budget limits, things that are off-limits.
> Be specific. The model does better with real constraints than with vague directives.

<free-form background section - as short or long as needed>

## What the corpus contains

> Tell the model what kind of material it will find in the File Search corpus (research-brief)
> or concatenated into the prompt (synthesize). This helps it calibrate how to cite.
> For example: "100 academic arXiv papers from 2024-2026 on X, Y, Z."

<one paragraph describing the attached corpus>

## Required structure

> Define the sections you want. Numbered, named, with 1-2 sentences of guidance each.
> More specific guidance per section produces better output than vague section titles.

### 1. <section title>
<one-sentence description of what belongs in this section>

### 2. <section title>
<one-sentence description>

<etc. - typically 5-8 sections>

## Rules

> Standing requirements for the output. Example items:
> - Cite sources inline by title + identifier
> - Use specific claim-strength labels: [Corpus consensus] / [Single paper] / [Contested] / [Interpretation]
> - Prefer specificity over breadth
> - If a section cannot be written from the corpus, say so rather than padding
> - Register and tone appropriate for the primary reader

- <rule 1>
- <rule 2>
- <rule 3>
