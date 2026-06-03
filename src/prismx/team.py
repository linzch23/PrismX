from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Callable

from .context import RuntimeContextBuilder
from .context_backend import LocalContextBackend
from .memory import MemoryStore
from .runner import AgentRunner
from .tree_session import TreeSessionManager
from .tools.base import Tool
from .tools.registry import ToolRegistry


VALID_MESSAGE_TYPES = {
    "message",
    "broadcast",
    "shutdown_request",
    "shutdown_response",
}
RUNTIME_STATUSES = {"idle", "working"}
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def valid_name(name: str) -> bool:
    return bool(NAME_RE.fullmatch(name.strip()))


class MessageBus:
    """File-backed JSONL inboxes. Sending appends; reading drains."""

    def __init__(self, inbox_dir: Path) -> None:
        self.inbox_dir = inbox_dir
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def send(
        self,
        *,
        sender: str,
        to: str,
        content: str,
        msg_type: str = "message",
        extra: dict | None = None,
    ) -> str:
        sender = sender.strip()
        to = to.strip()
        if not valid_name(sender):
            return f"Error: invalid sender {sender!r}"
        if not valid_name(to):
            return f"Error: invalid inbox name {to!r}"
        if msg_type not in VALID_MESSAGE_TYPES:
            return f"Error: invalid msg_type {msg_type!r}. Valid: {sorted(VALID_MESSAGE_TYPES)}"

        message = {
            "type": msg_type,
            "from": sender,
            "content": content,
            "timestamp": time.time(),
        }
        if extra:
            message.update(extra)

        with self.lock:
            path = self.inbox_dir / f"{to}.jsonl"
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(message, ensure_ascii=False) + "\n")
        return f"Delivered {msg_type} to {to}."

    def read_inbox(self, name: str) -> list[dict]:
        name = name.strip()
        if not valid_name(name):
            return [
                {
                    "type": "message",
                    "from": "system",
                    "content": f"Error: invalid inbox name {name!r}",
                    "timestamp": time.time(),
                }
            ]

        path = self.inbox_dir / f"{name}.jsonl"
        with self.lock:
            if not path.exists():
                return []
            lines = path.read_text(encoding="utf-8").splitlines()
            path.write_text("", encoding="utf-8")

        messages = []
        for line in lines:
            if not line.strip():
                continue
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError as exc:
                messages.append(
                    {
                        "type": "message",
                        "from": "system",
                        "content": f"Error parsing inbox line: {exc}",
                        "timestamp": time.time(),
                    }
                )
        return messages

    def broadcast(self, *, sender: str, content: str, recipients: list[str]) -> str:
        count = 0
        for recipient in recipients:
            if recipient == sender:
                continue
            result = self.send(sender=sender, to=recipient, content=content, msg_type="broadcast")
            if not result.startswith("Error"):
                count += 1
        return f"Broadcast delivered to {count} teammate(s)."


class TeammateManager:
    """Persistent named teammate agents with status and inboxes."""

    BASE_TOOL_NAMES = (
        "run_command",
        "web_fetch",
        "load_skill",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "grep",
    )

    def __init__(
        self,
        *,
        team_dir: Path,
        bus: MessageBus,
        client,
        model: str,
        workspace: Path,
        parent_registry: ToolRegistry,
        teammate_tool_factory: Callable[[str], list[Tool]],
        max_tokens: int = 3000,
    ) -> None:
        self.team_dir = team_dir
        self.team_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.team_dir / "config.json"
        self.bus = bus
        self.client = client
        self.model = model
        self.workspace = workspace
        self.parent_registry = parent_registry
        self.teammate_tool_factory = teammate_tool_factory
        self.max_tokens = max_tokens
        self.config = self._load_config()
        self.threads: dict[str, threading.Thread] = {}
        self.lock = threading.Lock()
        self._mark_stale_members_offline()

    def _load_config(self) -> dict:
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("members"), list):
                    return data
            except json.JSONDecodeError:
                pass
        return {"team_name": "default", "members": []}

    def _save_config(self) -> None:
        self.config_path.write_text(
            json.dumps(self.config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _mark_stale_members_offline(self) -> None:
        changed = False
        for member in self.config["members"]:
            if member.get("status") in RUNTIME_STATUSES:
                member["status"] = "offline"
                changed = True
        if changed:
            self._save_config()

    def _find_member(self, name: str) -> dict | None:
        return next((member for member in self.config["members"] if member["name"] == name), None)

    def _set_status(self, name: str, status: str) -> None:
        with self.lock:
            member = self._find_member(name)
            if member:
                member["status"] = status
                self._save_config()

    def spawn(self, name: str, role: str, prompt: str) -> str:
        name = name.strip()
        role = role.strip() or "teammate"
        if not valid_name(name):
            return "Error: name must contain only letters, numbers, underscore, dot, or dash."

        with self.lock:
            member = self._find_member(name)
            running = self.threads.get(name)
            if member and running and running.is_alive():
                member["role"] = role
                member["status"] = "working"
                self._save_config()
                self.bus.send(sender="lead", to=name, content=prompt)
                return f"Teammate {name!r} is already running; sent the new task to its inbox."

            if member:
                member["role"] = role
                member["status"] = "working"
            else:
                self.config["members"].append({"name": name, "role": role, "status": "working"})
            self._save_config()

        thread = threading.Thread(
            target=self._teammate_loop,
            args=(name, role, prompt),
            daemon=True,
        )
        self.threads[name] = thread
        thread.start()
        return f"Spawned teammate {name!r} ({role})."

    def _teammate_loop(self, name: str, role: str, first_task: str) -> None:
        member_dir = self.team_dir / name
        member_dir.mkdir(parents=True, exist_ok=True)
        memory = MemoryStore(member_dir / "memory")
        tree = TreeSessionManager(
            session_dir=member_dir / "sessions",
            cwd=str(self.workspace),
        )
        session_id = "default"
        if session_id not in tree.listSessions():
            session_id = tree.createSession(session_id, cwd=str(self.workspace), title=name)
        tree.resumeSession(session_id)
        runtime_context = RuntimeContextBuilder(LocalContextBackend(memory), limit=4, max_chars=6000)
        system_prompt = (
            f"You are a persistent teammate agent named {name}. Your role is {role}.\n"
            f"Workspace: {self.workspace}\n\n"
            "You have an inbox. Use send_message to report results to lead. "
            "Use read_inbox to read your own messages when needed. "
            "Finish each assigned task, send a concise report to lead, then wait for more inbox "
            "messages. If you receive a shutdown_request, send shutdown_response and stop."
        )
        registry = self._build_teammate_registry(name)
        runner = AgentRunner(
            client=self.client,
            model=self.model,
            registry=registry,
            system_prompt=system_prompt,
            max_tokens=self.max_tokens,
            max_turns=20,
        )
        tree.append_message(session_id, {"role": "user", "content": first_task})
        has_work = True

        while True:
            inbox = self.bus.read_inbox(name)
            for message in inbox:
                if message.get("type") == "shutdown_request":
                    self.bus.send(
                        sender=name,
                        to=message.get("from", "lead"),
                        content="Shutdown acknowledged.",
                        msg_type="shutdown_response",
                    )
                    self._set_status(name, "shutdown")
                    return
                tree.append_message(
                    session_id,
                    {
                        "role": "user",
                        "content": (
                            "<inbox>\n"
                            + json.dumps(message, ensure_ascii=False, indent=2)
                            + "\n</inbox>"
                        ),
                    },
                )
                has_work = True

            if not has_work:
                time.sleep(1)
                continue

            self._set_status(name, "working")
            try:
                recall = runtime_context.build(
                    tree.buildModelContext(session_id)[-1].get("content", "")
                    if tree.buildModelContext(session_id)
                    else "",
                    recall_scope={
                        "session_id": session_id,
                        "active_branch_entry_ids": tree.debugBuildModelContext(session_id).get(
                            "activePathEntryIds", []
                        ),
                        "project": self.workspace.name,
                    },
                )
                runner.system_prompt = system_prompt + "\n\n" + recall

                def record_tool_call(block) -> None:
                    tree.append_tool_call(
                        session_id,
                        {"id": block.id, "name": block.name, "input": block.input},
                    )

                def record_tool_result(result: dict[str, str]) -> None:
                    tree.append_tool_result(session_id, result)

                final = runner.step(
                    tree.buildModelContext(session_id),
                    on_assistant_message=lambda content: tree.append_message(
                        session_id,
                        {"role": "assistant", "content": content},
                    ),
                    on_tool_call=record_tool_call,
                    on_tool_result=record_tool_result,
                    history_provider=lambda: tree.buildModelContext(session_id),
                )
            except Exception as exc:
                final = f"Error: teammate {name} failed: {exc}"
            if final.strip():
                self.bus.send(sender=name, to="lead", content=final.strip())
            self._set_status(name, "idle")
            has_work = False

    def _build_teammate_registry(self, sender: str) -> ToolRegistry:
        registry = ToolRegistry()
        for tool_name in self.BASE_TOOL_NAMES:
            tool = self.parent_registry.get(tool_name)
            if tool is not None:
                registry.register(tool)
        for tool in self.teammate_tool_factory(sender):
            registry.register(tool)
        return registry

    def list_all(self) -> str:
        with self.lock:
            if not self.config["members"]:
                return "No teammates."
            lines = [f"Team: {self.config.get('team_name', 'default')}"]
            for member in self.config["members"]:
                status = member["status"]
                note = " (spawn again to reactivate)" if status == "offline" else ""
                lines.append(f"- {member['name']} ({member['role']}): {status}{note}")
            return "\n".join(lines)

    def member_names(self) -> list[str]:
        with self.lock:
            return [member["name"] for member in self.config["members"]]
