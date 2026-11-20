#!/usr/bin/env python3
"""Prove the PHP, C++ and CDP packs end to end.

Run from the project root::

    python3 zombiecoder-agent-skills/tools/check_extra_packs.py

The script prints EXTRA_PACKS_OK only when all of these are true:

* ``packs/<slug>/SKILL.md`` exists with frontmatter, workflow steps, a failure
  path, verification and provenance;
* ``skills.db`` contains each slug once, active, from the local pack source,
  with a content hash that matches the source file;
* ``skills.meta.json`` and the JSONL exports match the database;
* the HTTP server routes English and Bengali queries to each slug, renders a
  compact card and a longer full body;
* ``php_example.php`` starts a real ``php -S`` server and checks JSON, the
  nosniff header and a 404;
* ``cpp_example.cpp`` compiles with ``g++ -std=c++17 -Wall -Wextra -Wpedantic
  -Werror`` and runs;
* ``cdp_example.mjs`` launches a real Chromium, speaks CDP over a WebSocket,
  evaluates the page and captures a screenshot;
* ``skills.db`` is byte-identical before and after the read-only server part.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
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
DB = ROOT / "skills.db"
META = ROOT / "skills.meta.json"
PACKS = ROOT / "packs"
EXAMPLES = ROOT / "examples" / "packs"
SERVER = ROOT / "server" / "skill_server.py"
SOURCE = "local/zombiecoder-packs"
BUILD = Path("/tmp/opencode/extra-pack-build")

SLUGS = ("php-operations", "cpp-operations", "cdp-operations")
EXPECTED_LOCAL_SKILLS = 8

CASES = {
    "php-operations": (
        "php fpm opcache deployment composer pdo prepared statement",
        "পিএইচপি ডিপ্লয় opcache fpm",
    ),
    "cpp-operations": (
        "c++ cmake sanitizer raii compiler build",
        "সি++ বিল্ড cmake sanitizer",
    ),
    "cdp-operations": (
        "chrome devtools protocol headless browser automation screenshot",
        "ক্রোম ডেভটুলস প্রোটোকল headless",
    ),
}

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


def http(method: str, url: str) -> tuple[int, dict]:
    request = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
    except Exception as exc:  # noqa: BLE001 - report the real transport error
        return 0, {"error": "transport", "detail": repr(exc)}
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return status, {"error": "invalid_json", "detail": repr(exc)}
    return status, payload if isinstance(payload, dict) else {"value": payload}


def wait_for_health(base: str, proc: subprocess.Popen[str]) -> dict | None:
    deadline = time.time() + 15
    while time.time() < deadline:
        if proc.poll() is not None:
            _, stderr = proc.communicate(timeout=2)
            check(False, f"server exited early: {stderr[-600:].strip()}")
            return None
        status, payload = http("GET", base + "/health")
        if status == 200 and payload.get("ok") is True:
            return payload
        time.sleep(0.1)
    check(False, "server did not answer /health within 15s")
    return None


def frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    data: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if ":" in line and not line.startswith((" ", "\t")):
            key, value = line.split(":", 1)
            data[key.strip().lower()] = value.strip().strip("\"'")
    return data


def check_pack_files() -> None:
    for slug in SLUGS:
        path = PACKS / slug / "SKILL.md"
        check(path.is_file(), f"missing pack file: {path.relative_to(ROOT)}")
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        meta = frontmatter(text)
        check(meta.get("name") == slug, f"{slug}: frontmatter name is {meta.get('name')!r}")
        check(bool(meta.get("description")), f"{slug}: missing description")
        check(meta.get("license") == "MIT", f"{slug}: license is {meta.get('license')!r}")
        check(meta.get("source") == SOURCE, f"{slug}: source is {meta.get('source')!r}")
        check(meta.get("source_url", "").startswith("https://"), f"{slug}: source_url is not https")
        for marker in ("## Workflow", "### Step 1", "## Failure path", "## Verify", "## Provenance"):
            check(marker in text, f"{slug}: missing {marker!r}")
        check(len(text.encode("utf-8")) > 2500, f"{slug}: body is too small to be a real runbook")


def check_database() -> tuple[int, int, dict[str, str]]:
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        active = int(conn.execute("SELECT COUNT(*) FROM skills WHERE active = 1").fetchone()[0])
        terms = int(
            conn.execute(
                "SELECT COUNT(*) FROM skill_terms t JOIN skills s ON s.id = t.skill_id "
                "WHERE s.active = 1"
            ).fetchone()[0]
        )
        ids: dict[str, str] = {}
        for slug in SLUGS:
            rows = conn.execute(
                "SELECT id, slug, name, body, path, source, license, content_hash, bytes, active "
                "FROM skills WHERE slug = ?",
                (slug,),
            ).fetchall()
            check(len(rows) == 1, f"{slug}: expected one database row, got {len(rows)}")
            if not rows:
                continue
            row = rows[0]
            ids[slug] = str(row["id"])
            check(int(row["active"]) == 1, f"{slug}: row is not active")
            check(row["source"] == SOURCE, f"{slug}: source is {row['source']!r}")
            check(row["license"] == "MIT", f"{slug}: license is {row['license']!r}")
            check(
                row["path"] == f"packs/{slug}/SKILL.md",
                f"{slug}: database path is {row['path']!r}",
            )
            check(
                bool(re.fullmatch(r"[0-9a-f]{64}", str(row["content_hash"] or ""))),
                f"{slug}: content_hash is not sha256",
            )
            source_file = PACKS / slug / "SKILL.md"
            if source_file.is_file():
                check(
                    sha256(source_file) == str(row["content_hash"]),
                    f"{slug}: database hash does not match packs/{slug}/SKILL.md",
                )
            body_bytes = len(str(row["body"]).encode("utf-8"))
            check(body_bytes == int(row["bytes"]), f"{slug}: bytes column does not match body")
            check(body_bytes > 2500, f"{slug}: stored body is too small")
        return active, terms, ids


def check_exports(active: int, terms: int, ids: dict[str, str]) -> None:
    check(META.is_file(), "missing skills.meta.json")
    if not META.is_file():
        return
    meta = json.loads(META.read_text(encoding="utf-8"))
    check(int(meta.get("skills") or 0) == active, f"meta skills {meta.get('skills')} != {active}")
    check(int(meta.get("terms") or 0) == terms, f"meta terms {meta.get('terms')} != {terms}")
    digest = str((meta.get("files") or {}).get("skills.db", {}).get("sha256") or "")
    check(digest == sha256(DB), "skills.meta.json does not hash the current skills.db")
    sources = {str(item.get("source")): item for item in meta.get("sources") or []}
    local = sources.get(SOURCE)
    check(local is not None, f"meta is missing source {SOURCE}")
    if local is not None:
        check(
            int(local.get("skills") or 0) >= EXPECTED_LOCAL_SKILLS,
            f"meta local source count is {local.get('skills')}, expected >= {EXPECTED_LOCAL_SKILLS}",
        )

    skill_lines = (ROOT / "skills.jsonl").read_text(encoding="utf-8").splitlines()
    check(len(skill_lines) == active, f"skills.jsonl has {len(skill_lines)} rows, expected {active}")
    jsonl_slugs = set()
    for line in skill_lines:
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("slug") in SLUGS:
            jsonl_slugs.add(str(item.get("slug")))
            check(item.get("source") == SOURCE, f"{item.get('slug')}: JSONL source mismatch")
    check(jsonl_slugs == set(SLUGS), f"skills.jsonl missing slugs: {set(SLUGS) - jsonl_slugs}")

    term_lines = (ROOT / "terms.jsonl").read_text(encoding="utf-8").splitlines()
    check(len(term_lines) == terms, f"terms.jsonl has {len(term_lines)} rows, expected {terms}")
    seen_ids = {str(json.loads(line).get("skill_id")) for line in term_lines if line.strip()}
    for slug, skill_id in ids.items():
        check(skill_id in seen_ids, f"{slug}: no term rows in terms.jsonl")


def check_server(active: int, terms: int) -> None:
    before = sha256(DB)
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
            check(int(health.get("skills") or 0) == active, f"health skills {health.get('skills')} != {active}")
            check(int(health.get("terms") or 0) == terms, f"health terms {health.get('terms')} != {terms}")

        for slug, (english, bengali) in CASES.items():
            for label, query in (("English", english), ("Bengali", bengali)):
                status, payload = http(
                    "GET",
                    base + "/route?q=" + urllib.parse.quote(query) + "&limit=3",
                )
                check(status == 200, f"{slug} {label} route HTTP {status}: {payload}")
                found = [str(match.get("slug")) for match in payload.get("matches") or []]
                check(slug in found, f"{slug} {label} route missed it: {found}")

            status, payload = http("GET", base + f"/skills/{slug}?mode=card")
            check(status == 200, f"{slug} card HTTP {status}")
            skill = payload.get("skill") or {}
            card = str(skill.get("card") or "")
            check(200 <= len(card) <= 1200, f"{slug} card length {len(card)} out of 200..1200")
            for marker in (f"SKILL: {slug}", "WHEN:", "STEPS:", "SOURCE:"):
                check(marker in card, f"{slug} card is missing {marker!r}")
            check("## " not in card, f"{slug} card leaked markdown headings")

            status, payload = http(
                "GET", base + f"/skills/{slug}?mode=full&max_chars=50000"
            )
            check(status == 200, f"{slug} full HTTP {status}")
            full = payload.get("skill") or {}
            body = str(full.get("body") or "")
            check(len(body) > len(card), f"{slug} full body {len(body)} <= card {len(card)}")
            check("## Verify" in body, f"{slug} full body is missing the Verify section")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
    check(sha256(DB) == before, "skills.db changed during the read-only server check")


def run_command(label: str, command: list[str], marker: str | None, timeout: int) -> None:
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        check(False, f"{label}: executable not found: {command[0]}")
        return
    except subprocess.TimeoutExpired:
        check(False, f"{label} timed out after {timeout}s")
        return
    output = (result.stdout or "").strip()
    if output:
        print(f"--- {label} ---")
        print(output[-2200:])
    if result.returncode != 0:
        detail = (result.stderr or output)[-1200:]
        check(False, f"{label} exited {result.returncode}: {detail}")
        return
    if marker is not None:
        check(marker in result.stdout, f"{label} did not print {marker}")


def run_examples() -> None:
    php = shutil.which("php")
    if php is None:
        check(False, "php is not installed")
    else:
        run_command("php_example.php", [php, str(EXAMPLES / "php_example.php")], "PHP_PACK_OK", 60)

    gxx = shutil.which("g++")
    if gxx is None:
        check(False, "g++ is not installed")
    else:
        BUILD.mkdir(parents=True, exist_ok=True)
        binary = BUILD / "cpp_example"
        run_command(
            "cpp_example.cpp (compile)",
            [
                gxx,
                "-std=c++17",
                "-Wall",
                "-Wextra",
                "-Wpedantic",
                "-Werror",
                "-O2",
                "-g",
                "-o",
                str(binary),
                str(EXAMPLES / "cpp_example.cpp"),
            ],
            None,
            120,
        )
        if binary.is_file():
            run_command("cpp_example.cpp (run)", [str(binary)], "CPP_PACK_OK", 60)
        else:
            check(False, "cpp_example.cpp (compile) did not produce a binary")

    node = shutil.which("node")
    if node is None:
        check(False, "node is not installed")
    else:
        run_command("cdp_example.mjs", [node, str(EXAMPLES / "cdp_example.mjs")], "CDP_PACK_OK", 120)


def main() -> int:
    if not DB.is_file():
        print(f"FAIL: missing database: {DB}")
        return 1
    if not SERVER.is_file():
        print(f"FAIL: missing server: {SERVER}")
        return 1

    check_pack_files()
    active, terms, ids = check_database()
    check_exports(active, terms, ids)
    check_server(active, terms)
    run_examples()

    if FAILURES:
        for failure in FAILURES:
            print(f"FAIL: {failure}")
        return 1

    print(
        f"packs={len(SLUGS)} active={active} terms={terms} "
        "english+bengali routing, cards, full bodies, 3 real examples"
    )
    print("EXTRA_PACKS_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
