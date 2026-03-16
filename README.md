# agents-debate

JSON-backed multi-agent debate workflow with:
- project-owned runtime
- static live web viewer
- installable skill template
- example debate data for testing

## Layout

- `runtime/`: state model, debate controller, and local viewer server
- `viewer/`: static web UI that polls the local API
- `skill/`: installable skill template
- `prompts/`: provider-agnostic install prompt for other coding agents
- `schemas/`: JSON schema for debate state
- `examples/`: test debate data

## Canonical State

`*.json` is the source of truth.

`*.md` is a rendered export for humans and compatibility with the original skill workflow.

## Common Commands

Normalize a markdown debate into JSON + markdown:

```bash
python3 runtime/debate_state.py normalize /path/to/debate.md
```

For a markdown source such as `debate.md`, normalization now writes:
- `debate.json` as canonical state
- `debate.normalized.md` as the rendered normalized markdown

The original markdown source is left unchanged.

Run a debate end-to-end:

```bash
python3 runtime/run_debate.py /path/to/debate.json
```

Serve the live viewer:

```bash
python3 runtime/serve_viewer.py --path /path/to/debate.json
```

Project-owned debate workflow with:
- canonical JSON debate state
- markdown transcript export
- Codex-driven runtime controller
- live local web viewer
- installable `debate` skill template

## Layout

- `runtime/`: controller, state helpers, local viewer server
- `viewer/`: static web UI
- `skill/`: installable skill template
- `prompts/`: provider-agnostic installation prompt
- `schemas/`: JSON schema
- `examples/`: sample debate data

## Run

Normalize or materialize a debate:

```bash
python3 runtime/run_debate.py iphone_vs_android.md --auto-normalize
```

Serve the viewer:

```bash
python3 runtime/serve_viewer.py --path iphone_vs_android.json
```

## Install The Skill

Install the repo-owned `debate` skill into a local Codex skills directory:

```bash
python3 scripts/install_skill.py
```

The installer copies `skill/debate/` into the target skills directory and fills the repository root into the installed wrapper scripts and instructions.
