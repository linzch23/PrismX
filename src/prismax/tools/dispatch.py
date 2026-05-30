from __future__ import annotations

from threading import Lock
from typing import Callable, TYPE_CHECKING

from prismax.subagents import SubagentRegistry, SubagentSpec

from .base import Tool, object_schema
from .registry import ToolRegistry

if TYPE_CHECKING:
    from prismax.runner import AgentRunner


class DispatchSubagentTool(Tool):
    name = "dispatch_subagent"

    def __init__(
        self,
        *,
        parent_registry: ToolRegistry,
        subagent_registry: SubagentRegistry,
        runner_factory: Callable[[SubagentSpec, ToolRegistry], "AgentRunner"],
    ) -> None:
        self.parent_registry = parent_registry
        self.subagent_registry = subagent_registry
        self.runner_factory = runner_factory
        self._lock = Lock()
        self._count = 0

    @property
    def concurrency_safe(self) -> bool:
        return True

    @property
    def description(self) -> str:
        return (
            "Delegate an isolated task to a focused subagent. The subagent has its own "
            "history and returns only a concise report. Independent subagent calls may "
            "run in parallel.\n\nAvailable subagents:\n"
            f"{self.subagent_registry.describe()}"
        )

    @property
    def parameters(self) -> dict:
        return object_schema(
            {
                "agent_type": {"type": "string", "enum": self.subagent_registry.names()},
                "task": {"type": "string", "minLength": 1},
                "label": {"type": ["string", "null"]},
            },
            required=["agent_type", "task"],
        )

    def execute(self, agent_type: str, task: str, label: str | None = None) -> str:
        spec = self.subagent_registry.get(agent_type)
        if spec is None:
            return f"Error: unknown subagent {agent_type!r}"

        sub_registry = ToolRegistry()
        for tool_name in spec.tool_names:
            tool = self.parent_registry.get(tool_name)
            if tool is not None:
                sub_registry.register(tool)

        with self._lock:
            self._count += 1
            count = self._count
        print(f"[subagent #{count}:{spec.name}] {label or task[:80]}")

        runner = self.runner_factory(spec, sub_registry)
        history = [{"role": "user", "content": task}]
        return runner.step(history)
