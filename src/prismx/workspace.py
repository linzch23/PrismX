from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from .tree_memory import TreeMemoryStore


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:10]}"


class WorkspaceStore:
    """Persistent project/session-tree metadata for the web workbench."""

    def __init__(self, root: Path, tree: Any) -> None:
        self.root = Path(root)
        self.tree = tree
        self.tree_memory = TreeMemoryStore(self.root / "memory" / "tree")
        self.path = self.root / "sessiontrees" / "workspace.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def payload(self) -> dict[str, Any]:
        data = self._load()
        changed = self._sync_sessions(data)
        if changed:
            self._save(data)
        return self._expanded_payload(data)

    def create_project(self, title: str) -> dict[str, Any]:
        data = self._load()
        now = _now()
        project = {
            "id": _new_id("project"),
            "title": title.strip() or "New Project",
            "treeIds": [],
            "createdAt": now,
            "updatedAt": now,
        }
        data["projects"].append(project)
        data["activeProjectId"] = project["id"]
        self._save(data)
        return self._expanded_payload(data)

    def update_project(self, project_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        data = self._load()
        project = self._project(data, project_id)
        title = str(updates.get("title") or "").strip()
        if title:
            project["title"] = title
            project["updatedAt"] = _now()
        self._save(data)
        return self._expanded_payload(data)

    def delete_project(self, project_id: str) -> dict[str, Any]:
        data = self._load()
        project = self._project(data, project_id)
        for tree_id in list(project.get("treeIds", [])):
            self._delete_session_tree_from_data(data, tree_id)
        data["projects"] = [item for item in data["projects"] if item["id"] != project_id]
        if data["activeProjectId"] == project_id:
            data["activeProjectId"] = data["projects"][0]["id"] if data["projects"] else None
        self._repair_selection(data)
        self._save(data)
        return self._expanded_payload(data)

    def create_session_tree(self, project_id: str, title: str) -> dict[str, Any]:
        data = self._load()
        project = self._project(data, project_id)
        now = _now()
        session_id = self.tree.createSession(title=title.strip() or "New Session Tree", cwd=str(self.root))
        tree_id = _new_id("tree")
        node = self._node(
            session_id=session_id,
            tree_id=tree_id,
            parent_id=None,
            title=title.strip() or "New Session Tree",
            position={"x": 80, "y": 180},
            now=now,
        )
        session_tree = {
            "id": tree_id,
            "projectId": project["id"],
            "title": node["title"],
            "rootSessionId": session_id,
            "activeSessionId": session_id,
            "sessionIds": [session_id],
            "createdAt": now,
            "updatedAt": now,
        }
        data["sessionTrees"].append(session_tree)
        data["sessionNodes"][session_id] = node
        project["treeIds"].append(tree_id)
        project["updatedAt"] = now
        data["activeProjectId"] = project["id"]
        data["activeTreeId"] = tree_id
        data["activeSessionId"] = session_id
        self._select_backend_session(session_id)
        self._save(data)
        return self._expanded_payload(data)

    def update_session_tree(self, tree_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        data = self._load()
        tree = self._session_tree(data, tree_id)
        title = str(updates.get("title") or "").strip()
        if title:
            tree["title"] = title
            tree["updatedAt"] = _now()
            root = data["sessionNodes"].get(tree["rootSessionId"])
            if root and root.get("title") == tree.get("title"):
                root["updatedAt"] = tree["updatedAt"]
        self._save(data)
        return self._expanded_payload(data)

    def delete_session_tree(self, tree_id: str) -> dict[str, Any]:
        data = self._load()
        tree = self._session_tree(data, tree_id)
        project_id = tree["projectId"]
        self._delete_session_tree_from_data(data, tree_id)
        if data["activeTreeId"] == tree_id:
            data["activeTreeId"] = None
            data["activeSessionId"] = None
        data["activeProjectId"] = project_id if any(item["id"] == project_id for item in data["projects"]) else data.get("activeProjectId")
        self._repair_selection(data)
        self._save(data)
        return self._expanded_payload(data)

    def create_session_node(self, tree_id: str, parent_id: str, title: str) -> dict[str, Any]:
        data = self._load()
        session_tree = self._session_tree(data, tree_id)
        parent = self._node_by_id(data, parent_id)
        if parent["treeId"] != tree_id:
            raise KeyError(f"parent session is not in tree: {parent_id}")
        now = _now()
        session_id = self.tree.createSession(title=title.strip() or "New Session", cwd=str(self.root))
        position = parent.get("position") or {"x": 80, "y": 120}
        node = self._node(
            session_id=session_id,
            tree_id=tree_id,
            parent_id=parent_id,
            title=title.strip() or "New Session",
            position={"x": int(position.get("x", 80)) + 280, "y": int(position.get("y", 120)) + 120},
            now=now,
        )
        parent.setdefault("children", []).append(session_id)
        parent["updatedAt"] = now
        data["sessionNodes"][session_id] = node
        session_tree.setdefault("sessionIds", []).append(session_id)
        session_tree["activeSessionId"] = session_id
        session_tree["updatedAt"] = now
        data["activeTreeId"] = tree_id
        data["activeSessionId"] = session_id
        data["activeProjectId"] = session_tree["projectId"]
        self._select_backend_session(session_id)
        self._save(data)
        return self._expanded_payload(data)

    def update_session_node(self, session_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        data = self._load()
        node = self._node_by_id(data, session_id)
        now = _now()
        if "title" in updates:
            title = str(updates.get("title") or "").strip()
            if title:
                node["title"] = title
                self.tree.saveSessionMetadata(session_id, title=title)
        if "status" in updates:
            status = str(updates.get("status") or "")
            if status in {"idle", "running", "completed", "error"}:
                node["status"] = status
        if isinstance(updates.get("position"), dict):
            position = updates["position"]
            node["position"] = {
                "x": int(float(position.get("x", node.get("position", {}).get("x", 0)))),
                "y": int(float(position.get("y", node.get("position", {}).get("y", 0)))),
            }
        node["updatedAt"] = now
        tree = self._session_tree(data, node["treeId"])
        tree["updatedAt"] = now
        self._save(data)
        return self._expanded_payload(data)

    def delete_session_node(self, session_id: str) -> dict[str, Any]:
        data = self._load()
        node = self._node_by_id(data, session_id)
        session_tree = self._session_tree(data, node["treeId"])
        if session_tree["rootSessionId"] == session_id:
            raise ValueError("root session node cannot be deleted")
        delete_ids = self._descendant_ids(data, session_id)
        parent_id = node.get("parentId")
        if parent_id and parent_id in data["sessionNodes"]:
            parent = data["sessionNodes"][parent_id]
            parent["children"] = [item for item in parent.get("children", []) if item not in delete_ids]
            parent["updatedAt"] = _now()
        for item_id in delete_ids:
            data["sessionNodes"].pop(item_id, None)
            if item_id in session_tree.get("sessionIds", []):
                session_tree["sessionIds"].remove(item_id)
            if item_id in self.tree.listSessions():
                self.tree.deleteSession(item_id)
        if session_tree.get("activeSessionId") in delete_ids:
            session_tree["activeSessionId"] = parent_id or session_tree["rootSessionId"]
        data["activeSessionId"] = session_tree["activeSessionId"]
        data["activeTreeId"] = session_tree["id"]
        data["activeProjectId"] = session_tree["projectId"]
        session_tree["updatedAt"] = _now()
        self._select_backend_session(data["activeSessionId"])
        self._save(data)
        return self._expanded_payload(data)

    def select_session_node(self, session_id: str) -> dict[str, Any]:
        data = self._load()
        node = self._node_by_id(data, session_id)
        session_tree = self._session_tree(data, node["treeId"])
        session_tree["activeSessionId"] = session_id
        data["activeProjectId"] = session_tree["projectId"]
        data["activeTreeId"] = session_tree["id"]
        data["activeSessionId"] = session_id
        self._select_backend_session(session_id)
        self._save(data)
        return self._expanded_payload(data)

    def select_backend_session(self, session_id: str) -> None:
        self._select_backend_session(session_id)

    def active_path(self, session_id: str) -> list[dict[str, Any]]:
        data = self._load()
        node = self._node_by_id(data, session_id)
        path = [node]
        parent_id = node.get("parentId")
        while parent_id:
            parent = self._node_by_id(data, str(parent_id))
            path.append(parent)
            parent_id = parent.get("parentId")
        return list(reversed(path))

    def active_path_session_ids(self, session_id: str) -> list[str]:
        return [str(node["id"]) for node in self.active_path(session_id)]

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return self._normalize(data)
            except json.JSONDecodeError:
                pass
        data = self._bootstrap()
        self._save(data)
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(self._normalize(data), ensure_ascii=False, indent=2), encoding="utf-8")

    def _bootstrap(self) -> dict[str, Any]:
        now = _now()
        project_id = _new_id("project")
        data = {
            "version": 1,
            "projects": [
                {
                    "id": project_id,
                    "title": "PrismX Workspace",
                    "treeIds": [],
                    "createdAt": now,
                    "updatedAt": now,
                }
            ],
            "sessionTrees": [],
            "sessionNodes": {},
            "activeProjectId": project_id,
            "activeTreeId": None,
            "activeSessionId": None,
        }
        self._sync_sessions(data)
        return data

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        data.setdefault("version", 1)
        data.setdefault("projects", [])
        data.setdefault("sessionTrees", [])
        data.setdefault("sessionNodes", {})
        if not data["projects"] and not self.path.exists():
            now = _now()
            project_id = _new_id("project")
            data["projects"].append(
                {"id": project_id, "title": "PrismX Workspace", "treeIds": [], "createdAt": now, "updatedAt": now}
            )
            data["activeProjectId"] = project_id
        data.setdefault("activeProjectId", data["projects"][0]["id"] if data["projects"] else None)
        data.setdefault("activeTreeId", data["sessionTrees"][0]["id"] if data["sessionTrees"] else None)
        data.setdefault("activeSessionId", None)
        return data

    def _sync_sessions(self, data: dict[str, Any]) -> bool:
        changed = False
        if not data["projects"]:
            return False
        project = data["projects"][0]
        known_ids = set(data["sessionNodes"])
        for index, session_id in enumerate(self.tree.listSessions()):
            if session_id in known_ids:
                continue
            session = self.tree.loadSession(session_id)
            now = session.createdAt or _now()
            title = session.title or f"Session {session_id[:8]}"
            tree_id = _new_id("tree")
            data["sessionNodes"][session_id] = self._node(
                session_id=session_id,
                tree_id=tree_id,
                parent_id=None,
                title=title,
                position={"x": 80, "y": 120 + index * 120},
                now=now,
            )
            data["sessionTrees"].append(
                {
                    "id": tree_id,
                    "projectId": project["id"],
                    "title": title,
                    "rootSessionId": session_id,
                    "activeSessionId": session_id,
                    "sessionIds": [session_id],
                    "createdAt": now,
                    "updatedAt": session.updatedAt or now,
                }
            )
            project.setdefault("treeIds", []).append(tree_id)
            changed = True
        if data["sessionTrees"] and not data.get("activeTreeId"):
            data["activeTreeId"] = data["sessionTrees"][0]["id"]
            data["activeSessionId"] = data["sessionTrees"][0]["activeSessionId"]
            changed = True
        if data.get("activeSessionId") is None and data.get("activeTreeId"):
            tree = self._session_tree(data, data["activeTreeId"])
            data["activeSessionId"] = tree["activeSessionId"]
            changed = True
        return changed

    def _expanded_payload(self, data: dict[str, Any]) -> dict[str, Any]:
        nodes = data["sessionNodes"]
        session_trees = []
        for tree in data["sessionTrees"]:
            session_ids = tree.get("sessionIds", [])
            session_trees.append(
                {
                    **tree,
                    "sessions": [nodes[item] for item in session_ids if item in nodes],
                }
            )
        return {
            "projects": data["projects"],
            "sessionTrees": session_trees,
            "sessionNodes": list(nodes.values()),
            "activeProjectId": data.get("activeProjectId"),
            "activeTreeId": data.get("activeTreeId"),
            "activeSessionId": data.get("activeSessionId"),
        }

    def _delete_session_tree_from_data(self, data: dict[str, Any], tree_id: str) -> None:
        tree = self._session_tree(data, tree_id)
        for session_id in list(tree.get("sessionIds", [])):
            data["sessionNodes"].pop(session_id, None)
            if session_id in self.tree.listSessions():
                self.tree.deleteSession(session_id)
        self.tree_memory.delete_tree(tree_id)
        data["sessionTrees"] = [item for item in data["sessionTrees"] if item["id"] != tree_id]
        for project in data["projects"]:
            project["treeIds"] = [item for item in project.get("treeIds", []) if item != tree_id]
            project["updatedAt"] = _now()

    def _repair_selection(self, data: dict[str, Any]) -> None:
        if not data["projects"]:
            data["activeProjectId"] = None
            data["activeTreeId"] = None
            data["activeSessionId"] = None
            return
        active_project = next((item for item in data["projects"] if item["id"] == data.get("activeProjectId")), None)
        if active_project is None:
            active_project = data["projects"][0]
            data["activeProjectId"] = active_project["id"]
        project_tree_ids = set(active_project.get("treeIds", []))
        active_tree = next(
            (item for item in data["sessionTrees"] if item["id"] == data.get("activeTreeId") and item["id"] in project_tree_ids),
            None,
        )
        if active_tree is None:
            active_tree = next((item for item in data["sessionTrees"] if item["id"] in project_tree_ids), None)
            data["activeTreeId"] = active_tree["id"] if active_tree else None
        if active_tree is None:
            data["activeSessionId"] = None
            return
        session_ids = set(active_tree.get("sessionIds", []))
        if data.get("activeSessionId") not in session_ids:
            data["activeSessionId"] = active_tree.get("activeSessionId") or active_tree.get("rootSessionId")
        active_tree["activeSessionId"] = data["activeSessionId"]

    def _node(
        self,
        *,
        session_id: str,
        tree_id: str,
        parent_id: str | None,
        title: str,
        position: dict[str, int],
        now: str,
    ) -> dict[str, Any]:
        return {
            "id": session_id,
            "treeId": tree_id,
            "parentId": parent_id,
            "title": title,
            "summary": "",
            "status": "idle",
            "createdAt": now,
            "updatedAt": now,
            "children": [],
            "memoryItemIds": [],
            "position": position,
        }

    def _project(self, data: dict[str, Any], project_id: str) -> dict[str, Any]:
        for project in data["projects"]:
            if project["id"] == project_id:
                return project
        raise KeyError(f"project not found: {project_id}")

    def _session_tree(self, data: dict[str, Any], tree_id: str) -> dict[str, Any]:
        for tree in data["sessionTrees"]:
            if tree["id"] == tree_id:
                return tree
        raise KeyError(f"session tree not found: {tree_id}")

    def _node_by_id(self, data: dict[str, Any], session_id: str) -> dict[str, Any]:
        node = data["sessionNodes"].get(session_id)
        if not node:
            raise KeyError(f"session node not found: {session_id}")
        return node

    def _descendant_ids(self, data: dict[str, Any], session_id: str) -> list[str]:
        node = self._node_by_id(data, session_id)
        ids = [session_id]
        for child_id in list(node.get("children", [])):
            ids.extend(self._descendant_ids(data, child_id))
        return ids

    def _select_backend_session(self, session_id: str) -> None:
        if session_id not in self.tree.listSessions():
            raise KeyError(f"session not found: {session_id}")
        self.tree.resumeSession(session_id)
