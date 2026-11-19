# Schema

`skills.db` is SQLite 3, created without extensions, and read by Python's
stdlib `sqlite3` and (optionally) Node's `node:sqlite`. The canonical copy is
the file in the repository root; `skills.jsonl` and `terms.jsonl` are exports
of the same rows.

```sql
CREATE TABLE skills (
    id            TEXT PRIMARY KEY,     -- "sk_" + sha256(source::slug)[:16]
    slug          TEXT NOT NULL,        -- lowercase [a-z0-9-], max 80
    name          TEXT NOT NULL,        -- frontmatter name or directory
    description   TEXT,                 -- frontmatter description, <= 600 chars
    body          TEXT NOT NULL,        -- SKILL.md body, <= 256 KiB
    source        TEXT NOT NULL,        -- "owner/repo"
    source_url    TEXT,                 -- blob URL of the file
    path          TEXT,                 -- path inside the source repo
    kind          TEXT NOT NULL DEFAULT 'skill',
    license       TEXT,
    tags          TEXT,                 -- JSON array string
    triggers      TEXT,                 -- JSON array string
    content_hash  TEXT,                 -- sha256 of the raw file
    bytes         INTEGER NOT NULL DEFAULT 0,
    active        INTEGER NOT NULL DEFAULT 1,
    imported_at   TEXT NOT NULL,        -- ISO-8601 UTC
    updated_at    TEXT NOT NULL
);
CREATE INDEX idx_skills_source ON skills(source, slug);

CREATE TABLE skill_terms (
    term      TEXT NOT NULL,
    skill_id  TEXT NOT NULL,
    weight    INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (term, skill_id)
);
CREATE INDEX idx_skill_terms_term ON skill_terms(term);

CREATE TABLE skill_sources (
    source          TEXT PRIMARY KEY,   -- "owner/repo"
    url             TEXT,
    kind            TEXT,
    default_branch  TEXT,
    license         TEXT,
    skill_count     INTEGER NOT NULL DEFAULT 0,
    status          TEXT,               -- ok | partial | error
    detail          TEXT,
    last_synced_at  TEXT
);

CREATE TABLE meta (
    key    TEXT PRIMARY KEY,
    value  TEXT
);
```

## Invariants

- `skills.id` is deterministic: `sk_` plus the first 16 hex characters of
  `sha256("{source}::{slug}")`. Re-importing the same source and slug updates
  the row instead of duplicating it.
- `skill_terms` is a routing index, not a copy of the text. Weights are:
  name `8`, tags `5`, triggers `5`, description `3`, body `1`, with a
  hyphen/slash sub-token at `weight - 1`. Each skill stores at most 400 terms.
- Two sources may publish the same slug (`design-system`, `browser-automation`).
  They stay as separate rows; the router deduplicates the final result by slug
  and keeps the highest-scoring copy.
- `active = 1` marks a row that the router may return. `tools/audit_skills.py
  --apply` removes dropped rows; `active` remains available for reversible
  filtering when you prefer to keep a row in the file.
- `bytes` is the UTF-8 length of `body`, not of the file.
- `tags` and `triggers` are JSON text in SQLite and become JSON arrays in
  `skills.jsonl`.

## Exports

| File | Row shape |
| --- | --- |
| `skills.jsonl` | one skill object per line, all `skills` columns, `tags`/`triggers` as arrays, sorted by `source, slug` |
| `terms.jsonl` | `{"term": "...", "skill_id": "sk_...", "weight": 3}`, sorted by `term, skill_id` |
| `skills.meta.json` | counts, source summary, audit counts, and SHA-256 + byte size for `skills.db`, `skills.jsonl`, `terms.jsonl` |

`skills.meta.json` is the trust anchor for remote sync: the gateway downloads
it first, then requires `skills.db` to match `files["skills.db"].sha256` and
`files["skills.db"].bytes` before importing.

## Current build

| Metric | Value |
| --- | ---: |
| Skills (`active=1`) | 248 |
| Term rows | 72,631 |
| Body bytes | 2,044,906 |
| Sources | 6 |
| DB size | ~8.6 MB after `VACUUM` |

Verify with:

```bash
python3 tools/refresh_exports.py --db skills.db --out .
PYTHONPATH=python python3 -m zombie_skills.cli stats
node node/bin/cli.js stats
```
