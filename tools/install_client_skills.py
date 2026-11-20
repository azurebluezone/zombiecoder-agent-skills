#!/usr/bin/env python3
"""Install the audited local packs into every supported client's skill folder.

Every editor below reads the portable ``SKILL.md`` layout, but each one looks in
a different directory. This installer copies the same eight packs to the shared
folder (``.agents/skills``), the Claude-compatible folder (``.claude/skills``)
and each client's native folder, then writes one marked index block into
``AGENTS.md`` and ``CLAUDE.md`` for agents that read instruction files instead
of scanning skill directories.

Usage::

    python3 tools/install_client_skills.py --detect
    python3 tools/install_client_skills.py --detect --json
    python3 tools/install_client_skills.py --auto --target .
    python3 tools/install_client_skills.py --auto --scope global
    python3 tools/install_client_skills.py --client all --target .
    python3 tools/install_client_skills.py --check --client all --target .

``--auto`` detects the operating system and the installed editors, finds the
project root from the current directory (git root, then the nearest project
marker, then the current directory), and installs only the detected clients
plus the shared paths. ``--detect`` prints the same information without writing.

The installer is idempotent: unchanged files are reported as ``unchanged`` and
the index block is replaced in place, never duplicated. A successful install
prints ``CLIENT_SKILLS_INSTALLED 8``; ``--check`` prints
``CLIENT_SKILLS_PRESENT 8``. In ``--auto`` mode both also print
``AUTO_CLIENT_INSTALL_OK``. Exit code 1 means at least one path is missing or
outdated.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packs"
SOURCE = "local/zombiecoder-packs"
BLOCK_BEGIN = "<!-- BEGIN zombiecoder-skills -->"
BLOCK_END = "<!-- END zombiecoder-skills -->"
INDEX_FILES = ("AGENTS.md", "CLAUDE.md")
SLUG_RE = re.compile(r"^[a-z0-9-]{1,64}$")

# Project-level paths, verified against the vendor documentation in
# docs/CLIENT-SKILLS.md.
PROJECT_PATHS = {
    "agents": Path(".agents/skills"),
    "claude": Path(".claude/skills"),
    "opencode": Path(".opencode/skills"),
    "cursor": Path(".cursor/skills"),
    "vscode": Path(".github/skills"),
    "windsurf": Path(".devin/skills"),
    "codex": Path(".agents/skills"),
}

# User-level paths, used with --scope global.
GLOBAL_PATHS = {
    "agents": Path.home() / ".agents" / "skills",
    "claude": Path.home() / ".claude" / "skills",
    "opencode": Path.home() / ".config" / "opencode" / "skills",
    "cursor": Path.home() / ".cursor" / "skills",
    "vscode": Path.home() / ".copilot" / "skills",
    "windsurf": Path.home() / ".config" / "devin" / "skills",
    "codex": Path.home() / ".agents" / "skills",
}

CLIENTS = tuple(PROJECT_PATHS)
SHARED_CLIENTS = ("agents", "claude")
CLIENT_LABELS = {
    "vscode": "VS Code",
    "codex": "Codex",
    "opencode": "OpenCode",
    "claude": "Claude Code",
    "cursor": "Cursor",
    "windsurf": "Windsurf",
}

# The first match wins when walking up from the current directory. The git root
# is tried before this list.
ROOT_MARKERS = (
    ".git",
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "composer.json",
    "Gemfile",
    "AGENTS.md",
    "CLAUDE.md",
    "opencode.json",
    ".vscode",
)


def frontmatter(text: str) -> dict[str, str]:
    """Parse the flat YAML subset used by the packs (no PyYAML dependency)."""
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


def discover() -> list[tuple[str, str]]:
    """Return ``(slug, text)`` for every pack, sorted by slug."""
    packs: list[tuple[str, str]] = []
    for path in sorted(PACKS.glob("*/SKILL.md")):
        if not path.parent.is_dir():
            continue
        slug = path.parent.name
        text = path.read_text(encoding="utf-8")
        meta = frontmatter(text)
        problems: list[str] = []
        if not SLUG_RE.match(slug):
            problems.append(f"folder {slug!r} is not a valid skill id")
        if str(meta.get("name") or "").strip() != slug:
            problems.append(
                f"frontmatter name is {meta.get('name')!r}, folder is {slug!r}"
            )
        description = str(meta.get("description") or "").strip()
        if not 1 <= len(description) <= 1024:
            problems.append(
                f"description length is {len(description)}, expected 1..1024"
            )
        if "\n" in description:
            problems.append("description contains a newline")
        if str(meta.get("source") or "") != SOURCE:
            problems.append(
                f"source is {meta.get('source')!r}, expected {SOURCE!r}"
            )
        if str(meta.get("license") or "") != "MIT":
            problems.append(f"license is {meta.get('license')!r}, expected 'MIT'")
        if problems:
            raise SystemExit(f"{path}: " + "; ".join(problems))
        packs.append((slug, text))
    if not packs:
        raise SystemExit(f"FAIL: no packs found under {PACKS}")
    return packs


def render_index(packs: list[tuple[str, str]]) -> str:
    lines = [
        BLOCK_BEGIN,
        "## ZombieCoder skills",
        "",
        "Installed by `tools/install_client_skills.py` from `zombiecoder-agent-skills`.",
        "When a task matches a skill, open `.agents/skills/<slug>/SKILL.md` (or the",
        "client's native copy) before acting.",
        "",
    ]
    for slug, text in packs:
        description = str(frontmatter(text).get("description") or "").strip()
        lines.append(f"- **{slug}** — {description}")
    lines.append(BLOCK_END)
    return "\n".join(lines)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def replace_index_block(path: Path, block: str) -> str:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    begin = text.count(BLOCK_BEGIN)
    end = text.count(BLOCK_END)
    if begin == 0 and end == 0:
        prefix = text.rstrip()
        updated = (prefix + "\n\n" if prefix else "") + block + "\n"
    elif begin == 1 and end == 1 and text.index(BLOCK_BEGIN) < text.index(BLOCK_END):
        start = text.index(BLOCK_BEGIN)
        stop = text.index(BLOCK_END) + len(BLOCK_END)
        updated = text[:start] + block + text[stop:]
        if not updated.endswith("\n"):
            updated += "\n"
    else:
        raise SystemExit(
            f"{path}: expected zero or one {BLOCK_BEGIN} ... {BLOCK_END} block, "
            f"found {begin} begin and {end} end marker(s)"
        )
    if path.is_file() and updated == text:
        return "unchanged"
    atomic_write(path, updated)
    return "updated"


def check_index(path: Path, slugs: list[str]) -> list[str]:
    problems: list[str] = []
    if not path.is_file():
        return [f"missing index file: {path}"]
    text = path.read_text(encoding="utf-8")
    if text.count(BLOCK_BEGIN) != 1:
        problems.append(
            f"{path}: expected one {BLOCK_BEGIN}, found {text.count(BLOCK_BEGIN)}"
        )
    if text.count(BLOCK_END) != 1:
        problems.append(
            f"{path}: expected one {BLOCK_END}, found {text.count(BLOCK_END)}"
        )
    if not problems:
        start = text.index(BLOCK_BEGIN)
        stop = text.index(BLOCK_END) + len(BLOCK_END)
        block = text[start:stop]
        for slug in slugs:
            if f"**{slug}**" not in block:
                problems.append(f"{path}: index block is missing {slug}")
    return problems


def detect_os() -> dict[str, str]:
    """Return the OS name, distro/version, kernel release and machine."""
    system = platform.system()
    info = {
        "system": system,
        "release": platform.release(),
        "machine": platform.machine(),
    }
    if system == "Linux":
        try:
            for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
                if line.startswith("PRETTY_NAME="):
                    info["distro"] = line.split("=", 1)[1].strip().strip('"')
                    break
        except OSError:
            pass
    elif system == "Darwin":
        info["distro"] = f"macOS {platform.mac_ver()[0]}".strip()
    elif system == "Windows":
        info["distro"] = f"Windows {platform.version()}".strip()
    info.setdefault("distro", system)
    return info


def format_os(info: dict[str, str]) -> str:
    return f"{info['system']} ({info['distro']}) {info['machine']}".strip()


def display_path(path: Path) -> str:
    try:
        relative = path.resolve().relative_to(Path.home().resolve())
        return "~/" + str(relative)
    except ValueError:
        return str(path)


def which_any(names: tuple[str, ...]) -> str | None:
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


def command_version(path: str | None) -> str | None:
    if not path:
        return None
    try:
        result = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    output = (result.stdout or result.stderr).strip()
    return output.splitlines()[0].strip() if output else None


def list_extensions(code: str | None) -> list[str]:
    if not code:
        return []
    try:
        result = subprocess.run(
            [code, "--list-extensions"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def scan_known_extensions() -> list[str]:
    """Fallback for a desktop install whose CLI is not on PATH."""
    home = Path.home()
    known = ("openai.chatgpt", "github.copilot", "github.copilot-chat")
    found: set[str] = set()
    for base in (home / ".vscode" / "extensions", home / ".vscode-insiders" / "extensions"):
        if not base.is_dir():
            continue
        names = [child.name for child in base.iterdir() if child.is_dir()]
        for extension in known:
            if any(name.startswith(extension + "-") for name in names):
                found.add(extension)
    return sorted(found)


def vscode_config_dirs() -> list[Path]:
    home = Path.home()
    system = platform.system()
    if system == "Darwin":
        base = home / "Library" / "Application Support"
        return [base / "Code", base / "Code - Insiders", home / ".vscode"]
    if system == "Windows":
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        return [appdata / "Code", appdata / "Code - Insiders", home / ".vscode"]
    return [home / ".config" / "Code", home / ".config" / "Code - Insiders", home / ".vscode"]


def app_path(client: str) -> Path | None:
    system = platform.system()
    if system == "Darwin":
        names = {
            "vscode": "Visual Studio Code.app",
            "cursor": "Cursor.app",
            "windsurf": "Windsurf.app",
        }
        name = names.get(client)
        return Path("/Applications") / name if name else None
    if system == "Windows":
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        names = {
            "vscode": local / "Programs" / "Microsoft VS Code" / "Code.exe",
            "cursor": local / "Programs" / "cursor" / "Cursor.exe",
            "windsurf": local / "Programs" / "Windsurf" / "Windsurf.exe",
        }
        return names.get(client)
    return None


def bundled_codex() -> Path | None:
    home = Path.home()
    patterns = (
        ".vscode/extensions/openai.chatgpt-*/bin/*/codex",
        ".vscode-insiders/extensions/openai.chatgpt-*/bin/*/codex",
    )
    for pattern in patterns:
        matches = sorted(home.glob(pattern), key=lambda path: str(path), reverse=True)
        for path in matches:
            if path.is_file():
                return path
    return None


def detect_clients() -> list[dict[str, object]]:
    """Detect the installed editors and return evidence for each one."""
    home = Path.home()
    code = which_any(("code", "code-insiders"))
    extensions = list_extensions(code) or scan_known_extensions()
    vscode_configs = [path for path in vscode_config_dirs() if path.exists()]
    vscode_app = app_path("vscode")
    vscode_installed = bool(
        code or extensions or vscode_configs or (vscode_app and vscode_app.exists())
    )
    vscode_version = command_version(code)
    vscode_evidence: list[str] = []
    if code:
        vscode_evidence.append(code)
    if vscode_version:
        vscode_evidence.append(vscode_version)
    if vscode_configs:
        vscode_evidence.append(", ".join(display_path(path) for path in vscode_configs))
    if extensions:
        vscode_evidence.append("extensions: " + ", ".join(extensions))

    codex_cli = which_any(("codex",))
    codex_bundle = bundled_codex()
    codex_binary = codex_cli or (str(codex_bundle) if codex_bundle else None)
    codex_home = Path(os.environ.get("CODEX_HOME", str(home / ".codex"))).expanduser()
    codex_extension = "openai.chatgpt" in extensions
    codex_installed = bool(
        codex_cli or codex_bundle or codex_home.exists() or codex_extension
    )
    codex_version = command_version(codex_binary)
    codex_evidence: list[str] = []
    if codex_cli:
        codex_evidence.append(codex_cli)
    if codex_home.exists():
        codex_evidence.append(display_path(codex_home))
    if codex_bundle:
        codex_evidence.append("bundled " + display_path(codex_bundle))
    if codex_extension:
        codex_evidence.append("VS Code extension openai.chatgpt")
    if codex_version:
        codex_evidence.append(codex_version)

    opencode_cli = which_any(("opencode",))
    opencode_configs = [home / ".config" / "opencode", home / ".opencode"]
    opencode_installed = bool(
        opencode_cli or any(path.exists() for path in opencode_configs)
    )
    opencode_version = command_version(opencode_cli)
    opencode_evidence: list[str] = []
    if opencode_cli:
        opencode_evidence.append(opencode_cli)
    if opencode_version:
        opencode_evidence.append(opencode_version)
    for path in opencode_configs:
        if path.exists():
            opencode_evidence.append(display_path(path))

    claude_cli = which_any(("claude",))
    claude_configs = [home / ".claude.json", home / ".claude" / "settings.json"]
    claude_installed = bool(
        claude_cli or any(path.is_file() for path in claude_configs)
    )
    claude_version = command_version(claude_cli)
    claude_evidence: list[str] = []
    if claude_cli:
        claude_evidence.append(claude_cli)
    if claude_version:
        claude_evidence.append(claude_version)
    for path in claude_configs:
        if path.is_file():
            claude_evidence.append(display_path(path))

    cursor_cli = which_any(("cursor",))
    cursor_configs = [home / ".cursor", home / ".config" / "Cursor"]
    cursor_app = app_path("cursor")
    cursor_installed = bool(
        cursor_cli
        or any(path.exists() for path in cursor_configs)
        or (cursor_app and cursor_app.exists())
    )
    cursor_version = command_version(cursor_cli)
    cursor_evidence: list[str] = []
    if cursor_cli:
        cursor_evidence.append(cursor_cli)
    if cursor_version:
        cursor_evidence.append(cursor_version)
    for path in cursor_configs:
        if path.exists():
            cursor_evidence.append(display_path(path))

    windsurf_cli = which_any(("windsurf",))
    windsurf_configs = [
        home / ".codeium" / "windsurf",
        home / ".config" / "devin",
        home / ".windsurf",
    ]
    windsurf_app = app_path("windsurf")
    windsurf_installed = bool(
        windsurf_cli
        or any(path.exists() for path in windsurf_configs)
        or (windsurf_app and windsurf_app.exists())
    )
    windsurf_version = command_version(windsurf_cli)
    windsurf_evidence: list[str] = []
    if windsurf_cli:
        windsurf_evidence.append(windsurf_cli)
    if windsurf_version:
        windsurf_evidence.append(windsurf_version)
    for path in windsurf_configs:
        if path.exists():
            windsurf_evidence.append(display_path(path))

    return [
        {
            "client": "vscode",
            "label": CLIENT_LABELS["vscode"],
            "installed": vscode_installed,
            "version": vscode_version,
            "evidence": vscode_evidence,
            "extensions": extensions,
            "project_path": str(PROJECT_PATHS["vscode"]),
            "global_path": str(GLOBAL_PATHS["vscode"]),
        },
        {
            "client": "codex",
            "label": CLIENT_LABELS["codex"],
            "installed": codex_installed,
            "version": codex_version,
            "evidence": codex_evidence,
            "binary": codex_binary,
            "project_path": str(PROJECT_PATHS["codex"]),
            "global_path": str(GLOBAL_PATHS["codex"]),
        },
        {
            "client": "opencode",
            "label": CLIENT_LABELS["opencode"],
            "installed": opencode_installed,
            "version": opencode_version,
            "evidence": opencode_evidence,
            "project_path": str(PROJECT_PATHS["opencode"]),
            "global_path": str(GLOBAL_PATHS["opencode"]),
        },
        {
            "client": "claude",
            "label": CLIENT_LABELS["claude"],
            "installed": claude_installed,
            "version": claude_version,
            "evidence": claude_evidence,
            "project_path": str(PROJECT_PATHS["claude"]),
            "global_path": str(GLOBAL_PATHS["claude"]),
        },
        {
            "client": "cursor",
            "label": CLIENT_LABELS["cursor"],
            "installed": cursor_installed,
            "version": cursor_version,
            "evidence": cursor_evidence,
            "project_path": str(PROJECT_PATHS["cursor"]),
            "global_path": str(GLOBAL_PATHS["cursor"]),
        },
        {
            "client": "windsurf",
            "label": CLIENT_LABELS["windsurf"],
            "installed": windsurf_installed,
            "version": windsurf_version,
            "evidence": windsurf_evidence,
            "project_path": str(PROJECT_PATHS["windsurf"]),
            "global_path": str(GLOBAL_PATHS["windsurf"]),
        },
    ]


def find_project_root(start: Path) -> tuple[Path, str]:
    """Resolve the project root: explicit target, git root, marker, or cwd."""
    start = start.resolve()
    try:
        result = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip()).resolve(), "git"
    except (OSError, subprocess.TimeoutExpired):
        pass

    current = start
    while True:
        for marker in ROOT_MARKERS:
            if (current / marker).exists():
                return current, f"marker:{marker}"
        if current.parent == current:
            return start, "cwd"
        current = current.parent


def auto_clients(detections: list[dict[str, object]]) -> list[str]:
    clients = list(SHARED_CLIENTS)
    for item in detections:
        if item["installed"]:
            client = str(item["client"])
            if client not in clients:
                clients.append(client)
    return clients


def print_detection(
    os_info: dict[str, str],
    root: Path,
    root_source: str,
    detections: list[dict[str, object]],
) -> None:
    print(f"os: {format_os(os_info)}")
    print(f"root: {root} ({root_source})")
    for item in detections:
        status = "yes" if item["installed"] else "no"
        version = f" {item['version']}" if item.get("version") else ""
        evidence = "; ".join(str(value) for value in item["evidence"])
        suffix = f" {evidence}" if evidence else ""
        print(f"  {str(item['client']):<8} {status:<3}{version}{suffix}".rstrip())


def detection_payload(
    os_info: dict[str, str],
    root: Path,
    root_source: str,
    detections: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "os": os_info,
        "root": {"path": str(root), "source": root_source},
        "clients": detections,
    }


def destinations(
    clients: list[str], scope: str, target: Path
) -> list[tuple[str, str, Path]]:
    pairs: list[tuple[str, str, Path]] = []
    seen: set[Path] = set()
    for client in clients:
        candidates: list[tuple[str, str, Path]] = []
        if scope in ("project", "both"):
            candidates.append(
                (client, "project", (target / PROJECT_PATHS[client]).resolve())
            )
        if scope in ("global", "both"):
            candidates.append(
                (client, "global", GLOBAL_PATHS[client].expanduser().resolve())
            )
        for name, kind, path in candidates:
            if path in seen:
                continue
            seen.add(path)
            pairs.append((name, kind, path))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client",
        choices=CLIENTS + ("all",),
        default=None,
        help="client to install (default: all unless --auto is used)",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="detect the OS and installed editors; install only those clients",
    )
    parser.add_argument(
        "--detect",
        action="store_true",
        help="print the OS, project root and installed editors; write nothing",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="with --detect, print machine-readable JSON",
    )
    parser.add_argument(
        "--scope",
        choices=("project", "global", "both"),
        default="project",
        help="project tree, home directory or both (default: project)",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="explicit project root; default: git root, nearest marker, or cwd",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the installed copies without writing anything",
    )
    args = parser.parse_args()

    if args.json and not args.detect:
        parser.error("--json requires --detect")
    if args.auto and args.client:
        parser.error("--auto cannot be combined with --client")

    os_info = detect_os()
    if args.target:
        target = Path(args.target).expanduser().resolve()
        root_source = "explicit"
    else:
        target, root_source = find_project_root(Path.cwd())

    detections = detect_clients()

    if args.detect:
        if args.json:
            print(
                json.dumps(
                    detection_payload(os_info, target, root_source, detections),
                    indent=2,
                )
            )
        else:
            print_detection(os_info, target, root_source, detections)
        return 0

    if args.auto:
        clients = auto_clients(detections)
        detected = [str(item["client"]) for item in detections if item["installed"]]
        missing = [str(item["client"]) for item in detections if not item["installed"]]
        print(f"os: {format_os(os_info)}")
        print(f"root: {target} ({root_source})")
        print("detected: " + (", ".join(detected) if detected else "none"))
        if missing:
            print("not found: " + ", ".join(missing))
        if not detected:
            print("no supported editor detected; installing shared paths only")
    else:
        clients = list(CLIENTS) if args.client in (None, "all") else [args.client]

    packs = discover()
    slugs = [slug for slug, _ in packs]
    pairs = destinations(clients, args.scope, target)

    failures: list[str] = []
    if not args.check:
        for _, _, dest in pairs:
            dest.mkdir(parents=True, exist_ok=True)

    for client, kind, dest in pairs:
        installed = unchanged = 0
        for slug, text in packs:
            target_file = dest / slug / "SKILL.md"
            if args.check:
                if not target_file.is_file():
                    failures.append(f"{client}: missing {target_file}")
                    continue
                if target_file.read_text(encoding="utf-8") != text:
                    failures.append(f"{client}: outdated {target_file}")
                    continue
                installed += 1
                continue
            if target_file.is_file() and target_file.read_text(encoding="utf-8") == text:
                unchanged += 1
                continue
            atomic_write(target_file, text)
            installed += 1
        state = "present" if args.check else "installed"
        print(
            f"{kind} {client}: {installed} {state}, {unchanged} unchanged -> {dest}"
        )

    if args.scope in ("project", "both"):
        block = render_index(packs)
        if args.check:
            for name in INDEX_FILES:
                failures.extend(check_index(target / name, slugs))
        else:
            for name in INDEX_FILES:
                print(f"index {name}: {replace_index_block(target / name, block)}")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1

    print(f"packs: {len(slugs)} ({', '.join(slugs)})")
    if args.check:
        print(f"CLIENT_SKILLS_PRESENT {len(slugs)}")
    else:
        print(f"CLIENT_SKILLS_INSTALLED {len(slugs)}")
    if args.auto:
        print("AUTO_CLIENT_INSTALL_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
