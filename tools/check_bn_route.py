#!/usr/bin/env python3
"""Prove the Bengali intent bridge against the real library.

Run from the project root:

    python3 zombiecoder-agent-skills/tools/check_bn_route.py

The script prints SKILLS_BN_ROUTE_OK only when every condition passes. It
checks the Python SQLite router, the Node JSONL CLI, English parity and the
negative cases, so a passing marker is evidence for both readers.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "skills.db"
INTENTS = ROOT / "data" / "bn-intents.json"
sys.path.insert(0, str(ROOT / "python"))

from zombie_skills import SkillStore  # noqa: E402
from zombie_skills.router import expand_query, load_intents, normalize_text  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def slugs(matches: list[dict]) -> list[str]:
    return [str(match.get("slug") or "") for match in matches]


def node_route(text: str, *extra: str) -> list[str]:
    node = shutil.which("node")
    check(node is not None, "node executable not found")
    if not node:
        return []
    command = [
        node,
        str(ROOT / "node" / "bin" / "cli.js"),
        "route",
        text,
        "--limit",
        "3",
        "--json",
        *extra,
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        FAILURES.append(f"node route failed for {text!r}: {result.stderr.strip()}")
        return []
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        FAILURES.append(f"node route returned invalid JSON for {text!r}: {exc}")
        return []
    return slugs(payload.get("matches") or [])


def main() -> int:
    if not INTENTS.is_file():
        print(f"FAIL: missing intent bridge: {INTENTS}")
        return 1
    if not DB.is_file():
        print(f"FAIL: missing database: {DB}")
        return 1

    raw = json.loads(INTENTS.read_text(encoding="utf-8"))
    entries = raw.get("entries") or []
    check(raw.get("schema_version") == "1.0.0", "schema_version must be 1.0.0")
    check(raw.get("normalization") == "NFC", "normalization must be NFC")
    check(len(entries) >= 40, f"expected >=40 entries, got {len(entries)}")
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            FAILURES.append(f"entry {index} is not an object")
            continue
        bengali = str(entry.get("bn") or "")
        english = str(entry.get("en") or "").strip()
        check(bool(bengali), f"entry {index} has no Bengali key")
        check(bool(english), f"entry {bengali or index} has no English query")
        check(bengali not in seen, f"duplicate Bengali key: {bengali}")
        seen.add(bengali)
        check(
            unicodedata.normalize("NFC", bengali) == bengali,
            f"entry is not NFC-normalized: {bengali}",
        )
        check(
            normalize_text(bengali) == bengali,
            f"entry has a decomposed Bengali letter: {bengali}",
        )

    bridge = load_intents()
    check(len(bridge.get("entries") or []) == len(entries), "loader did not keep every entry")

    store = SkillStore(DB)
    cases = {
        "ল্যান্ডিং পেজ ডিজাইন করো": {"landing"},
        "ডেটাবেস ডিজাইন করো": {"database-designer", "database-schema-designer"},
        "ব্রাউজার অটোমেশন": {"browser-automation"},
        "কোড রিভিউ": {"code-reviewer"},
        "ডিজাইন সিস্টেম": {"design-system", "ui-design-system"},
        "পারফরম্যান্স অডিট": {"performance-profiler"},
        "সিকিউরিটি অডিট": {"senior-security", "threat-hunting", "ai-security", "code-audit"},
    }
    for text, expected in cases.items():
        matches = store.route(text, limit=3)
        got = set(slugs(matches))
        check(
            bool(got & expected),
            f"{text}: expected one of {sorted(expected)}, got {slugs(matches)}",
        )

    check(
        "browser automation" in expand_query("ব্রাউজার অটোমেশন"),
        "Bengali expansion did not produce 'browser automation'",
    )
    decomposed = "\u0993\u09af\u09bc\u09c7\u09ac \u09a1\u09bf\u099c\u09be\u0987\u09a8"
    check("web" in expand_query(decomposed), "decomposed Bengali yya did not normalize")
    check(
        store.route("আজকের আবহাওয়া কেমন", limit=2) == [],
        "unmapped Bengali sentence must not match a skill",
    )
    check(
        store.route("ব্রাউজার অটোমেশন", limit=3, expand=False) == [],
        "raw Bengali must not match without the bridge",
    )

    for text in (
        "design a tailwind ux design system landing page",
        "debug a failing playwright test",
        "write a changelog for the last release",
    ):
        expanded = slugs(store.route(text, limit=3))
        plain = slugs(store.route(text, limit=3, expand=False))
        check(expanded == plain, f"English routing changed for {text!r}: {expanded} vs {plain}")

    for text in ("ব্রাউজার অটোমেশন", "কোড রিভিউ"):
        python_top = slugs(store.route(text, limit=3))
        node_top = node_route(text)
        check(
            bool(python_top) and bool(node_top) and python_top[0] == node_top[0],
            f"Node/Python top mismatch for {text!r}: python={python_top} node={node_top}",
        )

    no_expand_js = node_route("ব্রাউজার অটোমেশন", "--no-expand")
    check(no_expand_js == [], f"node --no-expand must return no match, got {no_expand_js}")

    store.close()

    if FAILURES:
        for failure in FAILURES:
            print(f"FAIL: {failure}")
        return 1

    print(
        f"bengali bridge: {len(entries)} entries, "
        f"{len(cases)} intent cases, Python + Node parity, English unchanged"
    )
    print("SKILLS_BN_ROUTE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
