from __future__ import annotations

from pathlib import Path


class RuntimePaths:
    """Canonical PrismX runtime paths.

    New runtime data lives under data/. The old memory/ and sessiontrees/
    directories are deprecated read fallbacks only.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.data = self.root / "data"
        self.legacy_memory = self.root / "memory"
        self.legacy_sessiontrees = self.root / "sessiontrees"

    @property
    def workspace(self) -> Path:
        return self.data / "workspace.json"

    @property
    def legacy_workspace(self) -> Path:
        return self.legacy_sessiontrees / "workspace.json"

    @property
    def knowledge(self) -> Path:
        return self.data / "knowledge"

    @property
    def tree_memory(self) -> Path:
        return self.data / "tree_memory"

    @property
    def sessions(self) -> Path:
        return self.data / "sessions"

    def tree_dir(self, tree_id: str) -> Path:
        return self.sessions / _safe_id(tree_id)

    def tree_file(self, tree_id: str) -> Path:
        return self.tree_dir(tree_id) / "tree.json"

    def tree_session_dir(self, tree_id: str) -> Path:
        return self.tree_dir(tree_id) / "sessions"

    def tree_session_file(self, tree_id: str, session_id: str) -> Path:
        return self.tree_session_dir(tree_id) / f"{_safe_id(session_id)}.jsonl"


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in str(value))
