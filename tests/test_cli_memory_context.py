from __future__ import annotations

import unittest

from helpers import make_temp_dir

from prismx.memory import MemoryStore


class CLIOutputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_dir()
        self.store = MemoryStore(self.tmp / "memory")

    def test_render_memory_shows_tgm_2_categories(self):
        self.store.remember_note(
            "User prefers tabs",
            category="preferences",
            title="Tab Style",
            source_tree_id="tree-a",
            source_memory_id="mem-a",
        )
        output = self.store.render_memory()
        self.assertIn("feedback", output)
        self.assertIn("Tab Style", output)

    def test_render_memory_empty_does_not_crash(self):
        output = self.store.render_memory()
        self.assertIn("Long-term Memory", output)

    def test_list_context_finds_traceable_objects(self):
        self.store.remember_note(
            "Test event",
            category="events",
            source_tree_id="tree-a",
            source_memory_id="mem-b",
        )
        results = self.store.list_context(prefix="mem://project/", limit=10)
        self.assertGreaterEqual(len(results), 1)
