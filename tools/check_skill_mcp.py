#!/usr/bin/env python3
"""Prove the stdio MCP server against a real JSON-RPC client.

Run from the project root::

    python3 zombiecoder-agent-skills/tools/check_skill_mcp.py

The script spawns ``server/skill_mcp.py``, performs the MCP handshake, lists
the two tools, routes English and Bengali queries, loads a card and a full
body, checks the error paths, and verifies that ``skills.db`` is byte-identical
before and after. It prints SKILL_MCP_OK only when every condition passes.
"""
from __future__ import annotations

import hashlib
import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server" / "skill_mcp.py"
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


class McpClient:
    def __init__(self, server: Path, cwd: Path) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, str(server)],
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self.stderr = ""
        self.next_id = 1
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.error_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self.error_reader.start()

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            text = line.strip()
            if not text:
                continue
            try:
                message = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict):
                self.queue.put(message)

    def _read_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self.stderr += line

    def _send(self, payload: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: dict[str, Any] | None = None, timeout: float = 15.0) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        self._send(payload)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server exited {self.proc.returncode}: {self.stderr[-800:]}")
            try:
                message = self.queue.get(timeout=min(0.5, max(deadline - time.time(), 0.05)))
            except queue.Empty:
                continue
            if message.get("id") == request_id:
                return message
        raise TimeoutError(f"{method} timed out; stderr={self.stderr[-800:]}")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self._send(payload)

    def close(self) -> None:
        if self.proc.stdin is not None:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)


def tool_text(response: dict[str, Any]) -> str:
    result = response.get("result") or {}
    content = result.get("content") or []
    return str(content[0].get("text") if content else "")


def tool_json(response: dict[str, Any]) -> dict[str, Any]:
    text = tool_text(response)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {"error": "invalid_json", "text": text}
    return payload if isinstance(payload, dict) else {"value": payload}


def main() -> int:
    if not SERVER.is_file():
        print(f"FAIL: missing server: {SERVER}")
        return 1
    if not DB.is_file():
        print(f"FAIL: missing database: {DB}")
        return 1

    before = sha256(DB)
    client = McpClient(SERVER, ROOT)
    try:
        init = client.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "zc-skill-check", "version": "1"},
            },
        )
        result = init.get("result") or {}
        check(init.get("jsonrpc") == "2.0", "initialize is not JSON-RPC 2.0")
        check(result.get("serverInfo", {}).get("name") == "zombiecoder-skills",
              f"unexpected serverInfo: {result.get('serverInfo')}")
        check(isinstance(result.get("capabilities", {}).get("tools"), dict),
              "initialize did not advertise tools")
        check(isinstance(result.get("protocolVersion"), str), "missing protocolVersion")
        client.notify("notifications/initialized")

        listed = client.request("tools/list", {})
        tools = (listed.get("result") or {}).get("tools") or []
        names = [str(tool.get("name")) for tool in tools]
        check(set(names) == {"search_skills", "get_skill"}, f"unexpected tools: {names}")
        check(len(names) == 2, f"expected 2 tools, got {names}")
        for tool in tools:
            schema = tool.get("inputSchema") or {}
            check(schema.get("type") == "object", f"{tool.get('name')}: inputSchema is not an object")
            check(bool(schema.get("required")), f"{tool.get('name')}: inputSchema has no required field")
            check(len(str(tool.get("description") or "")) > 40,
                  f"{tool.get('name')}: description is too short")

        cases = {
            "sqlite-operations": "sqlite wal mode migration backup embedded database",
            "mysql-operations": "মাইএসকিউএল ডেটাবেস EXPLAIN ইনডেক্স",
            "hosting-deployment": "হোস্টিং ডিপ্লয় Apache vhost",
        }
        for expected, query in cases.items():
            response = client.request(
                "tools/call",
                {"name": "search_skills", "arguments": {"query": query, "limit": 3}},
            )
            check(not (response.get("result") or {}).get("isError"),
                  f"search_skills failed for {query!r}: {tool_text(response)}")
            payload = tool_json(response)
            matches = payload.get("matches") or []
            found = [str(match.get("slug")) for match in matches]
            check(found and found[0] == expected,
                  f"{query!r}: expected {expected} first, got {found}")

        card_response = client.request(
            "tools/call",
            {"name": "get_skill", "arguments": {"slug": "hosting-deployment", "mode": "card"}},
        )
        card_payload = tool_json(card_response)
        card = str(card_payload.get("card") or "")
        check(200 <= len(card) <= 1200, f"card length {len(card)} out of range")
        for marker in ("SKILL: hosting-deployment", "WHEN:", "STEPS:", "SOURCE:"):
            check(marker in card, f"card is missing {marker!r}")
        check("## " not in card, "card leaked markdown headings")

        full_response = client.request(
            "tools/call",
            {
                "name": "get_skill",
                "arguments": {"slug": "hosting-deployment", "mode": "full", "max_chars": 50000},
            },
        )
        full_payload = tool_json(full_response)
        body = str(full_payload.get("body") or "")
        check(len(body) > len(card), f"full body {len(body)} is not longer than card {len(card)}")
        check("## Verify" in body, "full body is missing the Verify section")
        check(full_payload.get("truncated") is False, "full body was unexpectedly truncated")

        unknown_tool = client.request(
            "tools/call",
            {"name": "run_shell", "arguments": {"command": "id"}},
        )
        check((unknown_tool.get("result") or {}).get("isError") is True,
              "unknown tool did not set isError")
        check("unknown tool" in tool_text(unknown_tool).lower(),
              f"unknown tool text is not explicit: {tool_text(unknown_tool)}")

        unknown_skill = client.request(
            "tools/call",
            {"name": "get_skill", "arguments": {"slug": "not-a-real-skill"}},
        )
        check((unknown_skill.get("result") or {}).get("isError") is True,
              "unknown slug did not set isError")

        unknown_method = client.request("tools/nope", {})
        error = unknown_method.get("error") or {}
        check(error.get("code") == -32601, f"unknown method returned {error}")

        ping = client.request("ping", {})
        check(ping.get("result") == {}, f"ping returned {ping.get('result')}")
    except Exception as exc:  # noqa: BLE001 - report the real failure
        check(False, f"{type(exc).__name__}: {exc}")
    finally:
        client.close()

    check(sha256(DB) == before, "skills.db changed during the MCP check")

    if FAILURES:
        for failure in FAILURES:
            print(f"FAIL: {failure}")
        return 1

    print(
        "mcp: 2 tools, initialize/tools/list/tools/call, English+Bengali, "
        "card/full, errors, ping, read-only database"
    )
    print("SKILL_MCP_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
