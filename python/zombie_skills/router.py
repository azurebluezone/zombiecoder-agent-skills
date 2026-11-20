"""Deterministic keyword router shared by the CLI, server and tests."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any

DEFAULT_INTENTS = Path(__file__).resolve().parents[2] / "data" / "bn-intents.json"
_MAX_INTENT_CACHE = 4
_INTENTS_CACHE: dict[str, dict[str, Any]] = {}
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


def normalize_text(text: str) -> str:
    """Normalise Bengali text to NFC.

    Unicode decomposes yya, rra and rha to base + nukta, so precomposed and
    decomposed keyboard input meet on the same spelling.
    """
    return unicodedata.normalize("NFC", str(text or ""))


def _intent_candidates() -> list[Path]:
    """Default bridge locations: repo layout, vendored project, user cache."""
    return [
        DEFAULT_INTENTS,
        Path.cwd() / "data" / "bn-intents.json",
        Path.home() / ".zombie-skills" / "data" / "bn-intents.json",
    ]


def load_intents(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Load the Bengali intent bridge, or an empty bridge if it is absent.

    An explicitly configured path (argument or ZOMBIE_SKILLS_INTENTS) must
    exist; a missing default file keeps the library English-only instead of
    breaking an installed package.
    """
    env = os.environ.get("ZOMBIE_SKILLS_INTENTS", "").strip()
    explicit = bool(path or env)
    if path:
        target = Path(path).expanduser()
    elif env:
        target = Path(env).expanduser()
    else:
        target = next(
            (candidate for candidate in _intent_candidates() if candidate.is_file()),
            DEFAULT_INTENTS,
        )
    key = str(target)
    cached = _INTENTS_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        entries = [
            {"bn": normalize_text(str(entry.get("bn"))), "en": str(entry.get("en"))}
            for entry in (raw.get("entries") or [])
            if isinstance(entry, dict) and entry.get("bn") and entry.get("en")
        ]
        entries.sort(key=lambda entry: (-len(entry["bn"]), entry["bn"]))
        data = {
            "schema_version": str(raw.get("schema_version") or ""),
            "locale": str(raw.get("locale") or ""),
            "max_terms": int(raw.get("max_terms") or 24),
            "entries": entries,
        }
    except Exception as exc:
        if explicit:
            raise FileNotFoundError(f"intent bridge unavailable: {target} ({exc})") from exc
        data = {"schema_version": "", "locale": "", "max_terms": 0, "entries": []}
    if len(_INTENTS_CACHE) >= _MAX_INTENT_CACHE:
        _INTENTS_CACHE.clear()
    _INTENTS_CACHE[key] = data
    return data


def expand_query(
    text: str,
    intents: dict[str, Any] | None = None,
    path: str | os.PathLike[str] | None = None,
) -> str:
    """Expand Bengali intent into English retrieval terms.

    Entries are applied longest first, so a phrase wins over one of its words.
    The cap keeps the rewritten query inside the router's token budget.
    """
    source = normalize_text(text)
    data = intents if intents is not None else load_intents(path)
    entries = data.get("entries") or []
    if not entries:
        return source
    limit = max(int(data.get("max_terms") or 24), 1)
    output = source
    added = 0
    applied = 0
    for entry in entries:
        bengali = entry["bn"]
        if bengali not in output:
            continue
        occurrences = output.count(bengali)
        english_terms = len(entry["en"].split()) * occurrences
        if added + english_terms > limit:
            continue
        output = output.replace(bengali, f" {entry['en']} ")
        added += english_terms
        applied += occurrences
        if applied >= limit:
            break
    output = re.sub(r"[ \t]{2,}", " ", output)
    output = re.sub(r"\s+([,.;:!?])", r"\1", output)
    return output.strip()


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
    expand: bool = True,
    intents_path: str | os.PathLike[str] | None = None,
) -> list[dict[str, Any]]:
    """Score skills by term weight divided by document frequency.

    A term stored in hundreds of skills ("file", "download") is weak evidence;
    rare terms dominate. Exact name and slug matches get a bonus. Bengali
    input is expanded through the intent bridge before scoring; pass
    expand=False to route the raw text.
    """
    query = expand_query(text, path=intents_path) if expand else normalize_text(text)
    tokens = tokenize(query)[:40]
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
    haystack = (query or "").lower()
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
