#!/usr/bin/env python3
"""Real MySQL 8 workflow against an isolated temporary server.

Run from the repository root:

    python3 examples/packs/mysql_example.py

The script initializes a throwaway data directory under the system temporary
directory, starts ``mysqld`` on a Unix socket, creates a schema, proves an
index with EXPLAIN, checks transaction rollback, dumps and restores the
database, and stops the server. It never touches the user's MySQL instance.

It prints MYSQL_PACK_OK only when every assertion passes.
"""
from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import mysql.connector


def fail(message: str, log: Path | None = None) -> int:
    print(f"MYSQL_PACK_FAIL: {message}")
    if log is not None and log.is_file():
        tail = log.read_text(encoding="utf-8", errors="replace")[-1800:]
        print("--- mysqld log tail ---")
        print(tail.strip())
    return 1


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, timeout=180, **kwargs)


def wait_for_server(socket_path: Path, log: Path, proc: subprocess.Popen) -> mysql.connector.MySQLConnection:
    deadline = time.time() + 45
    last_error = ""
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"mysqld exited with {proc.returncode}")
        if socket_path.exists():
            try:
                return mysql.connector.connect(
                    unix_socket=str(socket_path),
                    user="root",
                    password="",
                    connection_timeout=2,
                    autocommit=True,
                )
            except mysql.connector.Error as exc:
                last_error = str(exc)
        time.sleep(0.25)
    raise RuntimeError(f"mysqld did not accept a connection: {last_error}")


def main() -> int:
    mysqld = shutil.which("mysqld")
    mysqldump = shutil.which("mysqldump")
    mysql = shutil.which("mysql")
    if not mysqld or not mysqldump or not mysql:
        return fail("mysqld, mysqldump and mysql must all be on PATH")

    tmp = Path(tempfile.mkdtemp(prefix="zc-mysql-"))
    data = tmp / "data"
    socket_path = tmp / "mysql.sock"
    pid_file = tmp / "mysql.pid"
    log = tmp / "mysql.log"
    init_log = tmp / "init.log"
    proc: subprocess.Popen | None = None
    conn: mysql.connector.MySQLConnection | None = None

    try:
        data.mkdir()
        init = run(
            [
                mysqld,
                "--no-defaults",
                "--basedir=/usr",
                f"--datadir={data}",
                "--initialize-insecure",
                f"--log-error={init_log}",
            ]
        )
        if init.returncode != 0:
            return fail(f"initialize-insecure failed ({init.returncode})", init_log)

        proc = subprocess.Popen(
            [
                mysqld,
                "--no-defaults",
                "--basedir=/usr",
                f"--datadir={data}",
                f"--socket={socket_path}",
                f"--pid-file={pid_file}",
                f"--log-error={log}",
                "--port=0",
                "--mysqlx=0",
                "--skip-networking",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        conn = wait_for_server(socket_path, log, proc)
        cur = conn.cursor()

        cur.execute(
            "CREATE DATABASE library CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
        )
        cur.execute("USE library")
        cur.execute(
            "CREATE TABLE members ("
            "id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, "
            "email VARCHAR(255) NOT NULL UNIQUE, "
            "joined_at DATE NOT NULL"
            ") ENGINE=InnoDB"
        )
        cur.execute(
            "CREATE TABLE books ("
            "id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, "
            "isbn CHAR(13) NOT NULL UNIQUE, "
            "title VARCHAR(255) NOT NULL"
            ") ENGINE=InnoDB"
        )
        cur.execute(
            "CREATE TABLE loans ("
            "id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, "
            "member_id BIGINT UNSIGNED NOT NULL, "
            "book_id BIGINT UNSIGNED NOT NULL, "
            "loaned_at DATE NOT NULL, "
            "due_date DATE NOT NULL, "
            "returned_at DATE NULL, "
            "CONSTRAINT fk_loans_member FOREIGN KEY (member_id) REFERENCES members(id), "
            "CONSTRAINT fk_loans_book FOREIGN KEY (book_id) REFERENCES books(id), "
            "INDEX idx_loans_member_due (member_id, due_date)"
            ") ENGINE=InnoDB"
        )

        cur.executemany(
            "INSERT INTO members(email, joined_at) VALUES (%s, %s)",
            [("a@example.test", "2026-01-01"), ("b@example.test", "2026-02-01")],
        )
        cur.executemany(
            "INSERT INTO books(isbn, title) VALUES (%s, %s)",
            [("9780000000001", "Book One"), ("9780000000002", "Book Two")],
        )
        cur.executemany(
            "INSERT INTO loans(member_id, book_id, loaned_at, due_date) "
            "VALUES (%s, %s, %s, %s)",
            [(1, 1, "2026-11-01", "2026-11-15"), (1, 2, "2026-11-10", "2026-11-24")],
        )

        cur.execute(
            "EXPLAIN SELECT * FROM loans WHERE member_id = 1 ORDER BY due_date"
        )
        columns = [str(column[0]) for column in cur.description]
        rows = cur.fetchall()
        key_index = columns.index("key") if "key" in columns else -1
        if key_index < 0:
            return fail(f"EXPLAIN has no key column: {columns}")
        chosen = {str(row[key_index]) for row in rows}
        if "idx_loans_member_due" not in chosen:
            return fail(f"EXPLAIN chose {sorted(chosen)}, expected idx_loans_member_due")

        cur.execute(
            "EXPLAIN ANALYZE SELECT * FROM loans WHERE member_id = 1 ORDER BY due_date"
        )
        analyze = " ".join(str(row[0]) for row in cur.fetchall())
        if "idx_loans_member_due" not in analyze:
            return fail("EXPLAIN ANALYZE did not use idx_loans_member_due")

        cur.execute("START TRANSACTION")
        cur.execute(
            "INSERT INTO loans(member_id, book_id, loaned_at, due_date) "
            "VALUES (2, 1, '2026-11-20', '2026-12-04')"
        )
        cur.execute("ROLLBACK")
        cur.execute("SELECT COUNT(*) FROM loans")
        count = int(cur.fetchone()[0])
        if count != 2:
            return fail(f"rollback left {count} loans, expected 2")

        cur.execute("SHOW CREATE TABLE loans")
        create_sql = str(cur.fetchone()[1])
        if "idx_loans_member_due" not in create_sql:
            return fail("SHOW CREATE TABLE is missing the index")

        cur.execute("CHECK TABLE loans")
        check_row = cur.fetchone()
        if not check_row or str(check_row[-1]).upper() != "OK":
            return fail(f"CHECK TABLE returned {check_row!r}")

        dump = run(
            [
                mysqldump,
                "--protocol=SOCKET",
                f"--socket={socket_path}",
                "-uroot",
                "--single-transaction",
                "--routines",
                "--triggers",
                "library",
            ]
        )
        if dump.returncode != 0 or "CREATE TABLE" not in dump.stdout:
            return fail(f"mysqldump failed ({dump.returncode}): {dump.stderr[-500:]}")

        cur.execute(
            "CREATE DATABASE library_restore CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
        )
        restore = run(
            [
                mysql,
                "--protocol=SOCKET",
                f"--socket={socket_path}",
                "-uroot",
                "library_restore",
            ],
            input=dump.stdout,
        )
        if restore.returncode != 0:
            return fail(f"mysql restore failed ({restore.returncode}): {restore.stderr[-500:]}")

        cur.execute(
            "CHECKSUM TABLE library.loans, library_restore.loans"
        )
        checksums = {str(row[0]): row[1] for row in cur.fetchall()}
        source_sum = checksums.get("library.loans")
        restore_sum = checksums.get("library_restore.loans")
        if source_sum is None or source_sum != restore_sum:
            return fail(f"checksum mismatch: {checksums}")

        cur.execute("DROP DATABASE library_restore")
        cur.execute("DROP DATABASE library")
        print(f"mysql {conn.get_server_info()} isolated socket={socket_path.name}")
        print(f"EXPLAIN used idx_loans_member_due; rows={count}; dump/restore checksum={source_sum}")
        print("MYSQL_PACK_OK")
        return 0
    except Exception as exc:  # noqa: BLE001 - report the real failure
        return fail(f"{type(exc).__name__}: {exc}", log)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
