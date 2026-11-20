#!/usr/bin/env python3
"""Read-only MCP stdio server for the ZombieCoder skill library.

This is a separate module from the OpenCode plugin. It exposes the same two
tools as ``server/skill_server.py`` over the Model Context Protocol:

    search_skills(query, limit)   find skills by English or Bengali intent
    get_skill(slug, mode)         load a compact card or the full body

The server reads ``skills.db`` in SQLite read-only mode, writes JSON-RPC
responses to stdout, writes logs to stderr, and never executes a skill body.

OpenCode config (project-local, separate from the plugin)::

    {
      "mcp": {
        "servers": {
          "skills": {
            "type": "local",
            "command": ["python3", "/absolute/path/server/skill_mcp.py"]
          }
        }
      }
    }
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "server"))

from zombie_skills import SkillStore  # noqa: E402
from skill_server import (  # noqa: E402
    DEFAULT_CARD_CHARS,
    MAX_CARD_CHARS,
    MAX_FULL_CHARS,
    MIN_CARD_CHARS,
    TOOL_SPECS,
    compact_card,
    public_match,
)

VERSION = "1.0.0"
SERVER_NAME = "zombiecoder-skills"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
ALLOWED_TOOLS = "search_skills, get_skill"

MCP_TOOLS = [
    {
        "name": spec["function"]["name"],
        "description": spec["function"]["description"],
        "inputSchema": spec["function"]["parameters"],
    }
    for spec in TOOL_SPECS
]


def text_result(payload: Any, is_error: bool = False) -> dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(
        payload, ensure_ascii=False, indent=2
    )
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["isError"] = True
    return result


def call_tool(store: SkillStore, name: str, arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        return text_result("Error: arguments_object_required", True)

    if name == "search_skills":
        query = str(arguments.get("query") or "").strip()
        if not query:
            return text_result("Error: missing_query", True)
        try:
            limit = max(1, min(int(arguments.get("limit") or 3), 5))
        except (TypeError, ValueError):
            return text_result("Error: invalid_limit", True)
        matches = store.route(query, limit=limit)
        return text_result(
            {
                "query": query,
                "matches": [public_match(match) for match in matches],
            }
        )

    if name == "get_skill":
        slug = str(arguments.get("slug") or "").strip()
        if not SLUG_RE.match(slug):
            return text_result("Error: invalid_slug", True)
        skill = store.get(slug)
        if not skill:
            return text_result(f"Error: not_found {slug}", True)
        mode = str(arguments.get("mode") or "card").lower()
        if mode not in {"card", "full"}:
            return text_result("Error: invalid_mode (card or full)", True)
        try:
            requested = int(arguments.get("max_chars") or DEFAULT_CARD_CHARS)
        except (TypeError, ValueError):
            return text_result("Error: invalid_max_chars", True)
        if mode == "card":
            max_chars = max(MIN_CARD_CHARS, min(requested, MAX_CARD_CHARS))
            return text_result(
                {
                    "slug": skill.get("slug"),
                    "name": skill.get("name"),
                    "mode": "card",
                    "card": compact_card(skill, max_chars=max_chars),
                }
            )
        max_chars = max(MIN_CARD_CHARS, min(requested, MAX_FULL_CHARS))
        body = str(skill.get("body") or "")
        return text_result(
            {
                "slug": skill.get("slug"),
                "name": skill.get("name"),
                "mode": "full",
                "body": body[:max_chars],
                "truncated": len(body) > max_chars,
            }
        )

    return text_result(
        f'Error: unknown tool "{name}"; allowed: {ALLOWED_TOOLS}', True
    )


def error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def handle_rpc(request: dict[str, Any], store: SkillStore) -> dict[str, Any]:
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params")
    if not isinstance(params, dict):
        params = {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": str(params.get("protocolVersion") or "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": VERSION},
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": MCP_TOOLS}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/call":
        name = str(params.get("name") or "")
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": call_tool(store, name, params.get("arguments")),
        }
    return error_response(request_id, -32601, f"Method not found: {method}")


def write_message(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    store = SkillStore(ROOT / "skills.db")
    print(
        f"{SERVER_NAME} MCP {VERSION} (stdio, read-only, {ROOT / 'skills.db'})",
        file=sys.stderr,
        flush=True,
    )
    try:
        for line in sys.stdin:
            text = line.strip()
            if not text:
                continue
            try:
                request = json.loads(text)
            except json.JSONDecodeError:
                write_message(error_response(None, -32700, "Parse error"))
                continue
            if not isinstance(request, dict):
                write_message(error_response(None, -32600, "Invalid Request"))
                continue
            if request.get("id") is None:
                # MCP notifications (for example notifications/initialized)
                # have no response.
                continue
            try:
                response = handle_rpc(request, store)
            except Exception as exc:  # noqa: BLE001 - keep the server alive
                response = error_response(
                    request.get("id"), -32603, f"Internal error: {exc}"
                )
            write_message(response)
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
