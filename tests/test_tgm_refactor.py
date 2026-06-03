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

        tree.jumpToEntry(sid, root)
        kruskal = tree.append_message(sid, {"role": "user", "content": "Kruskal 算法"})
        branch_text = str(tree.buildModelContext(sid))
        self.assertIn("Kruskal", branch_text)
        self.assertNotIn("Prim 算法", branch_text)

        hits = store.search(sid, "Kruskal 最小生成树 连通图", limit=5)
        self.assertTrue(any(hit["uri"].startswith("tree://default/memory/") for hit in hits))
        self.assertIn("连通无向图", hits[0]["overview"])
        self.assertNotEqual(kruskal, prim)


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

        self.assertTrue(tree_uri.startswith("tree://s1/memory/"))
        self.assertTrue(long_uri.startswith("mem://user/preferences/"))
        self.assertIn("简洁实现", gateway.read(tree_uri))
        self.assertIn("摘要", gateway.read(long_uri))


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
        memory.remember_note(
            "长期知识：图算法方案需要区分稠密图和稀疏图。",
            category="research",
            title="图算法密度取舍",
        )

        builder = TgmRuntimeRecallBuilder(gateway, limit=4)
        text = builder.build(
            "Kruskal 稠密图 最小生成树",
            active_path_summary="Root -> 最小生成树 -> Kruskal",
            recall_scope={"session_id": "s1"},
        )

        self.assertIn("Active Path Retrieval", text)
        self.assertIn("Tree Memory Retrieval", text)
        self.assertIn("Long-term Knowledge Retrieval", text)
        self.assertIn("tree://s1/memory/", text)


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
        self.assertIn("tree-memory", operations[0]["tags"])
        self.assertEqual(operations[0]["links"][0]["relation"], "derived_from")


if __name__ == "__main__":
    unittest.main()

