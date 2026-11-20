"use strict";

const assert = require("assert");
const path = require("path");
const { SkillLibrary, tokenize } = require("./index.js");

const root = path.join(__dirname, "..");
const library = new SkillLibrary({
  jsonl: path.join(root, "skills.jsonl"),
  terms: path.join(root, "terms.jsonl"),
  db: path.join(root, "skills.db"),
});

const stats = library.stats();
assert.strictEqual(stats.mode, "jsonl");
assert.ok(stats.active >= 200, `expected >=200 skills, got ${stats.active}`);
assert.strictEqual(stats.total, stats.active);
assert.ok(stats.terms > 10000, `expected >10000 terms, got ${stats.terms}`);

const design = library.route("design a tailwind ux design system landing page", { limit: 3 });
assert.ok(design.length >= 2, "design query should match");
assert.strictEqual(design[0].name, "landing");
assert.ok(design[0].score >= 10);

const playwright = library.route("debug a failing playwright test", { limit: 3 });
assert.ok(playwright.length >= 1, "playwright query should match");
assert.strictEqual(playwright[0].name, "fix");

const changelog = library.route("write a changelog for the last release", { limit: 3 });
assert.ok(changelog.some((match) => match.name.includes("changelog")));
assert.deepStrictEqual(library.route("hello how are you", { limit: 2 }), []);

// Bengali intent bridge: phrase wins over token, and expansion is the cause.
const bengaliLanding = library.route("ল্যান্ডিং পেজ ডিজাইন করো", { limit: 3 });
assert.ok(bengaliLanding.some((match) => match.slug === "landing"), "Bengali landing query");
assert.ok(
  library.route("ডেটাবেস ডিজাইন করো", { limit: 3 }).some((match) =>
    ["database-designer", "database-schema-designer"].includes(match.slug)
  ),
  "Bengali database query"
);
assert.ok(
  library.route("ব্রাউজার অটোমেশন", { limit: 3 }).some((match) => match.slug === "browser-automation"),
  "Bengali browser query"
);
assert.ok(
  library.route("কোড রিভিউ", { limit: 3 }).some((match) => match.slug === "code-reviewer"),
  "Bengali code review query"
);
assert.deepStrictEqual(library.route("ব্রাউজার অটোমেশন", { limit: 3, expand: false }), []);
assert.deepStrictEqual(library.route("আজকের আবহাওয়া কেমন", { limit: 2 }), []);
assert.ok(library.expand("ব্রাউজার অটোমেশন").includes("browser automation"));
assert.ok(library.expand("ওয়েব ডিজাইন").includes("web design"));
assert.ok(
  library
    .expand("\u0993\u09af\u09bc\u09c7\u09ac \u09a1\u09bf\u099c\u09be\u0987\u09a8")
    .includes("web"),
  "decomposed Bengali yya should normalise"
);

const englishOn = library.route("debug a failing playwright test", { limit: 3 });
const englishOff = library.route("debug a failing playwright test", { limit: 3, expand: false });
assert.deepStrictEqual(
  englishOn.map((match) => match.slug),
  englishOff.map((match) => match.slug),
  "English routing must not change"
);

const skill = library.get("ui-ux-pro-max");
assert.ok(skill, "ui-ux-pro-max should exist");
assert.ok(String(skill.body).length > 1000);
assert.strictEqual(library.get("definitely-not-a-real-skill"), null);

const listed = library.list({ source: "nextlevelbuilder/ui-ux-pro-max-skill", limit: 20 });
assert.ok(listed.length >= 5);
assert.ok(listed.every((item) => item.source === "nextlevelbuilder/ui-ux-pro-max-skill"));

const original = [{ role: "user", content: "design a landing page" }];
const injected = library.inject(original, "design a landing page");
assert.strictEqual(original.length, 1);
assert.strictEqual(injected.messages[0].role, "system");
assert.ok(injected.messages[0].content.includes("Skill:"));
assert.ok(injected.names.length >= 1);
assert.strictEqual(injected.messages.length, 2);

const tokens = tokenize("design a Tailwind landing page");
assert.ok(tokens.includes("tailwind"));

// Optional SQLite path: only when the runtime ships node:sqlite.
try {
  require("node:sqlite");
  const sqliteLibrary = new SkillLibrary({
    jsonl: path.join(root, "skills.jsonl"),
    terms: path.join(root, "terms.jsonl"),
    db: path.join(root, "skills.db"),
    preferSqlite: true,
  });
  const sqliteStats = sqliteLibrary.stats();
  assert.strictEqual(sqliteStats.mode, "sqlite");
  assert.strictEqual(sqliteStats.active, stats.active);
  const sqliteDesign = sqliteLibrary.route("design a tailwind ux design system landing page", { limit: 2 });
  assert.strictEqual(sqliteDesign[0].name, "landing");
  console.log("node:sqlite path ok");
} catch (error) {
  if (error && error.code !== "ERR_UNKNOWN_BUILTIN_MODULE" && !/node:sqlite/.test(error.message)) {
    throw error;
  }
  console.log("node:sqlite unavailable, JSONL path only");
}

console.log("NODE_SKILL_LIBRARY_OK", stats.active, stats.terms);
