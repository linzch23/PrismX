from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .base import Tool, object_schema


class RunCommandTool(Tool):
    name = "run_command"
    description = (
        "Run a shell command in the workspace and return stdout/stderr. "
        "Use for inspection, tests, and build commands."
    )
    exclusive = True

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    @property
    def parameters(self) -> dict:
        return object_schema(
            {
                "command": {"type": "string", "minLength": 1},
                "timeout": {"type": "integer", "description": "seconds, default 60"},
            },
            required=["command"],
        )

    def execute(self, command: str, timeout: int = 60, **_: Any) -> str:
        result = subprocess.run(
            command,
            shell=True,
            cwd=self.workspace,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout + result.stderr).strip()
        return output or f"(Command exited with code {result.returncode} and no output.)"
