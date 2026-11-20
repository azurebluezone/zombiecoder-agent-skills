# MCP module

This is a separate module, not part of the ZombieCoder OpenCode plugin. It
exposes the same read-only skill library over the Model Context Protocol
(MCP), so any MCP host can discover and call the skills without custom HTTP
glue.

## Why MCP

The HTTP server is still useful for scripts and non-MCP hosts. MCP adds a
standard tool surface:

- the host lists `search_skills` and `get_skill` during the handshake;
- the model calls them with typed JSON arguments;
- the result is a text block the host can display or feed back;
- the same server works with OpenCode, Claude Desktop, Cursor and other MCP
  clients.

The adapter is thin: it imports the existing `SkillStore` and `compact_card`
from `server/skill_server.py`. It does not duplicate the database, the router
or the card renderer.

## Tools

| Tool | Arguments | Returns |
| --- | --- | --- |
| `search_skills` | `query` (string), `limit` (1–5, default 3) | Compact matches: slug, name, description, source, score |
| `get_skill` | `slug`, `mode` (`card` or `full`), `max_chars` | A 200–1200 character card, or the full body |

`card` is the default and the small-model surface. `full` is an explicit
second call; it is never injected automatically.

## Run

The server is stdio-only and opens `skills.db` read-only:

```bash
python3 /absolute/path/to/zombiecoder-agent-skills/server/skill_mcp.py
```

It writes JSON-RPC responses to stdout and logs to stderr. It never runs a
shell command, never writes the database and never fetches a URL.

## OpenCode setup

Add a project-local server; this does not touch the plugin configuration:

```bash
cd /path/to/project
opencode mcp add skills -- python3 /absolute/path/to/zombiecoder-agent-skills/server/skill_mcp.py
opencode mcp list
```

Expected:

```text
✓ skills       connected
```

The command writes `opencode.json` in the project root:

```json
{
  "mcp": {
    "servers": {
      "skills": {
        "type": "local",
        "command": [
          "python3",
          "/absolute/path/to/zombiecoder-agent-skills/server/skill_mcp.py"
        ]
      }
    }
  }
}
```

After a reload, the host exposes `search_skills` and `get_skill` as native
tools. A normal session can call them directly.

## Plugin boundary

The ZombieCoder plugin has its own tool allowlist. A `skills_*` tool may be
listed by the MCP host and still be denied to a plugin-controlled agent. That
denial is a plugin policy decision, not an MCP server failure. Do not edit the
plugin to make this module work; either use the MCP server from a session
without that allowlist, or add `skills_*` to the plugin allowlist as a separate,
reviewed change.

## Verify

```bash
python3 tools/check_skill_mcp.py
```

The check spawns the server, performs `initialize`, lists exactly two tools,
routes English and Bengali queries, loads a card and a full body, rejects an
unknown tool and an unknown method, answers `ping`, and proves `skills.db` is
byte-identical before and after. It prints `SKILL_MCP_OK` only when all of
those pass.

The host-level check is:

```bash
opencode mcp list
```

A connected line is proof that OpenCode loaded the server. It does not prove a
particular agent is allowed to call the tools; the plugin boundary above is a
separate permission layer.

## Client loop

```text
user task
  -> search_skills(query)          # deterministic router
  -> get_skill(slug, mode="card")  # compact procedure
  -> answer from the card
  -> get_skill(slug, mode="full")  # only if the card is insufficient
```

For a small model, give it only one action at a time. The router already
selected the candidates; the model only needs to load the top card.

## Trust

Skill text is untrusted reference. It is not permission to run a command,
read a secret or change a file. The server is local and unauthenticated; do not
expose the stdio process over a network socket.
