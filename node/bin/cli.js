#!/usr/bin/env node
"use strict";

const { SkillLibrary, tokenize } = require("../index.js");

function usage() {
  console.log(`Usage: zombie-skills <command> [options]

Commands:
  stats                         show database counts and sources
  list [--q text] [--source s]  list skills
  get <id|slug>                 show one skill body
  route <text...>               route text to the best skills
  doctor                        validate the library

Options:
  --jsonl <path>   skills.jsonl (default: repo export or ZOMBIE_SKILLS_JSONL)
  --terms <path>   terms.jsonl  (default: next to skills.jsonl)
  --db <path>      skills.db    (default: next to skills.jsonl)
  --sqlite         read skills.db via node:sqlite instead of JSONL
  --json           machine-readable output
  --limit <n>      max results (default: 2 for route, 50 for list)
  --min-score <n>  routing threshold (default: 3.0)
  --offset <n>     list offset`);
}

function parse(argv) {
  const args = [...argv];
  const options = { json: false, limit: null, minScore: 3.0, offset: 0, q: "", source: "" };
  const positional = [];
  let command = null;
  while (args.length) {
    const arg = args.shift();
    if (arg === "--json") options.json = true;
    else if (arg === "--sqlite") options.preferSqlite = true;
    else if (arg === "--jsonl") options.jsonl = args.shift();
    else if (arg === "--terms") options.terms = args.shift();
    else if (arg === "--db") options.db = args.shift();
    else if (arg === "--limit") options.limit = Number(args.shift());
    else if (arg === "--offset") options.offset = Number(args.shift());
    else if (arg === "--min-score" || arg === "--minScore") options.minScore = Number(args.shift());
    else if (arg === "--q") options.q = args.shift();
    else if (arg === "--source") options.source = args.shift();
    else if (arg === "-h" || arg === "--help") {
      usage();
      process.exit(0);
    } else if (arg.startsWith("--")) {
      throw new Error(`unknown option: ${arg}`);
    } else if (!command) {
      command = arg;
    } else {
      positional.push(arg);
    }
  }
  if (!command) {
    usage();
    process.exit(0);
  }
  return { command, options, positional };
}

function main(argv) {
  const { command, options, positional } = parse(argv);
  const library = new SkillLibrary(options);

  if (command === "stats") {
    const stats = library.stats();
    if (options.json) console.log(JSON.stringify(stats, null, 2));
    else {
      console.log(`mode     : ${stats.mode}`);
      console.log(`database : ${stats.db}`);
      console.log(`skills   : ${stats.active} active / ${stats.total} total`);
      console.log(`terms    : ${stats.terms}`);
      console.log(`bodies   : ${stats.bytes} bytes`);
      for (const source of stats.sources) {
        console.log(`  - ${source.source}: ${source.skills ?? source.skill_count} skills`);
      }
    }
    return 0;
  }

  if (command === "list") {
    const items = library.list({
      q: options.q,
      source: options.source,
      limit: options.limit || 50,
      offset: options.offset,
    });
    if (options.json) console.log(JSON.stringify(items, null, 2));
    else {
      for (const item of items) {
        console.log(`${String(item.slug).padEnd(40)} ${String(item.source).padEnd(34)} ${String(item.bytes).padStart(7)}  ${item.name}`);
      }
    }
    return 0;
  }

  if (command === "get") {
    const identifier = positional[0];
    if (!identifier) throw new Error("get needs a skill id or slug");
    const skill = library.get(identifier);
    if (!skill) {
      console.error(`skill not found: ${identifier}`);
      return 1;
    }
    if (options.json) console.log(JSON.stringify(skill, null, 2));
    else {
      console.log(`# ${skill.name}`);
      console.log(`slug: ${skill.slug}  source: ${skill.source}  license: ${skill.license || "—"}`);
      console.log(`path: ${skill.path || "—"}\n`);
      console.log(skill.body || "");
    }
    return 0;
  }

  if (command === "route") {
    const text = positional.join(" ").trim();
    if (!text) throw new Error("route needs some text");
    const matches = library.route(text, {
      limit: options.limit || 2,
      minScore: options.minScore,
    });
    if (options.json) {
      console.log(JSON.stringify({ text, tokens: tokenize(text).slice(0, 20), matches }, null, 2));
    } else if (!matches.length) {
      console.log("no match above threshold");
    } else {
      for (const match of matches) {
        console.log(`${String(match.score).padStart(6)}  ${String(match.name).padEnd(34)} ${match.source}`);
        console.log(`        ${match.description || ""}`);
      }
    }
    return 0;
  }

  if (command === "doctor") {
    const failures = [];
    let stats;
    try {
      stats = library.stats();
      if (stats.active < 1) failures.push("database has no active skills");
      if (stats.terms < 100) failures.push("term index looks empty");
      const sample = library.route("debug a failing playwright test", { limit: 2 });
      if (!sample.length) failures.push("sample route returned no match");
      console.log(`mode     : ${stats.mode}`);
      console.log(`skills   : ${stats.active} active / ${stats.total} total`);
      console.log(`terms    : ${stats.terms}`);
      console.log(`sample   : ${sample.map((item) => item.name).join(", ") || "none"}`);
    } catch (error) {
      failures.push(error.message);
    }
    if (failures.length) {
      for (const failure of failures) console.error(`FAIL: ${failure}`);
      return 1;
    }
    console.log("DOCTOR_OK");
    return 0;
  }

  usage();
  return 2;
}

try {
  process.exitCode = main(process.argv.slice(2));
} catch (error) {
  console.error(`error: ${error.message}`);
  process.exitCode = 1;
}
