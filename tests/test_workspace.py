from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from prismx.tree_session import FakeSummarizer, TreeSessionManager
from prismx.workspace import WorkspaceStore


class WorkspaceStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.tree = TreeSessionManager(
            session_dir=self.root / "sessiontrees",
            data_root=self.root / "data",
            summarizer=FakeSummarizer(),
        )
        self.store = WorkspaceStore(self.root, self.tree)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_bootstrap_maps_existing_sessions_to_session_tree_nodes(self) -> None:
        payload = self.store.payload()

        self.assertEqual(len(payload["projects"]), 1)
        self.assertEqual(len(payload["sessionTrees"]), 1)
        self.assertEqual(len(payload["sessionNodes"]), 1)
        node = payload["sessionNodes"][0]
        self.assertEqual(node["id"], self.tree.listSessions()[0])
        self.assertIsNone(node["parentId"])

    def test_create_project_tree_and_child_session_persist_relationships(self) -> None:
        project_payload = self.store.create_project("Research")
        project_id = project_payload["activeProjectId"]
        tree_payload = self.store.create_session_tree(project_id, "Main Task")
        tree_id = tree_payload["activeTreeId"]
        root_id = tree_payload["activeSessionId"]

        child_payload = self.store.create_session_node(tree_id, root_id, "Child Task")
        child_id = child_payload["activeSessionId"]
        root = next(node for node in child_payload["sessionNodes"] if node["id"] == root_id)
        child = next(node for node in child_payload["sessionNodes"] if node["id"] == child_id)

        self.assertIn(child_id, root["children"])
        self.assertEqual(child["parentId"], root_id)
        self.assertIn(child_id, self.tree.listSessions())
        self.assertTrue((self.root / "data" / "workspace.json").exists())
        self.assertTrue((self.root / "data" / "sessions" / tree_id / "tree.json").exists())
        self.assertTrue((self.root / "data" / "sessions" / tree_id / "sessions" / f"{root_id}.jsonl").exists())
        self.assertTrue((self.root / "data" / "sessions" / tree_id / "sessions" / f"{child_id}.jsonl").exists())

    def test_active_path_returns_root_to_current_session(self) -> None:
        payload = self.store.payload()
        tree_id = payload["activeTreeId"]
        root_id = payload["activeSessionId"]
        child_id = self.store.create_session_node(tree_id, root_id, "Child")["activeSessionId"]
        grandchild_id = self.store.create_session_node(tree_id, child_id, "Grandchild")["activeSessionId"]

        self.assertEqual(self.store.active_path_session_ids(grandchild_id), [root_id, child_id, grandchild_id])

    def test_create_session_tree_under_specific_project_selects_new_root(self) -> None:
        first_project = self.store.payload()["activeProjectId"]
        second_project = self.store.create_project("Second Project")["activeProjectId"]

        payload = self.store.create_session_tree(first_project, "First Project Tree")
        new_tree = next(tree for tree in payload["sessionTrees"] if tree["id"] == payload["activeTreeId"])
        root = next(node for node in payload["sessionNodes"] if node["id"] == new_tree["rootSessionId"])

        self.assertEqual(payload["activeProjectId"], first_project)
        self.assertNotEqual(payload["activeProjectId"], second_project)
        self.assertEqual(payload["activeSessionId"], new_tree["rootSessionId"])
        self.assertEqual(new_tree["projectId"], first_project)
        self.assertIsNone(root["parentId"])
        self.assertEqual(root["treeId"], new_tree["id"])

    def test_update_session_node_renames_and_persists_position(self) -> None:
        payload = self.store.payload()
        session_id = payload["activeSessionId"]

        updated = self.store.update_session_node(
            session_id,
            {"title": "Renamed Session", "position": {"x": 320, "y": 220}},
        )
        node = next(item for item in updated["sessionNodes"] if item["id"] == session_id)

        self.assertEqual(node["title"], "Renamed Session")
        self.assertEqual(node["position"], {"x": 320, "y": 220})
        self.assertEqual(self.tree.loadSession(session_id).title, "Renamed Session")

    def test_delete_child_session_recursively_and_reselect_parent(self) -> None:
        payload = self.store.payload()
        tree_id = payload["activeTreeId"]
        root_id = payload["activeSessionId"]
        child_payload = self.store.create_session_node(tree_id, root_id, "Child")
        child_id = child_payload["activeSessionId"]
        grandchild_payload = self.store.create_session_node(tree_id, child_id, "Grandchild")
        grandchild_id = grandchild_payload["activeSessionId"]

        deleted = self.store.delete_session_node(child_id)
        remaining_ids = {node["id"] for node in deleted["sessionNodes"]}

        self.assertNotIn(child_id, remaining_ids)
        self.assertNotIn(grandchild_id, remaining_ids)
        self.assertEqual(deleted["activeSessionId"], root_id)
        self.assertNotIn(child_id, self.tree.listSessions())
        self.assertNotIn(grandchild_id, self.tree.listSessions())

    def test_root_session_node_cannot_be_deleted(self) -> None:
        payload = self.store.payload()

        with self.assertRaises(ValueError):
            self.store.delete_session_node(payload["activeSessionId"])

    def test_project_rename_and_delete_repair_selection(self) -> None:
        first_project = self.store.payload()["activeProjectId"]
        second_project = self.store.create_project("Second")["activeProjectId"]
        self.store.create_session_tree(second_project, "Second Tree")

        renamed = self.store.update_project(second_project, {"title": "Renamed Project"})
        project = next(item for item in renamed["projects"] if item["id"] == second_project)
        self.assertEqual(project["title"], "Renamed Project")

        deleted = self.store.delete_project(second_project)
        self.assertEqual(deleted["activeProjectId"], first_project)
        self.assertNotIn(second_project, {item["id"] for item in deleted["projects"]})

        empty = self.store.delete_project(first_project)
        self.assertEqual(empty["projects"], [])
        self.assertIsNone(empty["activeProjectId"])
        self.assertIsNone(empty["activeTreeId"])
        self.assertIsNone(empty["activeSessionId"])

    def test_session_tree_rename_and_delete_repair_selection(self) -> None:
        payload = self.store.payload()
        project_id = payload["activeProjectId"]
        first_tree = payload["activeTreeId"]
        second = self.store.create_session_tree(project_id, "Second Tree")
        second_tree = second["activeTreeId"]

        renamed = self.store.update_session_tree(second_tree, {"title": "Renamed Tree"})
        tree = next(item for item in renamed["sessionTrees"] if item["id"] == second_tree)
        self.assertEqual(tree["title"], "Renamed Tree")

        deleted = self.store.delete_session_tree(second_tree)
        self.assertEqual(deleted["activeTreeId"], first_tree)
        self.assertNotIn(second_tree, {item["id"] for item in deleted["sessionTrees"]})


if __name__ == "__main__":
    unittest.main()
