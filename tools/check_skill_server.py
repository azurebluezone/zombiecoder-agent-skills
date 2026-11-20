#!/usr/bin/env python3
"""Prove the read-only skill server against the real library.

Run from the project root::

    python3 zombiecoder-agent-skills/tools/check_skill_server.py

The script prints SKILL_SERVER_OK only when every endpoint behaves, both
English and Bengali routing reach ``database-designer``, the card is compact,
the full body is longer, unknown tools are rejected, and ``skills.db`` is
byte-identical before and after the run.
"""
from __future__ import annotations

import hashlib
import json
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server" / "skill_server.py"
DB = ROOT / "skills.db"

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http(method: str, url: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
    except Exception as exc:  # noqa: BLE001 - the check reports the real failure
        return 0, {"error": "transport", "detail": repr(exc)}
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return status, {"error": "invalid_json", "detail": repr(exc)}
    return status, payload if isinstance(payload, dict) else {"value": payload}


def wait_for_health(base: str, proc: subprocess.Popen[str]) -> dict | None:
    deadline = time.time() + 12
    while time.time() < deadline:
        if proc.poll() is not None:
            _, stderr = proc.communicate(timeout=2)
            check(False, f"server exited early: {stderr[-600:].strip()}")
            return None
        status, payload = http("GET", base + "/health")
        if status == 200 and payload.get("ok") is True:
            return payload
        time.sleep(0.1)
    check(False, "server did not answer /health within 12s")
    return None


def main() -> int:
    if not SERVER.is_file():
        print(f"FAIL: missing server: {SERVER}")
        return 1
    if not DB.is_file():
        print(f"FAIL: missing database: {DB}")
        return 1

    before_hash = sha256(DB)
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as conn:
        expected_active = int(
            conn.execute("SELECT COUNT(*) FROM skills WHERE active = 1").fetchone()[0]
        )
        expected_terms = int(conn.execute("SELECT COUNT(*) FROM skill_terms").fetchone()[0])

    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [sys.executable, str(SERVER), "--port", str(port), "--quiet"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        health = wait_for_health(base, proc)
        if health is not None:
            check(int(health.get("skills") or 0) == expected_active,
                  f"health skills {health.get('skills')} != {expected_active}")
            check(int(health.get("terms") or 0) == expected_terms,
                  f"health terms {health.get('terms')} != {expected_terms}")

        status, payload = http(
            "GET",
            base + "/route?q=" + urllib.parse.quote("design a database schema") + "&limit=3",
        )
        check(status == 200, f"English route HTTP {status}")
        slugs = {str(match.get("slug")) for match in payload.get("matches") or []}
        check("database-designer" in slugs, f"English route missing database-designer: {slugs}")

        status, payload = http(
            "GET",
            base + "/route?q=" + urllib.parse.quote("ডেটাবেস ডিজাইন করো") + "&limit=3",
        )
        check(status == 200, f"Bengali route HTTP {status}")
        slugs = {str(match.get("slug")) for match in payload.get("matches") or []}
        check("database-designer" in slugs, f"Bengali route missing database-designer: {slugs}")

        status, payload = http("GET", base + "/skills/database-designer?mode=card")
        check(status == 200, f"card HTTP {status}")
        skill = payload.get("skill") or {}
        card = str(skill.get("card") or "")
        check(200 <= len(card) <= 1200, f"card length out of range: {len(card)}")
        check("database-designer" in card, "card is missing the slug")
        check("Design a database schema" in card, "card is missing the description")
        check("SOURCE:" in card, "card is missing the source")

        status, payload = http(
            "GET",
            base + "/skills/database-designer?mode=full&max_chars=20000",
        )
        check(status == 200, f"full HTTP {status}")
        full = payload.get("skill") or {}
        body = str(full.get("body") or "")
        check(len(body) > len(card), f"full body {len(body)} is not longer than card {len(card)}")
        check("# Database Designer" in body, "full body does not start with the real skill")
        check(full.get("content_hash") is not None, "full body is missing content_hash")

        status, payload = http("GET", base + "/skills/not-a-real-skill")
        check(status == 404, f"unknown slug HTTP {status}")
        check(payload.get("ok") is False, "unknown slug did not return ok=false")

        status, payload = http("GET", base + "/tools")
        check(status == 200, f"tools HTTP {status}")
        tools = payload.get("tools") or []
        names = {
            str(tool.get("function", {}).get("name"))
            for tool in tools
            if isinstance(tool, dict)
        }
        check(names == {"search_skills", "get_skill"}, f"unexpected tools: {names}")
        for tool in tools:
            required = tool.get("function", {}).get("parameters", {}).get("required") or []
            check(bool(required), f"tool has no required argument: {tool}")

        status, payload = http(
            "POST",
            base + "/tool-call",
            {
                "name": "search_skills",
                "arguments": {"query": "design a database schema", "limit": 3},
            },
        )
        check(status == 200, f"tool-call search HTTP {status}")
        matches = (payload.get("result") or {}).get("matches") or []
        check(
            any(match.get("slug") == "database-designer" for match in matches),
            f"tool-call search missing database-designer: {matches}",
        )

        status, payload = http(
            "POST",
            base + "/tool-call",
            {"name": "get_skill", "arguments": {"slug": "database-designer", "mode": "card"}},
        )
        check(status == 200, f"tool-call get HTTP {status}")
        tool_card = str((payload.get("result") or {}).get("card") or "")
        check("database-designer" in tool_card, "tool-call get returned no card")

        status, payload = http(
            "POST",
            base + "/tool-call",
            {"name": "run_shell", "arguments": {"cmd": "id"}},
        )
        check(status == 400, f"unknown tool HTTP {status}")
        check(payload.get("error") == "unknown_tool", f"unknown tool error: {payload}")

        status, payload = http(
            "POST",
            base + "/inject",
            {
                "text": "design a database schema",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        check(status == 200, f"inject HTTP {status}")
        messages = payload.get("messages") or []
        check(len(messages) == 2, f"inject message count {len(messages)}")
        check(bool(messages) and messages[0].get("role") == "system",
              "inject did not prepend a system message")
        check(bool(payload.get("names")), f"inject names: {payload.get('names')}")
        check(int(payload.get("block_chars") or 0) > 0, "inject block is empty")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

    after_hash = sha256(DB)
    check(before_hash == after_hash, "skills.db changed during the run")

    if FAILURES:
        for failure in FAILURES:
            print(f"FAIL: {failure}")
        return 1

    print(
        f"skill server: {expected_active} active skills, {expected_terms} terms, "
        "English + Bengali routing, card/full, 2 tools, read-only database"
    )
    print("SKILL_SERVER_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
