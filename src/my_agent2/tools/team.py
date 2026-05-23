from __future__ import annotations

import json

from my_agent2.team import MessageBus, TeammateManager, VALID_MESSAGE_TYPES

from .base import Tool, object_schema


class SpawnTeammateTool(Tool):
    name = "spawn_teammate"
    description = (
        "Spawn or reactivate a persistent named teammate agent. Teammates have independent "
        "threads, histories, roles, and inboxes. Use for long-running multi-agent collaboration."
    )

    def __init__(self, manager: TeammateManager) -> None:
        self.manager = manager

    @property
    def parameters(self) -> dict:
        return object_schema(
            {
                "name": {"type": "string", "minLength": 1},
                "role": {"type": "string", "minLength": 1},
                "prompt": {"type": "string", "minLength": 1},
            },
            required=["name", "role", "prompt"],
        )

    def execute(self, name: str, role: str, prompt: str) -> str:
        return self.manager.spawn(name, role, prompt)


class ListTeammatesTool(Tool):
    name = "list_teammates"
    description = "List persistent teammate names, roles, and runtime statuses."
    read_only = True

    def __init__(self, manager: TeammateManager) -> None:
        self.manager = manager

    @property
    def parameters(self) -> dict:
        return object_schema({})

    def execute(self) -> str:
        return self.manager.list_all()


class SendMessageTool(Tool):
    name = "send_message"

    def __init__(self, bus: MessageBus, *, sender: str) -> None:
        self.bus = bus
        self.sender = sender

    @property
    def description(self) -> str:
        return f"Send an inbox message as {self.sender} to lead or a teammate."

    @property
    def parameters(self) -> dict:
        return object_schema(
            {
                "to": {"type": "string", "minLength": 1},
                "content": {"type": "string", "minLength": 1},
                "msg_type": {"type": "string", "enum": sorted(VALID_MESSAGE_TYPES)},
            },
            required=["to", "content"],
        )

    def execute(self, to: str, content: str, msg_type: str = "message") -> str:
        return self.bus.send(sender=self.sender, to=to, content=content, msg_type=msg_type)


class ReadInboxTool(Tool):
    name = "read_inbox"
    description = "Read and clear this agent's inbox."

    def __init__(self, bus: MessageBus, *, reader: str) -> None:
        self.bus = bus
        self.reader = reader

    @property
    def parameters(self) -> dict:
        return object_schema({})

    def execute(self) -> str:
        return json.dumps(self.bus.read_inbox(self.reader), ensure_ascii=False, indent=2)


class BroadcastTool(Tool):
    name = "broadcast"
    description = "Broadcast a message to every persistent teammate."

    def __init__(self, bus: MessageBus, manager: TeammateManager, *, sender: str = "lead") -> None:
        self.bus = bus
        self.manager = manager
        self.sender = sender

    @property
    def parameters(self) -> dict:
        return object_schema({"content": {"type": "string", "minLength": 1}}, required=["content"])

    def execute(self, content: str) -> str:
        return self.bus.broadcast(
            sender=self.sender,
            content=content,
            recipients=self.manager.member_names(),
        )
