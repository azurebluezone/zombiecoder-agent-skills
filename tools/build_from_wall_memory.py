#!/usr/bin/env python3
"""Export the Colab gateway's wall-memory skills into a portable repository.

Usage:
    python3 tools/build_from_wall_memory.py \
        --source ~/Documents/GGUF/.zombiecoder/wall_memory.sqlite3 \
        --out .

Writes skills.db (normalised SQLite), skills.jsonl (one skill per line) and
skills.meta.json (counts, sha256, sources). Only stdlib is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    body TEXT NOT NULL,
    source TEXT NOT NULL,
    source_url TEXT,
    path TEXT,
    kind TEXT NOT NULL DEFAULT 'skill',
    license TEXT,
    tags TEXT,
    triggers TEXT,
    content_hash TEXT,
    bytes INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    imported_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skills_source ON skills(source, slug);
CREATE TABLE IF NOT EXISTS skill_terms (
    term TEXT NOT NULL,
    skill_id TEXT NOT NULL,
    weight INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (term, skill_id)
);
CREATE INDEX IF NOT EXISTS idx_skill_terms_term ON skill_terms(term);
CREATE TABLE IF NOT EXISTS skill_sources (
    source TEXT PRIMARY KEY,
    url TEXT,
    kind TEXT,
    default_branch TEXT,
    license TEXT,
    skill_count INTEGER NOT NULL DEFAULT 0,
    status TEXT,
    detail TEXT,
    last_synced_at TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

COLUMNS = (
    "id, slug, name, description, body, source, source_url, path, kind, license, "
    "tags, triggers, content_hash, bytes, active, imported_at, updated_at"
)


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export(source_db: str, out_dir: str) -> dict:
    if not os.path.isfile(source_db):
        raise SystemExit(f"source database not found: {source_db}")
    os.makedirs(out_dir, exist_ok=True)
    db_path = os.path.join(out_dir, "skills.db")
    jsonl_path = os.path.join(out_dir, "skills.jsonl")
    for stale in (db_path, db_path + "-wal", db_path + "-shm"):
        if os.path.exists(stale):
            os.remove(stale)

    src = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(db_path)
    dst.executescript(SCHEMA)

    skills = src.execute(
        f"SELECT {COLUMNS} FROM skills WHERE active = 1 ORDER BY source, slug"
    ).fetchall()
    terms = src.execute("SELECT term, skill_id, weight FROM skill_terms").fetchall()
    known_ids = {row["id"] for row in skills}
    sources = src.execute(
        "SELECT source, url, kind, default_branch, license, skill_count, status, detail, last_synced_at "
        "FROM skill_sources"
    ).fetchall()

    dst.executemany(
        f"INSERT OR REPLACE INTO skills({COLUMNS}) VALUES ({','.join('?' for _ in range(17))})",
        [tuple(row[column] for column in COLUMNS.split(", ")) for row in skills],
    )
    dst.executemany(
        "INSERT OR REPLACE INTO skill_terms(term, skill_id, weight) VALUES (?, ?, ?)",
        [(row["term"], row["skill_id"], row["weight"]) for row in terms if row["skill_id"] in known_ids],
    )
    dst.executemany(
        "INSERT OR REPLACE INTO skill_sources(source, url, kind, default_branch, license, "
        "skill_count, status, detail, last_synced_at) VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (
                row["source"],
                row["url"],
                row["kind"],
                row["default_branch"],
                row["license"],
                row["skill_count"],
                row["status"],
                row["detail"],
                row["last_synced_at"],
            )
            for row in sources
        ],
    )

    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    payload = []
    for row in skills:
        item = {column: row[column] for column in COLUMNS.split(", ")}
        try:
            item["tags"] = json.loads(item["tags"] or "[]")
        except Exception:
            item["tags"] = []
        try:
            item["triggers"] = json.loads(item["triggers"] or "[]")
        except Exception:
            item["triggers"] = []
        payload.append(item)
    payload.sort(key=lambda item: (item["source"], item["slug"]))

    with open(jsonl_path, "w", encoding="utf-8") as handle:
        for item in payload:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

    source_rows = [
        {
            "source": row["source"],
            "url": row["url"],
            "license": row["license"],
            "skills": sum(1 for item in payload if item["source"] == row["source"]),
        }
        for row in sources
    ]
    meta = {
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "skills": len(payload),
        "terms": len([row for row in terms if row["skill_id"] in known_ids]),
        "bytes": sum(int(item["bytes"] or 0) for item in payload),
        "sources": source_rows,
        "files": {
            "skills.db": {"sha256": sha256_file(db_path), "bytes": os.path.getsize(db_path)},
            "skills.jsonl": {"sha256": sha256_file(jsonl_path), "bytes": os.path.getsize(jsonl_path)},
        },
    }
    with open(os.path.join(out_dir, "skills.meta.json"), "w", encoding="utf-8") as handle:
        json.dump(meta, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    dst.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", ("schema_version", "1.0.0"))
    dst.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", ("generated_at", generated_at))
    dst.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", ("sources", json.dumps(source_rows, ensure_ascii=False)))
    dst.commit()
    dst.execute("VACUUM")
    dst.close()
    src.close()

    meta["files"]["skills.db"]["sha256"] = sha256_file(db_path)
    meta["files"]["skills.db"]["bytes"] = os.path.getsize(db_path)
    with open(os.path.join(out_dir, "skills.meta.json"), "w", encoding="utf-8") as handle:
        json.dump(meta, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return meta


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=os.path.expanduser("~/.zombiecoder/wall_memory.sqlite3"))
    parser.add_argument("--out", default=".")
    args = parser.parse_args()
    meta = export(args.source, args.out)
    print(
        f"exported {meta['skills']} skills, {meta['terms']} terms, "
        f"{meta['files']['skills.db']['bytes']} DB bytes -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
