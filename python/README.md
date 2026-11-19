# zombie-skills (Python)

`pip install -e python` from the repository root, or `pip install git+https://github.com/azurebluezone/zombiecoder-agent-skills.git#subdirectory=python`.

The package reads the repository's `skills.db` (SQLite, read-only). Point it anywhere with `ZOMBIE_SKILLS_DB`:

```bash
export ZOMBIE_SKILLS_DB=/path/to/skills.db
zombie-skills stats
zombie-skills route "debug a failing playwright test"
```

```python
from zombie_skills import SkillStore, route_skills

store = SkillStore("/path/to/skills.db")
matches = store.route("design a tailwind landing page", limit=2)
print([(m["score"], m["name"]) for m in matches])

messages = [{"role": "user", "content": "fix this Playwright flake"}]
messages, names = store.inject(messages, "fix this Playwright flake")
```

Full integration guide: `docs/PYTHON.md` in the repository root.
