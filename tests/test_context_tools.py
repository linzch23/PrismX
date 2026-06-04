from __future__ import annotations

import unittest
from pathlib import Path
from helpers import make_temp_dir, make_contextfs_root

from prismx.contextfs import ContextFS, ContextObject
from prismx.memory_graph import MemoryGraph
from prismx.tools.context import SearchContextTool, ReadContextTool, ListContextTool, ShowContextLinksTool


class FakeMemoryStore:
    def __init__(self, memory_dir):
        self._cfs = ContextFS(memory_dir)
        self._graph = MemoryGraph(memory_dir / "context" / "links.jsonl")

    def search_memory(self, query, limit=6):
        return self._cfs.search_objects(query, limit=limit)

    def read_context(self, uri, layer="auto"):
        try:
            r = self._cfs.read_object(uri, layer=layer)
            return r.get("content", "")
        except KeyError:
            return f"Error: URI not found: {uri}"

    def list_context(self, prefix="mem://", limit=50):
        return self._cfs.list_objects(prefix=prefix, limit=limit)

    def graph_neighbors(self, uri, limit=5):
        return self._graph.neighbors(uri, limit=limit)

    def remember_note(self, note, category="events", title=None):
        return f"mem://user/{category}/2026/05/24/test-slug"


class ContextToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_dir()
        root = make_contextfs_root(self.tmp)
        self.store = FakeMemoryStore(self.tmp / "memory")
        self.store._cfs.write_object(ContextObject(
            uri="mem://user/prefs/editor", context_type="memory", title="Editor",
            abstract="VS Code.", overview="User prefers VS Code.",
            content_path="mem/user/prefs/editor.md",
            source="manual", trust_score=0.9, sensitivity="public", status="active",
            tags=["preference"], metadata={}, digest="x", created_at="", updated_at="",
        ), "Full VS Code preference details.")

    def test_search_context_tool(self):
        tool = SearchContextTool(self.store)
        result = tool.execute(query="editor", limit=5)
        self.assertIn("mem://user/prefs/editor", result)

    def test_read_context_tool_auto(self):
        tool = ReadContextTool(self.store)
        result = tool.execute(uri="mem://user/prefs/editor", layer="auto")
        self.assertIn("VS Code", result)

    def test_read_context_tool_full(self):
        tool = ReadContextTool(self.store)
        result = tool.execute(uri="mem://user/prefs/editor", layer="full")
        self.assertIn("Full VS Code", result)

    def test_list_context_tool(self):
        tool = ListContextTool(self.store)
        result = tool.execute(prefix="mem://user/prefs/", limit=10)
        self.assertIn("mem://user/prefs/editor", result)

    def test_read_context_tool_unknown_uri(self):
        tool = ReadContextTool(self.store)
        result = tool.execute(uri="mem://nonexistent", layer="auto")
        self.assertIn("Error", result)


class RememberToolUpgradeTests(unittest.TestCase):
    def test_remember_with_note_only_still_works(self):
        from prismx.tools.state import RememberTool
        calls = []
        class MemStore:
            def remember(self, note, category="events", title=None, scope="tree", memory_type=None):
                calls.append((note, category, title, scope, memory_type))
                return "tree://default/memory/slug"
        tool = RememberTool(MemStore())
        result = tool.execute(note="Important fact")
        self.assertIn("Remembered", result)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "Important fact")
        self.assertEqual(calls[0][3], "tree")

    def test_remember_with_category_and_title(self):
        from prismx.tools.state import RememberTool
        calls = []
        class MemStore:
            def remember(self, note, category="events", title=None, scope="tree", memory_type=None):
                calls.append((note, category, title, scope, memory_type))
                return "tree://default/memory/theme"
        tool = RememberTool(MemStore())
        result = tool.execute(note="Dark mode", category="preferences", title="Theme Preference")
        self.assertIn("Remembered", result)
        self.assertEqual(calls[0], ("Dark mode", "preferences", "Theme Preference", "tree", None))

    def test_special_memory_type_routes_through_gateway(self):
        from prismx.memory import MemoryStore
        from prismx.runtime_recall import TgmContextGateway
        from prismx.tools.state import RememberTool
        from prismx.tree_memory import TreeMemoryStore

        tmp = make_temp_dir()
        tree_memory = TreeMemoryStore(tmp / "memory" / "tree")
        gateway = TgmContextGateway(
            memory_store=MemoryStore(tmp / "memory"),
            tree_memory=tree_memory,
            tree_id_provider=lambda: "s1",
        )
        tool = RememberTool(gateway)

        result = tool.execute(note="记住暗号123123", memory_type="user_profile", title="暗号")

        self.assertIn("tree://s1/memory/", result)
        self.assertIn("mem://user/", result)
        self.assertEqual(len(tree_memory.items("s1")), 1)

