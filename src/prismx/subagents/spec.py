from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SubagentSpec:
    name: str
    description: str
    system_prompt: str
    tool_names: tuple[str, ...]
    max_turns: int
