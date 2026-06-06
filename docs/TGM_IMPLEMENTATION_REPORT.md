# PrismX Tree-Guided Memory 实现报告

本文说明 `PrismX-refactor` 如何按 `TGM.md` 重构核心上下文与记忆架构。当前实现采用 TGM 主链路：旧的线性 `history.jsonl`、`MEMORY.md`、`compactions.md` 和 legacy compactor 已移除。

## 1. 总体架构

TGM 在代码中的主链路是：

```text
TreeSession
→ Active Path Context
→ Tree Memory
→ Knowledge Compilation
→ Long-term Knowledge
→ Runtime Recall
→ Working Context
→ LLM
```

核心模块：

- `src/prismx/tree_session.py`：树状会话、active leaf、active branch、分支跳转与压缩。
- `src/prismx/tree_memory.py`：当前会话树内的短期共享经验。
- `src/prismx/knowledge_compiler.py`：将稳定 Tree Memory 编译为长期知识操作。
- `src/prismx/knowledge.py`：Wiki-style Knowledge Base 和本地语义索引。
- `src/prismx/runtime_recall.py`：Active Path、Tree Memory、Long-term Knowledge 三层运行时召回。
- `src/prismx/working_set.py`：最终注入 system prompt 的 Working Set。
- `src/prismx/loop.py`：每轮 Agent 调用的 TGM 编排入口。

## 2. TreeSession 与 Active Path Context

TreeSession 仍以 append-only JSONL 作为事实来源。每个条目有 `id` 和 `parentId`，当前上下文由 active leaf 回溯到 root 得到。

实现位置：

- `TreeSessionManager.getActiveBranch()`
- `TreeSessionManager.buildModelContext()`
- `TreeSessionManager.debugBuildModelContext()`

行为：

- 当前分支只继承 root 到 active leaf 的路径。
- sibling branch 的原始消息不会进入当前模型上下文。
- `/jump`、`/fork`、`/clone` 改变 active leaf 或创建新分支，但不把兄弟分支历史混入 active path。

这对应 `TGM.md` 中的纵向上下文继承能力。

## 3. Tree Memory：树内横向经验共享

新增 `TreeMemoryStore`，每棵会话树拥有独立短期记忆池，URI 形如：

```text
tree://{tree_id}/memory/{item_id}
```

Tree Memory 只保存可复用经验，不保存完整聊天记录或完整工具输出。支持类型：

- `conclusion`：阶段结论
- `decision`：技术决策
- `constraint`：项目约束
- `todo`：共享 Todo
- `finding`：关键发现
- `hypothesis`：待验证假设
- `discarded_option`：废弃方案及原因

运行效果：

- Prim 分支可以写入“最小生成树适用于连通无向图”。
- Kruskal 分支不会读取 Prim 原始消息，但可通过 Tree Memory 召回该结论。
- Tree Memory 以 `tree_id` 隔离，不跨会话树泄漏。

## 4. Long-term Knowledge：长期知识复用

长期知识仍采用 Wiki-style Knowledge Base，并保留本地轻量语义索引：

```text
memory/Wiki/
memory/semantic_index.jsonl
memory/context/index.jsonl
```

实现位置：

- `WikiKnowledgeBase`
- `LocalSemanticVectorIndex`
- `MemoryStore.commit_session_archive()`
- `MemoryStore.search_memory()`

设计取舍：

- 语义索引用于找候选，不直接把全文塞入 prompt。
- 默认召回 L0/L1 摘要；需要全文时通过 `read_context(uri, layer="full")` 渐进披露。
- 长期知识只接收稳定、可验证、跨项目有效的信息。

## 5. 记忆晋升机制

新增 `KnowledgeCompiler`，将满足条件的 Tree Memory 编译为长期知识 operation：

```text
TreeMemoryItem
→ Candidate Knowledge
→ KnowledgeObject
→ Wiki Knowledge Base
→ Semantic Index
```

当前默认晋升条件：

- `confidence >= 0.85`，或
- `reuse_count >= 2`

晋升在 `/compact` 后由 `SessionMemoryCommitter.commit_compaction()` 触发。它会合并两类长期知识来源：

- LLM 从 active path compaction summary 提取的长期记忆。
- `KnowledgeCompiler` 从稳定 Tree Memory 生成的长期知识 operation。

## 6. Runtime Recall 与 Working Context

新增 `TgmRuntimeRecallBuilder`，每轮召回分三层：

1. `Active Path Retrieval`
   - active path 原始消息仍通过 `tree.buildModelContext()` 作为 model messages 传入。
   - Runtime Recall 中记录 active path 摘要和检索路径。

2. `Tree Memory Retrieval`
   - 从当前 `tree_id` 的 Tree Memory 检索树内共享经验。
   - 用于解决兄弟分支横向共享问题。

3. `Long-term Knowledge Retrieval`
   - 从 ContextFS/Wiki/Semantic Index 检索跨树知识候选。
   - 默认注入摘要层，不注入全文。

`AgentApp.ask()` 的调用顺序：

```text
append user message
→ debug active path
→ TgmRuntimeRecallBuilder.build()
→ WorkingSetBuilder.build()
→ ContextBuilder.build()
→ tree.buildModelContext()
→ AgentRunner.step()
```

最终 Working Context 通过 `WorkingSet.render()` 注入 system prompt。

## 7. 工具层变化

`remember` 的默认行为已从“直接写长期记忆”改为“写当前 Tree Memory”：

```text
remember(note, scope="tree")
```

需要跨项目长期保存时显式使用：

```text
remember(note, scope="long_term")
```

上下文工具支持两类 URI：

- `tree://...`：Tree Memory
- `mem://...` / `wiki://...`：长期记忆与知识库

工具：

- `search_context`：同时检索 Tree Memory 和长期知识。
- `read_context`：读取 tree/mem/wiki URI。
- `list_context`：默认列出当前 Tree Memory，可用 `prefix="mem://"` 查看长期记忆。
- `show_context_links`：长期知识显示 MemoryGraph 链接；Tree Memory 当前无图链接。

## 8. Web 影响

本轮没有重做网页，只保留必要兼容：

- 会话树读取 `sessiontrees/*.jsonl`。
- `compaction`、`branch_summary` 等旧节点展示仍保留。
- 新增的 `tree://` Tree Memory 主要通过 context 工具和 Working Set 暴露。

后续网页重构建议把页面拆为四个可视区域：

- TreeSession / Active Path
- Tree Memory
- Long-term Knowledge
- Runtime Recall Trace

## 9. 测试覆盖

新增 `tests/test_tgm_refactor.py`，覆盖：

- sibling branch 不共享原始消息，但可召回 Tree Memory。
- `remember` 默认写 Tree Memory，显式 `scope="long_term"` 写长期记忆。
- Runtime Recall 输出 Active Path、Tree Memory、Long-term Knowledge 三层。
- 稳定 Tree Memory 可被 KnowledgeCompiler 编译为长期知识 operation。

这些测试对应 `TGM.md` 的关键成功标准：纵向继承、横向共享、长期复用和运行时动态注入。

