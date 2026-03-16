#!/usr/bin/env python3
"""Run a debate using JSON state as the canonical source of truth."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from debate_state import (
    append_turn,
    clear_runner,
    clear_typing,
    conclude_debate,
    load_debate,
    paired_paths,
    pop_pending_note,
    save_debate,
    set_typing,
    touch_runner,
    validate_state,
)


def extract_json(text: str) -> dict[str, object]:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = next((part for part in parts if "{" in part), text)
        text = text[text.find("{") :]
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError(f"expected JSON object, got: {text[:200]}")
        text = text[start : end + 1]
    return json.loads(text)


def transcript_text(state: dict, include_operator: bool = False) -> str:
    turns = state["turns"] if include_operator else [turn for turn in state["turns"] if turn["speaker"] != "Operator"]
    if not turns:
        return "(no turns yet)"
    return "\n\n".join(f"Turn {turn['id']} - {turn['speaker']}\n{turn['text']}" for turn in turns)


def latest_moderator_text(state: dict) -> str:
    for turn in reversed(state["turns"]):
        if turn["speaker"] == "Moderator":
            return turn["text"]
    return ""


def referenced_paths(text: str) -> list[str]:
    matches = re.findall(r"/[^\s`]+", text)
    seen: set[str] = set()
    paths: list[str] = []
    for match in matches:
        cleaned = match.rstrip(".,:;)]}")
        if cleaned not in seen:
            seen.add(cleaned)
            paths.append(cleaned)
    return paths


def read_path_block(path_str: str) -> str:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = path.resolve()
    if not path.exists():
        return f"Path: {path}\nStatus: missing"
    if path.is_dir():
        entries = sorted(item.name for item in path.iterdir())
        preview = "\n".join(f"- {name}" for name in entries[:50])
        suffix = "\n- ..." if len(entries) > 50 else ""
        return f"Path: {path}\nStatus: directory\nEntries:\n{preview}{suffix}"
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"Path: {path}\nStatus: binary or non-utf8 file; not inlined"
    return f"Path: {path}\nStatus: file\nContents:\n```text\n{content.rstrip()}\n```"


def materialize_context(context: str) -> str:
    paths = referenced_paths(context)
    if not paths:
        return context
    blocks = "\n\n".join(read_path_block(path) for path in paths)
    return f"""{context}

Resolved local material:
{blocks}"""


class CodexInterrupted(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        process.wait(timeout=5)


def run_codex(prompt: str, workdir: Path, use_search: bool, debate_path: Path, baseline_note: str) -> str:
    with tempfile.TemporaryDirectory(prefix="agents-debate-") as temp_dir:
        output_path = Path(temp_dir) / "last_message.txt"
        json_path, markdown_path = paired_paths(debate_path)
        cmd = ["codex"]
        if use_search:
            cmd.append("--search")
        cmd.extend(
            [
                "exec",
                "--skip-git-repo-check",
                "--color",
                "never",
                "--output-last-message",
                str(output_path),
                "-C",
                str(workdir),
                "--",
                prompt,
            ]
        )
        result = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        last_heartbeat = 0.0
        while result.poll() is None:
            state = load_debate(debate_path)
            current_note = str(state["state"].get("pending_note", "")).strip()
            if state["state"].get("paused"):
                terminate_process(result)
                raise CodexInterrupted("paused")
            if current_note != baseline_note:
                terminate_process(result)
                raise CodexInterrupted("note_updated")
            now = time.monotonic()
            if now - last_heartbeat >= 1.0:
                state = touch_runner(state, os.getpid(), "thinking")
                save_debate(state, json_path, markdown_path)
                last_heartbeat = now
            time.sleep(0.5)
        stdout, stderr = result.communicate()
        if result.returncode != 0:
            raise RuntimeError((stderr or "").strip() or (stdout or "").strip() or "codex exec failed")
        return output_path.read_text(encoding="utf-8").strip()


def moderator_prompt(state: dict, max_rounds: int) -> str:
    pending_note = str(state["state"].get("pending_note", "")).strip()
    operator_block = "No live operator note."
    if pending_note:
        operator_block = f"""There is a live operator note waiting for you. Your very next action MUST follow this note before any normal debate flow.
- Do not ignore it.
- Do not continue the old line of discussion unchanged.
- Adapt your moderation plan, next speaker choice, or conclusion to reflect it.
- Do not mention the operator note, hidden instructions, or any meta-process in `turn_text`.
- `turn_text` must read like a normal moderator message visible to users.
- The note is control input, not part of the visible chat response.

Live operator note:
{pending_note}
"""
    debaters = "\n".join(
        f"- {debater['name']}: {debater['stance']}; {debater['role']}" for debater in state["debaters"]
    )
    return f"""SYSTEM INSTRUCTIONS:
You are the Moderator for a structured debate.

Return JSON only with this schema:
{{
  "status": "continue" | "end",
  "next_speaker": "one declared debater or Moderator",
  "advance_round": true | false,
  "reason": "why this speaker or why the debate should end",
  "turn_text": "the moderator text to append to the transcript",
  "conclusion": "required only when status is end"
}}

Operator control layer:
{operator_block}

Choose exactly one next speaker when continuing. End when arguments have converged, no materially new points are appearing, or the configured round limit has effectively been reached.
If an operator note is present, satisfying it takes priority over the default flow.

USER CONTEXT:

Topic:
{state['topic']}

Debaters:
{debaters}

Moderator instructions:
{state['moderator']['instructions']}

Rules:
{json.dumps(state['rules'], indent=2)}

Current state:
{json.dumps(state['state'], indent=2)}

Max rounds:
{max_rounds}

Transcript:
{transcript_text(state)}
"""


def debater_prompt(state: dict, debater: dict) -> str:
    context = str(debater["context"]).strip()
    materialized_context = materialize_context(context)
    return f"""You are the debater "{debater['name']}" in a structured debate.

Return only the next debate turn text. Do not include JSON, markdown headings, or meta commentary.
Use the material in your private context below as your evidence base. Treat any inlined local file contents as authoritative project context.

Topic:
{state['topic']}

Your stance:
{debater['stance']}

Your role:
{debater['role']}

Your private context:
{materialized_context}

Rules:
{json.dumps(state['rules'], indent=2)}

Latest moderator instruction:
{latest_moderator_text(state) or "(none yet)"}

Transcript:
{transcript_text(state)}
"""


def resolve_turn_budget(state: dict, requested: int | None) -> int:
    if requested is not None:
        return requested
    max_rounds = int(state["rules"].get("max_rounds", "6"))
    return max(24, 2 + len(state["debaters"]) * max_rounds * 2)


def run_loop(path: Path, use_search: bool) -> None:
    json_path, markdown_path = paired_paths(path)
    state = load_debate(path)
    errors = validate_state(state)
    if errors:
        raise ValueError("; ".join(errors))
    save_debate(state, json_path, markdown_path)


def run_debate(path: Path, use_search: bool, max_turns: int | None) -> None:
    json_path, markdown_path = paired_paths(path)
    state = load_debate(path)
    errors = validate_state(state)
    if errors:
        raise ValueError("; ".join(errors))
    state = touch_runner(state, os.getpid(), "idle")
    save_debate(state, json_path, markdown_path)

    state = load_debate(json_path)
    turn_budget = resolve_turn_budget(state, max_turns)
    if turn_budget == 0:
        save_debate(state, json_path, markdown_path)
        return
    max_rounds = int(state["rules"].get("max_rounds", "6"))

    turns_completed = 0
    while turns_completed < turn_budget:
        state = load_debate(json_path)
        if state["state"]["status"] == "complete":
            state = clear_runner(state)
            save_debate(state, json_path, markdown_path)
            return
        if state["state"].get("paused"):
            state = touch_runner(state, os.getpid(), "paused")
            save_debate(state, json_path, markdown_path)
            time.sleep(1)
            continue
        state = touch_runner(state, os.getpid(), "idle")
        save_debate(state, json_path, markdown_path)

        if state["state"]["next_speaker"] == "Moderator":
            baseline_note = str(state["state"].get("pending_note", "")).strip()
            state = set_typing(state, "Moderator")
            state = touch_runner(state, os.getpid(), "thinking")
            save_debate(state, json_path, markdown_path)
            try:
                decision = extract_json(
                    run_codex(moderator_prompt(state, max_rounds), json_path.parent, use_search, json_path, baseline_note)
                )
            except CodexInterrupted:
                state = clear_typing(load_debate(json_path))
                state = touch_runner(state, os.getpid(), "idle")
                save_debate(state, json_path, markdown_path)
                continue
            state = load_debate(json_path)
            if state["state"].get("paused") or str(state["state"].get("pending_note", "")).strip() != baseline_note:
                state = clear_typing(state)
                state = touch_runner(state, os.getpid(), "idle")
                save_debate(state, json_path, markdown_path)
                continue
            state, _ = pop_pending_note(state)
            status = str(decision.get("status", "")).strip()
            turn_text = str(decision.get("turn_text", "")).strip() or str(decision.get("reason", "")).strip()
            advance_round = bool(decision.get("advance_round"))
            if status == "continue":
                next_speaker = str(decision.get("next_speaker", "")).strip()
                state = append_turn(state, "Moderator", turn_text, next_speaker, advance_round=advance_round)
                state = touch_runner(state, os.getpid(), "idle")
                save_debate(state, json_path, markdown_path)
                turns_completed += 1
                continue
            if status == "end":
                state = append_turn(state, "Moderator", turn_text, "Moderator", advance_round=advance_round)
                state = conclude_debate(state, str(decision.get("conclusion", "")).strip())
                state = clear_runner(state)
                save_debate(state, json_path, markdown_path)
                return
            raise ValueError(f"invalid moderator status: {status}")

        debater = next(
            (item for item in state["debaters"] if item["name"] == state["state"]["next_speaker"]),
            None,
        )
        if debater is None:
            raise ValueError(f"unknown next speaker: {state['state']['next_speaker']}")
        baseline_note = str(state["state"].get("pending_note", "")).strip()
        state = set_typing(state, debater["name"])
        state = touch_runner(state, os.getpid(), "thinking")
        save_debate(state, json_path, markdown_path)
        try:
            turn_text = run_codex(debater_prompt(state, debater), json_path.parent, use_search, json_path, baseline_note)
        except CodexInterrupted as exc:
            state = clear_typing(load_debate(json_path))
            if exc.reason == "note_updated" and state["state"]["status"] != "complete":
                state["state"]["next_speaker"] = "Moderator"
            state = touch_runner(state, os.getpid(), "idle")
            save_debate(state, json_path, markdown_path)
            continue
        state = load_debate(json_path)
        if (
            state["state"].get("paused")
            or str(state["state"].get("pending_note", "")).strip() != baseline_note
            or state["state"].get("next_speaker") != debater["name"]
        ):
            state = clear_typing(state)
            if str(state["state"].get("pending_note", "")).strip() and state["state"]["status"] != "complete":
                state["state"]["next_speaker"] = "Moderator"
            state = touch_runner(state, os.getpid(), "idle")
            save_debate(state, json_path, markdown_path)
            continue
        state = append_turn(state, debater["name"], turn_text, "Moderator")
        state = touch_runner(state, os.getpid(), "idle")
        save_debate(state, json_path, markdown_path)
        turns_completed += 1

    state = clear_runner(load_debate(json_path))
    save_debate(state, json_path, markdown_path)
    raise RuntimeError(f"debate did not complete within {turn_budget} turns")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="Path to a debate .json or .md file")
    parser.add_argument("--no-search", action="store_true")
    parser.add_argument("--max-turns", type=int)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    run_debate(Path(args.path), use_search=not args.no_search, max_turns=args.max_turns)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
