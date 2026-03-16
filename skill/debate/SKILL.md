---
name: debate
description: Run structured multi-agent debates from a markdown or JSON debate file using the agents-debate project runtime. Use when Codex needs to normalize legacy debate markdown, keep JSON as the canonical state, run the moderator/debater loop end-to-end, and automatically start a live local web viewer for the debate.
---

# Debate

Use the agents-debate project runtime instead of embedding debate logic in the skill itself.

## Runtime

Repository root for this installed skill: `{{AGENTS_DEBATE_ROOT}}`.

Normalize a debate file:

```bash
python3 {{AGENTS_DEBATE_ROOT}}/runtime/debate_state.py normalize /path/to/debate.md
```

For a markdown source such as `debate.md`, normalization writes `debate.json` plus `debate.normalized.md`, leaving the original source markdown unchanged.

Start the viewer server before running the debate:

```bash
python3 {{AGENTS_DEBATE_ROOT}}/runtime/serve_viewer.py --path /path/to/debate.json
```

Run the debate:

```bash
python3 {{AGENTS_DEBATE_ROOT}}/runtime/run_debate.py /path/to/debate.md
```

## Expectations

- Use `*.json` as the source of truth.
- Keep `*.md` as a rendered export.
- Let the runtime serialize the debate loop and state updates.
- Start the viewer server automatically whenever you run a debate through this skill.
- If the viewer server is started, tell the user to open `http://127.0.0.1:8765/`.
- Tell the user the exact JSON path being served.
- Use the viewer for live monitoring instead of parsing markdown manually when a visual timeline helps.
