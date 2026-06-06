# PrismX Tree-Guided Memory 2.0 设计方案

# 1. 设计背景

PrismX 的目标不是做一个普通的聊天分支系统，而是做一个能够长期协作、分支探索、经验复用的 Tree-Guided Memory Agent。

传统 AI Agent 在长任务中通常面临三个问题：

- 上下文线性堆叠，越聊越长，难以表达任务分支。
- 分支之间彼此隔离，一个分支得到的经验很难被兄弟分支复用。
- 长期记忆容易被临时信息污染，缺少清晰的晋升规则和来源追溯。

TGM 2.0 的核心改动是重新划清三层记忆的职责：

```text
Active Path Context
=
纵向继承

Tree Memory
=
树内横向共享

Long-term Knowledge
=
跨树、跨项目长期复用
```

也就是说，PrismX 不把所有内容都塞进长期记忆，也不把兄弟分支的原始聊天记录直接混入当前分支，而是通过 Tree Memory 和 Long-term Knowledge 形成有层次的经验流动。

------

# 2. TGM 2.0 核心思想

TGM 2.0 可以概括为：

```text
TGM 2.0
=
TreeSession
+
Active Path Context
+
Tree Memory
+
Long-term Knowledge
+
Runtime Recall
```

其中：

- TreeSession 负责把任务组织成 Session Tree。
- Active Path Context 负责当前 Session 从 root 到 current 的纵向上下文继承。
- Tree Memory 负责当前 Session Tree 内不同分支之间的经验共享。
- Long-term Knowledge 负责跨 Session Tree、跨项目、跨长期任务的稳定知识复用。
- Runtime Recall 负责在每次 Agent 推理前动态检索三层上下文，并组成 Working Context。

TGM 2.0 的关键原则是：

```text
所有长期知识必须可追溯到 Tree Memory。
```

也就是说，Long-term Knowledge 不能凭空产生。它必须来自某条 Tree Memory，并记录：

```text
source_tree_id
source_memory_id
```

这样可以避免长期记忆污染，也让知识晋升路径可解释、可调试、可审计。

------

# 3. TreeSession 与 Active Path Context

PrismX 当前的树节点不是单条 message，而是一个完整的 Session。

一个 Session Tree 可以表示为：

```text
数据结构与算法
├── 最小生成树总览
│   ├── Prim 算法
│   ├── Kruskal 算法
│   └── 例题讲解
└── 图算法复习计划
```

每个节点都是一个 SessionNode，每个 SessionNode 对应一个真实后端 Session。消息历史保存在该 Session 自己的 JSONL 记录中。

当用户位于 `Kruskal 算法` Session 时，系统会沿父链向上收集路径：

```text
数据结构与算法
-> 最小生成树总览
-> Kruskal 算法
```

这条路径就是 Active Path。

Active Path Context 解决的是：

```text
父节点知识如何传给子节点？
```

它不会读取兄弟分支的原始聊天记录。例如 `Kruskal 算法` 不会自动继承 `Prim 算法` 分支里的完整对话。

------

# 4. Tree Memory：树内经验池

Tree Memory 是 TGM 2.0 的核心层。

它不是：

- 聊天记录
- Session
- 工具输出全集
- 长期知识库

它是：

```text
当前 Session Tree 的经验池
```

Tree Memory 解决的是：

```text
兄弟分支之间如何共享经验？
```

例如：

```text
最小生成树总览
├── Prim 算法
└── Kruskal 算法
```

`Prim 算法` 分支中得到结论：

```text
最小生成树适用于连通无向图；Prim 更适合稠密图。
```

这条信息不应该作为 `Prim` 的原始聊天记录直接塞给 `Kruskal`，但它可以沉淀为 Tree Memory。之后 `Kruskal` 分支 Runtime Recall 时，可以通过 Tree Memory 召回该结论。

这就是：

```text
树内横向共享
```

------

# 5. Tree Memory 存储结构

Tree Memory 存储位置：

```text
data/tree_memory/{tree_id}.jsonl
```

每条 Tree Memory 是一个 `TreeMemoryItem`。

核心字段：

```text
id
tree_id

title
content

memory_type
tags

confidence
reuse_count

status
promoted

created_at
updated_at

source_session_id
source_branch
source_entry_id

metadata
```

URI 形式：

```text
tree://{tree_id}/memory/{memory_id}
```

允许的 `memory_type`：

```text
decision
constraint
finding
conclusion
todo
hypothesis
discarded_option
fact
```

其中 `fact` 用于保存明确事实，例如：

```text
暗号123123
```

它默认仍只是 Tree Memory，不会因为是事实就自动进入长期记忆。

------

# 6. Tree Memory 生命周期

Tree Memory 的生命周期包括：

```text
写入
-> 检索复用
-> 晋升
-> 归档/废弃
```

## 6.1 写入

Tree Memory 可以来自：

- 用户显式命令
- Agent `remember` 工具
- CLI `/memory add TYPE CONTENT`
- 后续自动抽取器

普通记忆默认只进入 Tree Memory。

例如：

```text
记住暗号123123
```

结果是：

```text
Tree Memory 存在
Long-term Knowledge 不存在
```

因为这条信息虽然是事实，但还没有证明它需要跨树、跨项目长期复用。

## 6.2 检索复用

Tree Memory 检索使用 Top-K Retrieval。

默认：

```text
Top 5
```

评分因素包括：

```text
Query Match
+
Tag Match
+
Memory Type
+
Confidence
+
Reuse Count
```

每次 Runtime Recall 命中 Tree Memory 后：

```text
reuse_count += 1
```

这让系统能够识别哪些经验真的被反复使用。

## 6.3 晋升

Tree Memory 满足以下条件之一时，可以晋升为 Long-term Knowledge：

```text
confidence >= 0.85
```

或：

```text
reuse_count >= 3
```

或：

```text
Knowledge Compiler 判定值得长期保留
```

晋升后：

```text
status = promoted
promoted = true
```

同时生成对应 Long-term Knowledge。

## 6.4 归档与废弃

Tree Memory 可以被标记为：

```text
active
archived
promoted
discarded
```

含义：

- `active`：当前可检索、可复用。
- `archived`：保留记录，但不参与主要召回。
- `promoted`：已经晋升为长期知识。
- `discarded`：明确废弃的经验或方案。

------

# 7. Long-term Knowledge：可追溯长期知识

Long-term Knowledge 负责跨树、跨项目、跨长期任务的稳定知识复用。

TGM 2.0 中，长期知识只保存四类信息：

```text
user
feedback
project
reference
```

含义：

- `user`：用户画像，例如用户身份、长期目标、稳定背景。
- `feedback`：用户偏好与行为反馈，例如输出偏好、工具偏好。
- `project`：项目动态、项目决策、稳定约束。
- `reference`：外部参考、文档链接、图片、资料指针。

长期知识的核心规则是：

```text
任何 Long-term Knowledge 都必须能追溯到 Tree Memory。
```

因此每条长期知识必须包含：

```text
source_tree_id
source_memory_id
```

这意味着长期知识不是直接从用户消息凭空生成的，而是从当前树内已经沉淀过的 Tree Memory 晋升而来。

------

# 8. Long-term Knowledge 存储结构

Long-term Knowledge 存储位置：

```text
data/knowledge/
```

当前 TGM 2.0 使用轻量 Markdown 存储结构：

```text
data/knowledge/
├── MEMORY.md
└── memories/
    ├── user/
    ├── feedback/
    ├── project/
    └── reference/
```

`MEMORY.md` 是长期记忆索引，只保留摘要信息：

```markdown
# Long-term Memory Index

## user
- ...

## feedback
- ...

## project
- ...

## reference
- ...
```

长期记忆正文存储在：

```text
data/knowledge/memories/{type}/{id}.md
```

每条长期记忆文件包含 frontmatter：

```yaml
---
id:
name:
description:
type:
source_tree_id:
source_memory_id:
created_at:
updated_at:
confidence:
status:
tags:
---
```

正文部分保存完整内容。

TGM 2.0 不再把旧的 `wiki/`、`context/`、`semantic_index.jsonl`、`memory_graph` 作为新长期记忆写入主路径。

------

# 9. 特殊类型的双层写入

普通记忆默认只写 Tree Memory。

但是有些信息虽然刚出现一次，也具有长期意义：

```text
user_profile
user_feedback
project_state
reference
```

这些类型采用双层写入：

```text
先写 Tree Memory
再由该 Tree Memory 生成 Long-term Knowledge
```

映射关系：

```text
user_profile  -> user
user_feedback -> feedback
project_state -> project
reference     -> reference
```

这样既满足：

```text
当前树内可见、可复用
```

也满足：

```text
长期知识可追溯来源
```

例如：

```text
用户喜欢 Python
```

如果被标记为 `user_profile`，则结果是：

```text
Tree Memory
存在 special 条目

Long-term Knowledge
存在 user 类型条目

source_tree_id
指向当前 tree

source_memory_id
指向刚写入的 Tree Memory
```

------

# 10. Runtime Recall 三层检索

Runtime Recall 在每次 Agent 推理前执行。

顺序固定为：

```text
Active Path Context
↓
Tree Memory
↓
Long-term Knowledge
```

## 10.1 Active Path Retrieval

从当前 Session 沿父链回溯到 root：

```text
Root Session
-> Parent Session
-> Current Session
```

这部分解决纵向继承。

## 10.2 Tree Memory Retrieval

检索当前 active tree 的：

```text
data/tree_memory/{tree_id}.jsonl
```

默认取：

```text
Top 5
```

这部分解决树内横向共享。

## 10.3 Long-term Knowledge Retrieval

先读取：

```text
data/knowledge/MEMORY.md
```

基于：

```text
name
description
type
tags
```

筛选 Top-K，默认：

```text
Top 5
```

然后加载对应：

```text
data/knowledge/memories/{type}/{id}.md
```

这部分解决跨树、跨项目复用。

Runtime Recall 不会把全部 Tree Memory 或全部 Long-term Knowledge 塞给模型。

------

# 11. Working Context 构建

最终进入模型的上下文称为 Working Context。

结构为：

```text
Working Context
=
Active Path Context
+
Tree Memory Recall
+
Long-term Knowledge Recall
+
Current Session State
```

其中：

- Active Path Context 保证当前任务继承父路径目标和约束。
- Tree Memory Recall 保证兄弟分支经验可以被当前分支复用。
- Long-term Knowledge Recall 保证稳定知识可以跨树、跨项目复用。
- Current Session State 保证模型知道当前 Session 的最新消息和状态。

Working Context 是动态构建的，不是一个静态大 prompt。

------

# 12. TGM 2.0 存储结构总览

TGM 2.0 的运行数据主要位于：

```text
data/
```

## 12.1 Workspace 与 Session Tree

```text
data/workspace.json
data/sessions/{tree_id}/tree.json
data/sessions/{tree_id}/sessions/{session_id}.jsonl
```

保存：

- Project
- Session Tree
- SessionNode parent/child 关系
- 每个 Session 的消息历史

## 12.2 Tree Memory

```text
data/tree_memory/{tree_id}.jsonl
```

保存当前树内经验：

- decision
- constraint
- finding
- conclusion
- todo
- hypothesis
- discarded_option
- fact

## 12.3 Long-term Knowledge

```text
data/knowledge/MEMORY.md
data/knowledge/memories/user/
data/knowledge/memories/feedback/
data/knowledge/memories/project/
data/knowledge/memories/reference/
```

保存跨树、跨项目长期知识。

------

# 13. TGM 2.0 生命周期闭环

完整生命周期如下：

```text
Session Message
↓
Tree Memory
↓
Runtime Recall Reuse
↓
reuse_count 增长
↓
Knowledge Promotion
↓
Long-term Knowledge
↓
Future Runtime Recall
↓
Working Context
↓
Agent Reasoning
```

也可以理解为：

```text
任务执行
-> 经验沉淀
-> 树内复用
-> 稳定知识晋升
-> 跨树复用
```

这形成了一个从任务经历到知识复用的闭环。

------

# 14. 示例

## 14.1 暗号示例

用户说：

```text
记住暗号123123
```

默认结果：

```text
Tree Memory
存在 fact/finding 条目

Long-term Knowledge
不存在
```

原因是：

```text
普通记住不等于直接长期化。
```

如果后续多次召回：

```text
reuse_count >= 3
```

则该 Tree Memory 可以晋升为 Long-term Knowledge。

## 14.2 用户画像示例

用户说：

```text
用户喜欢 Python
```

如果 Agent 或 CLI 将其标记为：

```text
user_profile
```

结果：

```text
Tree Memory
存在

Long-term Knowledge
存在 user 类型条目
```

长期条目包含：

```text
source_tree_id
source_memory_id
```

因此仍然可以追溯到原始 Tree Memory。

## 14.3 Prim / Kruskal 经验迁移

Session Tree：

```text
最小生成树总览
├── Prim 算法
└── Kruskal 算法
```

`Prim 算法` 分支沉淀 Tree Memory：

```text
最小生成树适用于连通无向图；Prim 更适合稠密图。
```

切换到 `Kruskal 算法` 分支后：

- Active Path 不包含 Prim 原始聊天记录。
- Tree Memory Recall 可以命中该结论。
- Agent 能用该结论比较 Prim 与 Kruskal 的适用场景。

这体现了：

```text
不污染分支上下文
但共享树内经验
```

------

# 15. 一句话总结

PrismX TGM 2.0 是一套分层认知架构：它用 Active Path Context 实现纵向继承，用 Tree Memory 实现树内横向经验共享，用可追溯的 Long-term Knowledge 实现跨树、跨项目长期复用，并通过 Runtime Recall 动态构建 Agent 每次推理所需的 Working Context。
