# PrismX Tree-Guided Memory 3.0 实现说明

## 1 设计背景

PrismX 的目标不是把所有历史消息都塞进上下文窗口，而是让 Agent 能主动管理上下文：知道什么时候需要查历史、查哪一层历史、根据什么证据判断，以及如何把一次执行经历沉淀为未来可复用的知识。

TGM 2.0 已经把记忆分成三层：

```text
Active Path Context
Tree Memory
Long-term Knowledge
```

但 TGM 2.0 的 Tree Memory 更像“树内经验条目池”，Long-term Knowledge 更像“长期 Markdown 条目库”。它能解决一部分跨分支复用问题，但仍然缺少执行轨迹、原始证据、回滚依据、知识晋升日志和更明确的 Runtime Recall 决策流程。

TGM 3.0 的核心升级是：

```text
从“记忆条目”升级为“可折叠、可验证、可回滚、可晋升的执行记忆系统”
```

当前实现对应代码主要位于：

- `PrismaX-refactor/src/prismx/tree_memory.py`
- `PrismaX-refactor/src/prismx/memory.py`
- `PrismaX-refactor/src/prismx/runtime_recall.py`
- `PrismaX-refactor/src/prismx/loop.py`
- `PrismaX-refactor/src/prismx/cli.py`
- `PrismaX-refactor/src/prismx/server.py`

## 2 核心思想

### 2.1 三层记忆结构

TGM 3.0 保留 TGM 的三层架构：

| 层级 | 职责 | 当前实现 |
|---|---|---|
| Active Path Context | 当前 Session 沿父链继承上下文 | `WorkspaceStore.active_path(...)` 与 server 端 active path context |
| Tree Memory | 当前 Session Tree 内的执行记忆、证据和经验复用 | `TreeMemoryStore` |
| Long-term Knowledge | 跨树、跨项目、可追溯长期知识 | `MemoryStore` |

三层职责不同：

- Active Path Context 负责纵向继承。
- Tree Memory 负责树内横向共享。
- Long-term Knowledge 负责跨树、跨项目复用。

### 2.2 Evidence-first 原则

TGM 3.0 不把摘要当作唯一事实来源。

```text
FoldedNode 负责导航
Evidence 负责验证
```

也就是说，模型可以先通过 FoldedNode 快速知道“发生过什么”，但如果要把历史经验注入当前推理，应尽量通过 Evidence Snippet 回看原始证据。

当前实现中，Evidence 会保存到：

```text
data/tree_memory/{tree_id}/evidence/
```

并通过 `Evidence.id` 被 FoldedNode 引用。

### 2.3 LLM-first Runtime Recall

TGM 3.0 的 Runtime Recall 不再只是简单的关键词 Top-K 拼接，而是先让 LLM 做粗粒度判断和检索意图生成：

```text
Current Context
-> LLM Coarse Reasoning
-> LLM Retrieval Intent
-> Tree Memory Recall
-> Evidence Snippet
-> Long-term Knowledge Recall
-> ContextPacket
```

当前实现中，如果真实 LLM 不可用，代码会使用保守 fallback，保证测试和本地运行不被阻塞。但设计上，Runtime Recall 的主路径是 LLM-first。

### 2.4 可追溯长期知识

Long-term Knowledge 不允许凭空生成。每条长期知识都必须能追溯到 Tree Memory 的 FoldedNode。

长期知识至少保留：

```text
source_tree_id
source_fold_id
source_evidence_ids
```

这意味着长期知识不是“用户随手写入的孤立笔记”，而是从某个树内执行经历中晋升出来的可追溯知识。

## 3 整体架构

### 3.1 数据流总览

TGM 3.0 的完整闭环如下：

```text
User Request
-> Agent Execution
-> TraceEvent
-> Evidence
-> FoldedNode
-> Tree Memory
-> Runtime Recall
-> Agent Reasoning
-> Promotion
-> Long-term Knowledge
-> Future Recall
```

这个闭环把一次任务执行拆成三类资产：

1. 发生了什么：TraceEvent。
2. 证据是什么：Evidence。
3. 可以如何复用：FoldedNode 与 Long-term Knowledge。

### 3.2 Runtime 写入链路

`AgentApp.ask(...)` 中会把运行过程写入 Tree Memory：

- 用户输入记录为 `TraceEvent(event_type="user")`。
- 助手回复记录为 `TraceEvent(event_type="assistant")`。
- 工具调用记录为 `TraceEvent(event_type="tool_call")`。
- 工具结果记录为 `TraceEvent(event_type="tool_result")`。
- 对应内容会保存为 Evidence。

这让 Tree Memory 不只保存“结论”，也保存 Agent 运行过程中的原始材料。

### 3.3 Runtime Recall 链路

`TgmRuntimeRecallBuilder.build(...)` 负责构建运行时上下文：

1. 读取当前请求和 Active Path summary。
2. 调用 LLM 进行 Coarse Reasoning。
3. 如果需要检索，生成 RetrievalIntent。
4. 用 RetrievalIntent 检索 Tree Memory。
5. 根据命中的 FoldedNode 读取 Evidence Snippet。
6. 检索 Long-term Knowledge。
7. 组装为 ContextPacket 并注入 Agent Loop。

### 3.4 Promotion 链路

稳定的 FoldedNode 可以晋升为 Long-term Knowledge。

当前晋升来源包括：

- Runtime Recall 后发现高置信或多次复用的 Tree Memory。
- CLI/API 手动 promote。
- compaction 后通过 `KnowledgeCompiler` 生成长期知识操作。

晋升后会写入：

```text
data/knowledge/memories/{type}/
data/knowledge/graph/nodes.jsonl
data/knowledge/graph/edges.jsonl
data/knowledge/promotion_log.jsonl
```

## 4 TreeSession 与 Active Path Context

### 4.1 Session Tree 的职责

PrismX 的树节点不是单条消息，而是完整 Session。

```text
SessionTree
└── SessionNode
    └── Messages
```

Session Tree 负责组织任务分支：

- 管理项目内的 Session Tree。
- 管理 SessionNode 父子关系。
- 保存当前 active tree 与 active session。
- 为 Active Path Context 提供父链。

### 4.2 Active Path 的上下文继承

Active Path 是从 root Session 到当前 active Session 的路径：

```text
Root Session
-> Parent Session
-> Current Session
```

它解决的是“父节点目标、约束和已有对话如何传给子节点”的问题。

### 4.3 为什么 sibling 分支不直接共享原始消息

兄弟分支的原始对话不会直接进入当前 Session 上下文。这样可以避免：

- 兄弟分支的临时尝试污染当前推理。
- 失败路径被误当成当前指令。
- 上下文无限膨胀。

兄弟分支的可复用内容应通过 Tree Memory 共享，而不是直接共享原始消息。

## 5 Tree Memory：树内执行记忆系统

### 5.1 Tree Memory 的定位

TGM 3.0 中，Tree Memory 不再只是“当前树内可复用经验池”，而是当前 Session Tree 的执行记忆系统。

它负责保存：

- 执行轨迹。
- 原始证据。
- 折叠后的经验节点。
- 检索索引。
- 回滚依据。

### 5.2 存储结构

Tree Memory 新写入路径为：

```text
data/tree_memory/{tree_id}/
├─ trace_events.jsonl
├─ folded_nodes.jsonl
├─ memory_index.jsonl
├─ tree_state.json
├─ evidence_index.jsonl
└─ evidence/
   ├─ command_outputs/
   ├─ error_logs/
   ├─ file_diffs/
   ├─ search_results/
   ├─ code_snippets/
   └─ test_results/
```

旧的 TGM 2.0 主路径：

```text
data/tree_memory/{tree_id}.jsonl
```

不再作为新写入路径。

### 5.3 TraceEvent

`TraceEvent` 是最底层的执行记录。

当前字段包括：

```python
id
tree_id
session_id
event_type
content
created_at
actor
evidence_ids
metadata
```

支持的事件类型包括：

```text
user
assistant
tool_call
tool_result
error
test
diff
search
note
```

TraceEvent 回答的是：

```text
当时发生了什么？
是谁触发的？
属于哪个 Session？
关联哪些 Evidence？
```

### 5.4 Evidence

`Evidence` 保存可验证的原始材料。

当前字段包括：

```python
id
tree_id
evidence_type
title
path
created_at
source_event_id
metadata
```

支持的证据类型包括：

```text
command_output
error_log
file_diff
search_result
code_snippet
test_result
note
```

Evidence 的设计原则是：

```text
摘要可以压缩，证据必须可回看。
```

### 5.5 FoldedNode

`FoldedNode` 是 Tree Memory 的核心可复用单位。

当前字段包括：

```python
id
tree_id
title
summary
node_type
status
confidence
reuse_count
promoted
source_event_ids
evidence_ids
tags
created_at
updated_at
metadata
```

支持的 node type 包括：

```text
decision
constraint
finding
conclusion
todo
hypothesis
discarded_option
fact
failure
partial_fix
```

FoldedNode 回答的是：

```text
这段执行经历沉淀出了什么可复用经验？
它的状态是什么？
它的依据是什么？
未来如何召回？
```

### 5.6 MemoryIndexItem

`MemoryIndexItem` 是 FoldedNode 的轻量索引。

它保存：

```python
id
tree_id
fold_id
title
description
tags
node_type
status
confidence
updated_at
```

它的职责不是保存全文，而是帮助检索时快速定位候选 FoldedNode。

### 5.7 Tree Memory 的兼容外壳

为了避免一次性破坏 CLI、工具和前端，当前实现保留了一些兼容方法名：

```python
remember(...)
search(...)
list(...)
delete(...)
promotion_candidates(...)
mark_promoted(...)
```

但这些方法底层已经写入 TGM 3.0 的目录化结构。

例如 `remember(...)` 的实际行为是：

```text
record_event
-> store_evidence
-> fold
-> write memory_index
```

## 6 Memory Actions

TGM 3.0 把记忆管理变成显式动作，而不是隐藏在 Top-K 检索之后。

### 6.1 Fold

Fold 负责把一段执行轨迹压缩成 FoldedNode。

当前 CLI：

```text
/memory fold
```

当前 API：

```text
POST /api/memory/fold
```

### 6.2 Retrieve

Retrieve 根据 RetrievalIntent 或 query 检索 Tree Memory。

当前 CLI：

```text
/memory retrieve <query>
```

当前 API：

```text
POST /api/memory/retrieve
```

### 6.3 Snippet

Snippet 从 Evidence 中抽取与当前 query 相关的关键片段。

当前代码入口：

```python
TreeMemoryStore.snippet(...)
```

Runtime Recall 会在命中 FoldedNode 后读取对应 Evidence snippet。

### 6.4 Rollback

Rollback 不直接修改文件，而是生成一个基于证据的回滚计划。

当前 CLI：

```text
/memory rollback <fold_id>
```

当前 API：

```text
POST /api/memory/rollback-plan
```

返回结构包括：

```text
related_files
evidence_refs
suggested_steps
risk
```

### 6.5 Promote

Promote 把 FoldedNode 晋升为 Long-term Knowledge。

当前 CLI：

```text
/memory promote <fold_id> --type pattern
```

当前 API：

```text
POST /api/memory/promote
```

### 6.6 Archive

Archive 用于把 FoldedNode 标记为 archived、discarded 等状态。

当前代码入口：

```python
TreeMemoryStore.archive(...)
```

## 7 Long-term Knowledge：跨树知识系统

### 7.1 Long-term Knowledge 的定位

Long-term Knowledge 负责跨树、跨项目的长期复用。

它保存的不是所有短期经验，而是从 FoldedNode 晋升出来、具备长期价值的知识。

### 7.2 存储结构

Long-term Knowledge 当前结构为：

```text
data/knowledge/
├─ MEMORY.md
├─ memories/
│  ├─ user/
│  ├─ feedback/
│  ├─ project/
│  ├─ reference/
│  └─ pattern/
├─ graph/
│  ├─ nodes.jsonl
│  └─ edges.jsonl
└─ promotion_log.jsonl
```

长期知识类型包括：

```text
user
feedback
project
reference
pattern
```

其中 `pattern` 是 TGM 3.0 新增类型，用于保存可跨任务复用的解决模式、失败模式、设计模式和操作模式。

### 7.3 KnowledgeNode

`KnowledgeNode` 是长期知识节点。

当前字段包括：

```python
id
name
description
type
source_tree_id
source_fold_id
source_evidence_ids
created_at
updated_at
confidence
status
tags
content
```

每个 KnowledgeNode 都会写成 Markdown 文件。

### 7.4 KnowledgeEdge

`KnowledgeEdge` 表示长期知识图谱中的关系。

当前字段包括：

```python
id
source_uri
target_uri
relation
confidence
created_at
metadata
```

当前晋升时会写入关系：

```text
tree://{tree_id}/fold/{fold_id}
-> mem://{type}/{id}
relation = promoted_to
```

### 7.5 MEMORY.md 索引

`MEMORY.md` 是长期知识轻量索引，只保存名称、描述和类型。

它的作用是：

- 让长期知识结构可读。
- 避免每次检索都先加载全部正文。
- 为后续更复杂的图谱或语义检索预留入口。

### 7.6 Promotion Log

`promotion_log.jsonl` 记录每次晋升：

```text
何时晋升
为什么晋升
来源 tree_id
来源 fold_id
来源 evidence_ids
目标 URI
目标类型
```

这让长期知识的演化过程可审计。

### 7.7 为什么长期知识必须来源于 FoldedNode

长期知识如果不能追溯来源，就会退化成不可验证的“模型印象”。

TGM 3.0 要求：

```text
Long-term Knowledge
必须来源于
Tree Memory FoldedNode
```

这样做的好处是：

- 能回看原始 Evidence。
- 能知道知识来自哪个 Session Tree。
- 能判断知识是否过期、是否被替代。
- 能支持 rollback、archive 和 graph relation。

## 8 Runtime Recall 3.0

### 8.1 ContextPacket

`ContextPacket` 是 Runtime Recall 的最终产物。

它包含：

```python
query
active_path_summary
coarse_reasoning
retrieval_intent
tree_memory
evidence_snippets
long_term
```

它不是简单字符串拼接，而是结构化的工作上下文包。

### 8.2 Coarse Reasoning

Coarse Reasoning 先判断当前任务是否需要检索记忆。

LLM 期望输出：

```json
{
  "needs_retrieval": true,
  "reason": "Need prior partial fix."
}
```

如果 LLM 不可用，当前实现会使用 fallback：

```text
默认需要检索
```

### 8.3 RetrievalIntent

`RetrievalIntent` 描述应该如何检索 Tree Memory。

当前字段包括：

```python
query
keywords
node_types
statuses
needs_evidence
limit
```

示例：

```json
{
  "query": "继续修 parser failed",
  "keywords": ["parser", "failed"],
  "node_types": ["partial_fix"],
  "statuses": ["partial"],
  "needs_evidence": true,
  "limit": 5
}
```

### 8.4 Tree Memory Recall

Tree Memory Recall 会根据 RetrievalIntent 检索 FoldedNode。

检索会考虑：

- query tokens
- keywords
- node_types
- statuses
- confidence
- reuse_count

命中后会增加 FoldedNode 的 `reuse_count`。

### 8.5 Evidence Snippet

命中 FoldedNode 后，Runtime Recall 会读取它关联的 Evidence。

如果 LLM 可用，会尝试进一步压缩 Evidence Snippet；如果不可用，则使用本地 `_best_snippet(...)` 截取相关片段。

### 8.6 Long-term Knowledge Recall

Long-term Knowledge Recall 使用同一个检索意图的 query、keywords 和推导出的长期知识类型检索 `MemoryStore`。

它返回的是 `mem://...` 知识节点，并保留来源字段：

```text
source_tree_id
source_fold_id
source_evidence_ids
```

### 8.7 Working Context 注入

最终 `ContextPacket.render(...)` 会渲染为 Runtime Recall 文本，并进入 `WorkingSetBuilder`。

随后系统 prompt 会由 `ContextBuilder.build(...)` 重新生成，把 Runtime Recall 注入 Agent Loop。

## 9 Agent Loop 集成

### 9.1 用户消息如何进入 TraceEvent

`AgentApp.ask(...)` 一开始会追加用户消息到 Session JSONL，然后记录：

```text
TraceEvent(event_type="user")
Evidence(evidence_type="note")
```

### 9.2 Tool Call / Tool Result 如何生成 Evidence

工具调用会记录为：

```text
TraceEvent(event_type="tool_call")
Evidence(evidence_type="code_snippet")
```

工具结果会记录为：

```text
TraceEvent(event_type="tool_result")
Evidence(evidence_type="command_output" 或 "error_log")
```

### 9.3 Assistant Reply 如何记录

助手最终回复会记录为：

```text
TraceEvent(event_type="assistant")
Evidence(evidence_type="note")
```

这让一次完整对话的用户输入、模型输出、工具执行和结果都进入 Tree Memory 执行轨迹。

### 9.4 Runtime Recall 与 AgentRunner 的关系

Runtime Recall 发生在 AgentRunner 真正生成回复之前。

流程是：

```text
append user message
-> build Runtime Recall
-> build Working Set
-> rebuild system prompt
-> AgentRunner.step(...)
```

为了测试稳定性，当前实现会识别测试 fake client，避免 Runtime Recall 消耗 AgentRunner 的测试回复队列。

## 10 CLI 与 API

### 10.1 CLI Memory Actions

当前 CLI 支持：

```text
/memory
/memory add TYPE CONTENT
/memory delete ID
/memory fold
/memory retrieve QUERY
/memory promote FOLD_ID --type pattern
/memory evidence EVIDENCE_ID
/memory rollback FOLD_ID
/memory status
```

其中：

- `/memory fold` 把最近 trace events 折叠成 FoldedNode。
- `/memory retrieve` 检索 Tree Memory。
- `/memory promote` 晋升 Long-term Knowledge。
- `/memory evidence` 查看原始证据。
- `/memory rollback` 生成回滚计划。
- `/memory status` 查看当前树的记忆状态。

### 10.2 HTTP API Memory Actions

当前 server 新增：

```text
POST /api/memory/fold
POST /api/memory/retrieve
POST /api/memory/promote
GET  /api/memory/evidence/{id}
POST /api/memory/rollback-plan
GET  /api/memory/status
```

这些接口用于前端或外部工具调用 Memory Actions。

### 10.3 Memory Tab 数据结构

`/api/workspace` 中继续返回：

```text
treeMemoryItems
longTermKnowledgeItems
```

但 Tree Memory item 现在会包含更多 TGM 3.0 字段：

```text
foldId
evidenceIds
reuseCount
confidence
status
promoted
```

Long-term Knowledge item 会包含：

```text
sourceTreeId
sourceFoldId
sourceMemoryId
sourceEvidenceIds
confidence
status
```

## 11 存储目录总览

### 11.1 data/tree_memory/{tree_id}/

Tree Memory 每棵树一个目录：

```text
data/tree_memory/{tree_id}/
├─ trace_events.jsonl
├─ folded_nodes.jsonl
├─ memory_index.jsonl
├─ tree_state.json
├─ evidence_index.jsonl
└─ evidence/
```

### 11.2 data/knowledge/

Long-term Knowledge 使用 Markdown + graph：

```text
data/knowledge/
├─ MEMORY.md
├─ memories/
├─ graph/
└─ promotion_log.jsonl
```

### 11.3 data/sessions/

SessionTree 和 Session 消息仍然由 `TreeSessionManager` 和 `WorkspaceStore` 管理，消息源文件位于：

```text
data/sessions/{tree_id}/tree.json
data/sessions/{tree_id}/sessions/{session_id}.jsonl
```

### 11.4 不再使用的 TGM2.0 主路径

TGM 3.0 新写入不再使用：

```text
data/tree_memory/{tree_id}.jsonl
```

旧路径不作为新主路径，也不作为 TGM 3.0 文档中的核心结构。

## 12 示例 walkthrough

### 12.1 “继续修一个”：从意图到证据召回

用户说：

```text
继续修一个
```

Runtime Recall 不应只按字面搜索“继续修一个”，而应先生成检索意图：

```text
查找最近的 partial_fix
查找失败状态的 FoldedNode
查找相关 error_log 或 test_result Evidence
```

然后召回：

```text
FoldedNode: Parser partial failure
Evidence: Traceback: parser failed
ContextPacket: 当前需要继续修 parser 失败分支
```

这体现了 TGM 3.0 的 LLM-first retrieval intent。

### 12.2 失败修复的 rollback plan

当某个 FoldedNode 状态为 `partial` 或 `failed`，可以执行：

```text
/memory rollback <fold_id>
```

系统会返回：

```text
related_files
evidence_refs
suggested_steps
risk
```

注意：rollback plan 是建议，不会自动修改文件。

### 12.3 FoldedNode 晋升为 pattern 长期知识

一个稳定结论：

```text
Parser failures should be reproduced with a narrow test first.
```

可以从 FoldedNode 晋升为：

```text
mem://pattern/...
```

同时写入：

```text
memories/pattern/*.md
graph/nodes.jsonl
graph/edges.jsonl
promotion_log.jsonl
```

这让“修 parser 失败”的经验变成跨任务复用的模式。

### 12.4 用户画像 / reference 的可追溯写入

特殊记忆类型仍然先写 Tree Memory，再写 Long-term Knowledge。

例如：

```text
memory_type=user_profile
content=用户喜欢 Python
```

结果是：

```text
Tree Memory: FoldedNode 存在
Long-term Knowledge: mem://user/... 存在
source_tree_id/source_fold_id/source_evidence_ids 可追溯
```

这保证长期用户画像不是无来源写入，而是可追溯到当前树内的一次记忆动作。

## 13 测试与验收

### 13.1 Tree Memory 存储测试

`tests/test_tgm3_memory.py` 覆盖：

- TraceEvent 写入。
- Evidence 写入。
- FoldedNode 写入。
- memory_index 写入。
- evidence 文件路径正确。

### 13.2 Runtime Recall 测试

测试验证：

- LLM Coarse Reasoning 生效。
- LLM RetrievalIntent 生效。
- 能命中 `partial_fix` FoldedNode。
- 能加载 Evidence Snippet。
- 最终 ContextPacket 包含 Tree Memory 与 Evidence。

### 13.3 Long-term Knowledge 晋升测试

测试验证：

- FoldedNode 能晋升为 `mem://pattern/...`。
- Markdown 文件生成。
- graph node 写入。
- graph edge 写入。
- promotion log 写入。

### 13.4 CLI / API 测试

现有测试覆盖 CLI 的基础 memory 命令和 TGM 兼容行为。

建议后续继续补充：

- `/memory fold`
- `/memory retrieve`
- `/memory promote`
- `/memory rollback`
- `/api/memory/*`

## 14 TGM 3.0 相比 TGM 2.0 的变化

### 14.1 从 Memory Item 到 Execution Memory

TGM 2.0：

```text
Tree Memory = 可复用经验条目
```

TGM 3.0：

```text
Tree Memory = TraceEvent + Evidence + FoldedNode + MemoryIndex
```

### 14.2 从 Top-K 拼接到 ContextPacket

TGM 2.0 更接近：

```text
query -> Tree Top-K + Long-term Top-K -> 拼接上下文
```

TGM 3.0 变成：

```text
query
-> Coarse Reasoning
-> RetrievalIntent
-> Tree Memory
-> Evidence Snippet
-> Long-term Knowledge
-> ContextPacket
```

### 14.3 从长期记忆条目到知识图谱

TGM 2.0 的长期知识主要是 Markdown 条目。

TGM 3.0 增加：

```text
KnowledgeNode
KnowledgeEdge
promotion_log
pattern 类型
```

长期知识开始具备关系、来源和演化记录。

### 14.4 从“记住内容”到“管理证据”

TGM 3.0 的核心不是让 Agent 记住更多，而是让 Agent 能管理自己的历史：

- 哪些历史值得折叠。
- 哪些证据支持当前判断。
- 哪些经验可以复用。
- 哪些知识可以晋升。
- 哪些失败可以回滚。

## 15 一句话总结

TGM 3.0 把 PrismX 的记忆系统从“树内经验条目 + 长期知识条目”升级为“可折叠、可验证、可回滚、可晋升、可追溯的 Tree-Guided Memory 执行记忆系统”。

它的关键不是记住更多内容，而是让 Agent 知道：

```text
什么时候查历史
应该查哪段历史
依据什么证据判断
如何把经历折叠为经验
如何把经验晋升为长期知识
```

