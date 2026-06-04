from __future__ import annotations

import json
from typing import Any

from .loop import AgentApp
from .runtime_recall import LONG_TERM_SPECIAL_CATEGORY_MAP, LONG_TERM_SPECIAL_MEMORY_TYPES
from .tree_memory import TREE_MEMORY_TYPES
from .workspace import WorkspaceStore


HELP = """Available commands:

Basics:
  /help
  /exit

Agent Runtime:
  /agent
  /run
  /team
  /tools
  /mcp

TreeSession:
  /tree
  /tree list
  /tree new NAME
  /tree rename ID NAME
  /tree delete ID

  /session
  /session new NAME
  /session rename ID NAME
  /session delete ID

  /switch ID

TGM Memory:
  /path
  /memory
  /memory add TYPE CONTENT
  /memory delete ID

  /recall
  /working-context
  /knowledge

Debug:
  /state
  /debug
"""


def main() -> None:
    app = AgentApp()
    workspace = WorkspaceStore(app.root, app.tree)
    try:
        print(f"prismx ready. provider={app.provider} model={app.model} workspace={app.workspace}")
        print("Type /help for commands.\n")

        while True:
            try:
                user_input = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return

            if not user_input:
                continue
            if user_input in {"/exit", "/quit"}:
                return
            if user_input.startswith("/"):
                try:
                    handled = handle_command(app, workspace, user_input)
                except Exception as exc:
                    print(f"Error: {exc}\n")
                    handled = True
                if handled:
                    continue

            print("assistant> ", end="", flush=True)
            app.ask(user_input, on_text_delta=lambda text: print(text, end="", flush=True))
            workspace.payload()
            print("\n")
    finally:
        app.close()


def handle_command(app: AgentApp, workspace: WorkspaceStore, command: str) -> bool:
    if command == "/help":
        print(HELP)
        return True
    if command == "/tools":
        print("\n".join(app.registry.names()) + "\n")
        return True
    if command == "/mcp":
        print(app.mcp.report() + "\n")
        return True
    if command == "/team":
        print(app.team.list_all() + "\n")
        return True
    if command == "/agent":
        print(_agent_state(app, workspace) + "\n")
        return True
    if command == "/run":
        print("Type a normal message to run the Agent Loop in the active Session.\n")
        return True
    if command == "/tree":
        print(_render_tree(workspace.payload()) + "\n")
        return True
    if command == "/tree list":
        print(_tree_list(workspace.payload()) + "\n")
        return True
    if command.startswith("/tree new "):
        title = command.removeprefix("/tree new ").strip()
        payload = workspace.payload()
        project_id = payload.get("activeProjectId")
        if not project_id:
            payload = workspace.create_project("PrismX Workspace")
            project_id = payload["activeProjectId"]
        payload = workspace.create_session_tree(str(project_id), title)
        _select_session(app, workspace, str(payload["activeSessionId"]))
        print(f"Created SessionTree {payload['activeTreeId']}.\n")
        return True
    if command.startswith("/tree rename "):
        tree_id, title = _split_id_text(command, "/tree rename ")
        workspace.update_session_tree(tree_id, {"title": title})
        print("SessionTree renamed.\n")
        return True
    if command.startswith("/tree delete "):
        tree_id = command.removeprefix("/tree delete ").strip()
        payload = workspace.delete_session_tree(tree_id)
        if payload.get("activeSessionId"):
            _select_session(app, workspace, str(payload["activeSessionId"]))
        print("SessionTree deleted.\n")
        return True
    if command == "/session":
        print(_session_info(workspace.payload()) + "\n")
        return True
    if command.startswith("/session new "):
        title = command.removeprefix("/session new ").strip()
        payload = workspace.payload()
        tree_id = payload.get("activeTreeId")
        parent_id = payload.get("activeSessionId")
        if not tree_id or not parent_id:
            print("No active SessionTree. Use /tree new NAME first.\n")
            return True
        payload = workspace.create_session_node(str(tree_id), str(parent_id), title)
        _select_session(app, workspace, str(payload["activeSessionId"]))
        print(f"Created child Session {payload['activeSessionId']}.\n")
        return True
    if command.startswith("/session rename "):
        session_id, title = _split_id_text(command, "/session rename ")
        workspace.update_session_node(session_id, {"title": title})
        print("Session renamed.\n")
        return True
    if command.startswith("/session delete "):
        session_id = command.removeprefix("/session delete ").strip()
        payload = workspace.delete_session_node(session_id)
        if payload.get("activeSessionId"):
            _select_session(app, workspace, str(payload["activeSessionId"]))
        print("Session deleted.\n")
        return True
    if command.startswith("/switch "):
        session_id = command.removeprefix("/switch ").strip()
        payload = workspace.select_session_node(session_id)
        _select_session(app, workspace, str(payload["activeSessionId"]))
        print(f"Switched to Session {session_id}.\n")
        return True
    if command == "/path":
        print(_active_path(workspace.payload()) + "\n")
        return True
    if command == "/memory":
        print(_tree_memory(app, workspace.payload()) + "\n")
        return True
    if command.startswith("/memory add "):
        memory_type, content = _split_id_text(command, "/memory add ")
        if memory_type not in TREE_MEMORY_TYPES and memory_type not in LONG_TERM_SPECIAL_MEMORY_TYPES:
            valid = ", ".join(sorted(TREE_MEMORY_TYPES | LONG_TERM_SPECIAL_MEMORY_TYPES))
            print(f"Invalid memory type. Valid types: {valid}\n")
            return True
        payload = workspace.payload()
        tree_id = payload.get("activeTreeId")
        if not tree_id:
            print("No active SessionTree.\n")
            return True
        uri = app.tree_memory.remember(
            str(tree_id),
            content,
            memory_type="finding" if memory_type in LONG_TERM_SPECIAL_MEMORY_TYPES else memory_type,
            tags=[memory_type],
            source_session_id=str(payload.get("activeSessionId") or app.session_id),
            metadata={"long_term_special_type": memory_type} if memory_type in LONG_TERM_SPECIAL_MEMORY_TYPES else {},
        )
        if memory_type in LONG_TERM_SPECIAL_MEMORY_TYPES:
            long_uri = app.memory.remember_note(
                content,
                category=LONG_TERM_SPECIAL_CATEGORY_MAP[memory_type],
                source_tree_id=str(tree_id),
                source_memory_id=uri.rstrip("/").rsplit("/", 1)[-1],
            )
            print(f"Tree Memory added: {uri}\nLong-term Knowledge added: {long_uri}\n")
            return True
        print(f"Tree Memory added: {uri}\n")
        return True
    if command.startswith("/memory delete "):
        item_id = command.removeprefix("/memory delete ").strip().rsplit("/", 1)[-1]
        payload = workspace.payload()
        tree_id = payload.get("activeTreeId")
        deleted = bool(tree_id and app.tree_memory.delete(str(tree_id), item_id))
        print(("Tree Memory deleted." if deleted else "Tree Memory item not found.") + "\n")
        return True
    if command == "/recall":
        print(_recall(app) + "\n")
        return True
    if command == "/working-context":
        print(_working_context(app) + "\n")
        return True
    if command == "/knowledge":
        print(_knowledge(app) + "\n")
        return True
    if command == "/state":
        print(json.dumps(_state(app, workspace), ensure_ascii=False, indent=2) + "\n")
        return True
    if command == "/debug":
        print(json.dumps(app.working_context_debug(), ensure_ascii=False, indent=2) + "\n")
        return True
    print("Unknown command. Type /help for available commands.\n")
    return True


def _select_session(app: AgentApp, workspace: WorkspaceStore, session_id: str) -> None:
    workspace.select_backend_session(session_id)
    payload = workspace.payload()
    if payload.get("activeTreeId"):
        app.active_tree_id = str(payload["activeTreeId"])
    app.session_id = session_id
    app.history = app.tree.buildModelContext(session_id)


def _split_id_text(command: str, prefix: str) -> tuple[str, str]:
    rest = command.removeprefix(prefix).strip()
    parts = rest.split(maxsplit=1)
    if len(parts) != 2:
        raise ValueError(f"Usage: {prefix.strip()} ID TEXT")
    return parts[0], parts[1].strip()


def _active_tree(payload: dict[str, Any]) -> dict[str, Any] | None:
    active_tree_id = payload.get("activeTreeId")
    return next((tree for tree in payload.get("sessionTrees", []) if tree.get("id") == active_tree_id), None)


def _active_session(payload: dict[str, Any]) -> dict[str, Any] | None:
    tree = _active_tree(payload)
    if not tree:
        return None
    active_session_id = payload.get("activeSessionId")
    return next((session for session in tree.get("sessions", []) if session.get("id") == active_session_id), None)


def _session_by_id(payload: dict[str, Any], session_id: str | None) -> dict[str, Any] | None:
    if not session_id:
        return None
    tree = _active_tree(payload)
    if not tree:
        return None
    return next((session for session in tree.get("sessions", []) if session.get("id") == session_id), None)


def _active_path_sessions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    path = []
    current = _active_session(payload)
    while current:
        path.append(current)
        current = _session_by_id(payload, current.get("parentId"))
    return list(reversed(path))


def _render_tree(payload: dict[str, Any]) -> str:
    tree = _active_tree(payload)
    if not tree:
        return "No SessionTree."
    by_parent: dict[str | None, list[dict[str, Any]]] = {}
    for session in tree.get("sessions", []):
        by_parent.setdefault(session.get("parentId"), []).append(session)
    lines = [f"SessionTree {tree.get('id')}: {tree.get('title')}"]

    def visit(session: dict[str, Any], prefix: str = "") -> None:
        active = " <= active" if session.get("id") == payload.get("activeSessionId") else ""
        lines.append(f"{prefix}- {session.get('title')} ({session.get('id')}){active}")
        for child in by_parent.get(session.get("id"), []):
            visit(child, prefix + "  ")

    root = _session_by_id(payload, tree.get("rootSessionId"))
    if root:
        visit(root)
    return "\n".join(lines)


def _tree_list(payload: dict[str, Any]) -> str:
    if not payload.get("sessionTrees"):
        return "No SessionTrees."
    active = payload.get("activeTreeId")
    return "\n".join(
        f"- {tree.get('id')} {tree.get('title')}{' <= active' if tree.get('id') == active else ''}"
        for tree in payload.get("sessionTrees", [])
    )


def _session_info(payload: dict[str, Any]) -> str:
    session = _active_session(payload)
    if not session:
        return "No active Session."
    return json.dumps(session, ensure_ascii=False, indent=2)


def _active_path(payload: dict[str, Any]) -> str:
    path = _active_path_sessions(payload)
    if not path:
        return "Active Path: (empty)"
    return "Active Path:\n" + "\n".join(f"-> {session.get('title')} ({session.get('id')})" for session in path)


def _tree_memory(app: AgentApp, payload: dict[str, Any]) -> str:
    tree_id = payload.get("activeTreeId")
    if not tree_id:
        return "No active SessionTree."
    items = app.tree_memory.list(str(tree_id))
    if not items:
        return "No Tree Memory."
    return "\n".join(f"- {item['uri']} [{', '.join(item.get('tags', []))}] {item['overview']}" for item in items)


def _recall(app: AgentApp) -> str:
    results = getattr(app.runtime_context_builder, "last_results", []) or []
    lines = ["Active Path Retrieval", "Tree Memory Retrieval", "Long-term Knowledge Retrieval"]
    if results:
        lines.extend(f"- {item.get('uri', item)}" for item in results)
    else:
        lines.append("(No runtime recall has been generated in this CLI session yet.)")
    return "\n".join(lines)


def _working_context(app: AgentApp) -> str:
    if app.last_working_set is not None:
        return app.last_working_set.render()
    return json.dumps(app.working_context_debug(), ensure_ascii=False, indent=2)


def _knowledge(app: AgentApp) -> str:
    items = app.memory.list_context(prefix="mem://", limit=20)
    if not items:
        return "No Long-term Knowledge."
    return "\n".join(f"- {item.get('uri')} {item.get('title', '')}" for item in items)


def _agent_state(app: AgentApp, workspace: WorkspaceStore) -> str:
    state = _state(app, workspace)
    return "\n".join(
        [
            f"Provider: {state['provider']}",
            f"Model: {state['model']}",
            f"Project: {state['activeProjectId'] or '(none)'}",
            f"SessionTree: {state['activeTreeId'] or '(none)'}",
            f"Session: {state['activeSessionId'] or '(none)'}",
        ]
    )


def _state(app: AgentApp, workspace: WorkspaceStore) -> dict[str, Any]:
    payload = workspace.payload()
    return {
        "provider": app.provider,
        "model": app.model,
        "workspace": str(app.workspace),
        "activeProjectId": payload.get("activeProjectId"),
        "activeTreeId": payload.get("activeTreeId"),
        "activeSessionId": payload.get("activeSessionId"),
        "sessions": app.tree.listSessions(),
    }


if __name__ == "__main__":
    main()
