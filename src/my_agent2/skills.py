from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - only used before dependencies are installed
    yaml = None


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    path: Path
    tags: str = ""
    always: bool = False


class SkillsLoader:
    def __init__(self, skills_dir: Path) -> None:
        self.skills_dir = skills_dir

    def list(self) -> list[Skill]:
        skills: list[Skill] = []
        if not self.skills_dir.exists():
            return skills
        for path in sorted(self.skills_dir.rglob("SKILL.md")):
            text = path.read_text(encoding="utf-8")
            meta, body = self._split_frontmatter(text)
            skills.append(
                Skill(
                    name=meta.get("name") or path.parent.name,
                    description=meta.get("description") or "No description.",
                    body=body.strip(),
                    path=path,
                    tags=meta.get("tags") or "",
                    always=bool(meta.get("always", False)),
                )
            )
        return skills

    def always_skills(self) -> list[Skill]:
        return [skill for skill in self.list() if skill.always]

    def active_context(self) -> str:
        parts = [self.load(skill.name) for skill in self.always_skills()]
        return "\n\n".join(part for part in parts if not part.startswith("Error:"))

    def summary(self, exclude: set[str] | None = None) -> str:
        exclude = exclude or set()
        rows = []
        for skill in self.list():
            if skill.name in exclude:
                continue
            line = f"- {skill.name}: {skill.description}"
            if skill.tags:
                line += f" [{skill.tags}]"
            rows.append(line)
        return "\n".join(rows) if rows else "(No skills installed.)"

    def load(self, name: str) -> str:
        for skill in self.list():
            if skill.name == name or skill.path.parent.name == name:
                return f"# Skill: {skill.name}\n\n{skill.body}"
        available = ", ".join(skill.name for skill in self.list()) or "(none)"
        return f"Error: skill {name!r} not found. Available: {available}"

    @staticmethod
    def _split_frontmatter(text: str) -> tuple[dict, str]:
        if not text.startswith("---\n"):
            return {}, text
        _, raw_meta, body = text.split("---", 2)
        if yaml is not None:
            return yaml.safe_load(raw_meta) or {}, body
        meta = {}
        for line in raw_meta.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            value = value.strip()
            if value.lower() in {"true", "false"}:
                meta[key.strip()] = value.lower() == "true"
            else:
                meta[key.strip()] = value
        return meta, body
