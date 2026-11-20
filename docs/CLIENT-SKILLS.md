# Client skills — one install for six editors

The eight audited packs in `packs/` are portable `SKILL.md` files. Every client
below understands that format, but each one scans a different directory. This
page maps the real paths and gives the one command that installs all of them.

## Quick start — one command from any directory

```bash
git clone https://github.com/azurebluezone/zombiecoder-agent-skills.git
python3 /path/to/zombiecoder-agent-skills/install.py
```

`install.py` defaults to `--auto`. It detects the operating system, detects the
editors that are actually installed, finds the project root from the current
directory, and installs only the detected clients plus the two shared folders.
Run it from the project root or any nested folder; it does not need to be
copied into the project.

Preview what it would do without writing anything:

```bash
python3 /path/to/zombiecoder-agent-skills/install.py --detect
python3 /path/to/zombiecoder-agent-skills/install.py --detect --json
```

Verify an existing install (also defaults to `--auto`):

```bash
python3 /path/to/zombiecoder-agent-skills/install.py --check
```

### Root discovery

The installer resolves the project root in this order:

1. an explicit `--target` path;
2. `git rev-parse --show-toplevel` for the current directory;
3. the nearest parent containing a project marker (`.git`, `package.json`,
   `pyproject.toml`, `Cargo.toml`, `go.mod`, `composer.json`, `Gemfile`,
   `AGENTS.md`, `CLAUDE.md`, `opencode.json`, `.vscode`);
4. the current directory when no marker is found.

### Editor detection

| Client | Detection evidence |
| --- | --- |
| VS Code | `code` / `code-insiders` on `PATH`, VS Code config directory, desktop app, or a known extension |
| Codex | `codex` on `PATH`, `~/.codex`, the bundled CLI inside the `openai.chatgpt` VS Code extension, or that extension itself |
| OpenCode | `opencode` on `PATH`, `~/.config/opencode`, or `~/.opencode` |
| Claude Code | `claude` on `PATH`, `~/.claude.json`, or `~/.claude/settings.json` |
| Cursor | `cursor` on `PATH`, `~/.cursor`, `~/.config/Cursor`, or the desktop app |
| Windsurf | `windsurf` on `PATH`, `~/.codeium/windsurf`, `~/.config/devin`, `~/.windsurf`, or the desktop app |

A client that is not detected is skipped, so a Linux server never receives
macOS or Windows-only folders. The shared `.agents/skills` and `.claude/skills`
folders are always written.

The installer is dependency-free Python 3.10+. It copies the eight packs into
the detected clients' native folders, then writes one marked index block into
`AGENTS.md` and `CLAUDE.md`. Re-running it updates changed files and replaces
the block in place; it never duplicates the block.

For a home-directory install instead of one project:

```bash
python3 /path/to/zombiecoder-agent-skills/install.py --scope global
python3 /path/to/zombiecoder-agent-skills/install.py --check --scope global
```

## Path matrix

| Client | Project path | User path | Official documentation |
| --- | --- | --- | --- |
| Claude Code | `.claude/skills/<slug>/SKILL.md` | `~/.claude/skills/<slug>/SKILL.md` | <https://code.claude.com/docs/en/skills> |
| OpenCode | `.opencode/skills/<slug>/SKILL.md` | `~/.config/opencode/skills/<slug>/SKILL.md` | <https://opencode.ai/docs/skills/> |
| Cursor | `.cursor/skills/<slug>/SKILL.md` | `~/.cursor/skills/<slug>/SKILL.md` | <https://cursor.com/docs/context/skills> |
| VS Code (Copilot) | `.github/skills/<slug>/SKILL.md` | `~/.copilot/skills/<slug>/SKILL.md` | <https://code.visualstudio.com/docs/copilot/customization/agent-skills> |
| Windsurf | `.devin/skills/<slug>/SKILL.md` | `~/.config/devin/skills/<slug>/SKILL.md` | <https://docs.windsurf.com/windsurf/cascade/skills> |
| Codex | `.agents/skills/<slug>/SKILL.md` | `~/.agents/skills/<slug>/SKILL.md` | <https://developers.openai.com/codex/skills/> |

The installer also writes the two shared compatibility folders:

| Shared path | Read by |
| --- | --- |
| `.agents/skills/` | Codex, Cursor, VS Code, Windsurf, OpenCode |
| `.claude/skills/` | Claude Code, OpenCode, Cursor, VS Code |

That is the answer to “can we put everything in one folder?”. No single folder
is read by all six clients. `.agents/skills` covers five of them but not Claude
Code; `.claude/skills` covers four but not Codex or Windsurf. Writing both
covers all six, and the native paths above remain available for clients that
prefer their own folder. On top of that, `AGENTS.md` is read by Codex and
Windsurf, and `CLAUDE.md` by Claude Code, so the generated index also reaches
agents that never scan a skill folder.

## Per-client install

```bash
# Claude Code only
python3 tools/install_client_skills.py --client claude --target /path/to/project

# OpenCode only
python3 tools/install_client_skills.py --client opencode --target /path/to/project

# Cursor only
python3 tools/install_client_skills.py --client cursor --target /path/to/project

# VS Code Copilot only
python3 tools/install_client_skills.py --client vscode --target /path/to/project

# Windsurf only
python3 tools/install_client_skills.py --client windsurf --target /path/to/project

# Codex only
python3 tools/install_client_skills.py --client codex --target /path/to/project

# Shared .agents/skills only (useful for a monorepo)
python3 tools/install_client_skills.py --client agents --target /path/to/project
```

`--client all` writes the shared folders plus the native folders for all six
clients. `--client agents` is the shared-only option.

## What each client actually reads

- **Claude Code** — project `.claude/skills/`, personal `~/.claude/skills/`.
  Invoke a skill directly with `/skill-name`; Claude also invokes one when the
  task matches its description.
- **OpenCode** — native project `.opencode/skills/`, global
  `~/.config/opencode/skills/`. For compatibility it also reads
  `.claude/skills`, `.agents/skills`, `~/.claude/skills` and
  `~/.agents/skills`. A plugin-free server was verified to list all eight IDs.
- **Cursor** — project `.cursor/skills/` and `.agents/skills/`, user
  `~/.cursor/skills/` and `~/.agents/skills/`. Cursor also loads
  `.claude/skills/`, `.codex/skills/`, `~/.claude/skills/` and
  `~/.codex/skills/` for compatibility.
- **VS Code (Copilot)** — project `.github/skills/`, personal
  `~/.copilot/skills/`. Local sessions also read `.claude/skills/` and
  `.agents/skills/`, plus the personal `~/.claude/skills/` and
  `~/.agents/skills/`.
- **Windsurf** — project `.devin/skills/`, global `~/.config/devin/skills/`.
  `.agents/skills/` is also read, and older builds still read the legacy
  `.windsurf/skills/` folder.
- **Codex** — `.agents/skills/` in the repository (scanned from the current
  directory up to the repository root) and `~/.agents/skills/` for the user.

## The generated index

`AGENTS.md` and `CLAUDE.md` receive one block delimited by:

```text
<!-- BEGIN zombiecoder-skills -->
...
<!-- END zombiecoder-skills -->
```

The block lists every installed slug with its frontmatter description, so an
agent that only reads instruction files still knows when to open the full
`SKILL.md`. If the block already exists, the installer replaces its contents;
if the file has user text outside the block, that text is preserved.

## Verify

```bash
python3 tools/check_client_skills.py
python3 tools/check_client_skills.py --auto
```

The gate prints `CLIENT_SKILLS_OK` only after it has:

1. copied `packs/`, `tools/install_client_skills.py` and `install.py` into a
   clean temporary tree and installed them with one command;
2. found all eight `SKILL.md` files byte-identical in `.agents/skills` and
   `.claude/skills`;
3. passed `--check` and a second byte-for-byte idempotent install;
4. written each client's documented native path;
5. found exactly one marked block with all eight slugs in both `AGENTS.md` and
   `CLAUDE.md`;
6. started a plugin-free `opencode serve` with a clean XDG config and received
   all eight local IDs from `/api/skill`;
7. confirmed this document lists the six clients and their paths; and
8. confirmed `origin/main` equals the local HEAD (skip during development with
   `--no-remote`).

With `--auto` the gate also prints `AUTO_CLIENT_INSTALL_OK` only after it has:

1. matched `--detect --json` against the real OS (`/etc/os-release`,
   `platform.machine()`), found VS Code, Codex and OpenCode, and confirmed that
   Claude Code, Cursor and Windsurf are absent;
2. resolved the git root from a nested directory inside a real repository and
   the `opencode.json` marker root from a nested project;
3. installed only VS Code and OpenCode under a fake `PATH`/`HOME`, skipping the
   absent clients, and run `install.py` with no arguments to prove it defaults
   to `--auto`;
4. run the real bundled `codex debug prompt-input` and found
   `python-operations` and `.agents/skills` in its output; and
5. confirmed `docs/CLIENTS.md` is not staged.

## Scope and limits

- The installer only writes the eight pack slugs. Other skills in the same
  destination are left alone.
- It validates each pack before copying: `name` must match the folder,
  `description` must be 1–1024 characters, and `source`/`license` must match
  the repository policy.
- It does not touch `docs/CLIENTS.md` (gateway/client compatibility), the
  SQLite database, or the ZombieCoder plugin.
- OpenCode was verified live with a plugin-free server. The other five CLIs
  were not installed on the verification machine, so their discovery is
  validated against the official paths above and the file layout, not a live
  agent invocation. If a client changes its folder, update this table and the
  installer together.
- `SKILL.md` is instructions, not executable code. The packs are MIT-licensed
  and remain untrusted text when they come from another repository.
