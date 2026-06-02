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

    def build(self, *, workspace: Path, runtime_context: str = "") -> str:
        template_path = self.templates_dir / "system.md"
        active_skills = self.skills_loader.active_context()
        always_names = {skill.name for skill in self.skills_loader.always_skills()}
        values = {
            "workspace": str(workspace),
            "active_skills": active_skills,
            "skills_summary": self.skills_loader.summary(exclude=always_names),
            "user_profile": self.memory_store.read_user(),
            "runtime_context": runtime_context,
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
    rendered = rendered.replace("{{ runtime_context or \"(None)\" }}", values.get("runtime_context", "") or "(None)")
    rendered = rendered.replace("{{ runtime_context }}", values.get("runtime_context", ""))
    return rendered


class RuntimeContextBuilder:
    def __init__(self, backend: Any, *, limit: int = 6, max_chars: int = 12000) -> None:
        self.backend = backend
        self.limit = limit
        self.max_chars = max_chars
        self.last_results: list[dict[str, Any]] = []

    def build(self, query: str, recall_scope: dict[str, Any] | None = None) -> str:
        results = self.backend.search(query, limit=self.limit)
        results = self._rank_branch_safe(results, recall_scope or {})
        self.last_results = results
        if not results:
            return "(No runtime context recalled.)"

        lines = ["## Runtime Context"]
        total = 0
        for result in results:
            # 过滤已归档和内部敏感记忆
            if result.get("status") == "archived":
                continue
            if result.get("sensitivity") in ("sensitive", "internal"):
                continue
            uri = result.get("uri", "")
            neighbors = self.backend.neighbors(uri, limit=3)
            link_lines = ""
            if neighbors:
                link_lines = ", ".join(
                    f"{n['target_uri']} ({n.get('relation', 'related')})"
                    for n in neighbors[:2]
                )
                link_lines = f"\n  Links: {link_lines}"

            entry = (
                f"- URI: {uri}\n"
                f"  Trust: {result.get('trust_score', '?')}\n"
                f"  Recall reason: {result.get('recall_reason', 'keyword match')}\n"
                f"  Source: session={_metadata(result).get('source_session', '?')} "
                f"branch={_metadata(result).get('source_branch', '?')}\n"
                f"  Updated: {result.get('updated_at', '?')}\n"
                f"  Matched: {result.get('title', '?')}\n"
                f"  Summary: {result.get('abstract', result.get('overview', ''))}{link_lines}"
            )
            if total + len(entry) > self.max_chars:
                break
            lines.append(entry)
            total += len(entry)

        return "\n".join(lines) if len(lines) > 1 else "(No runtime context recalled.)"

    def _rank_branch_safe(
        self,
        results: list[dict[str, Any]],
        scope: dict[str, Any],
    ) -> list[dict[str, Any]]:
        active_branch_ids = set(scope.get("active_branch_entry_ids") or [])
        session_id = scope.get("session_id")
        project = scope.get("project")
        ranked = []
        for index, result in enumerate(results):
            if result.get("status") in {"archived", "quarantine"}:
                continue
            if result.get("sensitivity") in {"sensitive", "internal"}:
                continue
            meta = _metadata(result)
            score = float(result.get("trust_score") or 0.0)
            reason = ["base_match"]
            source_branch = meta.get("source_branch")
            source_session = meta.get("source_session")
            knowledge_type = meta.get("knowledge_type") or result.get("context_type")
            if source_branch and source_branch in active_branch_ids:
                score += 3.0
                reason.append("active_branch")
            if source_session and source_session == session_id:
                score += 2.0
                reason.append("same_session")
            if project and meta.get("project") == project:
                score += 1.2
                reason.append("same_project")
            if str(result.get("uri", "")).startswith("mem://project/"):
                score += 0.8
                reason.append("project_scope")
            if str(result.get("uri", "")).startswith("mem://user/"):
                score += 0.4
                reason.append("user_scope")
            if knowledge_type in {"architecture", "pattern", "project", "user", "research"}:
                score += 0.2
                reason.append(str(knowledge_type))
            item = dict(result)
            item["recall_score"] = score
            item["recall_reason"] = ", ".join(reason)
            ranked.append((score, -index, item))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [item for _, _, item in ranked[: self.limit]]


def _metadata(result: dict[str, Any]) -> dict[str, Any]:
    meta = result.get("metadata")
    return meta if isinstance(meta, dict) else {}
