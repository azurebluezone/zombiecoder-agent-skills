"""Command line interface for the ZombieCoder agent-skills library."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .router import tokenize
from .store import SkillStore, default_db_path


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _store(args: argparse.Namespace) -> SkillStore:
    return SkillStore(args.db or default_db_path())


def cmd_stats(args: argparse.Namespace) -> int:
    with _store(args) as store:
        stats = store.stats()
    if args.json:
        _print_json(stats)
    else:
        print(f"database : {stats['db']} ({stats['db_bytes']} bytes)")
        print(f"skills   : {stats['active']} active / {stats['total']} total")
        print(f"terms    : {stats['terms']}")
        print(f"bodies   : {stats['bytes']} bytes")
        for source in stats["sources"]:
            print(f"  - {source['source']}: {source['skill_count']} skills")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    with _store(args) as store:
        items = store.list(query=args.q or "", source=args.source or "", limit=args.limit, offset=args.offset)
    if args.json:
        _print_json(items)
    else:
        for item in items:
            print(f"{item['slug']:<40} {item['source']:<34} {item['bytes']:>7}  {item['name']}")
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    with _store(args) as store:
        skill = store.get(args.identifier)
    if not skill:
        print(f"skill not found: {args.identifier}", file=sys.stderr)
        return 1
    if args.json:
        _print_json(skill)
    else:
        print(f"# {skill['name']}")
        print(f"slug: {skill['slug']}  source: {skill['source']}  license: {skill.get('license') or '—'}")
        print(f"path: {skill.get('path') or '—'}")
        print()
        print(skill.get("body") or "")
    return 0


def cmd_route(args: argparse.Namespace) -> int:
    text = " ".join(args.text).strip()
    if not text:
        print("route needs some text", file=sys.stderr)
        return 2
    with _store(args) as store:
        matches = store.route(text, limit=args.limit, min_score=args.min_score)
    if args.json:
        _print_json({"text": text, "tokens": tokenize(text)[:20], "matches": matches})
    else:
        if not matches:
            print("no match above threshold")
            return 0
        for match in matches:
            print(f"{match['score']:>6}  {match['name']:<34} {match['source']}")
            print(f"        {match.get('description') or ''}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    failures: list[str] = []
    try:
        with _store(args) as store:
            stats = store.stats()
            if stats["active"] < 1:
                failures.append("database has no active skills")
            if stats["terms"] < 100:
                failures.append("term index looks empty")
            sample = store.route("debug a failing playwright test", limit=2)
            if not sample:
                failures.append("sample route returned no match")
            names = [match["name"] for match in sample]
            print(f"db        : {stats['db']}")
            print(f"skills    : {stats['active']} active / {stats['total']} total")
            print(f"terms     : {stats['terms']}")
            print(f"sample    : {', '.join(names) if names else 'none'}")
    except Exception as exc:  # pragma: no cover - CLI surface
        failures.append(str(exc))
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("DOCTOR_OK")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zombie-skills",
        description="Portable local skill library: route an input to SKILL.md instructions.",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", help="path to skills.db (default: ZOMBIE_SKILLS_DB or repo skills.db)")
    common.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True)

    stats = sub.add_parser("stats", parents=[common], help="database counts and sources")
    stats.set_defaults(func=cmd_stats)

    listing = sub.add_parser("list", parents=[common], help="list skills")
    listing.add_argument("--q", help="substring filter")
    listing.add_argument("--source", help="exact source filter")
    listing.add_argument("--limit", type=int, default=50)
    listing.add_argument("--offset", type=int, default=0)
    listing.set_defaults(func=cmd_list)

    get = sub.add_parser("get", parents=[common], help="show one skill body")
    get.add_argument("identifier", help="skill id or slug")
    get.set_defaults(func=cmd_get)

    route = sub.add_parser("route", parents=[common], help="route text to the best skills")
    route.add_argument("text", nargs="+")
    route.add_argument("--limit", type=int, default=2)
    route.add_argument("--min-score", type=float, default=3.0)
    route.set_defaults(func=cmd_route)

    doctor = sub.add_parser("doctor", parents=[common], help="validate the database")
    doctor.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except BrokenPipeError:  # pragma: no cover
        return 0
    except Exception as exc:  # pragma: no cover - CLI surface
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
