#!/usr/bin/env python3
"""Install the audited local packs into every supported client's skill folder.

Every editor below reads the portable ``SKILL.md`` layout, but each one looks in
a different directory. This installer copies the same eight packs to the shared
folder (``.agents/skills``), the Claude-compatible folder (``.claude/skills``)
and each client's native folder, then writes one marked index block into
``AGENTS.md`` and ``CLAUDE.md`` for agents that read instruction files instead
of scanning skill directories.

Usage::

    python3 tools/install_client_skills.py --client all --target .
    python3 tools/install_client_skills.py --client cursor --target .
    python3 tools/install_client_skills.py --client all --scope global
    python3 tools/install_client_skills.py --check --client all --target .

The installer is idempotent: unchanged files are reported as ``unchanged`` and
the index block is replaced in place, never duplicated. A successful install
prints ``CLIENT_SKILLS_INSTALLED 8``; ``--check`` prints
``CLIENT_SKILLS_PRESENT 8``. Exit code 1 means at least one path is missing or
outdated.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packs"
SOURCE = "local/zombiecoder-packs"
BLOCK_BEGIN = "<!-- BEGIN zombiecoder-skills -->"
BLOCK_END = "<!-- END zombiecoder-skills -->"
INDEX_FILES = ("AGENTS.md", "CLAUDE.md")
SLUG_RE = re.compile(r"^[a-z0-9-]{1,64}$")

# Project-level paths, verified against the vendor documentation in
# docs/CLIENT-SKILLS.md.
PROJECT_PATHS = {
    "agents": Path(".agents/skills"),
    "claude": Path(".claude/skills"),
    "opencode": Path(".opencode/skills"),
    "cursor": Path(".cursor/skills"),
    "vscode": Path(".github/skills"),
    "windsurf": Path(".devin/skills"),
    "codex": Path(".agents/skills"),
}

# User-level paths, used with --scope global.
GLOBAL_PATHS = {
    "agents": Path.home() / ".agents" / "skills",
    "claude": Path.home() / ".claude" / "skills",
    "opencode": Path.home() / ".config" / "opencode" / "skills",
    "cursor": Path.home() / ".cursor" / "skills",
    "vscode": Path.home() / ".copilot" / "skills",
    "windsurf": Path.home() / ".config" / "devin" / "skills",
    "codex": Path.home() / ".agents" / "skills",
}

CLIENTS = tuple(PROJECT_PATHS)


def frontmatter(text: str) -> dict[str, str]:
    """Parse the flat YAML subset used by the packs (no PyYAML dependency)."""
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


def discover() -> list[tuple[str, str]]:
    """Return ``(slug, text)`` for every pack, sorted by slug."""
    packs: list[tuple[str, str]] = []
    for path in sorted(PACKS.glob("*/SKILL.md")):
        if not path.parent.is_dir():
            continue
        slug = path.parent.name
        text = path.read_text(encoding="utf-8")
        meta = frontmatter(text)
        problems: list[str] = []
        if not SLUG_RE.match(slug):
            problems.append(f"folder {slug!r} is not a valid skill id")
        if str(meta.get("name") or "").strip() != slug:
            problems.append(
                f"frontmatter name is {meta.get('name')!r}, folder is {slug!r}"
            )
        description = str(meta.get("description") or "").strip()
        if not 1 <= len(description) <= 1024:
            problems.append(
                f"description length is {len(description)}, expected 1..1024"
            )
        if "\n" in description:
            problems.append("description contains a newline")
        if str(meta.get("source") or "") != SOURCE:
            problems.append(
                f"source is {meta.get('source')!r}, expected {SOURCE!r}"
            )
        if str(meta.get("license") or "") != "MIT":
            problems.append(f"license is {meta.get('license')!r}, expected 'MIT'")
        if problems:
            raise SystemExit(f"{path}: " + "; ".join(problems))
        packs.append((slug, text))
    if not packs:
        raise SystemExit(f"FAIL: no packs found under {PACKS}")
    return packs


def render_index(packs: list[tuple[str, str]]) -> str:
    lines = [
        BLOCK_BEGIN,
        "## ZombieCoder skills",
        "",
        "Installed by `tools/install_client_skills.py` from `zombiecoder-agent-skills`.",
        "When a task matches a skill, open `.agents/skills/<slug>/SKILL.md` (or the",
        "client's native copy) before acting.",
        "",
    ]
    for slug, text in packs:
        description = str(frontmatter(text).get("description") or "").strip()
        lines.append(f"- **{slug}** — {description}")
    lines.append(BLOCK_END)
    return "\n".join(lines)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def replace_index_block(path: Path, block: str) -> str:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    begin = text.count(BLOCK_BEGIN)
    end = text.count(BLOCK_END)
    if begin == 0 and end == 0:
        prefix = text.rstrip()
        updated = (prefix + "\n\n" if prefix else "") + block + "\n"
    elif begin == 1 and end == 1 and text.index(BLOCK_BEGIN) < text.index(BLOCK_END):
        start = text.index(BLOCK_BEGIN)
        stop = text.index(BLOCK_END) + len(BLOCK_END)
        updated = text[:start] + block + text[stop:]
        if not updated.endswith("\n"):
            updated += "\n"
    else:
        raise SystemExit(
            f"{path}: expected zero or one {BLOCK_BEGIN} ... {BLOCK_END} block, "
            f"found {begin} begin and {end} end marker(s)"
        )
    if path.is_file() and updated == text:
        return "unchanged"
    atomic_write(path, updated)
    return "updated"


def check_index(path: Path, slugs: list[str]) -> list[str]:
    problems: list[str] = []
    if not path.is_file():
        return [f"missing index file: {path}"]
    text = path.read_text(encoding="utf-8")
    if text.count(BLOCK_BEGIN) != 1:
        problems.append(
            f"{path}: expected one {BLOCK_BEGIN}, found {text.count(BLOCK_BEGIN)}"
        )
    if text.count(BLOCK_END) != 1:
        problems.append(
            f"{path}: expected one {BLOCK_END}, found {text.count(BLOCK_END)}"
        )
    if not problems:
        start = text.index(BLOCK_BEGIN)
        stop = text.index(BLOCK_END) + len(BLOCK_END)
        block = text[start:stop]
        for slug in slugs:
            if f"**{slug}**" not in block:
                problems.append(f"{path}: index block is missing {slug}")
    return problems


def destinations(
    clients: list[str], scope: str, target: Path
) -> list[tuple[str, str, Path]]:
    pairs: list[tuple[str, str, Path]] = []
    seen: set[Path] = set()
    for client in clients:
        candidates: list[tuple[str, str, Path]] = []
        if scope in ("project", "both"):
            candidates.append(
                (client, "project", (target / PROJECT_PATHS[client]).resolve())
            )
        if scope in ("global", "both"):
            candidates.append(
                (client, "global", GLOBAL_PATHS[client].expanduser().resolve())
            )
        for name, kind, path in candidates:
            if path in seen:
                continue
            seen.add(path)
            pairs.append((name, kind, path))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client",
        choices=CLIENTS + ("all",),
        default="all",
        help="client to install (default: all)",
    )
    parser.add_argument(
        "--scope",
        choices=("project", "global", "both"),
        default="project",
        help="project tree, home directory or both (default: project)",
    )
    parser.add_argument(
        "--target",
        default=".",
        help="project root for --scope project (default: current directory)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the installed copies without writing anything",
    )
    args = parser.parse_args()

    packs = discover()
    slugs = [slug for slug, _ in packs]
    clients = list(CLIENTS) if args.client == "all" else [args.client]
    target = Path(args.target).expanduser().resolve()
    pairs = destinations(clients, args.scope, target)

    failures: list[str] = []
    if not args.check:
        for _, _, dest in pairs:
            dest.mkdir(parents=True, exist_ok=True)

    for client, kind, dest in pairs:
        installed = unchanged = 0
        for slug, text in packs:
            target_file = dest / slug / "SKILL.md"
            if args.check:
                if not target_file.is_file():
                    failures.append(f"{client}: missing {target_file}")
                    continue
                if target_file.read_text(encoding="utf-8") != text:
                    failures.append(f"{client}: outdated {target_file}")
                    continue
                installed += 1
                continue
            if target_file.is_file() and target_file.read_text(encoding="utf-8") == text:
                unchanged += 1
                continue
            atomic_write(target_file, text)
            installed += 1
        state = "present" if args.check else "installed"
        print(
            f"{kind} {client}: {installed} {state}, {unchanged} unchanged -> {dest}"
        )

    if args.scope in ("project", "both"):
        block = render_index(packs)
        if args.check:
            for name in INDEX_FILES:
                failures.extend(check_index(target / name, slugs))
        else:
            for name in INDEX_FILES:
                print(f"index {name}: {replace_index_block(target / name, block)}")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1

    print(f"packs: {len(slugs)} ({', '.join(slugs)})")
    if args.check:
        print(f"CLIENT_SKILLS_PRESENT {len(slugs)}")
    else:
        print(f"CLIENT_SKILLS_INSTALLED {len(slugs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
