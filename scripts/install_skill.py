#!/usr/bin/env python3
"""Install the repo-owned debate skill into a local Codex skills directory."""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".py", ".txt", ".json"}


def replace_placeholders(path: Path, project_root: Path) -> None:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return
    text = path.read_text(encoding="utf-8")
    text = text.replace("{{AGENTS_DEBATE_ROOT}}", str(project_root))
    path.write_text(text, encoding="utf-8")


def install(skill_name: str, skills_dir: Path) -> Path:
    project_root = repo_root()
    template_dir = project_root / "skill" / skill_name
    if not template_dir.exists():
        raise FileNotFoundError(f"missing template skill: {template_dir}")

    destination = skills_dir / skill_name
    if destination.exists():
        shutil.rmtree(destination, ignore_errors=True)
    if destination.exists():
        for path in sorted(destination.rglob("*"), reverse=True):
            if path.is_file() or path.is_symlink():
                path.unlink()
            elif path.is_dir():
                os.rmdir(path)
        os.rmdir(destination)
    shutil.copytree(template_dir, destination)

    for path in destination.rglob("*"):
        if path.is_file():
            replace_placeholders(path, project_root)
            if path.suffix.lower() == ".py":
                path.chmod(0o755)

    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-name", default="debate")
    parser.add_argument("--skills-dir", default=str(Path.home() / ".codex" / "skills"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    destination = install(args.skill_name, Path(args.skills_dir).expanduser())
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
