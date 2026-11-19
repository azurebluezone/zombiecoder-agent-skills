#!/usr/bin/env python3
"""Audit the imported SKILL.md library and optionally remove unsafe/low-value skills.

The library is untrusted text that gets injected into a model prompt, so the
audit is deliberately purpose-based: a skill is judged by *what it says it is
for* (name + description + triggers + tags), not by words that happen to appear
deep inside its body.

Policy (v3)
-----------
keep    engineering, design, QA, docs, data/AI, defensive security, agent
        tooling and general productivity
drop    offensive/abuse playbooks, sales/marketing/brokerage/corporate/legal/
        medical-compliance filler, stubs and duplicate bodies
review  ambiguous purpose; kept for a human, never auto-deleted

Matching uses word boundaries, so "cro" no longer matches "cross" and "ads" no
longer matches "downloads".

Usage
-----
    python3 tools/audit_skills.py --db skills.db --report audit
    python3 tools/audit_skills.py --db skills.db --report audit --apply

`--apply` deletes every dropped skill and its terms from the database.
`audit/overrides.json` can force {"keep": [...], "drop": [...]} by id or slug.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
from collections import defaultdict

# --- explicit slug decisions -------------------------------------------------

OFFENSIVE_SLUGS = {
    # reverse-skill exploitation / CTF orchestration
    "attack-chain", "ctf-sandbox", "ctf-sandbox-orchestrator", "edr-bypass-re",
    "patch-diff-exploit", "pwn-chain", "firmware-pentest", "pentest-tools",
    "src-hunter", "windows-ad", "wifi-wireless", "reverse-skill-router",
    "reverse-skill-adapter",
    # claude-skills offensive or competition-harness skills
    "red-team", "security-pen-testing", "board", "agent-launcher-orchestrator",
    "hub-init", "hub-run", "hub-status", "spawn", "merge", "eval",
    "ar-loop", "ar-resume", "ar-run", "ar-status",
}

OFFENSIVE_PREFIXES = ("competition-", "ctf-", "pwn-")

BUSINESS_SLUGS = {
    # C-suite / board / company strategy
    "arquiteto-de-empresa", "board-deck-builder", "board-meeting", "board-prep",
    "boardroom", "brief", "business-growth-skills", "business-investment-advisor",
    "business-name-fit", "business-operations-skills", "c-level-agents",
    "c-level-skills", "caio-review", "cco-review", "cdo-review", "ceo-advisor",
    "cfo-advisor", "cfo-review", "change-management",
    "channel-economics", "chief-ai-officer-advisor", "chief-customer-officer-advisor",
    "chief-data-officer-advisor", "chief-of-staff", "chro-advisor", "ciso-advisor",
    "ciso-review", "cmo-advisor", "cmo-review", "coo-advisor", "cpo-advisor",
    "cpo-review", "cro-advisor", "cro-review", "cto-advisor", "cto-review",
    "company-os", "context-engine", "cross-eval", "culture-architect", "decide",
    "decision-logger", "execute", "executive-mentor", "founder-coach",
    "founder-mode", "freeze", "gc-review", "hard-call", "internal-comms",
    "internal-narrative", "intl-expansion", "ma-playbook", "office-hours",
    "okr", "onboard", "org-health-diagnostic", "post-mortem", "scenario-war-room",
    "strategic-alignment", "vpe-advisor", "vpe-review",
    # sales / revenue / growth / marketing
    "ad-creative", "aeo", "campaign-analytics", "channel-economics", "churn-prevention",
    "cold-email", "commercial-forecaster", "commercial-policy", "commercial-skills",
    "competitive-intel", "competitive-matrix", "competitive-teardown",
    "competitor-alternatives", "content-creator", "content-humanizer",
    "content-production", "content-strategist", "content-strategy", "copy-editing",
    "copywriting", "cs-aeo", "cs-content-creator", "cs-demand-gen-specialist",
    "cs-growth-strategist", "cs-webinar", "cs-webinar-marketer", "customer-success-manager",
    "deal-desk", "email-sequence", "form-cro", "free-tool-strategy", "growth-marketer",
    "launch-strategy", "lead-generation", "linkedin-analytics", "linkedin-content",
    "linkedin-engagement", "linkedin-profile", "linkedin-skills", "linkedin-strategy",
    "local-seo-manager", "marketing-context", "marketing-demand-acquisition",
    "marketing-ideas", "marketing-ops", "marketing-psychology", "marketing-skills",
    "marketing-strategy-pmm", "monetize", "onboarding-cro", "page-cro", "paid-ads",
    "partnerships-architect", "paywall-upgrade-cro", "popup-cro", "pricing-strategist",
    "pricing-strategy", "product-marketing", "programmatic-seo", "pulse",
    "referral-program", "revenue-operations", "rfp-responder", "sales-engineer",
    "schema-markup", "seo-audit", "seo-auditor", "signup-flow-cro", "site-architecture",
    "social-content", "social-media-analyzer", "social-media-manager", "support-ops",
    "video-content-strategist", "webinar-marketing", "x-twitter-growth", "youtube-full",
    # finance / legal / HR / procurement / workplace admin
    "atlassian-admin", "atlassian-templates", "capacity-planner",
    "contract-and-proposal-writer", "confluence-expert", "dossier",
    "finance-lead", "finance-skills", "financial-analyst", "financial-health",
    "general-counsel-advisor", "google-workspace", "google-workspace-cli",
    "grants", "interview-mapper", "interview-system-designer", "jira-expert",
    "month-end-close", "ms365-tenant-manager", "patent", "procurement-optimizer",
    "process-mapper", "research-finance", "saas-health", "saas-metrics-coach",
    "scrum-master", "stock-analysis", "team-communications", "vendor-management",
    # compliance / regulated-industry programmes
    "capa-officer", "clinical-research", "cmmc-readiness", "compliance-os",
    "compliance-readiness", "cra-readiness", "dora-readiness", "eu-ai-act-specialist",
    "fda-consultant-specialist", "fda-qsr-audit-prep", "gdpr-audit-prep",
    "gdpr-dsgvo-expert", "information-security-manager-iso27001", "isms-audit-expert",
    "iso13485-audit-prep", "iso27001-audit-prep", "iso42001-specialist",
    "mdr-745-specialist", "medical-device-software", "nis2-readiness",
    "qms-audit-expert", "quality-documentation-manager", "quality-manager-qmr",
    "quality-manager-qms-iso13485", "ra-qm-skills", "regulatory-affairs-head",
    "risk-management-specialist", "soc2-audit-prep", "soc2-compliance",
    # meta routers and fixture skills
    "product-skills", "research-ops-skills", "pm-skills", "engineering-skills",
    "engineering-advanced-skills", "sample-text-processor", "behuman",
    # meta harnesses, vendor-specific tools, misfiled files
    "agenthub", "setup", "stage-launch", "wrap-up", "grade-iterate",
    "run-without-you", "fable-goal", "notebooklm", "entities",
    # marketing/compliance strategy that a coding library does not need
    "app-store-optimization", "analytics-tracking", "market-research",
    "product-strategist", "ai-decision-authority", "aims-audit", "meetings",
    "ai-act-readiness", "andreessen",
}

KEEP_SLUGS = {
    # engineering / architecture / data / AI
    "aws-solution-architect", "azure-cloud-architect", "gcp-cloud-architect",
    "boost-asio-pro", "ci-cd-pipeline-builder", "code-reviewer", "code-tour",
    "code-to-prd", "codebase-onboarding", "commit-craft", "database-designer",
    "database-schema-designer", "data-quality-auditor", "dependency-auditor",
    "docker-development", "feature-flags-architect", "git-worktree-manager",
    "helm-chart-builder", "i18n-localization", "incident-commander",
    "incident-response", "kubernetes-operator", "llm-cost-optimizer",
    "mcp-oauth-triage", "mcp-server-builder", "memory-engineering", "memory-review",
    "memory-status", "migration-architect", "monorepo-navigator",
    "observability-designer", "performance-profiler", "pr-review-expert",
    "prompt-engineer-toolkit", "prompt-governance", "rag-architect",
    "red-green-proof", "runbook-generator", "saas-scaffolder", "senior-architect",
    "senior-backend", "senior-computer-vision", "senior-data-engineer",
    "senior-data-scientist", "senior-devops", "senior-frontend", "senior-fullstack",
    "senior-ml-engineer", "senior-prompt-engineer", "senior-qa", "senior-secops",
    "senior-security", "slo-architect", "snowflake-development",
    "sql-database-assistant", "statistical-analyst", "stripe-integration-expert",
    "tech-debt", "tech-debt-tracker", "tech-stack-evaluator", "terraform-patterns",
    "tdd", "tdd-guide", "universal-scraping-architect", "zero-hallucination-coder",
    "karpathy-check", "karpathy-coder", "minimalist", "strict-api",
    "security-guidance", "secrets-vault-manager", "env-secrets-manager",
    "cloud-security", "threat-detection", "skill-security-auditor",
    # design / frontend / content production
    "banner-design", "beautiful-article", "brand", "brand-guidelines", "design",
    "design-qa", "design-system", "epic-design", "full-page-screenshot",
    "landing", "landing-page-generator", "markdown-html-orchestrator",
    "md-document", "md-review", "md-slides", "motion-showreel", "slides",
    "ui-design-system", "ui-styling", "ui-ux-pro-max", "web-design-engineer",
    "web-video-presentation", "gpt-image-2", "kb-retriever", "demo-video",
    "cinematic-shot-prompting",
    # QA / browser automation
    "browser-automation", "browserstack", "coverage", "fix", "generate",
    "migrate", "pw", "pw-init", "pw-review", "report", "testrail",
    # agent / knowledge / productivity
    "agent-memory", "autoresearch-agent", "book-to-skill", "capture", "caveman",
    "deep-work", "deepread", "extract", "grill-me", "grill-with-docs", "handoff",
    "human-gate", "interview", "knowledge-ops", "litreview", "memory-ops",
    "meta-research", "postmortem", "product-analytics", "product-discovery",
    "product-manager", "product-manager-toolkit", "product-research", "prd",
    "promote", "reflect", "remember", "research", "research-summarizer",
    "rice", "roadmap-communicator", "self-eval", "self-improving-agent",
    "session-handoff", "ship-gate", "skill-retro", "skill-tester",
    "skillopt-sleep", "sprint-health", "sprint-plan", "syllabus", "tc",
    "tc-tracker", "user-story", "weekly-review", "write-a-skill",
    "spec-driven-workflow", "spec-to-repo", "project-health", "senior-pm",
    "chaos-engineering", "chaos-experiment", "incident-commander",
    "deep-learning-book", "spinning-up-deep-rl", "swedish-mentor",
    "notebooklm", "experiment-designer", "product-manager",
    # reverse engineering / defensive security
    "anti-cheat-systems", "awesome-game-security-overview", "binary-diff",
    "binary-ninja-reverse", "browser-extension-reverse", "case-review",
    "cloud-k8s", "code-audit", "database-security", "digital-forensics",
    "diagram-generator", "dma-attack-techniques", "docs-generator",
    "dotnet-reverse", "dsl-vm-reverse", "email-security", "game-engine-resources",
    "game-hacking-techniques", "game-security-research-rigor",
    "game-server-security", "game-supply-chain-security", "ghidra-reverse",
    "go-rust-reverse", "graphics-api-hooking", "hardware-security",
    "identity-federation", "ida-reverse", "js-reverse", "linux-platform-security",
    "llm-security", "macos-reverse", "malware-analysis", "mobile-reverse",
    "mobile-security", "ot-ics", "protocol-reverse", "radare2", "radio-sdr",
    "rea-analysis-optimization", "rea-changelog-update", "rea-ci-tests-audit",
    "rea-tool-design", "reverse-engineer-anything",
    "reverse-engineering", "reverse-engineering-tools", "supply-chain-security",
    "thick-client", "threat-hunting", "threat-intelligence",
    "windows-kernel-security", "apk-reverse", "api-security",
    # plan review, agent delegation, UI platform guidance, cloud cost
    "challenge", "stress-test", "workflow-builder", "hivemind", "focused-fix",
    "apple-hig-expert", "cloud-finops", "collab-proof", "inbox-setup",
    "inbox-triage", "meeting-analyzer", "ab-test-setup", "access-lifecycle",
    "agile-product-owner", "claude-coach",
}

# --- purpose patterns --------------------------------------------------------

ENGINEERING = (
    "engineer", "developer", "backend", "frontend", "fullstack", "full-stack",
    "api", "database", "sql", "docker", "kubernetes", "terraform", "helm",
    "ci/cd", "ci cd", "devops", "testing", "test", "tdd", "playwright", "e2e",
    "debug", "refactor", "code review", "git", "monorepo", "observability", "slo",
    "performance", "profiler", "caching", "queue", "kafka", "redis", "graphql",
    "rest", "grpc", "websocket", "oauth", "authentication", "authorization",
    "regex", "python", "typescript", "javascript", "react", "next.js", "nextjs",
    "vue", "svelte", "node", "golang", "rust", "java", "dotnet", "c#", "php",
    "laravel", "django", "flask", "fastapi", "rails", "etl", "data pipeline",
    "machine learning", "llm", "rag", "prompt", "evals", "mcp", "documentation",
    "readme", "changelog", "technical writing", "accessibility", "tailwind", "css",
    "html", "figma", "prototype", "animation", "motion", "design system",
    "ui/ux", "product manager", "prd", "user story", "acceptance criteria",
    "roadmap", "spec", "reverse engineering", "forensics", "protocol", "firmware",
    "security", "cryptography", "sre", "networking", "linux", "bash", "agent",
    "skill", "memory", "handoff", "research", "summar", "review", "audit",
    "runbook", "incident", "postmortem", "migration", "release", "scraping",
    "screenshot", "slide", "document", "article", "video", "image", "design",
)

DEFENSIVE = (
    "analyze", "analyse", "detect", "defend", "defense", "defensive", "review",
    "audit", "forensic", "harden", "hardening", "investigate", "classify",
    "verify", "assess", "assessment", "threat hunt", "incident response",
    "malware analysis", "anti-cheat", "security research", "trust boundary",
)

OFFENSIVE = (
    "malware development", "malware dev", "build malware", "ransomware",
    "keylogger", "rootkit", "botnet", "trojan", "spyware", "stalkerware",
    "cryptominer", "wiper malware", "credential dump", "credential theft",
    "lsass", "dpapi", "mimikatz", "hashdump", "password dump", "ticket material",
    "phishing kit", "phishing campaign", "credential harvest", "mailbox abuse",
    "edr bypass", "av bypass", "antivirus evasion", "defense evasion",
    "anti-forensics", "log wiping", "defender bypass", "game hacking",
    "game-hack", "game hack", "dma attack", "cheat", "aimbot", "wallhack",
    "anti-cheat bypass", "graphics api hooking", "exploit weaponization",
    "weaponized exploit", "reverse shell", "shellcode", "c2 framework",
    "command and control", "carding", "skimmer", "sim swap", "account takeover",
    "credential stuffing", "red team engagement", "attack path", "pwn", "ctf",
    "competition", "exploit", "pentest", "penetration test",
)

BUSINESS = (
    "sales", "marketing", "seo", "ad copy", "ads", "campaign", "cold email",
    "cold outreach", "lead generation", "lead-gen", "prospecting", "pipeline",
    "quota", "upsell", "cross-sell", "churn", "customer success", "revenue",
    "pricing", "discount", "deal", "forecast", "board", "investor", "fundraising",
    "venture capital", "pitch deck", "okr", "kpi", "stakeholder", "c-level",
    "ceo", "cfo", "cmo", "coo", "cpo", "chro", "ciso", "cto", "founder",
    "recruit", "hiring", "talent", "compensation", "org structure", "culture",
    "compliance", "iso 27001", "iso27001", "soc 2", "soc2", "gdpr", "hipaa",
    "fda", "mdr", "cmmc", "nis2", "clinical", "medical device", "patent",
    "contract", "legal", "procurement", "vendor", "rfp", "proposal", "dossier",
    "competitive", "competitor", "positioning", "brand strategy", "content strategy",
    "social media", "linkedin", "twitter", "youtube", "webinar", "newsletter",
    "affiliate", "referral", "sponsorship", "real estate", "investment",
    "finance", "financial", "accounting", "budget", "payroll", "hr ", "people ops",
    "google workspace", "jira", "confluence", "atlassian", "ms365", "office 365",
    "scrum", "sprint", "project management", "process mapping", "company os",
)

STUB_MARKERS = ("todo", "tbd", "placeholder", "coming soon", "lorem ipsum", "fill this in")


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower())


def phrase_re(phrase: str) -> re.Pattern:
    escaped = re.escape(phrase).replace(r"\ ", r"\s+")
    return re.compile(r"(?<![a-z0-9])" + escaped + r"(?![a-z0-9])", re.I)


COMPILED: dict[tuple[str, ...], list[tuple[str, re.Pattern]]] = {}


def hits(text: str, phrases: tuple[str, ...]) -> list[str]:
    key = phrases
    if key not in COMPILED:
        COMPILED[key] = [(phrase, phrase_re(phrase)) for phrase in phrases]
    found = []
    for phrase, pattern in COMPILED[key]:
        if pattern.search(text):
            found.append(phrase)
    return found


def load_overrides(report_dir: str) -> dict:
    path = os.path.join(report_dir, "overrides.json")
    if not os.path.isfile(path):
        return {"keep": [], "drop": []}
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return {
        "keep": [str(item) for item in data.get("keep", [])],
        "drop": [str(item) for item in data.get("drop", [])],
    }


def classify(row: sqlite3.Row, overrides: dict) -> dict:
    name = str(row["name"] or "")
    slug = str(row["slug"] or "")
    description = str(row["description"] or "")
    body = str(row["body"] or "")
    purpose = normalise(" ".join((name, description, str(row["triggers"] or ""), str(row["tags"] or ""))))

    identifiers = {str(row["id"]), slug}
    if identifiers & set(overrides.get("keep", [])):
        return {"decision": "keep", "category": "manual", "reasons": [], "manual": True}
    if identifiers & set(overrides.get("drop", [])):
        return {"decision": "drop", "category": "manual", "reasons": ["manual:override"], "manual": True}

    # Redirect-only command stubs have no instructions to inject, even when
    # their name looks useful. Drop them before the slug allow-list.
    reasons: list[str] = []
    if len(body.strip()) < 300:
        reasons.append(f"stub:body<{len(body.strip())}")
    if re.fullmatch(r"[\w./-]+\.md", description.strip()) and len(body.strip()) < 800:
        reasons.append("stub:redirect-description")
    if any(marker in normalise(body) for marker in STUB_MARKERS) and len(body.strip()) < 1500:
        reasons.append("stub:placeholder")
    if reasons:
        return {"decision": "drop", "category": "stub", "reasons": sorted(set(reasons)), "manual": False}

    # Deterministic slug decisions next: the slug is a curated label, not a
    # guess about body text.
    if slug in OFFENSIVE_SLUGS or slug.startswith(OFFENSIVE_PREFIXES):
        return {"decision": "drop", "category": "offensive", "reasons": ["offensive:slug"], "manual": False}
    if slug in BUSINESS_SLUGS:
        return {"decision": "drop", "category": "business", "reasons": ["business:slug"], "manual": False}
    if slug in KEEP_SLUGS:
        return {"decision": "keep", "category": "engineering", "reasons": ["engineering:slug"], "manual": False}

    offensive_hits = hits(purpose, OFFENSIVE)
    defensive_hits = hits(purpose, DEFENSIVE)
    if offensive_hits and not defensive_hits:
        return {
            "decision": "drop",
            "category": "offensive",
            "reasons": ["offensive:" + phrase for phrase in offensive_hits],
            "manual": False,
        }

    business_hits = hits(purpose, BUSINESS)
    engineering_hits = hits(purpose, ENGINEERING)
    if business_hits and not engineering_hits:
        return {
            "decision": "drop",
            "category": "business",
            "reasons": ["business:" + phrase for phrase in business_hits],
            "manual": False,
        }
    if engineering_hits:
        return {
            "decision": "keep",
            "category": "engineering",
            "reasons": ["engineering:" + phrase for phrase in engineering_hits[:4]],
            "manual": False,
        }
    return {"decision": "review", "category": "review", "reasons": ["needs human review"], "manual": False}


def build_report(db_path: str, report_dir: str, apply: bool) -> dict:
    if not os.path.isfile(db_path):
        raise SystemExit(f"database not found: {db_path}")
    os.makedirs(report_dir, exist_ok=True)
    overrides = load_overrides(report_dir)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro" if not apply else db_path, uri=not apply)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, slug, name, description, body, triggers, tags, source, path, bytes, content_hash "
        "FROM skills WHERE active = 1 ORDER BY source, slug"
    ).fetchall()

    # Exact duplicate content: keep the richest body per hash.
    by_hash: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_hash[str(row["content_hash"] or "")].append(row)
    duplicate_ids: set[str] = set()
    for digest, group in by_hash.items():
        if not digest or len(group) < 2:
            continue
        ordered = sorted(group, key=lambda row: (-int(row["bytes"] or 0), row["path"]))
        for row in ordered[1:]:
            duplicate_ids.add(str(row["id"]))

    counts = {"keep": 0, "drop": 0, "review": 0,
              "engineering": 0, "business": 0, "offensive": 0, "stub": 0, "duplicate": 0}
    entries = []
    for row in rows:
        verdict = classify(row, overrides)
        reasons = list(verdict["reasons"])
        category = verdict["category"]
        if str(row["id"]) in duplicate_ids:
            reasons.append("duplicate:content_hash")
            verdict["decision"] = "drop"
            category = "duplicate"
        counts[verdict["decision"]] += 1
        if verdict["decision"] == "keep":
            counts["engineering"] += 1
        elif verdict["decision"] == "drop":
            counts[category if category in counts else "stub"] += 1
        entries.append(
            {
                "id": row["id"],
                "slug": row["slug"],
                "name": row["name"],
                "description": (row["description"] or "")[:180],
                "source": row["source"],
                "path": row["path"],
                "bytes": row["bytes"],
                "decision": verdict["decision"],
                "category": category,
                "reasons": reasons,
                "manual": verdict["manual"],
            }
        )

    report = {
        "schema_version": "3.0.0",
        "database": os.path.abspath(db_path),
        "policy": {
            "keep": "engineering, design, QA, docs, data/AI, defensive security, agent tooling, productivity",
            "drop": "offensive/abuse, sales/marketing/brokerage/corporate/legal/medical compliance, stubs, duplicates",
            "review": "ambiguous purpose; kept for a human to decide",
        },
        "counts": counts,
        "entries": entries,
    }
    with open(os.path.join(report_dir, "report.json"), "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    with open(os.path.join(report_dir, "report.csv"), "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source", "name", "slug", "bytes", "decision", "category", "reasons", "path"])
        for entry in entries:
            writer.writerow(
                [entry["source"], entry["name"], entry["slug"], entry["bytes"],
                 entry["decision"], entry["category"], ";".join(entry["reasons"]), entry["path"]]
            )

    if apply:
        dropped = [entry["id"] for entry in entries if entry["decision"] == "drop"]
        for skill_id in dropped:
            conn.execute("DELETE FROM skill_terms WHERE skill_id = ?", (skill_id,))
        conn.executemany("DELETE FROM skills WHERE id = ?", [(skill_id,) for skill_id in dropped])
        conn.execute(
            "UPDATE skill_sources SET skill_count = "
            "(SELECT COUNT(*) FROM skills k WHERE k.source = skill_sources.source)"
        )
        conn.commit()
        report["applied"] = {"deleted": len(dropped)}
        with open(os.path.join(report_dir, "report.json"), "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    conn.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="skills.db")
    parser.add_argument("--report", default="audit")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    report = build_report(args.db, args.report, args.apply)
    print(json.dumps(report["counts"], ensure_ascii=False))
    if args.apply:
        print("deleted", report["applied"]["deleted"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
