from __future__ import annotations

import unittest
from pathlib import Path
from helpers import make_temp_dir

from prismx.memory import MemoryStore


class MemoryOSCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_dir()
        self.mem_dir = self.tmp / "memory"
        self.store = MemoryStore(self.mem_dir)

    def test_legacy_linear_memory_files_are_not_created(self):
        self.assertFalse((self.mem_dir / "MEMORY.md").exists())
        self.assertFalse((self.mem_dir / "history.jsonl").exists())
        self.assertFalse((self.mem_dir / "compactions.md").exists())

    def test_read_write_user(self):
        self.store.write_user("Name: Test User")
        self.assertEqual(self.store.read_user(), "Name: Test User")


class MemoryOSNewAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_dir()
        self.mem_dir = self.tmp / "memory"
        self.store = MemoryStore(self.mem_dir)

    def test_remember_note_creates_structured_memory_object(self):
        uri = self.store.remember_note("User prefers tabs over spaces", category="preferences", title="Tab Preference")
        self.assertTrue(uri.startswith("mem://"), f"Expected mem:// URI, got {uri}")
        result = self.store.read_context(uri, layer="auto")
        self.assertIn("tabs over spaces", result)

    def test_remember_note_does_not_write_legacy_memory(self):
        self.store.remember_note("Important project fact", category="events")
        self.assertFalse((self.mem_dir / "MEMORY.md").exists())

    def test_commit_session_archive_writes_archive_and_memory_objects(self):
        ops = [{
            "action": "upsert", "category": "decisions",
            "key": "use-sqlite", "title": "Use SQLite",
            "abstract": "Decided to use SQLite for storage.",
            "overview": "Team decided to use SQLite for local storage needs.",
            "content": "Full decision record: use SQLite as embedded DB.",
            "reason": "Architecture decision captured from session.",
            "trust_score": 0.8, "tags": ["architecture"],
            "links": [],
        }]
        archive_uri = self.store.commit_session_archive(
            session_uri="ctx://sessiontrees/archives/2026/05/24/s1-c1",
            summary="Compaction summary text.",
            operations=ops,
            metadata={"session_id": "s1", "compaction_id": "c1"},
        )
        self.assertIn("ctx://sessiontrees/archives", archive_uri)

        mem_results = self.store.search_memory("SQLite", limit=5)
        self.assertEqual(len(mem_results), 1)
        self.assertEqual(mem_results[0]["title"], "Use SQLite")

    def test_invalid_operation_goes_to_quarantine(self):
        ops = [{"action": "invalid_action", "category": "events", "key": "bad"}]
        self.store.commit_session_archive(
            session_uri="ctx://sessiontrees/archives/2026/05/24/s2-c1",
            summary="Test.",
            operations=ops,
            metadata={},
        )
        results = self.store.list_context(prefix="mem://quarantine/", limit=10)
        self.assertGreaterEqual(len(results), 1)

    def test_no_current_messages_jsonl_created(self):
        current = self.mem_dir / "context" / "sessiontrees" / "current"
        self.assertFalse(current.exists(), "sessiontrees/current/messages.jsonl must not exist")

