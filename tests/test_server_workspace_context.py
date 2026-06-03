from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from prismx.memory import MemoryStore
from prismx.server import _workspace_context_for_session, _workspace_payload
from prismx.tree_session import FakeSummarizer, TreeSessionManager
from prismx.tree_memory import TreeMemoryStore
from prismx.workspace import WorkspaceStore


class ServerWorkspaceContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.tree = TreeSessionManager(
            session_dir=self.root / "sessiontrees",
            data_root=self.root / "data",
            summarizer=FakeSummarizer(),
        )
        self.workspace = WorkspaceStore(self.root, self.tree)
        self.state = SimpleNamespace(root=self.root, workspace=self.workspace)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_workspace_context_uses_parent_path_and_excludes_siblings(self) -> None:
        payload = self.workspace.payload()
        tree_id = payload["activeTreeId"]
        root_id = payload["activeSessionId"]
        child_id = self.workspace.create_session_node(tree_id, root_id, "Child")["activeSessionId"]
        grandchild_id = self.workspace.create_session_node(tree_id, child_id, "Grandchild")["activeSessionId"]
        sibling_id = self.workspace.create_session_node(tree_id, root_id, "Sibling")["activeSessionId"]

        self.tree.append_message(root_id, {"role": "user", "content": "root theorem"})
        self.tree.append_message(child_id, {"role": "assistant", "content": "child lemma"})
        self.tree.append_message(grandchild_id, {"role": "user", "content": "current should not duplicate"})
        self.tree.append_message(sibling_id, {"role": "user", "content": "sibling-only note"})

        context = _workspace_context_for_session(self.state, grandchild_id)

        self.assertIsNotNone(context)
        self.assertIn("root theorem", context or "")
        self.assertIn("child lemma", context or "")
        self.assertNotIn("sibling-only note", context or "")
        self.assertNotIn("current should not duplicate", context or "")

    def test_workspace_payload_separates_tree_memory_from_long_term_knowledge(self) -> None:
        payload = self.workspace.payload()
        tree_id = payload["activeTreeId"]
        tree_memory = TreeMemoryStore(self.root / "memory" / "tree")
        memory = MemoryStore(self.root / "memory")
        tree_memory.remember(tree_id, "tree-only reusable finding", memory_type="finding")
        memory.remember_note("long-term reusable preference", category="preferences", title="Preference")
        state = SimpleNamespace(
            root=self.root,
            workspace=self.workspace,
            app=SimpleNamespace(tree=self.tree, tree_memory=tree_memory, memory=memory),
        )

        result = _workspace_payload(state)

        self.assertTrue(any("tree-only reusable finding" in item["content"] for item in result["treeMemoryItems"]))
        self.assertFalse(any("tree-only reusable finding" in item["content"] for item in result["longTermKnowledgeItems"]))
        self.assertTrue(any("long-term reusable preference" in item["content"] for item in result["longTermKnowledgeItems"]))


if __name__ == "__main__":
    unittest.main()
