"""Deterministic keyword router shared by the CLI, server and tests."""
from __future__ import annotations

import re
import sqlite3
from typing import Any

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


def route(
    conn: sqlite3.Connection,
    text: str,
    limit: int = 2,
    min_score: float = 3.0,
) -> list[dict[str, Any]]:
    """Score skills by term weight divided by document frequency.

    A term stored in hundreds of skills ("file", "download") is weak evidence;
    rare terms dominate. Exact name and slug matches get a bonus.
    """
    tokens = tokenize(text)[:40]
    if not tokens:
        return []
    marks = ",".join("?" for _ in tokens)
    rows = conn.execute(
        f"SELECT term, skill_id, weight FROM skill_terms WHERE term IN ({marks})",
        tokens,
    ).fetchall()
    if not rows:
        return []
    frequencies = {
        str(row["term"]): int(row["n"])
        for row in conn.execute(
            f"SELECT term, COUNT(*) AS n FROM skill_terms WHERE term IN ({marks}) GROUP BY term",
            tokens,
        ).fetchall()
    }
    scores: dict[str, float] = {}
    matched_terms: dict[str, int] = {}
    for row in rows:
        skill_id = str(row["skill_id"])
        frequency = max(frequencies.get(str(row["term"]), 1), 1)
        contribution = max(0.15, int(row["weight"]) / (frequency ** 0.4))
        scores[skill_id] = scores.get(skill_id, 0.0) + contribution
        matched_terms[skill_id] = matched_terms.get(skill_id, 0) + 1
    if not scores:
        return []
    shortlist = sorted(scores, key=lambda sid: -scores[sid])[: max(int(limit) * 4, 8)]
    id_marks = ",".join("?" for _ in shortlist)
    meta = {
        str(row["id"]): dict(row)
        for row in conn.execute(
            f"SELECT id, slug, name, description, source, kind, body "
            f"FROM skills WHERE id IN ({id_marks}) AND active = 1",
            shortlist,
        ).fetchall()
    }
    haystack = (text or "").lower()
    matches: list[dict[str, Any]] = []
    for skill_id, base in scores.items():
        row = meta.get(skill_id)
        if not row:
            continue
        score = float(base)
        # Several independent query terms pointing at one skill is stronger
        # evidence than a single rare term.
        score += 0.35 * max(matched_terms.get(skill_id, 1) - 1, 0)
        if str(row.get("name") or "").lower() in haystack:
            score += 10.0
        if str(row.get("slug") or "").replace("-", " ") in haystack:
            score += 6.0
        if score < min_score:
            continue
        row["score"] = round(score, 2)
        matches.append(row)
    matches.sort(key=lambda row: -row["score"])
    # Two sources can publish the same skill name; inject the best copy only.
    top: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()
    for match in matches:
        slug = str(match.get("slug") or "")
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        top.append(match)
        if len(top) >= max(int(limit), 1):
            break
    return top
