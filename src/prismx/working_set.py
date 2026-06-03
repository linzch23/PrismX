from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .tree_session import BranchSummaryEntry, CompactionEntry, ToolResultEntry


@dataclass
class WorkingSet:
    session_id: str
    active_leaf_id: str | None
    active_branch_entry_ids: list[str]
    active_branch_context: list[dict[str, Any]]
    current_task: str
    task_state: str
    recent_tool_result: dict[str, Any] | None = None
    episode_summaries: list[dict[str, Any]] = field(default_factory=list)
    runtime_recall: str = ""
    recall_results: list[dict[str, Any]] = field(default_factory=list)

    def render(self) -> str:
        lines = ["## Working Set"]
        lines.append(f"- Session: {self.session_id}")
        lines.append(f"- Active leaf: {self.active_leaf_id or '(none)'}")
        lines.append(f"- Active branch entries: {len(self.active_branch_entry_ids)}")
        if self.current_task:
            lines.append(f"- Current task: {self.current_task}")
        if self.task_state:
            lines.append("\n### Task State")
            lines.append(self.task_state)
        if self.episode_summaries:
            lines.append("\n### Episode Memory")
            for item in self.episode_summaries[-3:]:
                lines.append(f"- {item['id']} ({item['type']}): {item['summary']}")
        if self.recent_tool_result:
            content = str(self.recent_tool_result.get("content", ""))
            lines.append("\n### Recent Tool Result")
            lines.append(content[:1200])
        if self.runtime_recall and self.runtime_recall != "(No runtime context recalled.)":
            lines.append("\n### Runtime Recall")
            lines.append(self.runtime_recall)
        return "\n".join(lines)

    def debug(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "active_leaf_id": self.active_leaf_id,
            "active_branch_entry_ids": self.active_branch_entry_ids,
            "active_branch_context_messages": len(self.active_branch_context),
            "recent_tool_result": self.recent_tool_result,
            "episode_summaries": self.episode_summaries,
            "recall_result_uris": [item.get("uri") for item in self.recall_results],
        }


class WorkingSetBuilder:
    def __init__(self, tree: Any) -> None:
        self.tree = tree

    def build(
        self,
        *,
        session_id: str,
        current_task: str,
        task_state: str,
        runtime_recall: str,
        recall_results: list[dict[str, Any]] | None = None,
    ) -> WorkingSet:
        branch = self.tree.getActiveBranch(session_id)
        context = self.tree.buildModelContext(session_id)
        recent_tool = next(
            (entry.toolResult for entry in reversed(branch) if isinstance(entry, ToolResultEntry)),
            None,
        )
        episodes = []
        for entry in branch:
            if isinstance(entry, (CompactionEntry, BranchSummaryEntry)):
                episodes.append(
                    {
                        "id": entry.id,
                        "type": entry.type,
                        "summary": _truncate(entry.summary, 400),
                    }
                )
        active_leaf = branch[-1].id if branch else None
        return WorkingSet(
            session_id=session_id,
            active_leaf_id=active_leaf,
            active_branch_entry_ids=[entry.id for entry in branch],
            active_branch_context=context,
            current_task=current_task,
            task_state=task_state,
            recent_tool_result=recent_tool,
            episode_summaries=episodes,
            runtime_recall=runtime_recall,
            recall_results=list(recall_results or []),
        )


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
