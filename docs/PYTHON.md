# Python integration

## What you need

| Item | Why |
| --- | --- |
| Python 3.9+ | The package uses only the standard library (`sqlite3`, `re`, `json`) |
| `skills.db` | 9.9 MB SQLite file with 256 skills and 75,358 term rows |
| `data/bn-intents.json` | Bengali intent bridge; without it the router stays English-only |
| `python/` | The `zombie_skills` package (no runtime dependencies) |

No network, no API key and no GitHub access is needed at chat time.

## Install

From the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e python
```

Or vendor the package into the project root and run from that root:

```text
my-project/
  skills.db
  data/bn-intents.json
  zombie_skills/
```

```bash
cp -r python/zombie_skills ./zombie_skills
cp skills.db ./skills.db
mkdir -p data && cp data/bn-intents.json ./data/
```

The package reads `skills.db` read-only. The default lookup checks
`ZOMBIE_SKILLS_DB`, then the repo layout, then `./skills.db`, then
`~/.zombie-skills/skills.db`; run from the project root or set the variable.
The Bengali bridge is resolved the same way through `ZOMBIE_SKILLS_INTENTS`.

Point the package at the database:

```bash
export ZOMBIE_SKILLS_DB="$PWD/skills.db"       # explicit path
# or leave unset: the package looks next to python/, then ./skills.db, then ~/.zombie-skills/skills.db
```

## Minimal use

```python
from zombie_skills import SkillStore

with SkillStore("/data/skills.db") as store:
    stats = store.stats()
    print(stats["active"], "skills,", stats["terms"], "terms")

    matches = store.route("debug a failing playwright test", limit=2)
    for match in matches:
        print(match["score"], match["name"], match["source"])

    skill = store.get("ui-ux-pro-max")
    print(skill["description"])
```

`route()` returns full skill rows (including `body`) because the injector needs them. `list()` returns previews only.

## Bengali routing

The same call accepts Bengali; the intent bridge rewrites it to English terms
before scoring:

```python
with SkillStore() as store:
    print(store.route("পাইথন ভার্চুয়াল এনভায়রনমেন্ট", limit=2)[0]["slug"])
    # python-operations
```

The bridge is resolved from the repo layout, then `./data/bn-intents.json`,
then `~/.zombie-skills/data/bn-intents.json`; set `ZOMBIE_SKILLS_INTENTS` for
an explicit path. A missing default file keeps the library English-only; a
missing explicit path raises instead of silently degrading.

## Inject before an OpenAI-compatible call

```python
from openai import OpenAI
from zombie_skills import SkillStore

store = SkillStore()
client = OpenAI(base_url="https://gpu.zombiecoder.my.id/v1", api_key="...")

user_text = "fix this flaky Playwright test"
messages, names = store.inject(
    [{"role": "user", "content": user_text}],
    user_text,
    limit=2,
    min_score=3.0,
    per_skill=1800,
    total=6000,
)
print("injected:", names)

response = client.chat.completions.create(
    model="Llama-3.2-3B-Instruct-Q4_K_M",
    messages=messages,
)
```

`inject()` does not mutate the list you pass in. It returns `(new_messages, matched_names)`. If nothing crosses the threshold, it returns the original messages and `[]`.

Without the OpenAI SDK:

```python
import json
import urllib.request

payload = {
    "model": "Llama-3.2-3B-Instruct-Q4_K_M",
    "messages": messages,
    "max_tokens": 512,
}
request = urllib.request.Request(
    "https://gpu.zombiecoder.my.id/v1/chat/completions",
    data=json.dumps(payload).encode(),
    headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
)
with urllib.request.urlopen(request, timeout=120) as response:
    print(json.load(response)["choices"][0]["message"]["content"])
```

## FastAPI example

```python
from fastapi import FastAPI
from pydantic import BaseModel
from zombie_skills import SkillStore

app = FastAPI()
store = SkillStore("/data/skills.db")  # one read-only connection, thread-safe via an internal lock

class ChatRequest(BaseModel):
    messages: list[dict]

@app.post("/chat")
def chat(request: ChatRequest):
    text = str(request.messages[-1].get("content") or "") if request.messages else ""
    messages, names = store.inject(request.messages, text)
    return {"messages": messages, "skills": names}
```

If you already have a `messages` list with a system prompt, `inject()` puts the skill block **before** it, as the first system message. That is deliberate: the gateway does the same, and the model sees the skills before the conversation.

## Flask example

```python
from flask import Flask, jsonify, request
from zombie_skills import SkillStore

app = Flask(__name__)
store = SkillStore("/data/skills.db")

@app.post("/chat")
def chat():
    messages = request.get_json(force=True).get("messages", [])
    text = messages[-1]["content"] if messages else ""
    injected, names = store.inject(messages, text)
    return jsonify({"messages": injected, "skills": names})
```

## API reference

### `SkillStore(db_path=None)`

Read-only connection. Raises `FileNotFoundError` with a hint when the DB is missing, and `ValueError` when required tables are absent.

### `store.stats()`

```python
{
  "db": "/data/skills.db",
  "db_bytes": 9928704,
  "total": 256,
  "active": 256,
  "terms": 75358,
  "bytes": 2094643,
  "sources": [{"source": "...", "skill_count": 182, ...}],
}
```

### `store.list(query="", source="", limit=50, offset=0)`

Substring search over name, description, tags and slug. `limit` is clamped to 1..200. Returns preview rows (first 500 body characters), not full bodies.

### `store.get(identifier)`

Full row by `id` or `slug`, or `None`.

### `store.route(text, limit=2, min_score=3.0)`

Returns matches sorted by score, deduplicated by slug. Each row includes `id`, `slug`, `name`, `description`, `source`, `kind`, `body`, `score`.

### `store.inject(messages, text, limit=2, min_score=3.0, per_skill=1800, total=6000)`

Returns `(messages, names)`. The injected block is:

```
You have selected the following skill instructions ...
### Skill: <name>
<description>

<body, truncated>
```

### `store.terms_for(skill_id, limit=400)`

Inspect the routing terms and weights for one skill. Useful for debugging a miss.

## Controls

| Control | Default | Effect |
| --- | --- | --- |
| `ZOMBIE_SKILLS_DB` | repo/cwd DB | Database path |
| `min_score` | `3.0` | Lower to catch broader matches; raise to be stricter |
| `limit` | `2` | Number of skills injected |
| `per_skill` | `1800` | Body characters per skill |
| `total` | `6000` | Total block characters |
| no `inject()` call | — | Disable routing entirely; `route()` is still available for inspection |

The package never executes a skill, never downloads anything, and never writes to the database. The gateway's runtime switch (`skill_anchor` / `X-Skills-Anchor: off`) is separate and only applies to the gateway.

## Add your own skills

```bash
python3 tools/import_skill.py --db skills.db --source local/my-project \
  --url file:///path/to/my-project --license MIT path/to/skills/

python3 tools/audit_skills.py --db skills.db --report audit
python3 tools/refresh_exports.py --db skills.db --out .
```

`SKILL.md` frontmatter fields used by the importer:

```markdown
---
name: my-skill
description: What this skill does and when to use it.
tags: [my-tag, my-domain]
triggers: [my-skill, my trigger phrase]
license: MIT
---

# Instructions
...
```

The importer accepts files or directories (it walks for `SKILL.md`), caps each file at 256 KB, upserts by `source::slug`, and rebuilds that skill's terms. Run the audit before committing a new source.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `FileNotFoundError: skills database not found` | Set `ZOMBIE_SKILLS_DB` or pass `db_path=` |
| `ValueError: ... missing tables` | Point at the real `skills.db`, not the gateway's wall-memory DB |
| No matches for a reasonable query | Lower `min_score` to `2.5` and inspect with `store.terms_for()` |
| Too many matches / wrong skill | Raise `min_score`, reduce `limit`, or add a `triggers` entry to the skill |
| Slow first call | SQLite opens and verifies the schema once; later calls are in-memory term lookups |

## Tests

```bash
PYTHONPATH=python python3 -m unittest discover -s python/tests -v
PYTHONPATH=python python3 -m zombie_skills.cli doctor
```

The tests assert counts, filtering, `get`, known routes, no-match small talk, injection shape and the real CLI.
