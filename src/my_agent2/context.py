from __future__ import annotations

from pathlib import Path

try:
    from jinja2 import Template
except ModuleNotFoundError:  # pragma: no cover - only used before dependencies are installed
    Template = None


class ContextBuilder:
    def __init__(self, templates_dir: Path, skills_loader, memory_store) -> None:
        self.templates_dir = templates_dir
        self.skills_loader = skills_loader
        self.memory_store = memory_store

    def build(self, *, workspace: Path) -> str:
        template_path = self.templates_dir / "system.md"
        active_skills = self.skills_loader.active_context()
        always_names = {skill.name for skill in self.skills_loader.always_skills()}
        values = {
            "workspace": str(workspace),
            "active_skills": active_skills,
            "skills_summary": self.skills_loader.summary(exclude=always_names),
            "memory": self.memory_store.read_memory(),
            "user_profile": self.memory_store.read_user(),
        }
        raw = template_path.read_text(encoding="utf-8")
        if Template is not None:
            return Template(raw).render(**values).strip()
        return _fallback_render(raw, values).strip()


def _fallback_render(raw: str, values: dict[str, str]) -> str:
    rendered = raw
    rendered = rendered.replace('{{ active_skills or "(None)" }}', values["active_skills"] or "(None)")
    for key, value in values.items():
        rendered = rendered.replace("{{ " + key + " }}", value)
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered
