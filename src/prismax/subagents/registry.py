from __future__ import annotations

from pathlib import Path

from .spec import SubagentSpec


BUILTINS = {
    "researcher": {
        "description": "Read-only exploration for web pages, docs, and broad information gathering.",
        "tool_names": ("web_fetch", "read_file", "glob", "grep", "load_skill"),
        "max_turns": 10,
    },
    "analyst": {
        "description": "Read-only code and document analysis, summarization, and comparison.",
        "tool_names": ("read_file", "glob", "grep", "load_skill"),
        "max_turns": 10,
    },
    "coder": {
        "description": "Implementation helper that may edit files and run commands.",
        "tool_names": (
            "read_file",
            "write_file",
            "edit_file",
            "glob",
            "grep",
            "run_command",
            "load_skill",
        ),
        "max_turns": 14,
    },
    "reviewer": {
        "description": "Read-only verification, bug finding, and test-gap review.",
        "tool_names": ("read_file", "glob", "grep", "run_command", "load_skill"),
        "max_turns": 10,
    },
}


DEFAULT_PROMPT = """You are a focused subagent.

Work only on the delegated task. Use tools when useful. Return a concise report with:
- conclusion
- evidence or files checked
- blockers or risks

Do not delegate to other agents.
"""


class SubagentRegistry:
    def __init__(self, templates_dir: Path, skills_loader=None) -> None:
        self.templates_dir = templates_dir
        self.skills_loader = skills_loader
        self.specs = self._load()

    def _load(self) -> dict[str, SubagentSpec]:
        specs: dict[str, SubagentSpec] = {}
        for name, config in BUILTINS.items():
            prompt_path = self.templates_dir / f"{name}.md"
            prompt = prompt_path.read_text(encoding="utf-8").strip() if prompt_path.exists() else DEFAULT_PROMPT
            if self.skills_loader and "load_skill" in config["tool_names"]:
                prompt += "\n\nAvailable skills:\n" + self.skills_loader.summary()
            specs[name] = SubagentSpec(
                name=name,
                description=config["description"],
                system_prompt=prompt,
                tool_names=tuple(config["tool_names"]),
                max_turns=config["max_turns"],
            )
        return specs

    def get(self, name: str) -> SubagentSpec | None:
        return self.specs.get(name)

    def names(self) -> list[str]:
        return sorted(self.specs)

    def describe(self) -> str:
        return "\n".join(
            f"- {name}: {spec.description}" for name, spec in sorted(self.specs.items())
        )
