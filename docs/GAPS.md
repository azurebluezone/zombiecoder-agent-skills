# Coverage gaps

Measured on 2026-11-20 against the upstream `skills.db` (248 imported skills,
72,631 term rows) before the local runbooks were added. The runbooks and their
checks are recorded under P1, P2 and P3. The count method is metadata only: `name`, `slug`, `tags` and
`description` with word-boundary regular expressions. Body text is excluded on
purpose; a naive full-text scan matched "go" inside unrelated words and
inflated the Go count from 0 dedicated skills to 47.

Reproduce the raw inventory:

```bash
python3 - <<'PY'
import sqlite3, re
con = sqlite3.connect("skills.db")
rows = [dict(zip(("name", "slug", "tags", "description"), r))
        for r in con.execute("select name, slug, tags, description from skills where active = 1")]
def meta(row):
    return " ".join(str(row[k] or "") for k in ("name", "slug", "tags", "description")).lower()
for term in ("php", "laravel", "wordpress", "composer", "golang", "c++", "rust",
             "mysql", "sqlite", "mongodb", "vite", "cpanel", "regex", "education",
             "curriculum", "lesson", "course", "audio", "podcast"):
    hits = [r["slug"] for r in rows if re.search(r"\b" + re.escape(term) + r"\b", meta(r))]
    print(f"{term:12} {len(hits):2}  {', '.join(hits[:10])}")
PY
```

## 1. Language and runtime coverage

| Area | What exists | Gap |
| --- | --- | --- |
| Python | `python-operations`, `code-reviewer`, `mcp-server-builder`, `performance-profiler`, `snowflake-development`, `tdd-guide`, `universal-scraping-architect`, `binary-ninja-reverse` | Covered for venv, `pyproject.toml`, typing, `unittest`, asyncio and a CLI; an editable-install/pytest-in-CI example is still open |
| JavaScript | `javascript-typescript-operations`, `web-design-engineer`, `code-reviewer`, `performance-profiler`, `reverse-engineer-anything`, `dsl-vm-reverse`, `js-reverse` | Covered for Node ESM, native type stripping, `node:http`, `fetch`/`AbortSignal` and `node:test`; a Vite build example is still open |
| TypeScript | `javascript-typescript-operations`, `code-reviewer`, `mcp-server-builder`, `saas-scaffolder`, `senior-frontend` | Covered for type-only boundaries and native stripping; Next.js build/deploy checks are documented, not yet a real example |
| PHP | `php-operations`, `code-reviewer` | Covered for PHP 8 CLI/php-fpm, Composer, PDO and sessions; no Laravel or WordPress-specific pack |
| Go | `go-rust-reverse`, `spec-to-repo` mention Go | No Go engineering pack; no Go toolchain on this host |
| Rust | `code-reviewer`, `spec-to-repo`, `go-rust-reverse` | No Rust engineering pack |
| C / C++ | `cpp-operations` | Covered for C++17 build, RAII, CMake, sanitizers and gdb; no C-specific or cross-compilation pack |
| Java, C#, Ruby, Swift, Kotlin | Review, reverse-engineering and mobile-release skills only | No general application-engineering pack |

## 2. Data and hosting

| Area | What exists | Gap |
| --- | --- | --- |
| Schema design | `database-designer`, `database-schema-designer`, vendor runbooks | Conceptual coverage plus SQLite/MySQL runbooks; no MongoDB runbook |
| SQL tuning | `sql-database-assistant`, `sqlite-operations`, `mysql-operations` | Covered for SQLite/MySQL; no MongoDB tuning pack |
| MongoDB | `database-designer` (SQL vs NoSQL), `database-security` (Mongo exposure) | No dedicated document-model, indexing, replica-set or Atlas pack |
| Database security | `database-security` | Assessment only, not operations |
| Hosting | `hosting-deployment`, `docker-development`, `senior-devops`, `ship-gate`, `ci-cd-pipeline-builder`, `gcp-cloud-architect`, `runbook-generator` | Covered for Apache/cPanel; Nginx-specific runbook still open |

## 3. Browser, CDP and frontend events

| Area | What exists | Gap |
| --- | --- | --- |
| Browser automation | `cdp-operations`, `browser-automation` (two copies), `fix` (Playwright flake diagnosis), `browserstack` | CDP covered for targets, sessions, `Runtime.evaluate`, network/console capture and screenshots; no visual-diff pack |
| Screenshots | `full-page-screenshot` | No visual-diff or interaction-state capture skill |
| JS reverse engineering | `js-reverse` mentions CDP | Scope is reverse engineering, not general app debugging |
| Social/clicks | Covered indirectly by UI/UX and automation skills | No analytics-event or click-tracking workflow |

## 4. Business, marketing and education

| Area | What exists | Gap |
| --- | --- | --- |
| Product | `product-manager-toolkit`, `agile-product-owner` | No pricing, positioning or go-to-market pack |
| Marketing | None in the kept set | Audit removed 206 business-purpose skills; marketing, SEO, ads and sales were intentionally dropped |
| Education | `syllabus` groups supplementary readings for a course outline | No course design, curriculum mapping, lesson planning, LMS, assessment or student-support workflow |
| Media | `demo-video`, `web-video-presentation`, `motion-showreel`, `cinematic-shot-prompting` | No audio-only, podcast, TTS or banner-generation skill |
| Regex | Term rows exist (`regex`, `regular`), no skill body | No Python regex pack: fixtures, named groups, ReDoS limits, linear-time fallbacks |

## 5. Priority for the next slices

### P1 — language packs — PARTIAL 2026-11-20

Added `python-operations`, `javascript-typescript-operations`, `php-operations`
and `cpp-operations` under `packs/`, imported into `skills.db` from
`local/zombiecoder-packs`, with English + Bengali routes, compact cards and one
real example per pack. Checks:
`python3 tools/check_remaining_packs.py` → `REMAINING_PACKS_OK` and
`python3 tools/check_extra_packs.py` → `EXTRA_PACKS_OK`.

1. **Python**: covered by `python-operations` — real venv, typed package,
   `unittest`, asyncio and `python -m` CLI. Editable install and pytest in CI
   are still open.
2. **JavaScript/TypeScript**: covered by
   `javascript-typescript-operations` — Node ESM, native type stripping,
   `node:http`, `fetch`/`AbortSignal` and `node:test`. A Vite/Next.js built-app
   example is still open.
3. **PHP**: covered by `php-operations` — PHP 8 CLI/php-fpm, Composer, PDO,
   sessions and deployment. Laravel/WordPress-specific packs are still open.
4. **Go**: still open — no Go toolchain on this host (apt offers only 1.18);
   install Go 1.22+ before authoring a real example.
5. **C++**: covered by `cpp-operations` — C++17 build, RAII, CMake, sanitizers
   and gdb. Cross-compilation is still open.
6. **Rust**: still open — Cargo, ownership, `clippy`, release profiles.

### P2 — data and hosting — DONE 2026-11-20

Added `sqlite-operations`, `mysql-operations` and `hosting-deployment` under
`packs/`, imported into `skills.db` from `local/zombiecoder-packs`, with
English + Bengali routes, compact cards and one real example per pack. Check:
`python3 tools/check_skill_packs.py` → `SKILL_PACKS_OK`.

1. **MySQL**: covered by `mysql-operations` — schema, indexes, `EXPLAIN`,
   backup/restore and online DDL.
2. **SQLite**: covered by `sqlite-operations` — WAL, transactions, migrations,
   backup and embedded deployment.
3. **MongoDB**: still open — document modelling, indexes, aggregation, replica
   sets.
4. **Hosting**: covered by `hosting-deployment` — Apache/cPanel, document root,
   permissions, TLS and rollback. An Nginx-specific runbook is still open.

### P3 — browser and CDP — PARTIAL 2026-11-20

Added `cdp-operations` under `packs/` with a real Chromium WebSocket example.
Check: `python3 tools/check_extra_packs.py` → `EXTRA_PACKS_OK`.

1. **Chrome DevTools Protocol**: covered by `cdp-operations` — discovery,
   targets, sessions, `Runtime.evaluate`, network/console capture and
   screenshots. Trace capture is still open.
2. **Event instrumentation**: still open — click, form, navigation and
   conversion events.

### P4 — education and media

1. **Course workflow**: outcomes, module map, lesson plan, assessment rubric,
   LMS export.
2. **Audio**: scripting, TTS, loudness, SRT/transcript alignment.
3. **Business**: only after an explicit product decision; do not re-import the
   dropped 206 business skills wholesale.

## 6. Acceptance criteria for every new pack

- A real `SKILL.md` body with a trigger description, ordered steps, a failure
  path and a verification step.
- Provenance: `source`, `source_url`, `license`, `content_hash`.
- No offensive, credential-stealing or anti-detection content.
- Terms added for both English and Bengali retrieval; a route test proves the
  Bengali query reaches the new skill.
- Export refresh plus `skills.meta.json` SHA-256 update.
- No regression: `node node/test.js`,
  `PYTHONPATH=python python3 -m unittest discover -s python/tests`, and
  `python3 tools/check_bn_route.py` still pass.

## 7. How to add a pack

```bash
# Work on a copy first; the canonical database is a deliverable.
cp skills.db /tmp/skills.before_add.db
python3 tools/import_skill.py --help
python3 tools/audit_skills.py --db skills.db --report audit
python3 tools/refresh_exports.py --db skills.db --out .
```

Read `docs/AUDIT.md` before applying an audit. Never run
`build_from_wall_memory.py --source skills.db --out .`; it deletes the output
`skills.db`.
