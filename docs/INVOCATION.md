# Skill invocation contract

Status: v1, 2026-11-20. Contract `gc-mwo98y4o`. This document records what
the major agent hosts actually do, the portable pattern this repository
implements, and the limits of the current slice.

## 1. Verified host behaviour

Checked against the official documentation on 2026-11-20. The common pattern is
a directory per skill, a `SKILL.md` file, `name` + `description` metadata, and
progressive disclosure: the host sees the metadata first and reads the body
only when it selects the skill.

| Host | Discovery | Loading | Source |
| --- | --- | --- | --- |
| Claude Code | `.claude/skills/<name>/SKILL.md`, personal `~/.claude/skills/` | YAML `name` + `description`; body loaded on use; `/skill-name`; optional `allowed-tools`, `disable-model-invocation` | <https://code.claude.com/docs/en/skills.md> |
| Cursor | `.cursor/skills/`, `.agents/skills/`, user-level equivalents; also reads `.claude/skills/` and `.codex/skills/`; recursive below the skills root | `SKILL.md` frontmatter; `disable-model-invocation`; progressive | <https://cursor.com/docs/skills.md> |
| Codex / ChatGPT | `SKILL.md` skill folders | `name` + `description` required; progressive; descriptions may be shortened under a budget; `[[skills.config]]` in `~/.codex/config.toml` | <https://learn.chatgpt.com/docs/build-skills.md> |
| VS Code / Copilot | Project `.github/skills/`, personal `~/.copilot/skills/`; harness-dependent `.claude/skills/` and `.agents/skills/` | Agent Skills open standard; `SKILL.md`; folder name must match frontmatter `name`; `/skill-name`; `user-invocable`, `disable-model-invocation` | <https://code.visualstudio.com/docs/agent-customization/agent-skills.md> |
| Antigravity | Workspace `.agents/skills/<folder>/SKILL.md`, global `~/.gemini/config/skills/`; `.agents/skills.json` manifest for paths outside the one-level scan | Progressive; slash invocation; rules use `always_on`, `model_decision`, `glob`, `manual` triggers | <https://antigravity.google/docs/skills.md>, <https://antigravity.google/docs/customization-discovery.md> |
| Windsurf | Docs now redirect to Devin Desktop: `AGENTS.md`, `.devin/rules/*.md` (legacy `.windsurf/rules/`), skills in skill folders, workflows in `.devin/workflows/` | Skills use progressive disclosure; rules are always-on; workflows are explicit `/name` commands | <https://docs.devin.ai/desktop/customizations>, <https://docs.devin.ai/desktop/cascade> |
| Open standard | `SKILL.md` in a skill directory | YAML frontmatter with required `name` and `description`; body is the instruction payload | <https://agentskills.io/specification> |

What this repository adopts: directory-shaped `SKILL.md` content, `name` +
`description` as the routing surface, progressive loading, and an explicit
invocation path. It does not require any host SDK or runtime.

## 2. Decision

The library stays a **portable data plane**, not another agent runtime:

- canonical data: `skills.db` (SQLite) plus `skills.jsonl` / `terms.jsonl`;
- zero-dependency readers: `node/index.js` and `python/zombie_skills/`;
- one new data file: `data/bn-intents.json`, a Bengali retrieval bridge;
- no parser, no network call, no model call, and no code execution at load time;
- the host owns confirmation, tool permissions, and conversation state.

Skill text is context, not authority. Every row keeps `source`, `source_url`,
`license` and `content_hash`; the injection header says the block is untrusted
reference and not permission to run commands.

## 3. Invocation contract

### Request

```json
{
  "text": "ডেটাবেস ডিজাইন করো",
  "locale": "bn",
  "limit": 2,
  "min_score": 3.0,
  "expand": true,
  "explicit_skill": null,
  "per_skill_chars": 1800,
  "total_chars": 6000
}
```

### Response

```json
{
  "query": "database designer schema করো",
  "matched_terms": ["database", "designer", "schema"],
  "matches": [
    {
      "slug": "database-designer",
      "score": 11.43,
      "source": "alirezarezvani/claude-skills",
      "license": "MIT",
      "content_hash": "..."
    }
  ],
  "confidence": "high",
  "inject": true,
  "block_chars": 1840,
  "reason": "3 retrieval terms and an exact slug phrase"
}
```

### Steps

1. **Normalize** the input to NFC. Unicode decomposes Bengali yya, rra and rha
   to base + nukta, so precomposed and decomposed keyboard input meet on the
   same spelling.
2. **Expand** Bengali intent with `data/bn-intents.json`. Entries are applied
   longest first, so `ডিজাইন সিস্টেম` wins over `ডিজাইন`. Only the first
   `max_terms` (24) English terms are added; the file is data, never code.
3. **Tokenize** the rewritten query and cap it at 40 unique tokens. English
   input bypasses expansion because it contains no bridge keys.
4. **Score** each candidate: `weight / document_frequency^0.4`, a small
   co-occurrence bonus, and exact name/slug bonuses. Deduplicate by slug.
5. **Threshold** at `min_score` (default 3.0). Return at most `limit` skills.
6. **Classify confidence**: `high` for a score of 10+ or three or more matched
   terms; `medium` at the threshold; `low` for a weak single-term hit; `none`
   for no match.
7. **Verify before injection**. An explicit `@skill` / `/skill-name` request
   wins. Otherwise the host should inject only when the match fits the user's
   stated task; a low-confidence hit is a suggestion, not an instruction. The
   v1 router returns the evidence; the host applies this policy.
8. **Render** a system block with the trust header, at most 1,800 characters
   per skill and 6,000 characters total.
9. **Log** the selected slug, source, license and content hash so a later
   answer can be traced back to the skill that shaped it.

### Language-agnostic calls

```bash
# Any language: call the CLI and read JSON
node node/bin/cli.js route "ডেটাবেস ডিজাইন করো" --json
python -m zombie_skills.cli route "ডেটাবেস ডিজাইন করো" --json
```

```js
const { SkillLibrary } = require("./node/index.js");
const library = new SkillLibrary();
const query = library.expand("ডেটাবেস ডিজাইন করো");
const matches = library.route("ডেটাবেস ডিজাইন করো", { limit: 2 });
const { messages, names } = library.inject(messages, "ডেটাবেস ডিজাইন করো");
```

```python
from zombie_skills import SkillStore
from zombie_skills.router import expand_query

store = SkillStore("skills.db")
query = expand_query("ডেটাবেস ডিজাইন করো")
matches = store.route("ডেটাবেস ডিজাইন করো", limit=2)
messages, names = store.inject(messages, "ডেটাবেস ডিজাইন করো")
```

`expand=False` / `--no-expand` routes the raw text. It exists for parity tests
and for hosts that do their own translation.

## 4. Token budget

| Stage | Budget | Why |
| --- | --- | --- |
| Bengali expansion | 24 English terms | keeps the rewrite smaller than the context it replaces |
| Query tokens | 40 unique terms | bounds scoring work and noise |
| Injected skills | 2 by default | one primary procedure plus one supporting reference |
| Per skill | 1,800 characters | enough for a checklist, not a whole manual |
| Total block | 6,000 characters | a small, predictable system-message cost |

These are defaults, not universal truths. A host can raise them for a
long-running task, but the response should record the actual `block_chars`.

## 5. Distribution model

Use the repository folder (or its archive) as the unit of distribution:

```
zombiecoder-agent-skills/
├── skills.db
├── skills.jsonl
├── terms.jsonl
├── skills.meta.json      # counts + SHA-256 trust anchor
├── data/bn-intents.json  # Bengali bridge
├── node/
└── python/
```

- **Shared or cloud folder:** copy the whole folder; point readers at it with
  `ZOMBIE_SKILLS_DB`, `ZOMBIE_SKILLS_JSONL`, `ZOMBIE_SKILLS_TERMS`, and
  `ZOMBIE_SKILLS_INTENTS`.
- **Zero-install Node:** `node node/bin/cli.js ...` works with no
  `node_modules`. `npm install` is only for a global `zombie-skills` binary or
  publishing.
- **Python:** `PYTHONPATH=python` from the folder, or install the package. A
  pip-only install has no repository `data/` folder; set
  `ZOMBIE_SKILLS_INTENTS` to the bridge file, or the router stays English-only
  instead of failing.
- **Read-only:** open SQLite with `mode=ro`; never write to the database at
  request time.
- **Secrets:** keep bearer keys and gateway credentials out of the library,
  examples and logs.

## 6. Verification

```bash
python3 zombiecoder-agent-skills/tools/check_bn_route.py
```

The check exits 0 and prints `SKILLS_BN_ROUTE_OK` only after it validates the
bridge file, seven Bengali intent cases through the Python SQLite router, Node
and Python top-slug parity, `--no-expand` returning nothing for Bengali, three
English routes staying identical with expansion on and off, and an unmapped
Bengali sentence returning no match.

## 7. Limits

- The bridge is a curated retrieval map, not a translator. A new intent needs
  an entry; unknown Bengali text does not silently match.
- Routing is deterministic term scoring, not embeddings. A single common word
  can stay below the threshold even when it is relevant; that is deliberate.
- Skill bodies are untrusted content. The audit report is a review aid, not a
  sandbox; see `docs/SECURITY.md` and `docs/AUDIT.md`.
- This contract ships the bridge and the invocation contract. Language, domain
  and education coverage is tracked in `docs/GAPS.md` and needs separate,
  provenance-checked additions.
- Antigravity and Windsurf move quickly; the source links above are the
  authority, not this table.
