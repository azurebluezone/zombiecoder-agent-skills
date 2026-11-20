#!/usr/bin/env python3
"""Install the local skill packs as OpenCode native skills.

OpenCode loads a native skill from ``<skills-dir>/<name>/SKILL.md`` where the
frontmatter ``name`` matches the folder and ``description`` is 1-1024
characters. This script copies each ``packs/<slug>/SKILL.md`` to that layout so
the same audited runbooks are available to the host agent without importing the
whole library.

Usage::

    python3 tools/install_opencode_skills.py
    python3 tools/install_opencode_skills.py --dest /tmp/skills
    python3 tools/install_opencode_skills.py --check

The default destination is ``~/.opencode/skills``. The script is idempotent and
prints ``OPENCODE_SKILLS_INSTALLED <count>`` (or
``OPENCODE_SKILLS_PRESENT <count>`` with ``--check``).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packs"
DEFAULT_DEST = Path.home() / ".opencode" / "skills"
SOURCE = "local/zombiecoder-packs"


def frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    data: dict[str, str] = {}
    key = ""
    for line in text[3:end].splitlines():
        if not line.strip():
            continue
        if line[:1] in (" ", "\t") and key:
            data[key] = (data.get(key, "") + " " + line.strip()).strip()
            continue
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        key = name.strip().lower()
        data[key] = value.strip().strip("\"'")
    return data


def discover() -> list[Path]:
    return sorted(
        path for path in PACKS.glob("*/SKILL.md") if path.parent.is_dir()
    )


def validate(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    meta = frontmatter(text)
    slug = path.parent.name
    name = str(meta.get("name") or "").strip()
    description = str(meta.get("description") or "").strip()
    problems: list[str] = []
    if name != slug:
        problems.append(f"frontmatter name is {name!r}, folder is {slug!r}")
    if not 1 <= len(description) <= 1024:
        problems.append(f"description length is {len(description)}, expected 1..1024")
    if "\n" in description:
        problems.append("description contains a newline")
    if str(meta.get("source") or "") != SOURCE:
        problems.append(f"source is {meta.get('source')!r}, expected {SOURCE!r}")
    if str(meta.get("license") or "") != "MIT":
        problems.append(f"license is {meta.get('license')!r}, expected 'MIT'")
    if problems:
        raise SystemExit(f"{path}: " + "; ".join(problems))
    return slug, text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", default=os.environ.get("OPENCODE_SKILLS_DIR", str(DEFAULT_DEST)))
    parser.add_argument("--check", action="store_true", help="verify the installed copies only")
    args = parser.parse_args()

    dest = Path(args.dest).expanduser()
    files = discover()
    if not files:
        print(f"FAIL: no packs found under {PACKS}")
        return 1

    failures: list[str] = []
    installed = 0
    for path in files:
        slug, text = validate(path)
        target = dest / slug / "SKILL.md"
        if args.check:
            if not target.is_file():
                failures.append(f"missing {target}")
                continue
            if target.read_text(encoding="utf-8") != text:
                failures.append(f"outdated {target}")
                continue
            installed += 1
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and target.read_text(encoding="utf-8") == text:
            print(f"unchanged {slug} -> {target}")
            installed += 1
            continue
        temporary = target.with_suffix(".md.tmp")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, target)
        print(f"installed {slug} -> {target}")
        installed += 1

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1

    if args.check:
        print(f"destination {dest}")
        print(f"OPENCODE_SKILLS_PRESENT {installed}")
    else:
        print(f"destination {dest}")
        print(f"OPENCODE_SKILLS_INSTALLED {installed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
