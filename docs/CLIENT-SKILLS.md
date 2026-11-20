# Client skills — one install for six editors

The eight audited packs in `packs/` are portable `SKILL.md` files. Every client
below understands that format, but each one scans a different directory. This
page maps the real paths and gives the one command that installs all of them.

## Quick start

```bash
git clone https://github.com/azurebluezone/zombiecoder-agent-skills.git
cd zombiecoder-agent-skills

# Install into one project (the usual case)
python3 tools/install_client_skills.py --client all --target /path/to/your/project

# Verify the copies
python3 tools/install_client_skills.py --check --client all --target /path/to/your/project
```

The installer is dependency-free Python 3.10+. It copies the eight packs into
the shared folders and each client's native folder, then writes one marked
index block into `AGENTS.md` and `CLAUDE.md`. Re-running it updates changed
files and replaces the block in place; it never duplicates the block.

For a home-directory install instead of one project:

```bash
python3 tools/install_client_skills.py --client all --scope global
python3 tools/install_client_skills.py --check --client all --scope global
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
```

The gate prints `CLIENT_SKILLS_OK` only after it has:

1. copied `packs/` and `tools/install_client_skills.py` into a clean temporary
   tree and installed them with one command;
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
