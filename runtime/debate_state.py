#!/usr/bin/env python3
"""Load, validate, normalize, and export debate state."""

from __future__ import annotations

import argparse
import json
import re
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


REQUIRED_MARKDOWN_SECTIONS = [
    "Topic",
    "Debaters",
    "Moderator",
    "Rules",
    "State",
    "Transcript",
    "Conclusion",
]
TURN_RE = re.compile(r"^### Turn (\d+) - (.+)$", re.MULTILINE)
VALID_STATUS = {"pending", "running", "complete"}
VISIBLE_SPEAKERS = {"Moderator", "Operator"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(read_text(path))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def parse_kv_bullets(block: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") and ":" in stripped[2:]:
            key, value = stripped[2:].split(":", 1)
            data[key.strip()] = value.strip()
    return data


def split_sections(text: str) -> dict[str, str]:
    if not text.lstrip().startswith("# Debate"):
        raise ValueError("document must start with '# Debate'")
    matches = list(re.finditer(r"^## ([^\n]+)\n", text, re.MULTILINE))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(1).strip()] = text[start:end].strip("\n")
    return sections


def infer_role(name: str) -> str:
    lower = name.lower()
    if lower in {"mac", "macos"}:
        return "Apple platform advocate"
    if lower == "windows":
        return "Microsoft platform advocate"
    if lower == "linux":
        return "Open-source platform advocate"
    if lower in {"iphone", "ios"}:
        return "Apple mobile platform advocate"
    if lower == "android":
        return "Android ecosystem advocate"
    return f"{name} advocate"


def parse_debaters_block(block: str) -> list[dict]:
    debaters: list[dict] = []
    matches = list(re.finditer(r"^### ([^\n]+)\n", block, re.MULTILINE))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(block)
        name = match.group(1).strip()
        raw = block[start:end].strip("\n")
        if "Context:\n" in raw:
            before, after = raw.split("Context:\n", 1)
        elif "Context:" in raw:
            before, after = raw.split("Context:", 1)
        else:
            before, after = raw, ""
        metadata = parse_kv_bullets(before)
        debaters.append(
            {
                "name": name,
                "stance": metadata.get("stance", f"Prefer {name}"),
                "role": metadata.get("role", infer_role(name)),
                "context": after.strip(),
            }
        )
    return debaters


def parse_transcript_block(block: str) -> list[dict]:
    if not block.strip():
        return []
    matches = list(TURN_RE.finditer(block))
    turns: list[dict] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(block)
        turns.append(
            {
                "id": int(match.group(1)),
                "speaker": match.group(2).strip(),
                "role": "moderator" if match.group(2).strip() == "Moderator" else "debater",
                "text": block[start:end].strip(),
                "timestamp": None,
            }
        )
    return turns


def make_state(
    topic: str,
    debaters: list[dict],
    moderator_instructions: str,
    rules: dict[str, str] | None = None,
    state_block: dict[str, str] | None = None,
    turns: list[dict] | None = None,
    conclusion_text: str = "",
) -> dict:
    rules = rules or {
        "max_rounds": "4",
        "response_style": "concise",
        "stop_when": "End when no materially new arguments appear for two moderator checks.",
    }
    state_block = state_block or {"status": "pending", "round": "0", "next_speaker": "Moderator"}
    turns = turns or []
    round_value = int(str(state_block.get("round", "0")))
    status = state_block.get("status", "pending")
    next_speaker = state_block.get("next_speaker", "Moderator")
    return {
        "version": 2,
        "topic": topic,
        "moderator": {"instructions": moderator_instructions},
        "debaters": debaters,
        "rules": deepcopy(rules),
        "state": {
            "status": status,
            "round": round_value,
            "next_speaker": next_speaker,
            "turn_count": len(turns),
            "updated_at": utc_now(),
            "paused": False,
            "pending_note": "",
            "typing_speaker": "",
            "typing_since": None,
            "runner_heartbeat_at": None,
            "runner_pid": None,
            "runner_phase": "idle",
        },
        "turns": turns,
        "conclusion": {
            "text": conclusion_text,
            "timestamp": utc_now() if conclusion_text else None,
        },
    }


def parse_markdown_state(path: Path) -> dict:
    text = read_text(path)
    sections = split_sections(text)
    missing = [section for section in REQUIRED_MARKDOWN_SECTIONS if section not in sections]
    if missing:
        raise ValueError(f"missing sections: {', '.join(missing)}")
    return make_state(
        topic=sections["Topic"].strip(),
        debaters=parse_debaters_block(sections["Debaters"]),
        moderator_instructions=sections["Moderator"].strip(),
        rules=parse_kv_bullets(sections["Rules"]),
        state_block=parse_kv_bullets(sections["State"]),
        turns=parse_transcript_block(sections["Transcript"]),
        conclusion_text=sections["Conclusion"].strip(),
    )


def normalize_legacy_markdown(path: Path) -> dict:
    lines = read_text(path).splitlines()
    topic = ""
    topic_lines: list[str] = []
    debaters: list[dict] = []
    current_name = ""
    current_lines: list[str] = []
    in_debaters = False
    in_topic = False

    def flush() -> None:
        nonlocal current_name, current_lines
        if not current_name:
            return
        context = "\n".join(current_lines).strip()
        debaters.append(
            {
                "name": current_name,
                "stance": f"Prefer {current_name}",
                "role": infer_role(current_name),
                "context": context or f"Argue that {current_name} is the best option.",
            }
        )
        current_name = ""
        current_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# Topic:"):
            topic = stripped.split(":", 1)[1].strip()
            topic_lines = [topic] if topic else []
            in_topic = True
            continue
        if stripped == "## Topic":
            in_topic = True
            topic_lines = []
            continue
        if stripped in {"# Debaters:", "# Debaters", "## Debaters"}:
            in_debaters = True
            in_topic = False
            flush()
            continue
        if in_debaters and re.match(r"^##+\s+", stripped):
            flush()
            current_name = re.sub(r"^##+\s+", "", stripped).strip()
            continue
        if stripped == "# Debate":
            continue
        if in_topic:
            topic_lines.append(line)
            continue
        if in_debaters:
            current_lines.append(line)
        elif not topic and stripped and not stripped.startswith("#"):
            topic = stripped
            topic_lines = [topic]
    flush()

    if topic_lines:
        topic = "\n".join(topic_lines).strip()
    if not topic:
        topic = path.stem.replace("_", " ").strip() or "Debate topic"
    if len(debaters) < 2:
        raise ValueError("could not infer at least two debaters from legacy markdown")

    return make_state(
        topic=topic,
        debaters=debaters,
        moderator_instructions="Keep the debate focused on mainstream users rather than niche power users. Decide who speaks next, when the discussion has converged, and write a practical conclusion grounded in the transcript.",
    )


def load_debate(path: Path) -> dict:
    if path.suffix.lower() == ".json":
        return read_json(path)
    try:
        return parse_markdown_state(path)
    except Exception:
        return normalize_legacy_markdown(path)


def paired_paths(path: Path) -> tuple[Path, Path]:
    if path.suffix.lower() == ".json":
        return path, path.with_suffix(".md")
    normalized_name = path.name if path.name.endswith(".normalized.md") else f"{path.stem}.normalized.md"
    return path.with_suffix(".json"), path.with_name(normalized_name)


def export_markdown(state: dict) -> str:
    lines = ["# Debate", "", "## Topic", state["topic"], "", "## Debaters"]
    for debater in state["debaters"]:
        lines.extend(
            [
                f"### {debater['name']}",
                f"- stance: {debater['stance']}",
                f"- role: {debater['role']}",
                "Context:",
                debater["context"].strip(),
                "",
            ]
        )
    if lines[-1] == "":
        lines.pop()
    lines.extend(["", "## Moderator", state["moderator"]["instructions"].strip(), "", "## Rules"])
    for key, value in state["rules"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## State",
            f"- status: {state['state']['status']}",
            f"- round: {state['state']['round']}",
            f"- next_speaker: {state['state']['next_speaker']}",
            "",
            "## Transcript",
        ]
    )
    for turn in state["turns"]:
        lines.extend([f"### Turn {turn['id']} - {turn['speaker']}", turn["text"].strip(), ""])
    if lines[-1] == "":
        lines.pop()
    lines.extend(["", "## Conclusion", state["conclusion"]["text"].strip()])
    return "\n".join(lines).rstrip() + "\n"


def save_debate(state: dict, json_path: Path, markdown_path: Path | None) -> None:
    state.setdefault("state", {})
    state["state"].setdefault("paused", False)
    state["state"].setdefault("pending_note", "")
    state["state"].setdefault("typing_speaker", "")
    state["state"].setdefault("typing_since", None)
    state["state"].setdefault("runner_heartbeat_at", None)
    state["state"].setdefault("runner_pid", None)
    state["state"].setdefault("runner_phase", "idle")
    state["state"]["turn_count"] = len(state["turns"])
    state["state"]["updated_at"] = utc_now()
    write_json(json_path, state)
    if markdown_path is not None:
        write_text(markdown_path, export_markdown(state))


def validate_state(state: dict) -> list[str]:
    errors: list[str] = []
    if not state.get("topic"):
        errors.append("topic must not be empty")
    debaters = state.get("debaters", [])
    if len(debaters) < 2:
        errors.append("at least two debaters are required")
    names = {debater.get("name", "") for debater in debaters}
    if "" in names:
        errors.append("all debaters must have names")
    if state.get("state", {}).get("status") not in VALID_STATUS:
        errors.append("state.status must be pending, running, or complete")
    paused = state.get("state", {}).get("paused", False)
    if not isinstance(paused, bool):
        errors.append("state.paused must be a boolean")
    pending_note = state.get("state", {}).get("pending_note", "")
    if not isinstance(pending_note, str):
        errors.append("state.pending_note must be a string")
    typing_speaker = state.get("state", {}).get("typing_speaker", "")
    if typing_speaker and typing_speaker not in names | {"Moderator"}:
        errors.append("state.typing_speaker must be empty, Moderator, or a declared debater")
    runner_phase = state.get("state", {}).get("runner_phase", "idle")
    if runner_phase not in {"idle", "thinking", "paused"}:
        errors.append("state.runner_phase must be idle, thinking, or paused")
    next_speaker = state.get("state", {}).get("next_speaker")
    if next_speaker not in names | {"Moderator"}:
        errors.append("state.next_speaker must be Moderator or a declared debater")
    for expected_id, turn in enumerate(state.get("turns", []), start=1):
        if turn.get("id") != expected_id:
            errors.append("turn ids must be sequential starting at 1")
            break
        if turn.get("speaker") not in names | VISIBLE_SPEAKERS:
            errors.append(f"unknown turn speaker: {turn.get('speaker')}")
            break
    conclusion_text = state.get("conclusion", {}).get("text", "")
    if conclusion_text and state["state"]["status"] != "complete":
        errors.append("conclusion requires complete status")
    if state["state"]["status"] == "complete" and not conclusion_text:
        errors.append("complete debates need a conclusion")
    return errors


def append_turn(state: dict, speaker: str, text: str, next_speaker: str, advance_round: bool = False) -> dict:
    updated = deepcopy(state)
    expected = updated["state"]["next_speaker"]
    if updated["state"]["status"] == "complete":
        raise ValueError("cannot append to a completed debate")
    if speaker != expected:
        raise ValueError(f"speaker '{speaker}' is out of turn; expected '{expected}'")
    valid_names = {debater["name"] for debater in updated["debaters"]} | {"Moderator"}
    if next_speaker not in valid_names:
        raise ValueError(f"next speaker '{next_speaker}' is not declared")
    updated["turns"].append(
        {
            "id": len(updated["turns"]) + 1,
            "speaker": speaker,
            "role": "moderator" if speaker == "Moderator" else "debater",
            "text": text.strip(),
            "timestamp": utc_now(),
        }
    )
    updated["state"]["status"] = "running"
    updated["state"]["next_speaker"] = next_speaker
    updated["state"]["typing_speaker"] = ""
    updated["state"]["typing_since"] = None
    if advance_round:
        updated["state"]["round"] += 1
    return updated


def conclude_debate(state: dict, conclusion: str) -> dict:
    updated = deepcopy(state)
    if not updated["turns"] or updated["turns"][-1]["speaker"] != "Moderator":
        raise ValueError("the final turn must come from Moderator before concluding")
    if updated["state"]["next_speaker"] != "Moderator":
        raise ValueError("state.next_speaker must be Moderator before concluding")
    updated["state"]["status"] = "complete"
    updated["state"]["typing_speaker"] = ""
    updated["state"]["typing_since"] = None
    updated["conclusion"]["text"] = conclusion.strip()
    updated["conclusion"]["timestamp"] = utc_now()
    return updated


def clear_typing(state: dict) -> dict:
    updated = deepcopy(state)
    updated["state"]["typing_speaker"] = ""
    updated["state"]["typing_since"] = None
    return updated


def set_paused(state: dict, paused: bool) -> dict:
    updated = deepcopy(state)
    updated["state"]["paused"] = bool(paused)
    if paused:
        updated = clear_typing(updated)
    return updated


def append_operator_note(state: dict, note: str) -> dict:
    updated = deepcopy(state)
    updated["turns"].append(
        {
            "id": len(updated["turns"]) + 1,
            "speaker": "Operator",
            "role": "operator",
            "text": note.strip(),
            "timestamp": utc_now(),
        }
    )
    return updated


def set_pending_note(state: dict, note: str) -> dict:
    updated = append_operator_note(state, note)
    updated["state"]["pending_note"] = note.strip()
    if updated["state"]["status"] != "complete":
        updated["state"]["next_speaker"] = "Moderator"
        updated = clear_typing(updated)
    return updated


def pop_pending_note(state: dict) -> tuple[dict, str]:
    updated = deepcopy(state)
    note = str(updated["state"].get("pending_note", "")).strip()
    updated["state"]["pending_note"] = ""
    return updated, note


def set_typing(state: dict, speaker: str) -> dict:
    updated = deepcopy(state)
    updated["state"]["typing_speaker"] = speaker
    updated["state"]["typing_since"] = utc_now()
    return updated


def touch_runner(state: dict, pid: int | None, phase: str) -> dict:
    updated = deepcopy(state)
    updated["state"]["runner_pid"] = pid
    updated["state"]["runner_phase"] = phase
    updated["state"]["runner_heartbeat_at"] = utc_now()
    return updated


def clear_runner(state: dict) -> dict:
    updated = deepcopy(state)
    updated["state"]["runner_pid"] = None
    updated["state"]["runner_phase"] = "idle"
    updated["state"]["runner_heartbeat_at"] = utc_now()
    return updated


def cmd_validate(args: argparse.Namespace) -> int:
    state = load_debate(Path(args.path))
    errors = validate_state(state)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "topic": state["topic"],
                "debaters": [item["name"] for item in state["debaters"]],
                "status": state["state"]["status"],
                "round": state["state"]["round"],
                "next_speaker": state["state"]["next_speaker"],
                "turns": len(state["turns"]),
            },
            indent=2,
        )
    )
    return 0


def cmd_print_json(args: argparse.Namespace) -> int:
    state = load_debate(Path(args.path))
    print(json.dumps(state, indent=2))
    return 0


def cmd_normalize(args: argparse.Namespace) -> int:
    path = Path(args.path)
    state = load_debate(path)
    errors = validate_state(state)
    if errors:
        raise ValueError("; ".join(errors))
    output = Path(args.output) if args.output else path
    json_path, markdown_path = paired_paths(output)
    save_debate(state, json_path, markdown_path)
    print(str(json_path))
    if markdown_path != json_path:
        print(str(markdown_path))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("path")
    validate_parser.set_defaults(func=cmd_validate)

    json_parser = subparsers.add_parser("print-json")
    json_parser.add_argument("path")
    json_parser.set_defaults(func=cmd_print_json)

    normalize_parser = subparsers.add_parser("normalize")
    normalize_parser.add_argument("path")
    normalize_parser.add_argument("--output")
    normalize_parser.set_defaults(func=cmd_normalize)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
