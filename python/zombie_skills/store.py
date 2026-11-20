"""Portable SQLite skill store for the ZombieCoder agent-skills library."""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from . import router

VALID_TABLES = {"skills", "skill_terms", "skill_sources"}


def _candidates() -> list[Path]:
    env = os.environ.get("ZOMBIE_SKILLS_DB", "").strip()
    here = Path(__file__).resolve()
    return [
        Path(env).expanduser() if env else None,
        here.parents[2] / "skills.db",          # repo layout: python/zombie_skills/store.py
        Path.cwd() / "skills.db",
        Path.home() / ".zombie-skills" / "skills.db",
    ]


def default_db_path() -> Path:
    """Return the first existing database, else the env path or repo path."""
    for candidate in _candidates():
        if candidate and candidate.is_file():
            return candidate
    env = os.environ.get("ZOMBIE_SKILLS_DB", "").strip()
    if env:
        return Path(env).expanduser()
    return Path.cwd() / "skills.db"


def default_jsonl_path() -> Path:
    """Return the JSONL export next to the database, if present."""
    env = os.environ.get("ZOMBIE_SKILLS_JSONL", "").strip()
    if env:
        return Path(env).expanduser()
    db = default_db_path()
    return db.with_name("skills.jsonl")


class SkillStore:
    """Read-only access to a `skills.db` file.

    The connection is read-only (`mode=ro` + `query_only`) and safe to share
    between threads through an internal lock. No skill body is ever executed.
    """

    def __init__(self, db_path: str | os.PathLike[str] | None = None) -> None:
        path = Path(db_path).expanduser() if db_path else default_db_path()
        if not path.is_file():
            raise FileNotFoundError(
                f"skills database not found: {path}. "
                "Set ZOMBIE_SKILLS_DB or pass db_path=..."
            )
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA query_only=ON")
        self._verify()

    def _verify(self) -> None:
        names = {
            str(row["name"])
            for row in self._conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        missing = VALID_TABLES - names
        if missing:
            raise ValueError(f"{self.path} is missing tables: {', '.join(sorted(missing))}")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "SkillStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS total, COALESCE(SUM(bytes), 0) AS bytes FROM skills"
            ).fetchone()
            active = self._conn.execute(
                "SELECT COUNT(*) AS n FROM skills WHERE active = 1"
            ).fetchone()
            terms = self._conn.execute("SELECT COUNT(*) AS n FROM skill_terms").fetchone()
            sources = [
                dict(row)
                for row in self._conn.execute(
                    "SELECT source, url, license, skill_count, status, last_synced_at "
                    "FROM skill_sources ORDER BY source"
                ).fetchall()
            ]
        return {
            "db": str(self.path),
            "db_bytes": self.path.stat().st_size,
            "total": int(row["total"]),
            "active": int(active["n"]),
            "terms": int(terms["n"]),
            "bytes": int(row["bytes"]),
            "sources": sources,
        }

    def list(
        self,
        query: str = "",
        source: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        limit = min(max(int(limit), 1), 200)
        offset = max(int(offset), 0)
        where = ["active = 1"]
        args: list[Any] = []
        if query:
            where.append("(name LIKE ? OR description LIKE ? OR tags LIKE ? OR slug LIKE ?)")
            like = f"%{query}%"
            args.extend([like, like, like, like])
        if source:
            where.append("source = ?")
            args.append(source)
        sql = (
            "SELECT id, slug, name, description, source, source_url, path, kind, license, "
            "tags, bytes, substr(body, 1, 500) AS preview, updated_at FROM skills WHERE "
            + " AND ".join(where)
            + " ORDER BY name LIMIT ? OFFSET ?"
        )
        with self._lock:
            rows = self._conn.execute(sql, (*args, limit, offset)).fetchall()
        return [dict(row) for row in rows]

    def get(self, identifier: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM skills WHERE (id = ? OR slug = ?) AND active = 1 LIMIT 1",
                (identifier, identifier),
            ).fetchone()
        return dict(row) if row else None

    def route(
        self,
        text: str,
        limit: int = 2,
        min_score: float = 3.0,
        expand: bool = True,
        intents_path: str | os.PathLike[str] | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            return router.route(
                self._conn,
                text,
                limit=limit,
                min_score=min_score,
                expand=expand,
                intents_path=intents_path,
            )

    def inject(
        self,
        messages: Iterable[dict[str, Any]],
        text: str,
        limit: int = 2,
        min_score: float = 3.0,
        per_skill: int = 1800,
        total: int = 6000,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        from .inject import inject_messages

        return inject_messages(
            self,
            messages,
            text,
            limit=limit,
            min_score=min_score,
            per_skill=per_skill,
            total=total,
        )

    def terms_for(self, skill_id: str, limit: int = 400) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT term, weight FROM skill_terms WHERE skill_id = ? "
                "ORDER BY weight DESC, term LIMIT ?",
                (skill_id, max(1, min(int(limit), 2000))),
            ).fetchall()
        return [dict(row) for row in rows]
