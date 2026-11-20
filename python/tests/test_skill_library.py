"""Tests for the portable Python package. Run from the repository root:

    PYTHONPATH=python python3 -m unittest discover -s python/tests -v
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = Path(os.environ.get("ZOMBIE_SKILLS_DB", ROOT / "skills.db"))
sys.path.insert(0, str(ROOT / "python"))

from zombie_skills import SkillStore  # noqa: E402
from zombie_skills.router import expand_query  # noqa: E402


class SkillLibraryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store = SkillStore(DB)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.store.close()

    def test_stats(self) -> None:
        stats = self.store.stats()
        self.assertGreaterEqual(stats["active"], 200)
        self.assertEqual(stats["active"], stats["total"])
        self.assertGreater(stats["terms"], 10000)
        self.assertGreaterEqual(len(stats["sources"]), 5)

    def test_list_and_filter(self) -> None:
        items = self.store.list(limit=5)
        self.assertEqual(len(items), 5)
        self.assertNotIn("body", items[0])
        filtered = self.store.list(source="nextlevelbuilder/ui-ux-pro-max-skill", limit=20)
        self.assertTrue(filtered)
        self.assertTrue(all(item["source"] == "nextlevelbuilder/ui-ux-pro-max-skill" for item in filtered))

    def test_get(self) -> None:
        skill = self.store.get("ui-ux-pro-max")
        self.assertIsNotNone(skill)
        assert skill is not None
        self.assertIn("UI/UX", skill["description"])
        self.assertGreater(len(skill["body"]), 1000)
        self.assertIsNone(self.store.get("definitely-not-a-real-skill"))

    def test_route_design(self) -> None:
        matches = self.store.route("design a tailwind ux design system landing page", limit=3)
        names = [match["name"] for match in matches]
        self.assertTrue(matches)
        self.assertIn("landing", names)
        self.assertTrue(any(match["score"] >= 10 for match in matches))

    def test_route_playwright(self) -> None:
        matches = self.store.route("debug a failing playwright test", limit=3)
        self.assertTrue(matches)
        self.assertTrue(
            any("playwright" in (match["description"] or "").lower() or match["name"] in {"pw", "fix", "generate"} for match in matches),
            [match["name"] for match in matches],
        )

    def test_route_no_injection_for_smalltalk(self) -> None:
        self.assertEqual(self.store.route("hello how are you", limit=2), [])

    def test_route_bengali_landing(self) -> None:
        matches = self.store.route("ল্যান্ডিং পেজ ডিজাইন করো", limit=3)
        self.assertIn("landing", [match["slug"] for match in matches])

    def test_route_bengali_intents(self) -> None:
        cases = {
            "ডেটাবেস ডিজাইন করো": {"database-designer", "database-schema-designer"},
            "ব্রাউজার অটোমেশন": {"browser-automation"},
            "কোড রিভিউ": {"code-reviewer"},
            "ডিজাইন সিস্টেম": {"design-system", "ui-design-system"},
            "পারফরম্যান্স অডিট": {"performance-profiler"},
        }
        for text, expected in cases.items():
            slugs = {match["slug"] for match in self.store.route(text, limit=3)}
            self.assertTrue(slugs & expected, f"{text}: {slugs}")

    def test_bengali_bridge_is_data_driven(self) -> None:
        self.assertIn("browser automation", expand_query("ব্রাউজার অটোমেশন"))
        decomposed = "\u0993\u09af\u09bc\u09c7\u09ac \u09a1\u09bf\u099c\u09be\u0987\u09a8"
        self.assertIn("web", expand_query(decomposed))
        self.assertEqual(self.store.route("ব্রাউজার অটোমেশন", limit=3, expand=False), [])

    def test_route_english_unchanged_by_expansion(self) -> None:
        text = "debug a failing playwright test"
        expanded = [match["slug"] for match in self.store.route(text, limit=3)]
        plain = [match["slug"] for match in self.store.route(text, limit=3, expand=False)]
        self.assertEqual(expanded, plain)

    def test_route_unmapped_bengali_is_empty(self) -> None:
        self.assertEqual(self.store.route("আজকের আবহাওয়া কেমন", limit=2), [])

    def test_inject(self) -> None:
        messages = [{"role": "user", "content": "design a tailwind landing page"}]
        injected, names = self.store.inject(messages, "design a tailwind landing page")
        self.assertEqual(len(messages), 1)
        self.assertEqual(injected[0]["role"], "system")
        self.assertIn("Skill:", injected[0]["content"])
        self.assertTrue(names)
        self.assertEqual(len(injected), 2)

    def test_cli(self) -> None:
        env = dict(os.environ, PYTHONPATH=str(ROOT / "python"), ZOMBIE_SKILLS_DB=str(DB))
        result = subprocess.run(
            [sys.executable, "-m", "zombie_skills.cli", "route", "write a changelog for the last release"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("changelog", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
