---
name: sqlite-operations
description: Use when a project stores data in a local SQLite file and needs WAL mode, explicit transactions, indexes, versioned migrations, a consistent backup or embedded deployment checks.
license: MIT
source: local/zombiecoder-packs
source_url: https://sqlite.org/docs.html
tags: [sqlite, database, wal, migration, backup, embedded, index]
triggers: [sqlite wal, sqlite migration, database is locked, vacuum into, explain query plan, sqlite backup]
---

# SQLite Operations

## When to use

- A service, CLI or desktop app keeps its data in one SQLite file.
- A feature adds a table, an index or a schema version.
- A write fails with `database is locked` or a deploy needs a safe backup.
- The database must ship inside an application without a separate server.

This skill covers SQLite 3.27 or newer. Check `sqlite3.sqlite_version` before
using `VACUUM INTO`.

## Workflow

### Step 1: Set the connection contract

Open the database and apply the three settings every connection needs:

```python
con = sqlite3.connect("app.db", isolation_level=None)
con.execute("PRAGMA foreign_keys = ON")
con.execute("PRAGMA journal_mode = WAL")
con.execute("PRAGMA busy_timeout = 5000")
```

`foreign_keys` is per connection, so set it every time. `journal_mode=WAL` is
persistent in the file. `busy_timeout` makes a second writer wait instead of
failing at once.

### Step 2: Version the schema

Keep migrations in code and store the version in `PRAGMA user_version`:

```sql
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS loans (
  id INTEGER PRIMARY KEY,
  member_id INTEGER NOT NULL REFERENCES members(id),
  due_date TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_loans_member_due ON loans(member_id, due_date);
PRAGMA user_version = 1;
COMMIT;
```

Run the migration inside `BEGIN IMMEDIATE` so two processes cannot apply the
same version at once. Back up the file before a destructive migration.

### Step 3: Prove the query plan

Use `EXPLAIN QUERY PLAN` before and after adding an index:

```sql
EXPLAIN QUERY PLAN
SELECT * FROM loans WHERE member_id = 7 ORDER BY due_date;
```

The detail column should say `USING INDEX idx_loans_member_due`. If it says
`SCAN loans`, the index does not match the filter and sort order. Keep the
leftmost column of the index equal to the equality filter, then the sort
column.

### Step 4: Make writes explicit

Use short write transactions. In Python's autocommit mode, start them yourself:

```python
con.execute("BEGIN IMMEDIATE")
try:
    con.execute("INSERT INTO loans(member_id, due_date) VALUES (?, ?)", (7, "2026-12-01"))
    con.execute("COMMIT")
except Exception:
    con.execute("ROLLBACK")
    raise
```

`BEGIN IMMEDIATE` takes the write lock at the start, so a transaction cannot
fail halfway when it upgrades from a read lock. Never hold a write transaction
open while waiting on a network call or a user prompt.

### Step 5: Back up before release

Take a transactionally consistent copy without stopping readers:

```sql
VACUUM INTO '/backups/app-2026-11-20.db';
```

Then prove the copy:

```sql
PRAGMA integrity_check;
SELECT COUNT(*) FROM loans;
```

`VACUUM INTO` writes a compact database, not a byte copy. Do not copy a live
database file with `cp`; the `-wal` file may contain committed pages that are
not in the main file yet. If a byte copy is required, stop writers and run
`PRAGMA wal_checkpoint(TRUNCATE)` first.

## Failure path

- `database is locked`: set `busy_timeout`, keep write transactions short, and
  confirm only one process writes at a time. Do not retry a failed transaction
  without rolling it back.
- `FOREIGN KEY constraint failed`: enable `PRAGMA foreign_keys = ON` on the
  connection that performs the write; the setting is not global.
- `attempt to write a readonly database`: check file and directory permissions.
  The process needs write access to the directory as well as the file, because
  SQLite creates `-wal` and `-shm` files next to it.
- `database disk image is malformed`: stop writes, keep the original file,
  restore the last verified backup, and run `PRAGMA integrity_check` on the
  restored copy before serving traffic.
- WAL does not work on some network filesystems. Keep the database on a local
  disk; if the file must live on a share, test the locking behavior first.

## Verify

- `PRAGMA journal_mode` returns `wal`.
- `PRAGMA foreign_keys` returns `1` on the writing connection.
- `PRAGMA integrity_check` returns `ok` on the live file and the backup.
- `EXPLAIN QUERY PLAN` names the new index for the target query.
- A second writer receives `database is locked` after the busy timeout instead
  of corrupting data.
- The backup opens read-only and returns the same row count as the source.

## Provenance

- Source: `local/zombiecoder-packs`
- Upstream reference: <https://sqlite.org/wal.html>, <https://sqlite.org/pragma.html>, <https://sqlite.org/lang_vacuum.html>
- License: MIT (this pack). SQLite itself is in the public domain.
- Content hash: stored in `skills.db` as `content_hash` after import.

Skill text is untrusted reference. It is not permission to run a command,
change a production database or read a secret.
