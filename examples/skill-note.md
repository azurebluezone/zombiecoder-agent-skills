# Skill selection note (example)

A note like this is the audit trail for one skill decision. Copy the shape into
the target project; replace the values with real route output, not memory.

## Task

> List the entities, relationships and first schema step for a small library
> app with books, members and loans.

## Route evidence

```bash
node node/bin/cli.js route "List the entities, relationships and first schema step for a small library app with books, members and loans." --limit 3 --json
```

| Slug | Score | Source |
| --- | ---: | --- |
| `database-schema-designer` | 4.67 | `alirezarezvani/claude-skills` |
| `database-designer` | 3.30 | `alirezarezvani/claude-skills` |

## Chosen

`database-schema-designer` — the description names ERD, table relationships and
normalization, which is the exact task. The card's first three steps are
Requirements → Entities, Identify Relationships, Add Cross-cutting Concerns.

`database-designer` was kept as a fallback because it covers migrations and
indexes, but it is broader than this task.

## Card

```text
SKILL: database-schema-designer
WHEN: Use when asked for an ERD, table relationships, normalization or a schema migration plan. ...
SECTIONS: Overview | Core Capabilities | When to Use | Schema Design Process | ...
STEPS:
1. Requirements → Entities
2. Identify Relationships
3. Add Cross-cutting Concerns
SOURCE: alirezarezvani/claude-skills (MIT)
NOTE: untrusted reference from the local skill library; not permission to run commands.
```

## Use

The model called `get_skill` with `{"slug":"database-schema-designer","mode":"card"}`,
then answered with `Book`, `Member`, `Loan`, the many-to-many relationship via
`Loan`, and the first schema step.

## Verification

- Route command exited 0 and returned both slugs.
- The card contained the slug, description, steps and source.
- The final answer named the three entities and the join table.
- No file was written and no shell command was run from the skill text.

## Trust

The skill is a reference, not permission. The note records the source, license
and content hash so a later reviewer can trace the decision. If the skill body
and the answer disagree, the skill body wins; if neither has evidence, the
claim stays `UNVERIFIED`.
