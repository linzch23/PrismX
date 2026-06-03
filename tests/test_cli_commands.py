from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

from prismx.cli import HELP, handle_command
from prismx.tree_memory import TreeMemoryStore
from prismx.tree_session import FakeSummarizer, TreeSessionManager
from prismx.workspace import WorkspaceStore


class CliCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.tree = TreeSessionManager(
            session_dir=self.root / "sessiontrees",
            summarizer=FakeSummarizer(),
        )
        self.workspace = WorkspaceStore(self.root, self.tree)
        self.app = SimpleNamespace(
            root=self.root,
            tree=self.tree,
            tree_memory=TreeMemoryStore(self.root / "memory" / "tree"),
            history=[],
            session_id=self.workspace.payload()["activeSessionId"],
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_command(self, command: str) -> str:
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertTrue(handle_command(self.app, self.workspace, command))
        return output.getvalue()

    def test_help_removes_old_branch_message_commands(self) -> None:
        for old in ("/compact", "/inbox", "/fork", "/clone", "/label", "/jump", "/todos", "/context"):
            self.assertNotIn(old, HELP)
        for new in ("/session new NAME", "/switch ID", "/path", "/working-context"):
            self.assertIn(new, HELP)

    def test_session_new_and_switch_operate_on_session_nodes(self) -> None:
        root_id = self.workspace.payload()["activeSessionId"]

        self.run_command("/session new Child")
        payload = self.workspace.payload()
        child_id = payload["activeSessionId"]
        child = next(node for node in payload["sessionNodes"] if node["id"] == child_id)

        self.assertEqual(child["parentId"], root_id)
        self.assertIn(child_id, self.tree.listSessions())

        self.run_command(f"/switch {root_id}")
        self.assertEqual(self.workspace.payload()["activeSessionId"], root_id)

    def test_path_and_memory_add_use_active_session_tree(self) -> None:
        self.run_command("/memory add decision PrismX uses Session nodes")
        memory_output = self.run_command("/memory")
        path_output = self.run_command("/path")

        self.assertIn("PrismX uses Session nodes", memory_output)
        self.assertIn("Active Path", path_output)


if __name__ == "__main__":
    unittest.main()
