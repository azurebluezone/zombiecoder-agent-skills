#!/usr/bin/env python3
"""Prove the delivered files exist at their repository-prefixed paths.

The earlier report used ``server/skill_server.py`` as shorthand. That path is
relative to ``zombiecoder-agent-skills/``, not to the project root, so a path
validator correctly reported it missing. This check removes the ambiguity:
every path is resolved from this file's repository root, and the README links
must resolve to real files.

Run from the project root::

    python3 zombiecoder-agent-skills/tools/check_skill_paths.py
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent

REQUIRED = (
    "server/skill_server.py",
    "server/skill_mcp.py",
    "server/README.md",
    "docs/MCP.md",
    "docs/SKILL-PACK.md",
    "examples/ollama_tool_loop.py",
    "examples/skill-note.md",
    "examples/packs/php_example.php",
    "examples/packs/cpp_example.cpp",
    "examples/packs/cdp_example.mjs",
    "examples/packs/python_example.py",
    "examples/packs/js_ts_example.ts",
    "examples/packs/package.json",
    "packs/python-operations/SKILL.md",
    "packs/javascript-typescript-operations/SKILL.md",
    "tools/check_skill_server.py",
    "tools/check_skill_mcp.py",
    "tools/check_extra_packs.py",
    "tools/check_remaining_packs.py",
    "tools/install_opencode_skills.py",
    "tools/check_skill_paths.py",
)

SERVER_MARKERS = ("class Handler", "SKILL_SERVER_LISTENING")
MCP_MARKERS = ("SERVER_NAME", "search_skills", "get_skill")
CHECK_MARKER = "SKILL_SERVER_OK"
MCP_CHECK_MARKER = "SKILL_MCP_OK"
REMAINING_CHECK_MARKER = "REMAINING_PACKS_OK"
LINK_TARGETS = ("server/README.md", "docs/MCP.md", "docs/SKILL-PACK.md")

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def main() -> int:
    for relative in REQUIRED:
        path = ROOT / relative
        check(path.is_file(), f"missing file: {relative}")
        check(path.is_file() and path.stat().st_size > 0, f"empty file: {relative}")

    server = ROOT / "server" / "skill_server.py"
    if server.is_file():
        text = server.read_text(encoding="utf-8")
        for marker in SERVER_MARKERS:
            check(marker in text, f"server is missing marker: {marker}")

    mcp = ROOT / "server" / "skill_mcp.py"
    if mcp.is_file():
        text = mcp.read_text(encoding="utf-8")
        for marker in MCP_MARKERS:
            check(marker in text, f"MCP server is missing marker: {marker}")

    check_script = ROOT / "tools" / "check_skill_server.py"
    if check_script.is_file():
        text = check_script.read_text(encoding="utf-8")
        check(CHECK_MARKER in text, f"check script is missing marker: {CHECK_MARKER}")

    mcp_check = ROOT / "tools" / "check_skill_mcp.py"
    if mcp_check.is_file():
        text = mcp_check.read_text(encoding="utf-8")
        check(MCP_CHECK_MARKER in text, f"MCP check is missing marker: {MCP_CHECK_MARKER}")

    remaining_check = ROOT / "tools" / "check_remaining_packs.py"
    if remaining_check.is_file():
        text = remaining_check.read_text(encoding="utf-8")
        check(
            REMAINING_CHECK_MARKER in text,
            f"remaining-pack check is missing marker: {REMAINING_CHECK_MARKER}",
        )

    readme = ROOT / "README.md"
    if readme.is_file():
        text = readme.read_text(encoding="utf-8")
        for target in LINK_TARGETS:
            check(f"]({target})" in text, f"README is missing link target: {target}")
            check((ROOT / target).is_file(), f"README link target is missing: {target}")

    if FAILURES:
        for failure in FAILURES:
            print(f"FAIL: {failure}")
        return 1

    print(f"repository: {ROOT}")
    print(f"project root: {PROJECT}")
    for relative in REQUIRED:
        path = ROOT / relative
        print(f"OK {relative} {path.stat().st_size} bytes")
    print("README links: " + " -> ".join(LINK_TARGETS) + " resolved")
    print("SKILL_PATHS_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
