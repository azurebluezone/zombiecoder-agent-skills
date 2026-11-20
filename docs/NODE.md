# Node.js integration

## What you need

| Item | Why |
| --- | --- |
| Node 18+ | The package uses only `fs` and `path`; no native modules |
| `skills.jsonl` | 2.4 MB, one full skill per line |
| `terms.jsonl` | 5.2 MB, 75,358 routing terms |
| `node/` | The `SkillLibrary` reader/router/CLI |

The default path is **JSONL**, so it works on any Node version and needs no compiler. On Node 22.5+ you can opt into `skills.db` with `preferSqlite: true`.

## Install

### From this repository (local path)

```bash
npm install /path/to/zombiecoder-agent-skills
```

The root `package.json` points at `node/index.js` and includes `skills.jsonl` + `terms.jsonl`.

### From Git

```bash
npm install github:azurebluezone/zombiecoder-agent-skills
```

### Vendor the files

Copy `node/index.js`, `node/bin/cli.js`, `skills.jsonl` and `terms.jsonl` into your project. No install step is required.

```js
const { SkillLibrary } = require("./vendor/zombie-skills"); // whatever folder you copied node/ to
```

## Minimal use

```js
const { SkillLibrary } = require("zombiecoder-agent-skills");

const library = new SkillLibrary(); // skills.jsonl + terms.jsonl next to node/

console.log(library.stats());
const matches = library.route("debug a failing playwright test", { limit: 2 });
console.log(matches.map((match) => [match.score, match.name]));

const skill = library.get("ui-ux-pro-max");
console.log(skill.description);
```

### Explicit paths

```js
const library = new SkillLibrary({
  jsonl: "/data/zombie-skills/skills.jsonl",
  terms: "/data/zombie-skills/terms.jsonl",
});
```

Environment variables work too: `ZOMBIE_SKILLS_JSONL`, `ZOMBIE_SKILLS_TERMS`, `ZOMBIE_SKILLS_DB`.

## Inject before an OpenAI-compatible call

```js
const OpenAI = require("openai");
const { SkillLibrary } = require("zombiecoder-agent-skills");

const library = new SkillLibrary();
const client = new OpenAI({
  baseURL: "https://gpu.zombiecoder.my.id/v1",
  apiKey: process.env.ZOMBIECODER_API_KEY,
});

const userText = "fix this flaky Playwright test";
const { messages, names } = library.inject(
  [{ role: "user", content: userText }],
  userText,
  { limit: 2, minScore: 3.0, perSkill: 1800, total: 6000 }
);
console.log("injected:", names);

const response = await client.chat.completions.create({
  model: "Llama-3.2-3B-Instruct-Q4_K_M",
  messages,
});
```

`inject()` returns `{messages, names}`; it does not mutate the array you pass in. If no skill crosses the threshold it returns the original messages and `[]`.

## Express example

```js
const express = require("express");
const { SkillLibrary } = require("zombiecoder-agent-skills");

const app = express();
app.use(express.json());
const library = new SkillLibrary();

app.post("/chat", async (req, res) => {
  const input = req.body.messages || [];
  const text = String(input.at(-1)?.content || "");
  const { messages, names } = library.inject(input, text);
  res.json({ messages, skills: names });
});
```

## Next.js route handler

```ts
// app/api/chat/route.ts
import { NextResponse } from "next/server";
import { SkillLibrary } from "zombiecoder-agent-skills";

const library = new SkillLibrary();

export async function POST(request: Request) {
  const body = await request.json();
  const input = body.messages ?? [];
  const text = String(input.at(-1)?.content ?? "");
  const { messages, names } = library.inject(input, text);
  return NextResponse.json({ messages, skills: names });
}
```

For Next.js, keep the library in a server-only module (it reads files from disk). Do not import it in a client component.

## ESM

The package is CommonJS, but Node's ESM interop works:

```js
import { SkillLibrary } from "zombiecoder-agent-skills";
```

If your bundler is strict, use:

```js
import pkg from "zombiecoder-agent-skills";
const { SkillLibrary } = pkg;
```

## API reference

### `new SkillLibrary(options)`

| Option | Default | Meaning |
| --- | --- | --- |
| `jsonl` | repo `skills.jsonl` or `ZOMBIE_SKILLS_JSONL` | Skills export |
| `terms` | next to `jsonl` or `ZOMBIE_SKILLS_TERMS` | Terms export |
| `db` | next to `jsonl` or `ZOMBIE_SKILLS_DB` | SQLite file for `preferSqlite` |
| `preferSqlite` | `false` | Use `node:sqlite` when available (Node >= 22.5) |

### `library.stats()`

Returns `mode` (`jsonl` or `sqlite`), `total`, `active`, `terms`, `bytes`, `sources`.

### `library.list({q, source, limit=50, offset=0})`

Substring filter over name, description, tags and slug. Returns preview rows (first 500 body characters), not full bodies.

### `library.get(idOrSlug)`

Full row or `null`.

### `library.route(text, {limit=2, minScore=3.0})`

Returns matches sorted by score, deduplicated by slug. Each match includes `id`, `slug`, `name`, `description`, `source`, `kind`, `body`, `score`.

### `library.inject(messages, text, options)`

Returns `{messages, names}`. Options: `limit`, `minScore`, `perSkill` (default 1800), `total` (default 6000).

### `tokenize(text)`

The exact tokenizer used by the router. Useful for debugging.

## Optional SQLite path

```js
const library = new SkillLibrary({ preferSqlite: true });
console.log(library.stats().mode); // "sqlite"
```

`node:sqlite` is still marked experimental in some Node releases. The JSONL path is the portable default; the SQLite path is convenient when you already ship `skills.db` and run Node 22.5+.

## Controls

| Control | Default | Effect |
| --- | --- | --- |
| `ZOMBIE_SKILLS_JSONL` | repo/cwd | Skills export path |
| `ZOMBIE_SKILLS_TERMS` | next to JSONL | Terms export path |
| `minScore` | `3.0` | Lower to catch broader matches; raise to be stricter |
| `limit` | `2` | Number of skills injected |
| `perSkill` | `1800` | Body characters per skill |
| `total` | `6000` | Total block characters |
| no `inject()` call | — | Disable injection; `route()` still works |

The library never executes a skill, never downloads anything, and never writes to the data files.

## Add or update skills

The writer tools are Python because they share the import/audit logic:

```bash
python3 tools/import_skill.py --db skills.db --source local/my-project \
  --license MIT path/to/skills/
python3 tools/audit_skills.py --db skills.db --report audit
python3 tools/refresh_exports.py --db skills.db --out .
```

Commit the updated `skills.jsonl` and `terms.jsonl`; Node consumers pick them up on the next start.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `file not found: .../skills.jsonl` | Pass `jsonl`/`terms` paths or run from the repo root |
| `node:sqlite is unavailable` | Use the default JSONL mode or upgrade to Node >= 22.5 |
| No matches for a reasonable query | Lower `minScore` to `2.5`; inspect `library.route(text, {minScore: 0})` |
| Too many matches / wrong skill | Raise `minScore`, reduce `limit`, or add `triggers` to the skill |
| Slow first call | One-time JSONL parse (~2.3 MB + 4.8 MB); later calls use in-memory maps |

## Tests

```bash
node node/test.js
node node/bin/cli.js doctor
```

The tests assert counts, known routes, no-match small talk, `get`, list filtering, injection shape, and the optional `node:sqlite` path when available.
