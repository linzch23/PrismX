from __future__ import annotations

import json
import unittest

from helpers import make_temp_dir

from prismx.context import RuntimeContextBuilder
from prismx.context_backend import LocalContextBackend
from prismx.contextfs import ContextFS, ContextObject
from prismx.memory import MemoryStore
from prismx.tree_session import (
    EVENT_BRANCH_JUMPED,
    EVENT_KNOWLEDGE_COMMITTED,
    EVENT_MESSAGE_APPENDED,
    EVENT_TOOL_RESULT_RECORDED,
    FakeSummarizer,
    TreeSessionManager,
)
from prismx.working_set import WorkingSetBuilder


class PrismXTGMEventTests(unittest.TestCase):
    def test_experience_events_replay_semantics(self):
        tmp = make_temp_dir()
        tree = TreeSessionManager(session_dir=tmp / "sessiontrees")
        sid = "default"
        root = tree.append_message(sid, {"role": "user", "content": "root"})
        tree.append_tool_result(sid, {"type": "tool_result", "tool_use_id": "t1", "content": "ok"})
        tree.jumpToEntry(sid, root)
        tree.appendKnowledgeCommit(
            sid,
            compaction_id="c1",
            knowledge_uris=["mem://project/decisions/tgm"],
            archive_uri="ctx://sessiontrees/archives/x",
        )

        reloaded = TreeSessionManager(session_dir=tmp / "sessiontrees")
        events = reloaded.experienceEvents(sid)
        event_types = [event.type for event in events]
        self.assertIn(EVENT_MESSAGE_APPENDED, event_types)
        self.assertIn(EVENT_TOOL_RESULT_RECORDED, event_types)
        self.assertIn(EVENT_BRANCH_JUMPED, event_types)
        self.assertIn(EVENT_KNOWLEDGE_COMMITTED, event_types)


class PrismXWorkingSetTests(unittest.TestCase):
    def test_working_set_uses_active_branch_and_recent_tool_result(self):
        tmp = make_temp_dir()
        tree = TreeSessionManager(session_dir=tmp / "sessiontrees", compact_keep_messages=1)
        sid = "default"
        root = tree.append_message(sid, {"role": "user", "content": "root"})
        tree.append_message(sid, {"role": "assistant", "content": "base"})
        tree.append_message(sid, {"role": "user", "content": "sibling A"})
        tree.jumpToEntry(sid, root)
        tree.append_message(sid, {"role": "user", "content": "active B"})
        tree.append_tool_result(sid, {"type": "tool_result", "tool_use_id": "t1", "content": "tool B"})
        compaction_id = tree.compactActiveBranch(
            sid,
            maxContextTokens=1,
            keepRecentTokens=1,
            summarizer=FakeSummarizer(),
        )

        ws = WorkingSetBuilder(tree).build(
            session_id=sid,
            current_task="continue B",
            task_state="- continue",
            runtime_recall="## Runtime Context\n- URI: mem://x",
            recall_results=[{"uri": "mem://x"}],
        )
        text = json.dumps(ws.active_branch_context, ensure_ascii=False)
        self.assertIn("active B", text)
        self.assertNotIn("sibling A", text)
        self.assertEqual(ws.recent_tool_result["content"], "tool B")
        self.assertIn(compaction_id, [item["id"] for item in ws.episode_summaries])


class PrismXKnowledgeTests(unittest.TestCase):
    def test_compaction_commit_writes_tgm_2_memory_files(self):
        tmp = make_temp_dir()
        store = MemoryStore(tmp / "memory")
        uri = store.commit_session_archive(
            session_uri="ctx://sessiontrees/archives/2026/05/30/s1-c1",
            summary="TGM compaction summary",
            operations=[
                {
                    "action": "upsert",
                    "type": "project",
                    "source_tree_id": "tree-a",
                    "source_memory_id": "memory-a",
                    "category": "decisions",
                    "key": "tgm-runtime",
                    "title": "TGM Runtime",
                    "abstract": "PrismX uses Tree-Guided Memory.",
                    "overview": "Active branch context drives recall.",
                    "content": "PrismX compiles episode memory into wiki knowledge.",
                    "trust_score": 0.9,
                    "tags": ["tgm"],
                }
            ],
            metadata={
                "session_id": "s1",
                "compaction_id": "c1",
                "debug": {"activeLeafId": "leaf-b"},
            },
        )
        self.assertEqual(uri, "ctx://sessiontrees/archives/2026/05/30/s1-c1")
        index_path = tmp / "data" / "knowledge" / "MEMORY.md"
        memory_path = tmp / "data" / "knowledge" / "memories" / "project" / "tree-a-memory-a.md"
        self.assertTrue(index_path.exists())
        self.assertTrue(memory_path.exists())
        memory_text = memory_path.read_text(encoding="utf-8")
        self.assertIn("source_tree_id: tree-a", memory_text)
        self.assertIn("source_memory_id: memory-a", memory_text)
        hits = store.search_memory("TGM Runtime", limit=5)
        self.assertTrue(any(hit["uri"] == "mem://project/tree-a-memory-a" for hit in hits))


class PrismXBranchSafeRecallTests(unittest.TestCase):
    def test_runtime_recall_prefers_current_branch_knowledge(self):
        tmp = make_temp_dir()
        cfs = ContextFS(tmp / "memory")
        for uri, branch in [
            ("mem://project/decisions/current", "b-current"),
            ("mem://project/decisions/sibling", "b-sibling"),
        ]:
            cfs.write_object(
                ContextObject(
                    uri=uri,
                    context_type="memory",
                    title="TGM Decision",
                    abstract="Use branch-safe recall for PrismX.",
                    overview="Recall should avoid branch pollution.",
                    content_path=uri.replace("://", "/") + ".md",
                    source="test",
                    trust_score=0.6,
                    sensitivity="public",
                    status="active",
                    tags=["tgm"],
                    metadata={
                        "source_session": "s1",
                        "source_branch": branch,
                        "knowledge_type": "project",
                    },
                ),
                "branch-safe recall",
            )

        class Store:
            def search_memory(self, query, limit=6):
                return cfs.search_objects(query, limit=limit)
            def read_context(self, uri, layer="auto"):
                return cfs.read_object(uri, layer=layer).get("content", "")
            def list_context(self, prefix="mem://", limit=50):
                return cfs.list_objects(prefix=prefix, limit=limit)
            def graph_neighbors(self, uri, limit=5):
                return []

        builder = RuntimeContextBuilder(LocalContextBackend(Store()), limit=6)
        builder.build(
            "branch-safe recall",
            recall_scope={"session_id": "s1", "active_branch_entry_ids": ["b-current"]},
        )
        self.assertEqual(builder.last_results[0]["uri"], "mem://project/decisions/current")
        self.assertIn("active_branch", builder.last_results[0]["recall_reason"])


if __name__ == "__main__":
    unittest.main()
