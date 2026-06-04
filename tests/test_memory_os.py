from __future__ import annotations

import unittest

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
        self.store = MemoryStore(self.tmp / "memory")

    def test_remember_note_requires_tree_memory_source(self):
        uri = self.store.remember_note("User prefers tabs over spaces", category="preferences", title="Tab Preference")
        self.assertEqual(uri, "")
        self.assertEqual(self.store.search_memory("tabs", limit=5), [])

    def test_remember_note_creates_traceable_tgm_2_memory(self):
        uri = self.store.remember_note(
            "User prefers tabs over spaces",
            category="preferences",
            title="Tab Preference",
            source_tree_id="tree-a",
            source_memory_id="mem-a",
        )

        self.assertTrue(uri.startswith("mem://feedback/"), f"Expected feedback URI, got {uri}")
        self.assertTrue((self.tmp / "data" / "knowledge" / "MEMORY.md").exists())
        self.assertTrue((self.tmp / "data" / "knowledge" / "memories" / "feedback").exists())
        result = self.store.read_context(uri, layer="auto")
        self.assertIn("tabs over spaces", result)

    def test_commit_session_archive_writes_traceable_memory_objects(self):
        ops = [{
            "action": "upsert",
            "type": "project",
            "source_tree_id": "tree-a",
            "source_memory_id": "mem-a",
            "key": "use-sqlite",
            "title": "Use SQLite",
            "abstract": "Decided to use SQLite for storage.",
            "overview": "Team decided to use SQLite for local storage needs.",
            "content": "Full decision record: use SQLite as embedded DB.",
            "trust_score": 0.8,
            "tags": ["architecture"],
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
        self.assertEqual(mem_results[0]["metadata"]["source_tree_id"], "tree-a")

    def test_invalid_or_untraceable_operation_is_ignored(self):
        ops = [{"action": "upsert", "type": "project", "key": "bad"}]
        self.store.commit_session_archive(
            session_uri="ctx://sessiontrees/archives/2026/05/24/s2-c1",
            summary="Test.",
            operations=ops,
            metadata={},
        )
        self.assertEqual(self.store.list_context(prefix="mem://", limit=10), [])

    def test_no_old_contextfs_current_messages_jsonl_created(self):
        current = self.tmp / "data" / "knowledge" / "context" / "sessiontrees" / "current"
        self.assertFalse(current.exists(), "sessiontrees/current/messages.jsonl must not exist")
