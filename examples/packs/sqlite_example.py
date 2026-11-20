#!/usr/bin/env python3
"""Real SQLite workflow: WAL, migration, index proof, backup and lock test.

Run from the repository root:

    python3 examples/packs/sqlite_example.py

The script uses only the Python standard library and a temporary database.
It prints SQLITE_PACK_OK only when every assertion passes.
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path


def fail(message: str) -> int:
    print(f"SQLITE_PACK_FAIL: {message}")
    return 1


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="zc-sqlite-") as tmp:
        db = Path(tmp) / "library.db"
        backup = Path(tmp) / "library-backup.db"
        con = sqlite3.connect(db, isolation_level=None)
        try:
            con.execute("PRAGMA foreign_keys = ON")
            journal = con.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            if str(journal).lower() != "wal":
                return fail(f"journal_mode is {journal!r}, expected wal")
            con.execute("PRAGMA busy_timeout = 5000")

            con.execute("BEGIN IMMEDIATE")
            con.execute(
                "CREATE TABLE members("
                "id INTEGER PRIMARY KEY, "
                "email TEXT NOT NULL UNIQUE, "
                "joined_at TEXT NOT NULL)"
            )
            con.execute(
                "CREATE TABLE books("
                "id INTEGER PRIMARY KEY, "
                "isbn TEXT NOT NULL UNIQUE, "
                "title TEXT NOT NULL)"
            )
            con.execute(
                "CREATE TABLE loans("
                "id INTEGER PRIMARY KEY, "
                "member_id INTEGER NOT NULL REFERENCES members(id), "
                "book_id INTEGER NOT NULL REFERENCES books(id), "
                "loaned_at TEXT NOT NULL, "
                "due_date TEXT NOT NULL, "
                "returned_at TEXT)"
            )
            con.execute(
                "CREATE INDEX idx_loans_member_due ON loans(member_id, due_date)"
            )
            con.execute("PRAGMA user_version = 1")
            con.execute("COMMIT")

            version = con.execute("PRAGMA user_version").fetchone()[0]
            if version != 1:
                return fail(f"user_version is {version}, expected 1")

            con.executemany(
                "INSERT INTO members(id, email, joined_at) VALUES (?, ?, ?)",
                [(1, "a@example.test", "2026-01-01"), (2, "b@example.test", "2026-02-01")],
            )
            con.executemany(
                "INSERT INTO books(id, isbn, title) VALUES (?, ?, ?)",
                [(1, "9780000000001", "Book One"), (2, "9780000000002", "Book Two")],
            )
            con.executemany(
                "INSERT INTO loans(id, member_id, book_id, loaned_at, due_date) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (1, 1, 1, "2026-11-01", "2026-11-15"),
                    (2, 1, 2, "2026-11-10", "2026-11-24"),
                ],
            )

            plan = con.execute(
                "EXPLAIN QUERY PLAN "
                "SELECT * FROM loans WHERE member_id = 1 ORDER BY due_date"
            ).fetchall()
            detail = " ".join(str(row[-1]) for row in plan)
            if "idx_loans_member_due" not in detail:
                return fail(f"query plan did not use the index: {detail}")

            integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                return fail(f"integrity_check is {integrity!r}")

            # A rolled-back write must not change the row count.
            con.execute("BEGIN IMMEDIATE")
            con.execute(
                "INSERT INTO loans(id, member_id, book_id, loaned_at, due_date) "
                "VALUES (3, 2, 1, '2026-11-20', '2026-12-04')"
            )
            con.execute("ROLLBACK")
            count = con.execute("SELECT COUNT(*) FROM loans").fetchone()[0]
            if count != 2:
                return fail(f"rollback left {count} loans, expected 2")

            # VACUUM INTO is a consistent copy that can be opened read-only.
            quoted = str(backup).replace("'", "''")
            con.execute(f"VACUUM INTO '{quoted}'")
            copy = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
            try:
                copy_check = copy.execute("PRAGMA integrity_check").fetchone()[0]
                copy_count = copy.execute("SELECT COUNT(*) FROM loans").fetchone()[0]
            finally:
                copy.close()
            if copy_check != "ok" or copy_count != count:
                return fail(
                    f"backup check={copy_check!r} rows={copy_count}, expected ok/{count}"
                )

            # A second writer must fail cleanly instead of corrupting the file.
            writer = sqlite3.connect(db, isolation_level=None)
            second = sqlite3.connect(db, isolation_level=None)
            try:
                writer.execute("PRAGMA busy_timeout = 100")
                second.execute("PRAGMA busy_timeout = 100")
                writer.execute("BEGIN IMMEDIATE")
                try:
                    second.execute("BEGIN IMMEDIATE")
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).lower():
                        return fail(f"unexpected second-writer error: {exc}")
                else:
                    second.execute("ROLLBACK")
                    return fail("second writer acquired the write lock")
                finally:
                    writer.execute("ROLLBACK")
            finally:
                writer.close()
                second.close()

            print(f"sqlite version={sqlite3.sqlite_version} journal={journal}")
            print(f"query plan uses idx_loans_member_due; rows={count}; backup verified")
            print("SQLITE_PACK_OK")
            return 0
        finally:
            con.close()


if __name__ == "__main__":
    raise SystemExit(main())
