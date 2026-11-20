#!/usr/bin/env python3
"""Release gate for the multi-client skill install.

The gate copies only ``packs/``, ``tools/install_client_skills.py`` and
``install.py`` into a clean temporary tree, installs the packs with one command,
and then proves:

* ``.agents/skills`` and ``.claude/skills`` each contain all eight packs with
  byte-identical ``SKILL.md`` files;
* ``--check`` reports the copies as present;
* a second install is byte-for-byte idempotent;
* each client writes its documented native path;
* ``AGENTS.md`` and ``CLAUDE.md`` each contain exactly one marked block listing
  all eight slugs;
* a plugin-free ``opencode serve`` started in the temp project lists all eight
  local skill IDs from ``/api/skill``;
* ``docs/CLIENT-SKILLS.md`` documents the six clients and their paths;
* unless ``--no-remote`` is passed, ``origin/main`` equals the local HEAD.

With ``--auto`` it also proves the one-command installer:

* ``install.py --detect --json`` reports the OS and detects VS Code, Codex and
  OpenCode on this machine, with Claude, Cursor and Windsurf absent;
* root discovery returns the git root from a nested repository directory and
  the marker root from a nested project with ``opencode.json``;
* a fake PATH detects only the clients whose shims exist, and ``--auto``
  installs only those clients plus the shared paths;
* the real bundled Codex CLI sees ``python-operations`` through
  ``codex debug prompt-input`` after the install.

Run from the project root::

    python3 zombiecoder-agent-skills/tools/check_client_skills.py
    python3 zombiecoder-agent-skills/tools/check_client_skills.py --auto

The full gate prints ``CLIENT_SKILLS_OK``; ``--auto`` also prints
``AUTO_CLIENT_INSTALL_OK``. Nothing is printed when a check fails.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packs"
INSTALLER = ROOT / "tools" / "install_client_skills.py"
ENTRYPOINT = ROOT / "install.py"
DOC = ROOT / "docs" / "CLIENT-SKILLS.md"
MARKER = "CLIENT_SKILLS_OK"
AUTO_MARKER = "AUTO_CLIENT_INSTALL_OK"
BLOCK_BEGIN = "<!-- BEGIN zombiecoder-skills -->"
BLOCK_END = "<!-- END zombiecoder-skills -->"
SOURCE = "local/zombiecoder-packs"
EXPECTED_PACKS = 8

# Documented native project paths. Keep this table independent of the
# installer so the gate fails if the installer drifts from the documentation.
PROJECT_PATHS = {
    "agents": ".agents/skills",
    "claude": ".claude/skills",
    "opencode": ".opencode/skills",
    "cursor": ".cursor/skills",
    "vscode": ".github/skills",
    "windsurf": ".devin/skills",
    "codex": ".agents/skills",
}

DOC_CLIENTS = ("Claude Code", "OpenCode", "Cursor", "VS Code", "Windsurf", "Codex")
DOC_PATHS = (
    ".claude/skills",
    ".opencode/skills",
    ".cursor/skills",
    ".github/skills",
    ".devin/skills",
    ".agents/skills",
)

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


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


def run(
    command: list[str], cwd: Path | None = None, env: dict[str, str] | None = None,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(command, 124, "", f"timeout after {timeout}s")


def sha_tree(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def make_shim(path: Path, version: str, extensions: str = "") -> None:
    lines = [
        "#!/bin/sh",
        'if [ "$1" = "--version" ]; then',
        f"  echo {version}",
        "  exit 0",
        "fi",
    ]
    if extensions:
        lines.extend(
            [
                'if [ "$1" = "--list-extensions" ]; then',
                f"  echo {extensions}",
                "  exit 0",
                "fi",
            ]
        )
    lines.extend(["exit 0", ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    path.chmod(0o755)


def skill_copies(destination: Path, slugs: list[str], packs: dict[str, str]) -> list[str]:
    problems: list[str] = []
    for slug in slugs:
        target = destination / slug / "SKILL.md"
        if not target.is_file():
            problems.append(f"missing {target}")
        elif target.read_text(encoding="utf-8") != packs[slug]:
            problems.append(f"content mismatch: {target}")
    return problems


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def fetch_skills(
    executable: str, url: str, env: dict[str, str]
) -> tuple[tuple[set[str], str | None] | None, str | None]:
    try:
        result = subprocess.run(
            [executable, "api", "GET", "/api/skill", "--server", url],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return None, "timeout"
    if result.returncode != 0:
        return None, (result.stderr or result.stdout).strip()[:300]
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, result.stdout.strip()[:300]
    rows = payload.get("data") or []
    ids = {str(row.get("id")) for row in rows if isinstance(row, dict)}
    location = (payload.get("location") or {}).get("directory")
    return (ids, location), None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-remote",
        action="store_true",
        help="skip the origin/main == HEAD check while developing",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="also prove OS/editor detection, root discovery and one-command install",
    )
    args = parser.parse_args()

    base = Path("/tmp/opencode")
    tmp = Path(
        tempfile.mkdtemp(
            prefix="zc-client-gate-",
            dir=str(base) if base.is_dir() else None,
        )
    )
    packs: dict[str, str] = {}
    for path in sorted(PACKS.glob("*/SKILL.md")):
        slug = path.parent.name
        text = path.read_text(encoding="utf-8")
        packs[slug] = text
        meta = frontmatter(text)
        check(meta.get("name") == slug, f"{slug}: frontmatter name {meta.get('name')!r}")
        description = str(meta.get("description") or "").strip()
        check(
            1 <= len(description) <= 1024,
            f"{slug}: description length {len(description)} is outside 1..1024",
        )
        check(meta.get("source") == SOURCE, f"{slug}: source {meta.get('source')!r}")
        check(meta.get("license") == "MIT", f"{slug}: license {meta.get('license')!r}")
    check(
        len(packs) == EXPECTED_PACKS,
        f"expected {EXPECTED_PACKS} packs, found {len(packs)}",
    )
    slugs = sorted(packs)

    clean = tmp / "clean"
    shutil.copytree(PACKS, clean / "packs")
    (clean / "tools").mkdir(parents=True)
    shutil.copy2(INSTALLER, clean / "tools" / "install_client_skills.py")
    shutil.copy2(ENTRYPOINT, clean / "install.py")
    project = clean / "project"
    project.mkdir()

    installer = str(clean / "tools" / "install_client_skills.py")
    install = [sys.executable, installer, "--client", "all", "--target", str(project)]

    result = run(install, cwd=clean)
    check(result.returncode == 0, f"clean install failed: {result.stderr or result.stdout}")
    check(
        f"CLIENT_SKILLS_INSTALLED {len(slugs)}" in result.stdout,
        "clean install did not print CLIENT_SKILLS_INSTALLED",
    )

    for relative in (".agents/skills", ".claude/skills"):
        destination = project / relative
        check(destination.is_dir(), f"missing shared directory {relative}")
        if not destination.is_dir():
            continue
        found = sorted(path.name for path in destination.iterdir() if path.is_dir())
        check(found == slugs, f"{relative} has {found}, expected {slugs}")
        for slug in slugs:
            target = destination / slug / "SKILL.md"
            check(target.is_file(), f"missing {target}")
            if target.is_file():
                check(
                    target.read_text(encoding="utf-8") == packs[slug],
                    f"content mismatch: {target}",
                )

    result = run(
        [sys.executable, installer, "--check", "--client", "all", "--target", str(project)],
        cwd=clean,
    )
    check(result.returncode == 0, f"--check failed: {result.stderr or result.stdout}")
    check(
        f"CLIENT_SKILLS_PRESENT {len(slugs)}" in result.stdout,
        "--check did not print CLIENT_SKILLS_PRESENT",
    )

    before = sha_tree(project)
    result = run(install, cwd=clean)
    after = sha_tree(project)
    check(result.returncode == 0, f"second install failed: {result.stderr or result.stdout}")
    check(before == after, "second install changed at least one file")

    for name in ("AGENTS.md", "CLAUDE.md"):
        path = project / name
        check(path.is_file(), f"missing index file {name}")
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        check(text.count(BLOCK_BEGIN) == 1, f"{name}: expected one begin marker")
        check(text.count(BLOCK_END) == 1, f"{name}: expected one end marker")
        if text.count(BLOCK_BEGIN) == 1 and text.count(BLOCK_END) == 1:
            start = text.index(BLOCK_BEGIN)
            stop = text.index(BLOCK_END) + len(BLOCK_END)
            block = text[start:stop]
            for slug in slugs:
                check(f"**{slug}**" in block, f"{name}: block is missing {slug}")

    for client, relative in PROJECT_PATHS.items():
        native = tmp / "native" / client
        native.mkdir(parents=True)
        result = run(
            [sys.executable, installer, "--client", client, "--target", str(native)],
            cwd=clean,
        )
        check(
            result.returncode == 0,
            f"{client}: installer failed: {result.stderr or result.stdout}",
        )
        destination = native / relative
        for slug in slugs:
            target = destination / slug / "SKILL.md"
            check(target.is_file(), f"{client}: missing {relative}/{slug}/SKILL.md")
            if target.is_file():
                check(
                    target.read_text(encoding="utf-8") == packs[slug],
                    f"{client}: content mismatch for {slug}",
                )

    executable = shutil.which("opencode")
    check(executable is not None, "opencode CLI is not on PATH")
    if executable:
        xdg = tmp / "xdg"
        (xdg / "config" / "opencode").mkdir(parents=True)
        for name in ("data", "cache", "state"):
            (xdg / name).mkdir(parents=True)
        (xdg / "config" / "opencode" / "opencode.json").write_text(
            '{"$schema":"https://opencode.ai/config.json"}\n', encoding="utf-8"
        )
        env = os.environ.copy()
        env.update(
            {
                "XDG_CONFIG_HOME": str(xdg / "config"),
                "XDG_DATA_HOME": str(xdg / "data"),
                "XDG_CACHE_HOME": str(xdg / "cache"),
                "XDG_STATE_HOME": str(xdg / "state"),
                "OPENCODE_PASSWORD": "zc-client-gate",
            }
        )
        port = free_port()
        url = f"http://127.0.0.1:{port}"
        log_path = tmp / "opencode.log"
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                [executable, "serve", "--port", str(port), "--hostname", "127.0.0.1"],
                cwd=project,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                deadline = time.time() + 75
                found: tuple[set[str], str | None] | None = None
                last = ""
                while time.time() < deadline:
                    payload, error = fetch_skills(executable, url, env)
                    if payload is not None:
                        ids, location = payload
                        last = f"location={location} ids={len(ids)}"
                        if set(slugs) <= ids:
                            found = payload
                            break
                    else:
                        last = error or "no response"
                    time.sleep(2)
                check(
                    found is not None,
                    f"plugin-free opencode did not list all {len(slugs)} skills "
                    f"within 75s ({last})",
                )
                if found is not None:
                    ids, location = found
                    check(
                        location == str(project.resolve()),
                        f"opencode location {location!r} != {str(project.resolve())!r}",
                    )
                    for slug in slugs:
                        check(slug in ids, f"opencode /api/skill is missing {slug}")
            finally:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=5)

    if args.auto:
        auto_dir = tmp / "auto"
        auto_dir.mkdir()
        entry = str(clean / "install.py")

        def payload_of(process: subprocess.CompletedProcess[str], label: str) -> dict:
            if process.returncode != 0:
                check(False, f"{label} failed: {process.stderr or process.stdout}")
                return {}
            try:
                data = json.loads(process.stdout)
            except json.JSONDecodeError:
                check(False, f"{label} printed invalid JSON: {process.stdout[:300]}")
                return {}
            return data if isinstance(data, dict) else {}

        def client_index(data: dict) -> dict[str, dict]:
            rows = data.get("clients")
            if not isinstance(rows, list):
                return {}
            return {
                str(row.get("client")): row
                for row in rows
                if isinstance(row, dict)
            }

        # OS and editor detection must match this machine.
        os_release: dict[str, str] = {}
        release_file = Path("/etc/os-release")
        if release_file.is_file():
            for line in release_file.read_text(encoding="utf-8").splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    os_release[key] = value.strip().strip("\"'")
        detect_project = auto_dir / "detect"
        detect_project.mkdir()
        result = run(
            [
                sys.executable,
                entry,
                "--detect",
                "--json",
                "--target",
                str(detect_project),
            ],
            cwd=clean,
        )
        payload = payload_of(result, "--detect --json")
        os_info = payload.get("os") if isinstance(payload.get("os"), dict) else {}
        check(
            os_info.get("system") == platform.system(),
            f"--detect system {os_info.get('system')!r} != {platform.system()!r}",
        )
        check(
            os_info.get("machine") == platform.machine(),
            f"--detect machine {os_info.get('machine')!r} != {platform.machine()!r}",
        )
        expected_distro = os_release.get("PRETTY_NAME", "")
        check(bool(expected_distro), "cannot read PRETTY_NAME from /etc/os-release")
        check(
            os_info.get("distro") == expected_distro,
            f"--detect distro {os_info.get('distro')!r} != {expected_distro!r}",
        )
        detected = client_index(payload)
        for name in ("vscode", "codex", "opencode"):
            check(
                detected.get(name, {}).get("installed") is True,
                f"--detect did not find {name}",
            )
        for name in ("claude", "cursor", "windsurf"):
            check(
                detected.get(name, {}).get("installed") is False,
                f"--detect falsely reported {name} installed",
            )
        vscode_evidence = " ".join(
            str(value) for value in detected.get("vscode", {}).get("evidence") or []
        )
        check(
            "openai.chatgpt" in vscode_evidence,
            "VS Code detection did not report the openai.chatgpt extension",
        )
        check(
            bool(detected.get("vscode", {}).get("version")),
            "VS Code detection has no version",
        )
        codex_evidence = " ".join(
            str(value) for value in detected.get("codex", {}).get("evidence") or []
        )
        check(".codex" in codex_evidence, "Codex detection did not report ~/.codex")
        check("bundled" in codex_evidence, "Codex detection did not report the bundled CLI")
        check(
            bool(detected.get("opencode", {}).get("version")),
            "OpenCode detection has no version",
        )

        plain = run(
            [sys.executable, entry, "--detect", "--target", str(detect_project)],
            cwd=clean,
        )
        check(plain.returncode == 0, f"plain --detect failed: {plain.stderr or plain.stdout}")
        check("os: " in plain.stdout, "plain --detect does not print an os: line")
        check("root: " in plain.stdout, "plain --detect does not print a root: line")

        # Root discovery: a nested directory inside a real git repository.
        git_project = auto_dir / "git-project"
        git_nested = git_project / "src" / "nested"
        git_nested.mkdir(parents=True)
        init = run(["git", "init", "-q", str(git_project)])
        check(init.returncode == 0, f"git init failed: {init.stderr}")
        result = run([sys.executable, entry, "--detect", "--json"], cwd=git_nested)
        payload = payload_of(result, "git-root --detect")
        root = payload.get("root") if isinstance(payload.get("root"), dict) else {}
        check(root.get("source") == "git", f"git root source {root.get('source')!r} != 'git'")
        check(
            Path(str(root.get("path"))) == git_project.resolve(),
            f"git root {root.get('path')!r} != {str(git_project.resolve())!r}",
        )

        # Root discovery: the nearest project marker from a nested directory.
        marker_project = auto_dir / "marker-project"
        marker_nested = marker_project / "pkg" / "nested"
        marker_nested.mkdir(parents=True)
        (marker_project / "opencode.json").write_text("{}\n", encoding="utf-8")
        result = run([sys.executable, entry, "--detect", "--json"], cwd=marker_nested)
        payload = payload_of(result, "marker-root --detect")
        root = payload.get("root") if isinstance(payload.get("root"), dict) else {}
        check(
            root.get("source") == "marker:opencode.json",
            f"marker root source {root.get('source')!r} != 'marker:opencode.json'",
        )
        check(
            Path(str(root.get("path"))) == marker_project.resolve(),
            f"marker root {root.get('path')!r} != {str(marker_project.resolve())!r}",
        )

        # A real auto install writes every detected client's project path.
        auto_project = auto_dir / "auto-project"
        auto_project.mkdir()
        result = run(
            [sys.executable, entry, "--auto", "--target", str(auto_project)], cwd=clean
        )
        check(result.returncode == 0, f"--auto install failed: {result.stderr or result.stdout}")
        check(AUTO_MARKER in result.stdout, "--auto install did not print AUTO_CLIENT_INSTALL_OK")
        for relative in (".agents/skills", ".claude/skills", ".github/skills", ".opencode/skills"):
            problems = skill_copies(auto_project / relative, slugs, packs)
            check(not problems, f"--auto install {relative}: " + "; ".join(problems))
        result = run(
            [sys.executable, entry, "--auto", "--check", "--target", str(auto_project)],
            cwd=clean,
        )
        check(result.returncode == 0, f"--auto --check failed: {result.stderr or result.stdout}")
        check(AUTO_MARKER in result.stdout, "--auto --check did not print AUTO_CLIENT_INSTALL_OK")

        # Fake PATH: only the shims exist, so only those clients are installed.
        fake_home = auto_dir / "fake-home"
        fake_home.mkdir()
        shim_dir = auto_dir / "fake-bin"
        shim_dir.mkdir()
        make_shim(shim_dir / "code", "1.99.0", "github.copilot")
        make_shim(shim_dir / "opencode", "0.0.0-fake")
        fake_env = os.environ.copy()
        fake_env["HOME"] = str(fake_home)
        fake_env["PATH"] = str(shim_dir) + os.pathsep + fake_env.get("PATH", "")
        fake_env.pop("CODEX_HOME", None)
        fake_project = auto_dir / "fake-project"
        fake_nested = fake_project / "src" / "nested"
        fake_nested.mkdir(parents=True)
        (fake_project / "opencode.json").write_text("{}\n", encoding="utf-8")
        result = run(
            [sys.executable, entry, "--detect", "--json"], cwd=fake_nested, env=fake_env
        )
        payload = payload_of(result, "fake-PATH --detect")
        fake_clients = client_index(payload)
        check(
            fake_clients.get("vscode", {}).get("installed") is True,
            "fake PATH: VS Code was not detected",
        )
        check(
            fake_clients.get("opencode", {}).get("installed") is True,
            "fake PATH: OpenCode was not detected",
        )
        for name in ("codex", "claude", "cursor", "windsurf"):
            check(
                fake_clients.get(name, {}).get("installed") is False,
                f"fake PATH: {name} was falsely detected",
            )
        root = payload.get("root") if isinstance(payload.get("root"), dict) else {}
        check(
            Path(str(root.get("path"))) == fake_project.resolve(),
            f"fake-PATH root {root.get('path')!r} != {str(fake_project.resolve())!r}",
        )
        result = run([sys.executable, entry], cwd=fake_nested, env=fake_env)
        check(result.returncode == 0, f"no-argument install failed: {result.stderr or result.stdout}")
        check(
            AUTO_MARKER in result.stdout,
            "install.py without arguments did not default to --auto",
        )
        for relative in (".agents/skills", ".claude/skills", ".github/skills", ".opencode/skills"):
            problems = skill_copies(fake_project / relative, slugs, packs)
            check(not problems, f"fake-PATH install {relative}: " + "; ".join(problems))
        for relative in (".cursor/skills", ".devin/skills"):
            check(
                not (fake_project / relative).exists(),
                f"fake-PATH install wrote {relative} for an absent client",
            )

        # The real bundled Codex CLI must see the installed packs.
        codex_binary = str(detected.get("codex", {}).get("binary") or "")
        check(bool(codex_binary), "--detect did not report a Codex binary")
        if codex_binary:
            result = run(
                [codex_binary, "debug", "prompt-input", "hello"],
                cwd=auto_project,
                timeout=120,
            )
            check(
                result.returncode == 0,
                f"codex debug prompt-input failed: {(result.stderr or result.stdout)[:300]}",
            )
            check(
                "python-operations" in result.stdout,
                "codex prompt-input does not list python-operations",
            )
            check(
                ".agents/skills" in result.stdout,
                "codex prompt-input does not reference .agents/skills",
            )

        staged = run(["git", "-C", str(ROOT), "diff", "--cached", "--name-only"])
        check(
            "docs/CLIENTS.md" not in staged.stdout.splitlines(),
            "docs/CLIENTS.md must stay uncommitted",
        )

    check(DOC.is_file(), f"missing documentation: {DOC}")
    if DOC.is_file():
        text = DOC.read_text(encoding="utf-8")
        for client in DOC_CLIENTS:
            check(client in text, f"docs/CLIENT-SKILLS.md is missing {client}")
        for relative in DOC_PATHS:
            check(relative in text, f"docs/CLIENT-SKILLS.md is missing {relative}")
        for needle in ("install.py", "--auto", "--detect", "Root discovery"):
            check(needle in text, f"docs/CLIENT-SKILLS.md is missing {needle!r}")
        check(".cloud" not in text.lower(), "docs/CLIENT-SKILLS.md contains .cloud")

    head = run(["git", "-C", str(ROOT), "rev-parse", "HEAD"]).stdout.strip()
    check(bool(head), "cannot read the local git HEAD")
    if not args.no_remote:
        remote = run(
            ["git", "-C", str(ROOT), "ls-remote", "origin", "refs/heads/main"],
            timeout=60,
        )
        check(remote.returncode == 0, f"git ls-remote failed: {remote.stderr}")
        remote_head = remote.stdout.split()[0] if remote.stdout.strip() else ""
        check(
            remote_head == head,
            f"origin/main {remote_head[:12] or '(missing)'} != local HEAD {head[:12]}",
        )

    if FAILURES:
        for failure in FAILURES:
            print(f"FAIL: {failure}")
        print(f"gate directory kept for inspection: {tmp}")
        return 1

    print(f"clean copy: {clean}")
    print(f"project: {project}")
    print(f"packs: {len(slugs)}")
    print(f"local HEAD: {head[:12]}")
    if not args.no_remote:
        print("origin/main == local HEAD")
    shutil.rmtree(tmp, ignore_errors=True)
    print(MARKER)
    if args.auto:
        print(AUTO_MARKER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
