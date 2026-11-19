# Audit policy and report

The import started with **589 skills** from six public repositories. The audit
kept **248** and removed **341**. Nothing was relabelled and kept "for
completeness": a dropped row is deleted from `skills.db` and its terms are
deleted from `skill_terms`.

Full evidence: [`audit/report.json`](../audit/report.json) (per-skill decision,
category and matched reason) and [`audit/report.csv`](../audit/report.csv).

## Decision order

The classifier is deliberately purpose-based. It judges a skill by what its
name, description, triggers and tags say it is for, not by a word that happens
to appear somewhere in a long body. Matching is word-boundary based, which
fixes earlier false positives such as `cro` in "cross", `ads` in "downloads"
and `cheat` in "cheatsheet".

1. **Manual overrides** — `audit/overrides.json` can force a keep or drop by
   id or slug.
2. **Stub** — body shorter than 300 characters, a description that is only a
   `.md` redirect and a body under 800 characters, or placeholder markers
   (`todo`, `tbd`, `placeholder`, `coming soon`, `lorem ipsum`, `fill this in`)
   in a body under 1,500 characters.
3. **Offensive slug** — explicit slugs or the `competition-`, `ctf-`, `pwn-`
   prefixes.
4. **Business slug** — explicit slugs for sales, marketing, brokerage,
   real-estate, finance, compliance, HR and corporate-process packs.
5. **Keep slug** — the curated engineering/design/defensive allow-list.
6. **Offensive purpose** — offensive phrases with no defensive phrase.
7. **Business purpose** — business phrases with no engineering phrase.
8. **Engineering purpose** — kept.
9. Otherwise **review** (kept for a human, never auto-deleted).

The order matters: redirect-only stubs are removed before the allow-list, so
command names such as `tdd`, `tech-debt`, `user-story`, `prd` and `sprint-*`
are gone while their real counterparts (`tdd-guide`, `tech-debt-tracker`,
`product-manager-toolkit`, `agile-product-owner`) remain.

## Counts

| Decision | Count |
| --- | ---: |
| keep | 248 |
| drop | 341 |
| review | 0 |

Drop reasons overlap (a skill can be both business and a stub), so the reason
counts do not sum to 341:

| Category | Count |
| --- | ---: |
| business | 206 |
| offensive | 68 |
| stub | 67 |
| duplicate | 0 |

## What was removed

- **Offensive/abuse:** exploit development, C2/shellcode, credential dumping,
  EDR/AV bypass, phishing kits, game cheating and anti-cheat bypass, carding,
  SIM swap, account takeover, CTF/pwn/competition packs, generic pentest and
  red-team engagement kits.
- **Business/brokerage/corporate:** sales, SEO, ad copy, cold outreach, lead
  generation, pricing, fundraising, pitch decks, OKRs, recruiting, compliance
  programmes (ISO 27001, SOC 2, GDPR, HIPAA, FDA, CMMC, NIS2), legal/contracts,
  procurement, real estate, investment, accounting, Jira/Confluence/Scrum
  process packs, managed-agent harness setup/launch/wrap-up skills.
- **Stubs:** redirect-only command files and placeholder bodies with no
  instructions to inject.

## What was kept

Engineering, design, QA, docs, data/AI, defensive security, agent tooling and
productivity. Examples:

- `book-to-skill`, `agent-memory`, `workflow-builder`, `hivemind`
- `fix` (Playwright failure diagnosis), `browser-automation`, `testrail`
- `landing`, `design`, `design-system`, `apple-hig-expert`, `tailwind`-style UI
  guidance
- `changelog-generator`, `technical-writer`, `product-manager-toolkit`,
  `agile-product-owner`
- `anti-cheat-systems`, `malware-analysis`, `digital-forensics`,
  `reverse-engineering` (analysis/defence, not weaponisation)

## Re-run

```bash
# read-only report (no deletion)
python3 tools/audit_skills.py --db skills.db --report audit

# apply the drops, then rebuild the exports
python3 tools/audit_skills.py --db skills.db --report audit --apply
python3 tools/refresh_exports.py --db skills.db --out .
```

Before applying a new audit to a database you care about, copy it:

```bash
cp skills.db /tmp/skills.before_audit.db
```

## Limits

This is a review aid, not a sandbox. It cannot prove that a kept body contains
no prompt injection, and it cannot judge nuanced intent. Read
[SECURITY.md](SECURITY.md) before using the library in a sensitive environment,
and inspect any skill you enable for a high-impact workflow.
