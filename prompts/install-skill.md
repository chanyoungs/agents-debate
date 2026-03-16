# Install The Debate Skill

Use this prompt with another coding agent to install the debate skill from this repository in a provider-agnostic way.

```text
Install the `debate` skill from the repository at {{AGENTS_DEBATE_ROOT}}.

Requirements:
- Use the repository's installer if the platform is Codex-compatible:
  - python3 {{AGENTS_DEBATE_ROOT}}/scripts/install_skill.py
- Otherwise adapt the template skill in `skill/debate/` into the destination platform's native skill format.
- Create or update a local skill named `debate`.
- Keep `*.json` as the canonical debate state and `*.md` as a rendered export.
- The skill instructions should tell the agent to:
  - normalize legacy markdown into JSON when needed
  - run debates through the project runtime
  - serve the live viewer through the project runtime
- If the local skill system supports metadata, use:
  - display name: Debate
  - short description: Run live structured agent debates
  - default prompt: Use $debate on /path/to/debate.md
If the destination platform has a native skill format, adapt the template skill instead of copying files mechanically. Preserve the repo-owned runtime structure.
```

Replace `{{AGENTS_DEBATE_ROOT}}` with the absolute repository path before use.
