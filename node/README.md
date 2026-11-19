# zombie-skills (Node.js)

Zero runtime dependencies. Node 18+ reads `skills.jsonl` + `terms.jsonl`; Node 22.5+ can also read `skills.db` directly through `node:sqlite`.

```bash
# from the repository root
node node/bin/cli.js stats
node node/bin/cli.js route "debug a failing playwright test"
node node/bin/cli.js get ui-ux-pro-max
```

```js
const { SkillLibrary } = require("./node");

const library = new SkillLibrary(); // repo root: skills.jsonl + terms.jsonl
const matches = library.route("design a tailwind landing page", { limit: 2 });
console.log(matches.map((match) => [match.score, match.name]));

const { messages, names } = library.inject(
  [{ role: "user", content: "fix this Playwright flake" }],
  "fix this Playwright flake"
);
```

For a project installed elsewhere, copy `skills.jsonl` and `terms.jsonl` next to `node/index.js`, or pass explicit paths:

```js
new SkillLibrary({ jsonl: "/data/skills.jsonl", terms: "/data/terms.jsonl" });
```

Full integration guide: `docs/NODE.md` in the repository root.
