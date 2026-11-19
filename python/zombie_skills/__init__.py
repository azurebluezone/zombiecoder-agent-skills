"""ZombieCoder agent skills — portable SQLite store, router and injectors."""
from __future__ import annotations

from typing import Any

from .inject import inject_messages, skill_block, system_message
from .router import route, tokenize
from .store import SkillStore, default_db_path, default_jsonl_path


def route_skills(
    text: str,
    db_path: str | None = None,
    limit: int = 2,
    min_score: float = 3.0,
) -> list[dict[str, Any]]:
    """One-shot route helper; opens and closes the database for you."""
    with SkillStore(db_path) as store:
        return store.route(text, limit=limit, min_score=min_score)


def skill_terms(text: str) -> list[str]:
    """Alias for tokenize(), kept for early adopters."""
    return tokenize(text)


__all__ = [
    "SkillStore",
    "default_db_path",
    "default_jsonl_path",
    "route",
    "route_skills",
    "skill_terms",
    "tokenize",
    "inject_messages",
    "skill_block",
    "system_message",
]
__version__ = "1.0.0"
