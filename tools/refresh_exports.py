#!/usr/bin/env python3
"""Regenerate the portable exports from a curated skills.db.

The SQLite file is the source of truth for the repository.  This script writes
the dependency-free JSONL exports used by the Node package and by any runtime
that does not want to open SQLite:

    skills.jsonl  one skill per line, full body + metadata
    terms.jsonl   one routing term per line (term, skill_id, weight)
    skills.meta.json  counts, source summary, sha256 and byte sizes

Usage:
    python3 tools/refresh_exports.py --db skills.db --out .
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import time

SKILL_COLUMNS = (
    "id, slug, name, description, body, source, source_url, path, kind, license, "
    "tags, triggers, content_hash, bytes, active, imported_at, updated_at"
)


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def refresh(db_path: str, out_dir: str) -> dict:
    if not os.path.isfile(db_path):
        raise SystemExit(f"database not found: {db_path}")
    os.makedirs(out_dir, exist_ok=True)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    skills = conn.execute(
        f"SELECT {SKILL_COLUMNS} FROM skills WHERE active = 1 ORDER BY source, slug"
    ).fetchall()
    known = {str(row["id"]) for row in skills}
    terms = conn.execute(
        "SELECT term, skill_id, weight FROM skill_terms ORDER BY term, skill_id"
    ).fetchall()
    sources = conn.execute(
        "SELECT source, url, kind, default_branch, license, skill_count, status, detail, last_synced_at "
        "FROM skill_sources ORDER BY source"
    ).fetchall()

    skills_path = os.path.join(out_dir, "skills.jsonl")
    terms_path = os.path.join(out_dir, "terms.jsonl")
    meta_path = os.path.join(out_dir, "skills.meta.json")

    with open(skills_path, "w", encoding="utf-8") as handle:
        for row in skills:
            item = {column: row[column] for column in SKILL_COLUMNS.split(", ")}
            for key in ("tags", "triggers"):
                try:
                    item[key] = json.loads(item.get(key) or "[]")
                except Exception:
                    item[key] = []
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

    with open(terms_path, "w", encoding="utf-8") as handle:
        for row in terms:
            if str(row["skill_id"]) in known:
                handle.write(
                    json.dumps(
                        {"term": row["term"], "skill_id": row["skill_id"], "weight": int(row["weight"])},
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n"
                )

    audit_counts = {}
    audit_path = os.path.join(out_dir, "audit", "report.json")
    if os.path.isfile(audit_path):
        try:
            with open(audit_path, encoding="utf-8") as handle:
                audit_counts = json.load(handle).get("counts", {})
        except Exception:
            audit_counts = {}

    meta = {
        "schema_version": "1.0.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "skills": len(skills),
        "terms": sum(1 for row in terms if str(row["skill_id"]) in known),
        "bytes": sum(int(row["bytes"] or 0) for row in skills),
        "audit": audit_counts,
        "sources": [
            {
                "source": row["source"],
                "url": row["url"],
                "license": row["license"],
                "skills": sum(1 for item in skills if item["source"] == row["source"]),
            }
            for row in sources
        ],
        "files": {
            "skills.db": {"sha256": sha256_file(db_path), "bytes": os.path.getsize(db_path)},
            "skills.jsonl": {"sha256": sha256_file(skills_path), "bytes": os.path.getsize(skills_path)},
            "terms.jsonl": {"sha256": sha256_file(terms_path), "bytes": os.path.getsize(terms_path)},
        },
    }
    with open(meta_path, "w", encoding="utf-8") as handle:
        json.dump(meta, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    conn.close()
    return meta


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="skills.db")
    parser.add_argument("--out", default=".")
    args = parser.parse_args()
    meta = refresh(args.db, args.out)
    print(
        f"refreshed {meta['skills']} skills, {meta['terms']} terms, "
        f"db={meta['files']['skills.db']['bytes']} bytes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
