# Gateway integration (Colab / Flask)

The gateway is the single-file Flask app `welcome_to_colab.py`. It keeps the
skill library inside `wall_memory.sqlite3` and exposes a pull-from-git control
so a fresh Colab runtime can restore the curated library without a local git
checkout.

## Settings

| Key | Default | Meaning |
| --- | --- | --- |
| `skill_git_url` | `https://github.com/azurebluezone/zombiecoder-agent-skills.git` | Remote to pull |
| `skill_git_branch` | `main` | Branch used for the raw URLs |
| `skill_anchor` | `1` | Inject the top 2 skills into chat requests |
| `memory_enabled` | `1` | Record sessions/intents at all |

`skill_anchor` and the `X-Skills-Anchor: off` header remain the runtime opt-out.
The git settings control the source, not whether injection is enabled.

## Pull algorithm

`_skills_sync_from_git(url, branch)` performs these steps and never touches the
live tables until every check passes:

1. Normalise the remote:
   - `https://github.com/owner/repo(.git)` →
     `https://raw.githubusercontent.com/owner/repo/<branch>`
   - `https://raw.githubusercontent.com/owner/repo/<branch>` → used as-is
   - any other `http(s)` base → base + `/<branch>` (self-hosted mirror or test)
2. Download `skills.meta.json` with a 1 MB cap.
3. Read `files["skills.db"].sha256` and `.bytes`.
4. Stream `skills.db` to a temporary file in `.zombiecoder/` with a 128 MB cap,
   hashing while writing.
5. Reject on SHA-256 mismatch, byte-size mismatch, missing `skills`,
   `skill_terms` or `skill_sources` tables, or row counts that disagree with the
   manifest.
6. In one transaction: delete `skill_terms`, `skills`, `skill_sources`; insert
   the downloaded rows and the upstream source table; save the normalised URL
   and branch.
7. Delete the temporary file.

A failure at any earlier step leaves the previous library intact.

## HTTP API

### `POST /api/skills/git/sync`

```json
{
  "url": "https://github.com/azurebluezone/zombiecoder-agent-skills.git",
  "branch": "main",
  "token": "optional GitHub token for a private remote"
}
```

All fields are optional; omitted values come from the settings. `url` and
`branch` are saved when provided. Success:

```json
{
  "ok": true,
  "url": "...",
  "base": "https://raw.githubusercontent.com/.../main",
  "branch": "main",
  "sha256": "…",
  "bytes": 9928704,
  "skills": 256,
  "terms": 75358,
  "sources": 7,
  "elapsed_ms": 1234,
  "stats": { "...": "same shape as GET /api/skills stats" }
}
```

Errors use the gateway's OpenAI-style envelope: `400 skill_git_invalid` for a
bad URL/branch, `502 skill_git_failed` for a download or verification failure.

### `GET /api/skills`

The `stats` object now includes `git_url` and `git_branch` alongside `total`,
`active`, `terms`, `bytes`, `sources` and `enabled`.

### `POST /api/memory/settings`

Accepts `skill_git_url` and `skill_git_branch` in addition to the existing
toggles. The URL is validated by the same normaliser before it is saved.

## Admin UI

The **Skills** page has a new first row:

- `skillGitUrl` — remote URL
- `skillGitBranch` — branch (default `main`)
- **Pull from git** — calls `/api/skills/git/sync`, then reloads the stats

The status line reports the verified skill/term counts, byte size, SHA-256
prefix and elapsed time. The old **Sync all six upstream repos** button remains
for refreshing directly from GitHub's tree API (needs a token or waits for the
60/hour limit).

## CLI

```bash
# pull the configured remote
python3 welcome_to_colab.py --skills-sync

# explicit remote and branch
python3 welcome_to_colab.py --skills-sync \
  --url https://github.com/azurebluezone/zombiecoder-agent-skills.git \
  --branch main
```

It prints the same JSON result and `SKILLS_SYNC_OK skills=... terms=...`, or
`SKILLS_SYNC_FAILED <reason>` and exit code 1.

Self-test:

```bash
python3 welcome_to_colab.py --self-test
```

The new checks cover: repo files, manifest SHA-256, Python CLI routing, Node
CLI routing, a local HTTP pull, and rejection of a tampered `skills.db`. The
markers are:

```
HFCATALOG_SELFTEST_OK checks=... db=...
SKILL_LIBRARY_SELFTEST_OK checks=... skills=...
AGENT_SKILLS_REPO_OK checks=... skills=...
```

The self-test expects `zombiecoder-agent-skills/` next to `welcome_to_colab.py`
because it validates the packaged files and both CLIs. The runtime pull itself
only needs network access and the configured raw URL.

## Fresh Colab sequence

```python
# 1. start the gateway as usual
# 2. in the admin Skills page, click "Pull from git"
#    (or run the CLI flag in the same runtime)
```

Expected: 256 skills, 75,358 terms, seven sources, verified SHA-256. The Skills
page badge should show `256 skills`, and the wall-memory panel should show the
same count.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `HTTP 404 for .../skills.meta.json` | Repo not pushed yet, branch wrong, or file missing |
| `sha256 mismatch` | `skills.db` and `skills.meta.json` are out of sync; run `tools/refresh_exports.py` and commit both |
| `has N skills but skills.meta.json says M` | Partial commit or stale export |
| `has no valid files['skills.db'].sha256` | Old/incomplete metadata file |
| `HTTP 403` with a token | Token lacks access to a private repo, or GitHub raw is rate-limiting |
| Pull succeeds but the page still shows the old count | Browser cache; reload `/admin`, then check `GET /api/skills` |
| Raw URL serves an older file after a push | `raw.githubusercontent.com` caching; wait a minute and retry |
