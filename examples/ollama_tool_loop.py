#!/usr/bin/env python3
"""Run a real small-model tool loop against the local skill server.

Requires Ollama on 127.0.0.1:11434 with a tools-capable model. The default
``lfm3:1.7b`` produced a native ``get_skill`` call in this project's live probe.

The pattern is deliberately small-model friendly:

1. The deterministic router selects the top three skills (no model needed).
2. The model gets one tool, ``get_skill``, and must load the best card.
3. If the model skips the tool, the system loads the top card and asks the
   model to answer from it, so the demo still completes and the trace shows
   the fallback.

    python3 examples/ollama_tool_loop.py
    python3 examples/ollama_tool_loop.py --model lfm3:1.7b --task "..."

This is a loader demo, not an autonomous agent. It does not write files or run
shell commands.
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server" / "skill_server.py"
OLLAMA = "http://127.0.0.1:11434"
DEFAULT_MODEL = "lfm3:1.7b"
DEFAULT_TASK = "List the entities, relationships and first schema step for a small library app with books, members and loans."

SYSTEM = """You are a careful coding assistant. The router selected this skill: {slug}.

Call get_skill with slug="{slug}" and mode="card". Make one tool call and do not explain before it.
After the card arrives, use it to answer the task. Do not invent steps that are not in the card."""


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http_json(method: str, url: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
    except Exception as exc:  # noqa: BLE001 - callers decide whether to retry
        return 0, {"error": "transport", "detail": repr(exc)}
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {"raw": raw[:500].decode("utf-8", "replace")}
    return status, payload if isinstance(payload, dict) else {"value": payload}


def wait_health(base: str, proc: subprocess.Popen[str]) -> bool:
    deadline = time.time() + 12
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        status, payload = http_json("GET", base + "/health")
        if status == 200 and payload.get("ok") is True:
            return True
        time.sleep(0.1)
    return False


def chat(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    max_tokens: int = 768,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": 0,
        "max_tokens": max_tokens,
        "think": False,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    status, data = http_json("POST", OLLAMA + "/v1/chat/completions", payload)
    if status != 200:
        raise RuntimeError(f"Ollama HTTP {status}: {json.dumps(data, ensure_ascii=False)[:600]}")
    return data


def message_of(data: dict[str, Any]) -> tuple[dict[str, Any], str]:
    choice = (data.get("choices") or [{}])[0]
    return choice.get("message") or {}, str(choice.get("finish_reason") or "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Small-model skill tool loop")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--task", default=DEFAULT_TASK)
    args = parser.parse_args(argv)

    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [sys.executable, str(SERVER), "--port", str(port), "--quiet"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    used_tool_call = False
    final = ""
    try:
        if not wait_health(base, proc):
            stderr = ""
            if proc.poll() is not None:
                _, stderr = proc.communicate(timeout=2)
            print(f"FAIL: skill server did not start: {stderr[-400:].strip()}")
            return 1

        status, route = http_json(
            "GET",
            base + "/route?q=" + urllib.parse.quote(args.task) + "&limit=3",
        )
        matches = route.get("matches") or []
        if status != 200 or not matches:
            print(f"FAIL: route returned HTTP {status}: {route}")
            return 1
        print(f"MODEL {args.model}")
        print(f"TASK {args.task}")
        for match in matches:
            print(
                f"ROUTE {match.get('slug')} score={match.get('score')} "
                f"source={match.get('source')}"
            )

        status, tools_payload = http_json("GET", base + "/tools")
        tools = [
            tool
            for tool in tools_payload.get("tools") or []
            if tool.get("function", {}).get("name") == "get_skill"
        ]
        if status != 200 or not tools:
            print(f"FAIL: /tools returned HTTP {status}: {tools_payload}")
            return 1

        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": SYSTEM.format(slug=matches[0].get("slug")),
            },
            {"role": "user", "content": args.task},
        ]

        data = chat(args.model, messages, tools, max_tokens=400)
        message, finish = message_of(data)
        calls = message.get("tool_calls") or []
        print(
            f"ROUND 1 finish={finish} content={len(message.get('content') or '')} "
            f"reasoning={len(message.get('reasoning') or '')} tools={len(calls)}"
        )

        if calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": message.get("content") or "",
                    "tool_calls": calls,
                }
            )
            for call in calls:
                function = call.get("function") or {}
                name = str(function.get("name") or "")
                raw_args = function.get("arguments") or "{}"
                try:
                    arguments = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    arguments = {}
                print(f"  CALL {name} {json.dumps(arguments, ensure_ascii=False)[:300]}")
                status, result = http_json(
                    "POST",
                    base + "/tool-call",
                    {"name": name, "arguments": arguments},
                )
                if name == "get_skill" and status == 200:
                    used_tool_call = True
                summary = json.dumps(result, ensure_ascii=False)
                print(f"  RESULT HTTP {status} {summary[:300]}")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id") or "",
                        "name": name,
                        "content": summary[:8000],
                    }
                )
        else:
            print("  FALLBACK model skipped get_skill; loading the top card")
            status, result = http_json(
                "POST",
                base + "/tool-call",
                {
                    "name": "get_skill",
                    "arguments": {"slug": matches[0].get("slug"), "mode": "card"},
                },
            )
            card = (result.get("result") or {}).get("card") or ""
            print(f"  RESULT HTTP {status} card_chars={len(card)}")
            messages.append(
                {
                    "role": "system",
                    "content": "Use this skill card to answer the task:\n\n" + card,
                }
            )

        messages.append(
            {
                "role": "system",
                "content": (
                    "Answer the task in 8 short bullets using only the card. "
                    "Start with the entities, then the relationships, then the first step. "
                    "No preamble, no repetition of the card."
                ),
            }
        )
        data = chat(args.model, messages, None, max_tokens=1600)
        message, finish = message_of(data)
        final = str(message.get("content") or "").strip()
        print(
            f"ROUND 2 finish={finish} content={len(final)} "
            f"reasoning={len(message.get('reasoning') or '')}"
        )

        if final:
            print("FINAL")
            print(final)
        else:
            print("FINAL <empty>")

        lowered = final.lower()
        entity_hits = sum(term in lowered for term in ("book", "member", "loan"))
        if used_tool_call and len(final) >= 80 and entity_hits >= 2:
            print("OLLAMA_SKILL_LOOP_OK")
            return 0
        print(
            "OLLAMA_SKILL_LOOP_INCOMPLETE "
            f"used_tool_call={used_tool_call} final_chars={len(final)} "
            f"entity_hits={entity_hits}"
        )
        return 2
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
