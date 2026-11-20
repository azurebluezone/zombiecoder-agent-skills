#!/usr/bin/env python3
"""Prove the documented onboarding paths end to end.

Run from the project root::

    python3 zombiecoder-agent-skills/tools/check_agent_onboarding.py

The script prints ``AGENT_ONBOARDING_OK`` only when every applicable check
passes:

1. a clean copy of ``packs/`` plus the installer produces eight valid native
   ``SKILL.md`` files and ``--check`` accepts them;
2. a clean copy of the repository serves both MCP tools, the Python and JS/TS
   cards and full bodies, and a Bengali search;
3. the host registry exposes all eight local skill IDs (skipped only when the
   ``opencode`` binary is not on ``PATH``);
4. the documented Node vendor layout routes English and Bengali;
5. the documented Python vendor layout routes English and Bengali;
6. every local compact card carries ``VERIFY:`` and a concrete command;
7. ``origin/main`` equals the local HEAD.

Check 7 is why this runs after the push, not before it.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "skills.db"
INTENTS = ROOT / "data" / "bn-intents.json"
LOCAL_SLUGS = (
    "cdp-operations",
    "cpp-operations",
    "hosting-deployment",
    "javascript-typescript-operations",
    "mysql-operations",
    "php-operations",
    "python-operations",
    "sqlite-operations",
)
PY_QUERY = "python virtual environment pyproject typing unittest asyncio cli"
BN_QUERY = "পাইথন ভার্চুয়াল এনভায়রনমেন্ট"
JS_QUERY = "node typescript esm http server fetch abort test"
BACKTICK_RE = re.compile(r"`[^`]+`")

sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "server"))

from skill_server import compact_card  # noqa: E402
from zombie_skills import SkillStore  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def run(
    command: list[Any],
    cwd: Path | None = None,
    timeout: int = 180,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(part) for part in command],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def expect_marker(result: subprocess.CompletedProcess[str], marker: str, label: str) -> None:
    check(
        result.returncode == 0,
        f"{label}: exit {result.returncode}: {result.stderr.strip()[:300]}",
    )
    check(marker in result.stdout, f"{label}: missing marker {marker!r}")


def frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    data: dict[str, str] = {}
    key = ""
    for line in text[3:end].splitlines():
        if not line.strip():
            continue
        if line[:1] in (" ", "\t") and key:
            data[key] = (data.get(key, "") + " " + line.strip()).strip()
            continue
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        key = name.strip().lower()
        data[key] = value.strip().strip("\"'")
    return data


def clean_env() -> dict[str, str]:
    drop = {
        "ZOMBIE_SKILLS_DB",
        "ZOMBIE_SKILLS_JSONL",
        "ZOMBIE_SKILLS_TERMS",
        "ZOMBIE_SKILLS_INTENTS",
    }
    return {key: value for key, value in os.environ.items() if key not in drop}


def check_clean_install(base: Path) -> None:
    clean = base / "clean-install"
    (clean / "tools").mkdir(parents=True)
    shutil.copytree(ROOT / "packs", clean / "packs")
    shutil.copy2(ROOT / "tools" / "install_opencode_skills.py", clean / "tools")

    dest = base / "clean-skills"
    installed = run(
        [sys.executable, clean / "tools" / "install_opencode_skills.py", "--dest", dest]
    )
    expect_marker(installed, "OPENCODE_SKILLS_INSTALLED 8", "clean install")
    verified = run(
        [sys.executable, clean / "tools" / "install_opencode_skills.py", "--dest", dest, "--check"]
    )
    expect_marker(verified, "OPENCODE_SKILLS_PRESENT 8", "clean install --check")

    files = sorted(dest.glob("*/SKILL.md"))
    check(len(files) == 8, f"clean install wrote {len(files)} SKILL.md files, expected 8")
    for path in files:
        slug = path.parent.name
        text = path.read_text(encoding="utf-8")
        meta = frontmatter(text)
        check(slug in LOCAL_SLUGS, f"unexpected installed slug: {slug}")
        check(meta.get("name") == slug, f"{slug}: frontmatter name {meta.get('name')!r}")
        check(
            1 <= len(meta.get("description", "")) <= 1024,
            f"{slug}: description length {len(meta.get('description', ''))}",
        )
        check(
            meta.get("source") == "local/zombiecoder-packs",
            f"{slug}: source {meta.get('source')!r}",
        )
        check(meta.get("license") == "MIT", f"{slug}: license {meta.get('license')!r}")
        source = ROOT / "packs" / slug / "SKILL.md"
        check(
            source.is_file() and source.read_text(encoding="utf-8") == text,
            f"{slug}: installed copy differs from the pack",
        )
    print(f"clean install: {len(files)} packs, installer --check passed")


def check_mcp_clean_copy(base: Path) -> None:
    repo = base / "clean-repo"
    shutil.copytree(
        ROOT,
        repo,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "node_modules"),
    )
    process = subprocess.Popen(
        [sys.executable, str(repo / "server" / "skill_mcp.py")],
        cwd=str(repo),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=clean_env(),
    )
    next_id = 0

    def rpc(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        nonlocal next_id
        next_id += 1
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": next_id, "method": method}
        if params is not None:
            message["params"] = params
        assert process.stdin is not None
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()
        assert process.stdout is not None
        line = process.stdout.readline()
        if not line:
            raise RuntimeError(f"no MCP response for {method}")
        return json.loads(line)

    def payload(response: dict[str, Any]) -> Any:
        content = response["result"]["content"][0]
        check(content.get("type") == "text", "MCP content block is not text")
        return json.loads(content["text"])

    try:
        init = rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "agent-onboarding", "version": "0"},
            },
        )
        check(
            init["result"]["serverInfo"]["name"] == "zombiecoder-skills",
            "MCP server name is not zombiecoder-skills",
        )
        tools = rpc("tools/list")
        names = [tool["name"] for tool in tools["result"]["tools"]]
        check(names == ["search_skills", "get_skill"], f"MCP tools are {names}")

        card = payload(
            rpc(
                "tools/call",
                {"name": "get_skill", "arguments": {"slug": "python-operations", "mode": "card"}},
            )
        )
        check(card["slug"] == "python-operations", "MCP card returned the wrong slug")
        check("VERIFY:" in card["card"], "MCP python card has no VERIFY block")
        check(
            "python -m compileall" in card["card"],
            "MCP python card has no compileall command",
        )

        full_py = payload(
            rpc(
                "tools/call",
                {
                    "name": "get_skill",
                    "arguments": {
                        "slug": "python-operations",
                        "mode": "full",
                        "max_chars": 12000,
                    },
                },
            )
        )
        check(full_py["mode"] == "full", "MCP python full response has the wrong mode")
        check(full_py.get("truncated") is False, "MCP python full body was truncated")
        check("## Verify" in full_py["body"], "MCP python full body has no Verify section")
        check(
            "python -m compileall" in full_py["body"],
            "MCP python full body has no compileall command",
        )

        full_js = payload(
            rpc(
                "tools/call",
                {
                    "name": "get_skill",
                    "arguments": {
                        "slug": "javascript-typescript-operations",
                        "mode": "full",
                        "max_chars": 12000,
                    },
                },
            )
        )
        check(full_js.get("truncated") is False, "MCP JS/TS full body was truncated")
        check(
            "## Verify" in full_js["body"],
            "MCP JS/TS full body has no Verify section",
        )
        check("node --check" in full_js["body"], "MCP JS/TS full body has no node --check")

        search = payload(
            rpc(
                "tools/call",
                {
                    "name": "search_skills",
                    "arguments": {"query": BN_QUERY, "limit": 3},
                },
            )
        )
        matches = search.get("matches") or []
        check(bool(matches), "MCP Bengali search returned no matches")
        check(
            bool(matches) and matches[0].get("slug") == "python-operations",
            f"MCP Bengali search top match is {matches[0].get('slug') if matches else None}",
        )
    except Exception as exc:  # noqa: BLE001 - the failure is reported, not raised
        FAILURES.append(f"MCP clean copy failed: {exc!r}")
    finally:
        if process.stdin is not None:
            process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        if process.returncode not in (0, None):
            stderr = process.stderr.read().strip()[:300] if process.stderr else ""
            check(False, f"MCP clean copy exited {process.returncode}: {stderr}")
    print("MCP clean copy: initialize, tools, cards, full bodies, Bengali search")


def check_host_registry() -> None:
    opencode = shutil.which("opencode")
    if not opencode:
        print("host registry: skipped (opencode not on PATH)")
        return
    last_error = ""
    for attempt in range(2):
        result = run([opencode, "api", "GET", "/api/skill"], cwd=ROOT, timeout=180)
        if result.returncode == 0:
            try:
                body = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                last_error = f"invalid JSON: {exc}"
            else:
                rows = body.get("data") if isinstance(body, dict) else body
                ids = {
                    str(row.get("id"))
                    for row in (rows or [])
                    if isinstance(row, dict) and row.get("id")
                }
                missing = sorted(set(LOCAL_SLUGS) - ids)
                check(not missing, f"host registry missing local IDs: {missing}")
                print(f"host registry: {len(ids)} skills, local present {8 - len(missing)}/8")
                return
        else:
            last_error = f"exit {result.returncode}: {result.stderr.strip()[:300]}"
        if attempt == 0:
            time.sleep(3)
    check(False, f"host registry unavailable: {last_error}")


def check_node_vendor(base: Path) -> None:
    vendor = base / "node-vendor"
    (vendor / "zombie-skills" / "bin").mkdir(parents=True)
    (vendor / "data").mkdir()
    shutil.copy2(ROOT / "node" / "index.js", vendor / "zombie-skills" / "index.js")
    shutil.copy2(ROOT / "node" / "bin" / "cli.js", vendor / "zombie-skills" / "bin" / "cli.js")
    shutil.copy2(ROOT / "skills.jsonl", vendor / "skills.jsonl")
    shutil.copy2(ROOT / "terms.jsonl", vendor / "terms.jsonl")
    shutil.copy2(INTENTS, vendor / "data" / "bn-intents.json")

    script = vendor / "route.cjs"
    script.write_text(
        """
const { SkillLibrary } = require("./zombie-skills/index.js");
const library = new SkillLibrary();
const stats = library.stats();
const en = library.route(%s, { limit: 2 });
const bn = library.route(%s, { limit: 2 });
console.log(JSON.stringify({
  active: stats.active,
  terms: stats.terms,
  en: en.map((match) => match.slug),
  bn: bn.map((match) => match.slug),
}));
"""
        % (json.dumps(PY_QUERY), json.dumps(BN_QUERY)),
        encoding="utf-8",
    )
    result = run(["node", script], cwd=vendor, env=clean_env())
    if result.returncode != 0:
        check(False, f"Node vendor route failed: {result.stderr.strip()[:300]}")
        return
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        check(False, f"Node vendor route returned invalid JSON: {exc}")
        return
    check(data.get("active") == 256, f"Node vendor loaded {data.get('active')} skills")
    check(
        bool(data.get("en")) and data["en"][0] == "python-operations",
        f"Node English top match is {data.get('en')}",
    )
    check(
        bool(data.get("bn")) and data["bn"][0] == "python-operations",
        f"Node Bengali top match is {data.get('bn')}",
    )
    print(f"Node vendor: {data.get('active')} skills, EN {data['en'][0]}, BN {data['bn'][0]}")


def check_python_vendor(base: Path) -> None:
    project = base / "python-project"
    shutil.copytree(
        ROOT / "python" / "zombie_skills",
        project / "zombie_skills",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (project / "data").mkdir()
    shutil.copy2(DB, project / "skills.db")
    shutil.copy2(INTENTS, project / "data" / "bn-intents.json")

    script = project / "route.py"
    script.write_text(
        """
import json
from zombie_skills import SkillStore

with SkillStore() as store:
    stats = store.stats()
    en = store.route(%s, limit=2)
    bn = store.route(%s, limit=2)
print(json.dumps({
    "active": stats.get("active"),
    "en": [match["slug"] for match in en],
    "bn": [match["slug"] for match in bn],
}))
"""
        % (json.dumps(PY_QUERY), json.dumps(BN_QUERY)),
        encoding="utf-8",
    )
    result = run([sys.executable, "route.py"], cwd=project, env=clean_env())
    if result.returncode != 0:
        check(False, f"Python vendor route failed: {result.stderr.strip()[:300]}")
        return
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        check(False, f"Python vendor route returned invalid JSON: {exc}")
        return
    check(data.get("active") == 256, f"Python vendor loaded {data.get('active')} skills")
    check(
        bool(data.get("en")) and data["en"][0] == "python-operations",
        f"Python English top match is {data.get('en')}",
    )
    check(
        bool(data.get("bn")) and data["bn"][0] == "python-operations",
        f"Python Bengali top match is {data.get('bn')}",
    )
    print(f"Python vendor: {data.get('active')} skills, EN {data['en'][0]}, BN {data['bn'][0]}")


def check_cards() -> None:
    store = SkillStore(DB)
    try:
        for slug in LOCAL_SLUGS:
            skill = store.get(slug)
            check(skill is not None, f"missing local skill: {slug}")
            if not skill:
                continue
            card = compact_card(skill, max_chars=1600)
            check("VERIFY:" in card, f"{slug}: card has no VERIFY block")
            if "VERIFY:" not in card:
                continue
            block = card.split("VERIFY:", 1)[1].split("SOURCE:", 1)[0]
            check(
                BACKTICK_RE.search(block) is not None,
                f"{slug}: VERIFY block has no concrete command",
            )
    finally:
        store.close()
    print(f"cards: {len(LOCAL_SLUGS)} local cards carry VERIFY with a command")


def check_remote() -> None:
    local = run(["git", "-C", ROOT, "rev-parse", "HEAD"])
    remote = run(["git", "-C", ROOT, "ls-remote", "origin", "refs/heads/main"], timeout=120)
    if local.returncode != 0 or remote.returncode != 0:
        check(
            False,
            "git check failed: "
            + (local.stderr or remote.stderr).strip()[:300],
        )
        return
    local_head = local.stdout.strip()
    parts = remote.stdout.split()
    remote_head = parts[0] if parts else ""
    check(
        local_head == remote_head,
        f"origin/main {remote_head[:12] or '(missing)'} != local HEAD {local_head[:12]}",
    )
    print(f"remote: origin/main {remote_head[:12]} matches local HEAD")


def main() -> int:
    if not DB.is_file():
        print(f"FAIL: missing database: {DB}")
        return 1
    if not INTENTS.is_file():
        print(f"FAIL: missing intent bridge: {INTENTS}")
        return 1

    base = Path(tempfile.mkdtemp(prefix="agent-onboarding-", dir="/tmp/opencode"))
    print(f"workdir: {base}")
    try:
        check_clean_install(base)
        check_mcp_clean_copy(base)
        check_host_registry()
        check_node_vendor(base)
        check_python_vendor(base)
        check_cards()
        check_remote()
    finally:
        if FAILURES:
            print(f"artifacts kept at {base}")
        else:
            shutil.rmtree(base, ignore_errors=True)

    if FAILURES:
        for failure in FAILURES:
            print(f"FAIL: {failure}")
        return 1
    print("AGENT_ONBOARDING_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
