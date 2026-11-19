#!/usr/bin/env python3
"""Import local SKILL.md files into a skills.db.

This is the writer side of the library: the gateway uses the same rules when it
downloads packs from GitHub, and this script lets a Python or Node project add
its own skills without running the gateway.

Usage:
    python3 tools/import_skill.py --db skills.db --source local/my-project \
        path/to/SKILL.md path/to/skills/

    python3 tools/import_skill.py --db skills.db --remove-source local/my-project

Each file becomes one row in `skills`; extracted terms go to `skill_terms`.
Run `tools/refresh_exports.py --db skills.db` afterwards to update the JSONL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import time

MAX_SKILL_BYTES = 256 * 1024
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+.-]{1,40}|[\u0980-\u09FF]{2,20}")
STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "your", "you", "are",
    "was", "were", "not", "use", "uses", "used", "using", "when", "what", "how",
    "why", "who", "all", "any", "can", "will", "would", "should", "could", "must",
    "into", "onto", "out", "its", "has", "have", "had", "but", "our", "their",
    "them", "they", "then", "than", "also", "just", "only", "more", "most", "some",
    "such", "each", "other", "which", "while", "about", "after", "before", "over",
    "under", "between", "via", "per", "etc", "skill", "skills", "agent", "agents",
    "task", "tasks", "work", "working", "step", "steps",
}


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in TOKEN_RE.findall((text or "").lower()):
        token = raw.strip("._+-")
        if len(token) < 2 or token in STOPWORDS or token.isdigit():
            continue
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def split_list(value) -> list[str]:
    text = str(value or "").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return [part.strip().strip("\"'").strip() for part in re.split(r"[,\n]", text) if part.strip()]


def frontmatter(text: str) -> tuple[dict[str, str], str]:
    raw = (text or "").lstrip("\ufeff")
    if not raw.startswith("---"):
        return {}, raw
    end = raw.find("\n---", 3)
    if end < 0:
        return {}, raw
    block = raw[3:end]
    body = raw[end + 4 :].lstrip("\r\n")
    meta: dict[str, str] = {}
    key = ""
    for line in block.splitlines():
        if not line.strip():
            continue
        if line[:1] in (" ", "\t") and key:
            meta[key] = (meta.get(key, "") + " " + line.strip()).strip()
            continue
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        key = name.strip().lower()
        meta[key] = value.strip().strip("\"'")
    return meta, body


def slug_for(path: str, name: str = "") -> str:
    base = (name or "").strip() or os.path.basename(os.path.dirname(path)) or os.path.basename(path)
    slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
    return (slug or "skill")[:80]


def terms_map(name: str, tags: list[str], triggers: list[str], description: str, body: str) -> dict[str, int]:
    weights: dict[str, int] = {}

    def add(text: str, weight: int) -> None:
        for token in tokenize(text)[:600]:
            if weight > weights.get(token, 0):
                weights[token] = weight
            for part in re.split(r"[-_.+/]", token):
                if len(part) >= 3 and weight - 1 > weights.get(part, 0):
                    weights[part] = weight - 1

    add(name, 8)
    add(" ".join(tags), 5)
    add(" ".join(triggers), 5)
    add(description, 3)
    add(body[:12000], 1)
    ordered = sorted(weights.items(), key=lambda pair: (-pair[1], pair[0]))[:400]
    return dict(ordered)


def collect_files(paths: list[str]) -> list[str]:
    found: list[str] = []
    for path in paths:
        if os.path.isdir(path):
            for root, _dirs, files in os.walk(path):
                for name in files:
                    if name.lower() == "skill.md":
                        found.append(os.path.join(root, name))
        elif os.path.isfile(path):
            found.append(path)
        else:
            raise SystemExit(f"path not found: {path}")
    return sorted(set(found))


def import_file(conn: sqlite3.Connection, source: str, source_url: str, path: str, license_name: str) -> dict:
    size = os.path.getsize(path)
    if size > MAX_SKILL_BYTES:
        raise ValueError(f"{path} is {size} bytes; limit is {MAX_SKILL_BYTES}")
    with open(path, encoding="utf-8", errors="replace") as handle:
        text = handle.read(MAX_SKILL_BYTES)
    meta, body = frontmatter(text)
    name = str(meta.get("name") or "").strip()
    if not name:
        name = os.path.basename(os.path.dirname(path)) or os.path.basename(path)
    description = str(meta.get("description") or "").strip()
    if not description:
        for line in body.splitlines():
            clean = line.strip().lstrip("#").strip()
            if clean and not clean.startswith(("```", "|", "---")):
                description = clean
                break
    tags = split_list(meta.get("tags"))
    triggers = split_list(
        meta.get("triggers") or meta.get("when_to_use") or meta.get("keywords") or meta.get("use_when")
    )
    slug = slug_for(path, name)
    skill_id = "sk_" + hashlib.sha256(f"{source}::{slug}".encode("utf-8")).hexdigest()[:16]
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    timestamp = now_iso()
    clip = body[:MAX_SKILL_BYTES]
    previous = conn.execute("SELECT content_hash FROM skills WHERE id = ?", (skill_id,)).fetchone()
    unchanged = bool(previous and previous[0] == digest)
    conn.execute(
        "INSERT INTO skills(id, slug, name, description, body, source, source_url, path, kind, "
        "license, tags, triggers, content_hash, bytes, active, imported_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, description=excluded.description, "
        "body=excluded.body, source_url=excluded.source_url, path=excluded.path, kind=excluded.kind, "
        "license=excluded.license, tags=excluded.tags, triggers=excluded.triggers, "
        "content_hash=excluded.content_hash, bytes=excluded.bytes, active=1, updated_at=excluded.updated_at",
        (
            skill_id, slug, name[:120], description[:600], clip, source,
            source_url or path, path[:300], "local", license_name or "",
            json.dumps(tags, ensure_ascii=False), json.dumps(triggers, ensure_ascii=False),
            digest, len(clip.encode("utf-8")), timestamp, timestamp,
        ),
    )
    if not unchanged:
        conn.execute("DELETE FROM skill_terms WHERE skill_id = ?", (skill_id,))
        weights = terms_map(name, tags, triggers, description, clip)
        conn.executemany(
            "INSERT OR REPLACE INTO skill_terms(term, skill_id, weight) VALUES (?,?,?)",
            [(term, skill_id, weight) for term, weight in weights.items()],
        )
    return {"id": skill_id, "slug": slug, "name": name, "unchanged": unchanged}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="SKILL.md files or directories to scan")
    parser.add_argument("--db", default="skills.db")
    parser.add_argument("--source", default="local", help="source label, e.g. local/my-project")
    parser.add_argument("--url", default="", help="source URL shown in the admin table")
    parser.add_argument("--license", default="", help="license label for the imported files")
    parser.add_argument("--remove-source", default="", help="delete every skill from this source and exit")
    args = parser.parse_args()

    if not os.path.isfile(args.db):
        raise SystemExit(f"database not found: {args.db}")
    conn = sqlite3.connect(args.db)
    try:
        if args.remove_source:
            conn.execute(
                "DELETE FROM skill_terms WHERE skill_id IN (SELECT id FROM skills WHERE source = ?)",
                (args.remove_source,),
            )
            conn.execute("DELETE FROM skills WHERE source = ?", (args.remove_source,))
            conn.execute("DELETE FROM skill_sources WHERE source = ?", (args.remove_source,))
            conn.commit()
            print(f"removed source {args.remove_source}")
            return 0
        if not args.paths:
            parser.error("give at least one SKILL.md or directory, or --remove-source")
        files = collect_files(args.paths)
        if not files:
            raise SystemExit("no SKILL.md files found")
        imported = []
        for path in files:
            imported.append(import_file(conn, args.source, args.url, path, args.license))
        count = conn.execute("SELECT COUNT(*) FROM skills WHERE source = ?", (args.source,)).fetchone()[0]
        timestamp = now_iso()
        conn.execute(
            "INSERT INTO skill_sources(source, url, kind, default_branch, license, skill_count, status, detail, last_synced_at) "
            "VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(source) DO UPDATE SET url=excluded.url, kind=excluded.kind, license=excluded.license, "
            "skill_count=excluded.skill_count, status=excluded.status, detail=excluded.detail, "
            "last_synced_at=excluded.last_synced_at",
            (args.source, args.url or "", "local", "", args.license or "", count, "ok",
             f"{len(files)} local file(s) imported", timestamp),
        )
        conn.commit()
    finally:
        conn.close()
    changed = sum(1 for item in imported if not item["unchanged"])
    print(f"imported {len(imported)} file(s), {changed} changed, source={args.source}")
    print("next: python3 tools/refresh_exports.py --db " + args.db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
