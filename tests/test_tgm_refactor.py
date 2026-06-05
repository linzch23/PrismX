from __future__ import annotations

import unittest

from helpers import make_temp_dir

from prismx.knowledge_compiler import KnowledgeCompiler
from prismx.memory import MemoryStore
from prismx.runtime_recall import TgmContextGateway, TgmRuntimeRecallBuilder
from prismx.tree_memory import TreeMemoryStore
from prismx.tree_session import TreeSessionManager


class TreeMemoryTests(unittest.TestCase):
    def test_sibling_branch_can_recall_shared_tree_memory(self) -> None:
        tmp = make_temp_dir()
        tree = TreeSessionManager(session_dir=tmp / "sessiontrees")
        store = TreeMemoryStore(tmp / "memory" / "tree")
        sid = "default"

        root = tree.append_message(sid, {"role": "user", "content": "最小生成树"})
        prim = tree.append_message(sid, {"role": "user", "content": "Prim 算法"})
        store.remember(
            sid,
            "最小生成树适用于连通无向图；Prim 更适合稠密图。",
            title="MST 适用条件",
            memory_type="conclusion",
            tags=["mst", "prim"],
            source_branch=prim,
            confidence=0.9,
        )
        self.assertTrue((tmp / "data" / "tree_memory" / sid / "folded_nodes.jsonl").exists())
        self.assertTrue((tmp / "data" / "tree_memory" / sid / "trace_events.jsonl").exists())
        self.assertFalse((tmp / "memory" / "tree" / f"{sid}.jsonl").exists())

        tree.jumpToEntry(sid, root)
        kruskal = tree.append_message(sid, {"role": "user", "content": "Kruskal 算法"})
        branch_text = str(tree.buildModelContext(sid))
        self.assertIn("Kruskal", branch_text)
        self.assertNotIn("Prim 算法", branch_text)

        hits = store.search(sid, "Kruskal 最小生成树 连通图", limit=5)
        self.assertTrue(any(hit["uri"].startswith("tree://default/fold/") for hit in hits))
        self.assertIn("连通无向图", hits[0]["overview"])
        self.assertNotEqual(kruskal, prim)

    def test_fact_type_search_top_k_and_reuse_count(self) -> None:
        tmp = make_temp_dir()
        store = TreeMemoryStore(tmp / "memory" / "tree")
        for index in range(8):
            store.remember(
                "tree-a",
                f"shared fact {index} about graph algorithms",
                memory_type="fact",
                tags=["graph"],
            )

        hits = store.search("tree-a", "graph algorithms", limit=5)

        self.assertEqual(len(hits), 5)
        self.assertTrue(all(hit["metadata"]["memory_type"] == "fact" for hit in hits))
        self.assertEqual(sum(item.reuse_count for item in store.items("tree-a")), 5)


class TgmContextGatewayTests(unittest.TestCase):
    def test_remember_defaults_to_tree_memory_and_can_write_long_term(self) -> None:
        tmp = make_temp_dir()
        memory = MemoryStore(tmp / "memory")
        tree_memory = TreeMemoryStore(tmp / "memory" / "tree")
        gateway = TgmContextGateway(
            memory_store=memory,
            tree_memory=tree_memory,
            tree_id_provider=lambda: "s1",
            active_branch_provider=lambda: "leaf-a",
        )

        tree_uri = gateway.remember("本项目优先保持 TGM 简洁实现。", category="decisions", title="TGM 取舍")
        long_uri = gateway.remember(
            "用户喜欢先看摘要再看细节。",
            category="preferences",
            title="输出偏好",
            scope="long_term",
        )

        self.assertTrue(tree_uri.startswith("tree://s1/fold/"))
        self.assertIn("tree://s1/fold/", long_uri)
        self.assertIn("mem://feedback/", long_uri)
        self.assertTrue((tmp / "data" / "tree_memory" / "s1" / "folded_nodes.jsonl").exists())
        self.assertTrue((tmp / "data" / "knowledge" / "MEMORY.md").exists())
        self.assertIn("简洁实现", gateway.read(tree_uri))
        self.assertTrue(any("摘要" in item.content for item in tree_memory.items("s1")))
        self.assertTrue(any("摘要" in item["overview"] for item in gateway.search_long_term("摘要")))

    def test_special_memory_type_dual_writes_tree_and_long_term(self) -> None:
        tmp = make_temp_dir()
        memory = MemoryStore(tmp / "memory")
        tree_memory = TreeMemoryStore(tmp / "memory" / "tree")
        gateway = TgmContextGateway(
            memory_store=memory,
            tree_memory=tree_memory,
            tree_id_provider=lambda: "s1",
        )

        uri = gateway.remember("记住暗号123123", title="暗号", memory_type="user_profile")

        self.assertIn("tree://s1/fold/", uri)
        self.assertIn("mem://user/", uri)
        self.assertEqual(len(tree_memory.items("s1")), 1)
        self.assertEqual(tree_memory.items("s1")[0].memory_type, "finding")
        self.assertEqual(tree_memory.items("s1")[0].metadata["long_term_special_type"], "user_profile")
        self.assertTrue((tmp / "data" / "tree_memory" / "s1" / "folded_nodes.jsonl").exists())
        self.assertTrue(any("123123" in item["overview"] for item in gateway.search_tree("暗号123123")))
        self.assertTrue(any("123123" in item["overview"] for item in gateway.search_long_term("暗号123123")))


class TgmRuntimeRecallTests(unittest.TestCase):
    def test_runtime_recall_has_three_tgm_layers(self) -> None:
        tmp = make_temp_dir()
        memory = MemoryStore(tmp / "memory")
        tree_memory = TreeMemoryStore(tmp / "memory" / "tree")
        gateway = TgmContextGateway(
            memory_store=memory,
            tree_memory=tree_memory,
            tree_id_provider=lambda: "s1",
        )
        gateway.remember(
            "Kruskal 分支需要复用 Prim 分支发现的 MST 连通无向图约束。",
            category="constraints",
            title="MST 共享约束",
        )
        source_uri = gateway.remember(
            "长期知识：图算法方案需要区分稠密图和稀疏图。",
            category="research",
            title="图算法密度取舍",
            scope="long_term",
        )
        self.assertIn("mem://reference/", source_uri)

        builder = TgmRuntimeRecallBuilder(gateway, limit=4)
        text = builder.build(
            "Kruskal 稠密图 最小生成树",
            active_path_summary="Root -> 最小生成树 -> Kruskal",
            recall_scope={"session_id": "s1"},
        )

        self.assertIn("Active Path Context", text)
        self.assertIn("Tree Memory", text)
        self.assertIn("Long-term Knowledge", text)
        self.assertIn("tree://s1/fold/", text)

    def test_runtime_recall_promotes_tree_memory_after_three_reuses(self) -> None:
        tmp = make_temp_dir()
        memory = MemoryStore(tmp / "memory")
        tree_memory = TreeMemoryStore(tmp / "memory" / "tree")
        gateway = TgmContextGateway(
            memory_store=memory,
            tree_memory=tree_memory,
            tree_id_provider=lambda: "tree-a",
        )
        tree_memory.remember(
            "tree-a",
            "暗号123123 是当前树内事实。",
            title="暗号",
            memory_type="fact",
        )
        builder = TgmRuntimeRecallBuilder(gateway, limit=5)

        for _ in range(3):
            builder.build("暗号123123")

        item = tree_memory.items("tree-a")[0]
        self.assertEqual(item.reuse_count, 3)
        self.assertEqual(item.status, "promoted")
        self.assertTrue(item.promoted)
        hits = memory.search_memory("暗号123123", limit=5)
        self.assertTrue(any(hit["metadata"]["source_memory_id"] == item.id for hit in hits))


class KnowledgeCompilerTests(unittest.TestCase):
    def test_promotes_stable_tree_memory_to_long_term_operation(self) -> None:
        tmp = make_temp_dir()
        store = TreeMemoryStore(tmp / "memory" / "tree")
        store.remember(
            "default",
            "PrismX 的 Runtime Recall 分为 Active Path、Tree Memory、Long-term Knowledge 三层。",
            title="TGM 三层召回",
            memory_type="decision",
            confidence=0.9,
        )
        candidates = store.promotion_candidates("default")
        operations = KnowledgeCompiler().compile_tree_memory(
            candidates,
            session_uri="ctx://sessiontrees/archives/2026/06/02/default-c1",
        )

        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0]["category"], "decisions")
        self.assertEqual(operations[0]["type"], "pattern")
        self.assertEqual(operations[0]["source_tree_id"], "default")
        self.assertIn("tree-memory", operations[0]["tags"])
        self.assertEqual(operations[0]["links"][0]["relation"], "derived_from")

    def test_promoted_tree_memory_is_marked_after_commit(self) -> None:
        tmp = make_temp_dir()
        memory = MemoryStore(tmp / "memory")
        tree_memory = TreeMemoryStore(tmp / "memory" / "tree")
        tree_memory.remember("tree-a", "稳定结论", memory_type="decision", confidence=0.95)
        operations = KnowledgeCompiler().compile_tree_memory(
            tree_memory.promotion_candidates("tree-a"),
            session_uri="ctx://sessiontrees/archives/2026/06/02/s-c",
        )
        memory.commit_session_archive(
            "ctx://sessiontrees/archives/2026/06/02/s-c",
            "summary",
            operations,
            {"session_id": "s", "compaction_id": "c", "debug": {}},
        )
        for item in tree_memory.promotion_candidates("tree-a"):
            tree_memory.mark_promoted("tree-a", item.id)

        self.assertTrue((tmp / "data" / "knowledge" / "MEMORY.md").exists())
        self.assertTrue((tmp / "data" / "knowledge" / "memories" / "project").exists())
        self.assertEqual(tree_memory.items("tree-a")[0].status, "promoted")
        self.assertTrue(tree_memory.items("tree-a")[0].promoted)


if __name__ == "__main__":
    unittest.main()
