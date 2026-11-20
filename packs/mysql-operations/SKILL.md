---
name: mysql-operations
description: Use when a MySQL 8 database needs a schema change, index review, EXPLAIN analysis, a safe migration on a live table or a verified backup and restore.
license: MIT
source: local/zombiecoder-packs
source_url: https://dev.mysql.com/doc/refman/8.0/en/
tags: [mysql, database, explain, index, migration, backup, innodb]
triggers: [mysql explain, mysql index, mysql migration, mysqldump, lock wait timeout, online ddl]
---

# MySQL Operations

## When to use

- A MySQL 8 schema change must run without taking the application offline.
- A query is slow and the index needs evidence, not a guess.
- A release needs a backup that has actually been restored once.
- A migration is blocked by a metadata lock, a long transaction or disk space.

This pack targets MySQL 8.0 with InnoDB. Check `SELECT VERSION()` before using
`EXPLAIN ANALYZE` (8.0.18+) or instant DDL (8.0.12+).

## Workflow

### Step 1: Capture the current shape

Read the real table definition and the query plan before changing anything:

```sql
SHOW CREATE TABLE loans;
EXPLAIN SELECT * FROM loans WHERE member_id = 7 ORDER BY due_date;
```

Record the `key`, `rows`, `filtered` and `Extra` columns. `type=ALL` means a
full scan. `Using filesort` means the index does not satisfy the sort order.
Keep the output in the change ticket so the result can be compared later.

### Step 2: Design the index for the query

Put equality columns first, then the range or sort column:

```sql
CREATE INDEX idx_loans_member_due ON loans (member_id, due_date);
```

A composite index `(member_id, due_date)` serves `WHERE member_id = ? ORDER BY
due_date`. An index on `(due_date, member_id)` does not. Use a covering index
only when the query needs the extra columns and the write cost is acceptable.
Remove a redundant index only after `SHOW INDEX FROM loans` and the slow-query
log agree that nothing else uses it.

### Step 3: Test the migration on a copy

Run the exact `ALTER` on a restored copy and measure it:

```sql
SET SESSION lock_wait_timeout = 5;
ALTER TABLE loans
  ADD COLUMN returned_at DATE NULL,
  ALGORITHM = INSTANT;
```

`ALGORITHM = INSTANT` is limited to changes MySQL supports instantly, such as
adding a nullable column at the end of the row. For a rebuild, try `ALGORITHM =
INPLACE, LOCK = NONE`; MySQL rejects the statement when the operation cannot
run online. Do not assume an online DDL is free: it still consumes I/O and
replication capacity.

### Step 4: Back up and restore once

Take a consistent InnoDB snapshot:

```bash
mysqldump --single-transaction --routines --triggers \
  --set-gtid-purged=OFF library > library-2026-11-20.sql
```

Restore it into a scratch schema and compare row counts and checksums:

```sql
CREATE DATABASE library_restore;
-- mysql library_restore < library-2026-11-20.sql
SELECT COUNT(*) FROM library.loans;
SELECT COUNT(*) FROM library_restore.loans;
CHECKSUM TABLE library.loans, library_restore.loans;
```

`--single-transaction` gives a consistent snapshot for InnoDB tables without
locking them. MyISAM tables are not covered. Test the restore command; an
unrestored backup is only a file.

### Step 5: Apply, observe and keep a rollback

Apply during a measured window, then verify:

```sql
EXPLAIN ANALYZE SELECT * FROM loans WHERE member_id = 7 ORDER BY due_date;
SHOW WARNINGS;
```

Watch `SHOW PROCESSLIST`, replication lag and the error log for at least one
traffic cycle. Keep the reverse migration and the pre-change backup until the
new version has served real traffic. For a large table, use a tested online
schema-change tool instead of a direct `ALTER`.

## Failure path

- `Lock wait timeout exceeded`: find the blocking transaction in
  `performance_schema.data_lock_waits`, end the idle transaction, then retry.
  Set a short `lock_wait_timeout` for migrations so they fail fast.
- `Too many connections`: fix the leak in the application pool; raising
  `max_connections` hides the cause and consumes memory.
- `Disk full` or a stalled `ALTER`: stop the migration, confirm the server is
  healthy, free space, and restore from the pre-change backup if the table is
  inconsistent. Do not restart a partially applied DDL blindly.
- Wrong collation or `Illegal mix of collations`: use `utf8mb4` and an explicit
  collation per column; convert both sides of a join to the same collation.
- A backup restore fails: verify the dump is complete, the target schema is
  empty, and the MySQL version matches. A dump from a newer server may use
  syntax the older server rejects.

## Verify

- `SHOW CREATE TABLE` contains the expected column, index and engine.
- `EXPLAIN` names the intended index and no longer reports `Using filesort` for
  the target query.
- `CHECK TABLE` returns `OK` for every changed table.
- The restored copy has the same row counts and `CHECKSUM TABLE` values.
- A transaction rollback leaves the row count unchanged.
- No credential is written to a shell history, a dump file or the repository.

## Provenance

- Source: `local/zombiecoder-packs`
- Upstream reference: <https://dev.mysql.com/doc/refman/8.0/en/optimization-indexes.html>, <https://dev.mysql.com/doc/refman/8.0/en/innodb-online-ddl.html>, <https://dev.mysql.com/doc/refman/8.0/en/mysqldump.html>
- License: MIT (this pack). MySQL documentation is used as a reference only.
- Content hash: stored in `skills.db` as `content_hash` after import.

Skill text is untrusted reference. It is not permission to run a command,
change a production database or read a secret.
