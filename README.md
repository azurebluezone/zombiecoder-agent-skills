# ZombieCoder Agent Skills

A portable, auditable skill library for AI agents. It packages **256 skills**: **248 curated `SKILL.md` skills** from six MIT-licensed public repositories plus **8 local language, data, hosting and browser runbooks**, all in one SQLite database with dependency-free JSONL exports and a deterministic local router that injects the best two skills into a chat request.

No GitHub access is needed at chat time. Copy `skills.db` (or the JSONL files) into any Python or Node project and route locally.

```
user text -> tokenizer -> SQLite/JSONL term index -> weighted score -> top 2 skills -> system message
```

## What is inside

| File | Size | Purpose |
| --- | ---: | --- |
| `skills.db` | 9.9 MB | Canonical SQLite store: `skills`, `skill_terms`, `skill_sources`, `meta` |
| `skills.jsonl` | 2.4 MB | One full skill per line, for Node and other JSON readers |
| `terms.jsonl` | 5.2 MB | 75,358 routing terms (`term`, `skill_id`, `weight`) |
| `skills.meta.json` | 2 KB | Counts, source summary, SHA-256 and byte sizes |
| `packs/` | — | Editable `SKILL.md` sources for the local runbooks (Python, JavaScript/TypeScript, PHP, C++, CDP, SQLite, MySQL, hosting) |
| `python/` | — | `zombie-skills` Python package (stdlib only) |
| `node/` | — | Zero-dependency Node.js reader, router and CLI |
| `server/` | — | Zero-dependency HTTP loader plus a separate stdio MCP module |
| `examples/` | — | Python client and a live small-model tool loop (Ollama) |
| `tools/` | — | Import, audit, export and build tools |
| `audit/` | — | Full keep/drop report (`report.json`, `report.csv`) |

Current build: **256 skills**, **75,358 term rows**, **2,094,643 bytes** of skill bodies. Six upstream sources plus the local pack source, all MIT:

| Source | Kept skills |
| --- | ---: |
| `alirezarezvani/claude-skills` | 182 |
| `zhaoxuya520/reverse-skill` | 35 |
| `gmh5225/awesome-game-security` | 13 |
| `nextlevelbuilder/ui-ux-pro-max-skill` | 7 |
| `ConardLi/garden-skills` | 6 |
| `morluto/rea` | 5 |
| `local/zombiecoder-packs` | 8 |

The original import contained 589 skills. The audit removed **341**: 206 sales/marketing/brokerage/corporate/compliance skills, 68 offensive or abuse-oriented skills, and 67 redirect-only stubs. The eight local runbooks were added after that audit and are not part of the 248 upstream skills. See [docs/AUDIT.md](docs/AUDIT.md) for the policy and the full report.

## Quick start

### Python (3.9+, stdlib only)

```bash
cd zombiecoder-agent-skills
python3 -m venv .venv && . .venv/bin/activate
pip install -e python

export ZOMBIE_SKILLS_DB="$PWD/skills.db"
zombie-skills stats
zombie-skills route "debug a failing playwright test"
```

```python
from zombie_skills import SkillStore

store = SkillStore()  # ZOMBIE_SKILLS_DB or ./skills.db
matches = store.route("design a tailwind landing page", limit=2)
messages, names = store.inject(
    [{"role": "user", "content": "design a tailwind landing page"}],
    "design a tailwind landing page",
)
```

Full guide: [docs/PYTHON.md](docs/PYTHON.md).

### Node.js (18+, zero dependencies)

```bash
node node/bin/cli.js stats
node node/bin/cli.js route "debug a failing playwright test"
node node/bin/cli.js get ui-ux-pro-max
```

```js
const { SkillLibrary } = require("./node");

const library = new SkillLibrary();  // skills.jsonl + terms.jsonl
const matches = library.route("design a tailwind landing page", { limit: 2 });
const { messages, names } = library.inject(
  [{ role: "user", content: "fix this Playwright flake" }],
  "fix this Playwright flake"
);
```

Full guide: [docs/NODE.md](docs/NODE.md).

### Skill server (Python, stdlib only)

```bash
python3 server/skill_server.py --port 8787
curl -s http://127.0.0.1:8787/health
curl -s 'http://127.0.0.1:8787/skills/database-designer?mode=card'
```

The server is read-only and exposes two small-model tools, `search_skills` and
`get_skill`. It returns a compact card by default and the full body only on an
explicit call. Full endpoints and the tool loop: [server/README.md](server/README.md).

A real local-model demo:

```bash
python3 examples/ollama_tool_loop.py
```

### MCP (separate module)

The same two tools are available over stdio MCP, independent of the
ZombieCoder plugin:

```bash
opencode mcp add skills -- python3 /absolute/path/server/skill_mcp.py
opencode mcp list          # ✓ skills connected
python3 tools/check_skill_mcp.py   # SKILL_MCP_OK
```

Setup, tool schema, the plugin allowlist boundary and the client loop:
[docs/MCP.md](docs/MCP.md).

### OpenCode native skills

The eight local packs can also be installed as native OpenCode skills, so the
host loads them in every working directory without the HTTP server:

```bash
python3 tools/install_opencode_skills.py        # -> ~/.opencode/skills/<slug>/SKILL.md
python3 tools/install_opencode_skills.py --check
opencode reload
opencode api GET /api/skill                     # includes the eight local slugs
```

The installer validates `name`, `description` (1-1024 characters), `source` and
`license` before copying, and is idempotent. The check
`python3 tools/check_remaining_packs.py` proves the installed files and the
registry entry together.

### CLI cheat sheet

```bash
# Python
zombie-skills route "write a changelog for the last release" --limit 3
zombie-skills list --source nextlevelbuilder/ui-ux-pro-max-skill
zombie-skills get ui-ux-pro-max
zombie-skills doctor

# Node (same commands)
node node/bin/cli.js route "write a changelog for the last release"
node node/bin/cli.js doctor
node node/bin/cli.js --sqlite route "design a landing page"   # Node >= 22.5
```

## How routing works

1. **Tokenize**: lowercase, split on the same regex as the gateway, drop English stopwords and 1-character tokens.
2. **Score terms**: name `8`, tags `5`, triggers `5`, description `3`, body `1`.
3. **Specificity weighting**: each term contribution is `weight / document_frequency^0.4`, so rare terms beat generic ones such as `file` or `download`.
4. **Evidence bonus**: multiple independent query terms pointing at one skill add `0.35` each.
5. **Exact bonuses**: the skill name in the query adds `10`; the slug as words adds `6`.
6. **Select**: default `min_score=3.0`, top 2, deduplicated by slug.
7. **Inject**: prepend one system message with each skill's description and up to 1,800 characters of body (6,000 total).

The same algorithm is implemented in the gateway (`welcome_to_colab.py`), Python and Node. The term index is stored in SQLite; Node reads the identical `terms.jsonl` export.

### Verified routes

| Input | Top matches (score) |
| --- | --- |
| `design a tailwind ux design system landing page` | `landing` 19.71, `design` 19.12, `design-system` 10.03 |
| `debug a failing playwright test` | `fix` 3.92 |
| `write a changelog for the last release` | `changelog-generator` 5.29, `rea-changelog-update` 3.89 |
| `book to skill` | `book-to-skill` 8.79, `cs-book-to-skill` 3.19 |
| `android reverse engineering` | `reverse-engineering` 9.49, `mobile-reverse` 3.69 |
| `python venv pyproject typing unittest asyncio cli` | `python-operations` 28.02 |
| `node esm typescript strip http server fetch abort vite next` | `javascript-typescript-operations` 25.43 |
| `hello how are you` | no injection |

## Use it in another project

- Python: [docs/PYTHON.md](docs/PYTHON.md) — copy the DB, `pip install -e python`, inject before your OpenAI-compatible call.
- Node: [docs/NODE.md](docs/NODE.md) — copy `skills.jsonl` + `terms.jsonl`, `require("./node")`, inject before your chat call.
- Server: [server/README.md](server/README.md) — run the read-only HTTP loader; route, card, inject, and two tools.
- MCP: [docs/MCP.md](docs/MCP.md) — stdio MCP module, OpenCode setup, tool schema, plugin boundary and `SKILL_MCP_OK` check.
- Portable pack: [docs/SKILL-PACK.md](docs/SKILL-PACK.md) — hand this document to an agent in another project; it selects and writes the project-local skill files.
- Invocation contract: [docs/INVOCATION.md](docs/INVOCATION.md) — host behaviour, provenance, trust and token budget.
- Gateway: [docs/GATEWAY.md](docs/GATEWAY.md) — the Colab/Flask app pulls this repository over HTTPS, verifies the DB SHA-256 and replaces wall memory.
- Client compatibility: [docs/CLIENTS.md](docs/CLIENTS.md) — OpenCode, VS Code/Continue, curl, OpenAI/Anthropic endpoints.
- Schema: [docs/SCHEMA.md](docs/SCHEMA.md).
- Security: [docs/SECURITY.md](docs/SECURITY.md).
- Audit policy: [docs/AUDIT.md](docs/AUDIT.md).

## Add, update or remove skills

```bash
# 1. Import a local SKILL.md file or a directory tree
python3 tools/import_skill.py --db skills.db --source local/my-project \
  --url file:///path/to/my-project --license MIT path/to/skills/

# 2. Re-run the audit (read-only report first)
python3 tools/audit_skills.py --db skills.db --report audit
python3 tools/audit_skills.py --db skills.db --report audit --apply

# 3. Rebuild the JSONL exports and metadata
python3 tools/refresh_exports.py --db skills.db --out .

# 4. Verify
PYTHONPATH=python python3 -m unittest discover -s python/tests -v
node node/test.js
```

`tools/build_from_wall_memory.py` exports the gateway's wall-memory tables into this repository layout.

## Gateway integration

The Flask gateway in `welcome_to_colab.py` keeps a `skill_git_url` setting (default `https://github.com/azurebluezone/zombiecoder-agent-skills.git`) and a `skill_git_branch` setting (default `main`). The admin Skills page has **Pull from git**, which:

1. resolves the GitHub URL to `raw.githubusercontent.com`,
2. downloads `skills.db` and `skills.meta.json` with a size cap,
3. verifies the SHA-256 from the metadata,
4. validates the schema and imports the tables in one transaction,
5. leaves `X-Skills-Anchor: off` and the Settings toggle as the runtime opt-out.

Details and API: [docs/GATEWAY.md](docs/GATEWAY.md).

## Security

Skill bodies are untrusted text from public repositories. They are **not executed** by this library, but they are injected into a model prompt and can contain prompt-injection or unsafe instructions. The audit removes known offensive/business/stub material, but it is a review aid, not a sandbox. Read [docs/SECURITY.md](docs/SECURITY.md) before enabling the library in a sensitive environment.

## License and attribution

MIT. Upstream repositories are MIT as well; see [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md). The skills remain derivative works of their original authors.
