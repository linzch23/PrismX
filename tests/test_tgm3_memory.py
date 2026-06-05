from __future__ import annotations

import json
import unittest

from helpers import make_temp_dir

from prismx.memory import MemoryStore
from prismx.model_client import TextBlock
from prismx.runtime_recall import TgmContextGateway, TgmRuntimeRecallBuilder
from prismx.tree_memory import RetrievalIntent, TreeMemoryStore


class Tgm3TreeMemoryTests(unittest.TestCase):
    def test_trace_event_evidence_fold_and_index_are_written(self) -> None:
        tmp = make_temp_dir()
        store = TreeMemoryStore(tmp / "data" / "tree_memory")

        event = store.record_event("tree-a", "error", "pytest failed in parser", session_id="s1")
        evidence = store.store_evidence(
            "tree-a",
            "test_result",
            "FAILED parser test",
            title="pytest failure",
            source_event_id=event.id,
            metadata={"file": "tests/test_parser.py"},
        )
        fold = store.fold(
            "tree-a",
            title="Parser failure",
            summary="Parser test failed before handling empty input.",
            node_type="failure",
            status="failed",
            evidence_ids=[evidence.id],
            source_event_ids=[event.id],
        )

        root = tmp / "data" / "tree_memory" / "tree-a"
        self.assertTrue((root / "trace_events.jsonl").exists())
        self.assertTrue((root / "folded_nodes.jsonl").exists())
        self.assertTrue((root / "memory_index.jsonl").exists())
        self.assertTrue((root / "tree_state.json").exists())
        self.assertTrue((root / "evidence" / "test_results" / f"{evidence.id}.txt").exists())
        self.assertEqual(store.fold_by_id("tree-a", fold.id).status, "failed")

    def test_retrieve_uses_intent_and_returns_top_k_with_reuse_count(self) -> None:
        tmp = make_temp_dir()
        store = TreeMemoryStore(tmp / "data" / "tree_memory")
        for index in range(8):
            store.fold(
                "tree-a",
                title=f"Partial fix {index}",
                summary=f"继续修一个 parser failure case {index}",
                node_type="partial_fix",
                status="partial",
            )

        hits = store.retrieve(
            "tree-a",
            RetrievalIntent(query="继续修一个 parser failure", node_types=["partial_fix"], statuses=["partial"], limit=5),
        )

        self.assertEqual(len(hits), 5)
        self.assertEqual(sum(item.reuse_count for item in store.items("tree-a")), 5)

    def test_rollback_plan_references_evidence(self) -> None:
        tmp = make_temp_dir()
        store = TreeMemoryStore(tmp / "data" / "tree_memory")
        evidence = store.store_evidence(
            "tree-a",
            "file_diff",
            "diff --git a/app.py b/app.py",
            metadata={"file": "app.py"},
        )
        fold = store.fold(
            "tree-a",
            title="Risky partial fix",
            summary="Partial fix changed app.py.",
            status="partial",
            evidence_ids=[evidence.id],
        )

        plan = store.rollback_plan("tree-a", fold.id)

        self.assertIn("app.py", plan["related_files"])
        self.assertIn(evidence.id, plan["evidence_refs"][0])


class Tgm3RuntimeRecallTests(unittest.TestCase):
    def test_llm_intent_retrieves_folded_node_and_evidence_packet(self) -> None:
        tmp = make_temp_dir()
        tree_memory = TreeMemoryStore(tmp / "data" / "tree_memory")
        memory = MemoryStore(tmp / "data" / "knowledge")
        event = tree_memory.record_event("tree-a", "error", "old parser failure", session_id="s1")
        evidence = tree_memory.store_evidence("tree-a", "error_log", "Traceback: parser failed", source_event_id=event.id)
        tree_memory.fold(
            "tree-a",
            title="Parser partial failure",
            summary="之前修 parser 时还剩一个失败分支。",
            node_type="partial_fix",
            status="partial",
            evidence_ids=[evidence.id],
            source_event_ids=[event.id],
        )
        client = TinyMemoryPlanner(
            [
                {"needs_retrieval": True, "reason": "Need prior partial fix."},
                {
                    "query": "继续修 parser failed",
                    "keywords": ["parser", "failed"],
                    "node_types": ["partial_fix"],
                    "statuses": ["partial"],
                    "needs_evidence": True,
                    "limit": 5,
                },
                {"snippets": [{"uri": f"tree://tree-a/evidence/{evidence.id}", "snippet": "parser failed evidence"}]},
            ]
        )
        gateway = TgmContextGateway(
            memory_store=memory,
            tree_memory=tree_memory,
            tree_id_provider=lambda: "tree-a",
        )

        rendered = TgmRuntimeRecallBuilder(gateway, client=client, model="fake", limit=5).build("继续修一个")

        self.assertIn("Retrieval Intent", rendered)
        self.assertIn("Tree Memory", rendered)
        self.assertIn("Evidence Snippets", rendered)
        self.assertIn("parser failed evidence", rendered)


class Tgm3LongTermKnowledgeTests(unittest.TestCase):
    def test_promote_fold_writes_markdown_graph_and_promotion_log(self) -> None:
        tmp = make_temp_dir()
        tree_memory = TreeMemoryStore(tmp / "data" / "tree_memory")
        memory = MemoryStore(tmp / "data" / "knowledge")
        evidence = tree_memory.store_evidence("tree-a", "note", "Reusable fix pattern")
        fold = tree_memory.fold(
            "tree-a",
            title="Parser fix pattern",
            summary="Parser failures should be reproduced with a narrow test first.",
            node_type="conclusion",
            evidence_ids=[evidence.id],
            confidence=0.9,
        )

        uri = memory.promote_tree_memory(fold, memory_type="pattern")

        self.assertTrue(uri.startswith("mem://pattern/"))
        self.assertTrue((tmp / "data" / "knowledge" / "MEMORY.md").exists())
        self.assertTrue((tmp / "data" / "knowledge" / "graph" / "nodes.jsonl").exists())
        self.assertTrue((tmp / "data" / "knowledge" / "graph" / "edges.jsonl").exists())
        log = (tmp / "data" / "knowledge" / "promotion_log.jsonl").read_text(encoding="utf-8")
        self.assertIn(fold.id, log)


if __name__ == "__main__":
    unittest.main()


class TinyMemoryPlanner:
    def __init__(self, responses):
        self._responses = list(responses)

    def create_message(self, **kwargs):
        data = self._responses.pop(0)

        class Response:
            content = [TextBlock(json.dumps(data, ensure_ascii=False))]

        return Response()
