# PrismaX 源码导读

## 1. 项目整体说明

PrismaX 是一个本地运行的长期认知型 Agent 框架，核心目标是把智能体的运行上下文从“线性聊天历史”升级为“Tree-Guided Memory（TGM，树引导记忆）”。当前代码已经具备命令行 Agent、Web 工作台、工具调用、MCP 工具接入、TreeSession 会话树、Active Branch Context、Working Set、上下文压缩、结构化长期记忆、Wiki-style Knowledge Base、本地语义索引、运行时召回、一次性子代理和持久 TeamMate 等能力。

需要注意：当前实现是一个可运行的工程版本，不是技术报告书中所有概念的完全体。很多 TGM 能力已经有骨架和主链路，例如 `sessiontrees/*.jsonl`、`CompactionEntry`、`ContextFS`、`MemoryGraph`、`WikiKnowledgeBase`、`WorkingSetBuilder`；但部分能力仍是轻量实现，例如 Branch-safe Recall 还主要是排序策略，不是完整策略引擎。

## 2. 项目目录总览

```text
project-root/
├── src/
│   └── prismax/              # PrismaX 主源码包
├── tests/                    # 单元测试与集成测试
├── memory/                   # 运行时长期记忆、上下文对象、Wiki 知识库和 token 日志
├── sessiontrees/                 # 运行时 TreeSession JSONL 会话树，首次运行后生成
├── docs/                     # 项目文档、源码说明、历史设计文档
├── frontend/                 # 本地 Web 工作台静态前端
├── templates/                # 主 Agent 和子 Agent prompt 模板
├── skills/                   # Skill 目录，按 SKILL.md 加载
├── mcp_servers.json          # MCP server 配置
├── pyproject.toml            # Python 项目配置和命令入口
├── run.sh                    # CLI 启动脚本
├── run_web.sh                # Web 工作台启动脚本
└── README.md                 # 项目快速说明
```

顶级目录职责：

| 目录/文件 | 作用 |
|---|---|
| `src/prismax/` | Agent Runtime、会话树、记忆系统、工具系统、MCP、多智能体等核心代码。 |
| `tests/` | 覆盖 TreeSession、Memory OS、Runtime Context、Agent Loop、TGM 新增能力等行为。 |
| `memory/` | 运行生成的长期记忆、ContextFS 索引、MemoryGraph 链接、Wiki 知识页和 token 日志。 |
| `docs/` | 面向开发者、接口、测试方案和历史方案的文档。 |
| `frontend/` | Web 工作台页面、样式和前端脚本。 |
| `templates/` | system prompt、用户画像、子 Agent 角色模板。 |
| `skills/` | 可加载技能，目前包含 `summarize` 示例技能。 |

## 3. 程序运行入口

### CLI 入口

| 项 | 内容 |
|---|---|
| 打包命令 | `prismax = "prismax.cli:main"`，定义在 `pyproject.toml` |
| 入口文件 | `src/prismax/cli.py` |
| 核心函数 | `main()` |
| 应用装配 | `AgentApp`，定义在 `src/prismax/loop.py` |

CLI 启动流程：

```text
uv run prismax
→ src/prismax/cli.py::main()
→ 创建 AgentApp
→ 初始化模型客户端、MemoryStore、TreeSessionManager、ToolRegistry、MCP、Team、RuntimeContextBuilder
→ 进入 input("你> ") 循环
→ Slash Command 直接执行，普通文本交给 AgentApp.ask()
```

### Web 入口

| 项 | 内容 |
|---|---|
| 打包命令 | `prismax-web = "prismax.server:main"`，定义在 `pyproject.toml` |
| 入口文件 | `src/prismax/server.py` |
| 核心函数 | `main()` |
| Web 适配 | `src/prismax/web_adapter.py` |

Web 工作台复用 `AgentApp` 应用层，通过 HTTP/SSE 暴露聊天流、会话树、上下文、工具、MCP 和 team 状态。

### `AgentApp` 初始化流程

`src/prismax/loop.py::AgentApp.__init__()` 负责装配核心模块：

1. `load_dotenv()` 读取 `.env`。
2. `build_model_client()` 创建模型客户端。
3. `MemoryStore` 初始化 `memory/`。
4. `TokenLog` 初始化 `memory/tokens.jsonl`。
5. `SkillsLoader` 加载 `skills/`。
6. `MessageBus` 和 `TeammateManager` 初始化多智能体通信。
7. `MCPClientManager` 读取 `mcp_servers.json` 并启动 MCP。
8. `TreeSessionManager` 初始化 `sessiontrees/*.jsonl`。
9. `_build_registry()` 注册内置工具、MCP 工具、Team 工具、Context 工具和 `dispatch_subagent`。
10. `SessionMemoryCommitter` 连接 compaction 和长期记忆。
11. `RuntimeContextBuilder` 与 `WorkingSetBuilder` 准备每轮上下文构建。
12. `AgentRunner` 准备模型与工具调用循环。

## 4. Agent Runtime 源码说明

| 功能 | 代码路径 | 核心函数/类 | 作用说明 |
|---|---|---|---|
| 用户输入接收 | `src/prismax/cli.py` | `main()` | CLI 中读取用户输入，识别 Slash Command 或转给 `AgentApp.ask()`。 |
| 应用装配 | `src/prismax/loop.py` | `AgentApp` | 统一管理模型、工具、会话树、记忆、MCP、team 和上下文构建。 |
| 普通对话入口 | `src/prismax/loop.py` | `AgentApp.ask()` | 写入用户消息、构建 Runtime Recall 与 Working Set、调用 Runner。 |
| Working Set 构建 | `src/prismax/working_set.py` | `WorkingSetBuilder.build()` | 从 active branch、todo、最近工具结果、episode 摘要和召回结果生成工作集。 |
| System Prompt 构造 | `src/prismax/context.py` | `ContextBuilder.build()` | 把 workspace、skills、memory、user profile、runtime context 渲染进 prompt。 |
| LLM 调用 | `src/prismax/runner.py` | `AgentRunner.step()` | 调用 `client.create_message()` 或 `client.stream_message()`。 |
| Tool Call 解析 | `src/prismax/runner.py` | `AgentRunner.step()` | 从模型返回的 `message.content` 中筛出 `tool_use` block。 |
| Tool 执行 | `src/prismax/runner.py` | `_execute_tool_blocks()` | 通过 `ToolRegistry.execute()` 执行工具，支持安全工具并行。 |
| Tool Result 回注 | `src/prismax/runner.py`、`src/prismax/loop.py` | `on_tool_result` 回调 | 工具结果作为 user message 继续喂给模型，并写入 TreeSession。 |
| 多轮循环 | `src/prismax/runner.py` | `AgentRunner.step()` | 直到模型 `stop_reason != "tool_use"` 或达到 `max_turns`。 |
| 中间状态保存 | `src/prismax/tree_session.py` | `append_message()`、`append_tool_call()`、`append_tool_result()` | 用户消息、assistant 消息、工具调用、工具结果写入 JSONL 会话树。 |

核心数据流在 `AgentApp.ask()` 中：

```text
用户输入
→ tree.append_message()
→ TreeSession append-only event log
→ tree.debugBuildModelContext()
→ runtime_context_builder.build()
→ working_set_builder.build()
→ ContextBuilder.build()
→ runner.step()
→ on_assistant_message / on_tool_call / on_tool_result 回写 TreeSession
→ 返回最终回复
```

## 5. Slash Command 系统源码说明

Slash Command 当前集中写在 `src/prismax/cli.py::main()` 的输入循环中。它不是独立 parser，而是通过一组 `if user_input ...` 判断直接分发。

| 命令 | 代码位置 | 核心函数 | 功能说明 |
|---|---|---|---|
| `/help` | `src/prismax/cli.py` | `HELP`、`main()` | 打印命令帮助。 |
| `/tools` | `src/prismax/cli.py` | `app.registry.names()` | 列出当前注册工具。 |
| `/todos` | `src/prismax/cli.py` | `app.todos.render()` | 显示当前 todo 状态。 |
| `/memory` | `src/prismax/cli.py` | `app.memory.render_memory()` | 显示结构化长期记忆和 legacy MEMORY。 |
| `/context` | `src/prismax/cli.py` | `app.working_context_debug()`、`app.memory.list_context()` | 显示 Working Set 调试信息和最近 ContextObject。 |
| `/mcp` | `src/prismax/cli.py` | `app.mcp.report()` | 显示 MCP server 和工具状态。 |
| `/compact` | `src/prismax/cli.py` | `app.compact_now()` | 压缩当前 active branch，并触发记忆提交。 |
| `/team` | `src/prismax/cli.py` | `app.team.list_all()` | 查看持久 TeamMate 状态。 |
| `/inbox` | `src/prismax/cli.py` | `app.team_bus.read_inbox("lead")` | 读取并清空 lead inbox。 |
| `/tree` | `src/prismax/cli.py` | `app.tree_view()` | 渲染当前会话树。 |
| `/jump ID` | `src/prismax/cli.py` | `app.jump_to_entry()` | 把 active leaf 切换到历史节点。 |
| `/fork ID` | `src/prismax/cli.py` | `app.fork_from_entry()` | 选择分叉点，下一条输入形成兄弟分支。 |
| `/clone` | `src/prismax/cli.py` | `app.clone_active_branch()` | 克隆当前 active branch 到新 session。 |
| `/label ID LABEL` | `src/prismax/cli.py` | `app.label_entry()` | 给会话树节点追加标签。 |
| `/exit` | `src/prismax/cli.py` | `return` | 退出 CLI。 |

补充命令：代码中还支持 `/skills` 和 `/skill NAME`，用于列出和加载技能，但它们不在用户要求的最小命令清单内。

## 6. TreeSession 与会话树源码说明

TreeSession 的核心实现在 `src/prismax/tree_session.py`。

### 会话节点结构

基础节点类是 `SessionEntry`：

```python
@dataclass(kw_only=True)
class SessionEntry:
    type: EntryType
    id: str
    sessionId: str
    parentId: str | None
    timestamp: str
    metadata: dict[str, Any]
```

关键字段：

| 字段 | 说明 |
|---|---|
| `id` | 当前条目的唯一 ID。 |
| `parentId` | 父节点 ID，是树结构的核心。 |
| `sessionId` | 当前条目所属 session 文件。 |
| `timestamp` | 写入时间。 |
| `metadata` | 保存上下文层级、事件类型、来源分支等扩展信息。 |

主要条目类型：

| 类型 | 类 | 说明 |
|---|---|---|
| `session_info` | `SessionInfoEntry` | 会话元信息。 |
| `session_state` | `SessionStateEntry` | active leaf 变化，例如 jump、fork、resume。 |
| `message` | `MessageEntry` | 用户或 assistant 消息。 |
| `tool_call` | `ToolCallEntry` | 工具调用元数据。 |
| `tool_result` | `ToolResultEntry` | 工具结果。 |
| `branch_summary` | `BranchSummaryEntry` | 分支摘要。 |
| `compaction` | `CompactionEntry` | 上下文压缩摘要。 |
| `label` | `LabelEntry` | 节点标签。 |
| `context_layer` | `ContextLayerEntry` | 上下文层级覆盖。 |
| `raw` | `RawEntry` | 外部原始文件或日志引用。 |
| `custom` | `CustomEntry` | 自定义事件，目前用于 `knowledge_committed`。 |

### active branch 如何保存

`TreeSession` 内存结构维护：

```python
entries
entriesById
childrenByParent
labels
activeLeafId
rootId
```

`activeLeafId` 通过 `SessionStateEntry` append-only 写入，不覆盖旧记录。程序恢复时 replay JSONL，最后一次 state 生效。

### Active Branch Context 构建

`TreeSessionManager.getBranch(session_id, leaf_id=None)` 从当前 `activeLeafId` 开始沿 `parentId` 回溯到根，再反转为根到叶：

```text
activeLeafId
→ parentId
→ parentId
→ root
→ reverse
```

`buildModelContext()` 调用 `_build_context()`，只把 active branch 上可进入上下文的条目转为模型 messages。兄弟分支不会进入当前模型上下文。

### 会话树命令对应函数

| 命令/动作 | 函数 |
|---|---|
| `/tree` | `TreeSessionManager.render_tree()` |
| `/jump ID` | `TreeSessionManager.jumpToEntry()` |
| `/fork ID` | `TreeSessionManager.forkFromEntry()` |
| `/clone` | `TreeSessionManager.cloneActiveBranch()` |
| `/label ID LABEL` | `TreeSessionManager.addLabel()` |
| 写用户/助手消息 | `append_message()` |
| 写工具调用 | `append_tool_call()` |
| 写工具结果 | `append_tool_result()` |

### 持久化与恢复

持久化由 `JsonlSessionStorage` 负责：

| 函数 | 作用 |
|---|---|
| `append_line()` | 追加写入 `sessiontrees/{session_id}.jsonl`。 |
| `read_lines()` | 读取 JSONL 所有行。 |
| `listSessions()` | 列出 session 文件。 |

恢复逻辑在 `TreeSessionManager.loadSession()`：读取 JSONL 后逐行 `_entry_from_dict()`，再 `_apply_entry()` 重建索引、标签、active leaf 和上下文层级。

## 7. Working Set 与 Active Branch Context 源码说明

PrismaX 当前不是直接把全量历史拼给模型，而是使用 active branch 加运行时召回构造当前轮次上下文。

| 概念 | 当前代码对应 |
|---|---|
| 原始历史 | `sessiontrees/*.jsonl`，由 `TreeSessionManager` append-only 保存。 |
| Active Branch Context | `TreeSessionManager.getActiveBranch()`、`buildModelContext()`。 |
| Working Context | `WorkingSet`，定义在 `src/prismax/working_set.py`。 |
| Runtime Recall 注入内容 | `RuntimeContextBuilder.build()`，定义在 `src/prismax/context.py`。 |
| 最终 Working Set | `WorkingSetBuilder.build()` 产出后通过 `WorkingSet.render()` 注入 system prompt。 |

### 构建逻辑

`src/prismax/loop.py::AgentApp.ask()` 的顺序：

1. `tree.append_message()` 写入用户输入。
2. `tree.debugBuildModelContext()` 获取 active path 调试信息。
3. `runtime_context_builder.build()` 基于用户输入和 active branch scope 召回长期记忆。
4. `working_set_builder.build()` 汇总 active branch、todo、最近工具结果、episode 摘要和 recall 结果。
5. `ContextBuilder.build()` 把 `WorkingSet.render()` 注入 system prompt。
6. `tree.buildModelContext()` 构建当前 active branch messages。
7. `runner.step()` 调用模型和工具循环。

`WorkingSetBuilder.build()` 输入：

| 输入 | 来源 |
|---|---|
| `session_id` | 当前 `AgentApp.session_id`。 |
| `current_task` | 用户本轮输入。 |
| `task_state` | `TodoStore.render()`。 |
| `runtime_recall` | `RuntimeContextBuilder.build()` 输出。 |
| `recall_results` | `RuntimeContextBuilder.last_results`。 |

输出是 `WorkingSet`：

```python
session_id
active_leaf_id
active_branch_entry_ids
active_branch_context
current_task
task_state
recent_tool_result
episode_summaries
runtime_recall
recall_results
```

当前实现没有全量 history 拼接问题：模型 messages 由 `tree.buildModelContext()` 基于 active branch 构造。但 旧 `memory/history.jsonl` 已移除；TreeSession 是唯一原始对话事实源。

## 8. memory 文件夹详细说明

### memory 目录树

```text
memory/
├── semantic_index.jsonl
├── tokens.jsonl
├── tree/
├── context/
│   ├── diffs.jsonl
│   ├── index.jsonl
│   └── links.jsonl
└── Wiki/
    ├── Architecture/
    ├── Pattern/
    ├── Project/
    ├── Research/
    └── User/
```

`memory/` 由 `src/prismax/memory.py::MemoryStore`、`TreeMemoryStore` 和长期知识索引初始化。它不是 TreeSession 的唯一事实源；原始任务经历的主事实源是 `sessiontrees/*.jsonl`。`memory/` 主要负责 Tree Memory、长期知识、关系索引和召回索引。

旧线性文件 `memory/history.jsonl`、`memory/MEMORY.md`、`memory/compactions.md` 已删除。

### 8.1 `memory/tokens.jsonl`

#### 作用

记录模型 token 使用情况，用于判断是否需要压缩。

#### 核心文件

| 文件 | 作用 | 关键类/函数 |
|---|---|---|
| `memory/tokens.jsonl` | 记录 input/output token | `TokenLog.record()`、`should_compact()`、`stats_by_date()`、`stats_by_model()` |

#### 数据输入

来自 `AgentRunner` 的 `on_usage` 回调，实际由 `AgentApp` 传入 `self.tokens.record`。

#### 数据输出

写入模型名、输入 token、输出 token 和时间戳。

#### 与 TGM 的关系

辅助 Compaction 触发，不属于长期知识层。

### 8.2 `memory/tree/`

#### 作用

保存当前 TreeSession 内可横向共享的短期经验，URI 形如 `tree://{tree_id}/memory/{item_id}`。

#### 与 TGM 的关系

它对应 Tree Memory 层，解决同一棵会话树内 sibling branch 的经验共享问题。

#### 与 TGM 的关系

与 TGM 的 `CompactionEntry` 不同。TGM 当前主压缩记录在 `sessiontrees/*.jsonl` 的 `compaction` 条目中。

### 8.5 `memory/context/`

#### 作用

这是 ContextFS 与 MemoryGraph 的持久化目录，保存结构化上下文对象索引、变更记录和关系图谱。

#### 核心文件

| 文件 | 作用 | 关键类/函数 |
|---|---|---|
| `memory/context/index.jsonl` | ContextObject 索引 | `ContextFS._upsert_index()`、`list_objects()`、`search_objects()` |
| `memory/context/diffs.jsonl` | 记忆写入和变更记录 | `ContextFS.append_diff()` |
| `memory/context/links.jsonl` | URI 关系图谱 | `MemoryGraph.add_link()`、`neighbors()`、`expand()` |

#### 数据输入

来自：

- `MemoryStore.remember_note()`
- `MemoryStore.commit_session_archive()`
- `MemoryGraph.auto_link()`

#### 数据输出

输出可搜索、可读取、可链接的 ContextObject 和 URI 关系。

#### 与 TGM 的关系

- `index.jsonl` 对应 Semantic Knowledge Layer 的结构化索引。
- `links.jsonl` 对应 Relation Layer。
- `diffs.jsonl` 是长期记忆变更审计记录。

### 8.6 `memory/Wiki/`

#### 作用

Wiki-style Knowledge Base，把长期知识保存成可维护的 Markdown 页面。

#### 核心目录

| 目录 | 作用 | 关键类/函数 |
|---|---|---|
| `memory/Wiki/Project/` | 项目决策、约束、任务知识 | `WikiKnowledgeBase.write()` |
| `memory/Wiki/Architecture/` | 工具、技能、架构知识 | `WikiKnowledgeBase.write()` |
| `memory/Wiki/User/` | 用户偏好、画像、事件 | `WikiKnowledgeBase.write()` |
| `memory/Wiki/Pattern/` | 案例、模式、可复用经验 | `WikiKnowledgeBase.write()` |
| `memory/Wiki/Research/` | 调研知识 | `WikiKnowledgeBase.write()` |

#### 数据输入

来自 `MemoryStore.commit_session_archive()` 中的 memory extraction operations。每条 operation 会被转换成 `KnowledgeObject`。

#### 数据输出

输出 Markdown 知识页，内容包含 JSON front matter 风格元数据：

```text
title
summary
source_session
source_branch
source_compaction
trust_score
tags
updated_at
knowledge_type
```

#### 与 TGM 的关系

对应 Semantic Knowledge Layer。Wiki 负责“如何维护知识”，不是负责检索排序。

### 8.7 `memory/semantic_index.jsonl`

#### 作用

本地轻量 Semantic Vector Index。当前不是外部 embedding 向量数据库，而是基于 token overlap 的本地索引。

#### 核心文件

| 文件 | 作用 | 关键类/函数 |
|---|---|---|
| `memory/semantic_index.jsonl` | 本地语义索引 | `LocalSemanticVectorIndex.upsert()`、`search()` |

#### 数据输入

来自 `MemoryStore.commit_session_archive()` 写入 Wiki 后的 `LocalSemanticVectorIndex.upsert()`。

#### 数据输出

输出可被 `MemoryStore.search_memory()` 合并召回的知识结果，包含 `source_session`、`source_branch`、`source_compaction`、`trust_score`、`knowledge_type` 和 `wiki_path`。

#### 与 TGM 的关系

对应 Semantic Knowledge Layer 中的“如何找到知识”。当前是轻量本地实现，无外部 embedding。

### 8.8 memory 数据流

```text
/compact
→ TreeSessionManager.compactActiveBranch()
→ CompactionEntry 写入 sessiontrees/*.jsonl
→ SessionMemoryCommitter.commit_compaction()
→ MemoryStore.commit_session_archive()
→ ContextFS 写 session archive 和 memory object
→ WikiKnowledgeBase 写 Markdown 知识页
→ LocalSemanticVectorIndex 更新 semantic_index.jsonl
→ MemoryGraph 写 derived_from / related 等关系
→ RuntimeContextBuilder 后续可召回
```

## 9. Experience Replay Event Log 源码说明

当前 Event Log 的主实现是 `sessiontrees/*.jsonl`，不是独立事件数据库。每一行都是 append-only JSON。

### 事件结构

事件基础字段来自 `SessionEntry`：

```text
type
id
sessionId
parentId
timestamp
metadata
```

TGM 事件语义保存在 `metadata.eventType`，并由 `ExperienceEvent` 视图统一暴露。

### 事件类型

定义在 `src/prismax/tree_session.py`：

| 事件常量 | 含义 |
|---|---|
| `message_appended` | 写入用户或 assistant 消息。 |
| `tool_called` | 写入工具调用。 |
| `tool_result_recorded` | 写入工具结果。 |
| `branch_jumped` | active leaf 跳转。 |
| `branch_forked` | 从历史节点分叉。 |
| `branch_cloned` | 克隆 active branch。 |
| `branch_labeled` | 给节点打标签。 |
| `compaction_created` | 生成压缩摘要。 |
| `knowledge_committed` | 长期知识提交完成。 |
| `session_resumed` | 恢复会话。 |

### 写入位置

| 模块 | 写入函数 |
|---|---|
| `TreeSessionManager` | `append_message()`、`append_tool_call()`、`append_tool_result()`、`appendKnowledgeCommit()` |
| `JsonlSessionStorage` | `append_line()` |
| `AgentApp` | 在 `ask()` 回调中调用 TreeSession 写入函数 |
| `SessionMemoryCommitter` | knowledge commit 后调用 `appendKnowledgeCommit()` |

### replay 恢复逻辑

`TreeSessionManager.loadSession()`：

```text
read_lines()
→ _entry_from_dict()
→ _apply_entry()
→ 重建 entriesById / childrenByParent / labels / activeLeafId / contextLayer
```

它可以恢复 TreeSession、active leaf、标签、分支路径、compaction 和 knowledge commit 记录。当前还没有独立任务状态机 replay，例如 todo 状态仍在内存 `TodoStore` 中，不从 Event Log 完整恢复。

## 10. Compaction 与 Episode Memory 源码说明

### `/compact` 调用链

```text
src/prismax/cli.py
→ app.compact_now()
→ AgentApp._compact_active_branch()
→ TreeSessionManager.compactActiveBranch()
→ SessionMemoryCommitter.commit_compaction()
→ MemoryStore.commit_session_archive()
```

### 触发条件

- 用户显式执行 `/compact`。
- `AgentApp.ask()` 末尾会根据 `TokenLog.should_compact()` 尝试自动压缩。
- 旧 `HistoryCompactor` 已删除；TGM 只使用 TreeSession compaction。

### 输入上下文来源

`compactActiveBranch()` 使用当前 active branch，并通过 `_entries_after_latest_compaction()` 避免重复压缩旧摘要。

### 摘要生成逻辑

摘要由 `SummarizerProtocol` 抽象，生产环境使用 `LlmSummarizer`，测试可使用 `FakeSummarizer`。提示词常量包括：

- `SUMMARIZATION_SYSTEM_PROMPT`
- `SUMMARIZATION_PROMPT`
- `UPDATE_SUMMARIZATION_PROMPT`
- `BRANCH_SUMMARY_PROMPT`

### CompactionEntry 存储位置

`CompactionEntry` 追加写入 `sessiontrees/{session_id}.jsonl`，字段包括：

```text
summary
compactedEntryIds
firstKeptEntryId
tokenEstimateBefore
tokenEstimateAfter
metadata.eventType = compaction_created
```

### BranchSummary

`TreeSessionManager.createBranchSummary()` 支持生成 `BranchSummaryEntry`。它会收集旧分支相对共同祖先的内容，生成摘要后挂到目标节点下。

### 是否触发 Knowledge Extraction

`/compact` 会触发 `SessionMemoryCommitter.commit_compaction()`，再由 `LlmMemoryExtractor.extract()` 生成长期记忆 operations。之后 `MemoryStore.commit_session_archive()` 写入 ContextFS、Wiki、semantic index 和 MemoryGraph。

## 11. Semantic Knowledge 与 Wiki Knowledge Base 源码说明

### 长期知识对象结构

`src/prismax/knowledge.py::KnowledgeObject`：

```text
title
summary
content
source_session
source_branch
source_compaction
trust_score
tags
updated_at
knowledge_type
uri
```

### Markdown Wiki 保存路径

由 `WikiKnowledgeBase.write()` 写入：

```text
memory/Wiki/Project/{slug}.md
memory/Wiki/Architecture/{slug}.md
memory/Wiki/User/{slug}.md
memory/Wiki/Pattern/{slug}.md
memory/Wiki/Research/{slug}.md
```

目录映射由 `WIKI_BUCKETS` 控制。例如：

| category | Wiki 目录 |
|---|---|
| `decisions`、`constraints`、`open_tasks` | `Project` |
| `tools`、`skills` | `Architecture` |
| `profile`、`preferences`、`entities`、`events` | `User` |
| `cases`、`patterns` | `Pattern` |
| `research` | `Research` |

### 文件命名规则

`_slugify()` 会基于 operation 的 `key` 或知识标题生成文件名。非法字符会被移除，空白转为 `-`。

### 元数据结构

当前不是 YAML front matter，而是在 `---` 之间写入 JSON 元数据：

```text
---
{
  "title": "...",
  "summary": "...",
  "source_session": "...",
  "source_branch": "...",
  "source_compaction": "...",
  "trust_score": 0.8,
  "tags": [],
  "updated_at": "...",
  "knowledge_type": "project"
}
---
```

### 创建、更新、读取逻辑

| 行为 | 代码 |
|---|---|
| 创建/覆盖 Wiki 页面 | `WikiKnowledgeBase.write()` |
| 更新 semantic index | `LocalSemanticVectorIndex.upsert()` |
| 搜索长期知识 | `MemoryStore.search_memory()` 合并 `ContextFS.search_objects()` 和 `LocalSemanticVectorIndex.search()` |
| 读取 ContextFS 对象 | `MemoryStore.read_context()` |

当前 Wiki 页面本身没有专门的读取 API，召回入口主要通过 ContextFS 和 semantic index。

## 12. Runtime Recall 与 Branch-safe Recall 源码说明

### Recall 入口函数

`src/prismax/context.py::RuntimeContextBuilder.build()`。

### Query 如何构造

当前 query 直接使用本轮用户输入：

```python
runtime_context_builder.build(user_input, recall_scope={...})
```

`recall_scope` 来自 `AgentApp.ask()`：

```text
session_id
active_branch_entry_ids
project
```

### 从哪些知识源召回

`RuntimeContextBuilder` 调用 `LocalContextBackend.search()`，再进入 `MemoryStore.search_memory()`，合并：

1. `ContextFS.search_objects()`
2. `LocalSemanticVectorIndex.search()`

### 是否使用 source_session / source_branch / source_compaction / trust_score

当前排序使用：

- `source_session`
- `source_branch`
- `trust_score`
- `knowledge_type`
- `project`
- URI scope，例如 `mem://project/`、`mem://user/`

`source_compaction` 会保存在 semantic index 和 metadata 中，但当前 ranking 没有明显使用它加权。

### 分支安全过滤

`RuntimeContextBuilder._rank_branch_safe()` 会：

- 过滤 `archived`、`quarantine`、`sensitive`、`internal`。
- 当前 active branch 来源知识加权最高。
- 同 session 知识加权。
- 项目知识和用户知识按较低权重加分。

### 注入 Working Set

`RuntimeContextBuilder.build()` 输出 Markdown，然后传入 `WorkingSetBuilder.build()`，最后由 `WorkingSet.render()` 注入 system prompt。

当前差距：Branch-safe Recall 已有分支安全排序，但还不是完整策略引擎；没有复杂冲突检测、失效机制、跨分支隔离策略配置，也没有外部 embedding 检索。

## 13. Multi-Agent Team 源码说明

PrismaX 支持两类多智能体机制：一次性子代理 `dispatch_subagent` 和持久队友 `spawn_teammate`。

### dispatch_subagent

| 项 | 内容 |
|---|---|
| 工具类 | `src/prismax/tools/dispatch.py::DispatchSubagentTool` |
| 子代理注册 | `src/prismax/subagents/registry.py::SubagentRegistry` |
| 子代理规格 | `src/prismax/subagents/spec.py::SubagentSpec` |
| 注册位置 | `AgentApp._build_registry()` |

执行流程：

```text
模型调用 dispatch_subagent
→ DispatchSubagentTool.execute()
→ 根据 agent_type 查 SubagentSpec
→ 按 spec.tool_names 构造子 ToolRegistry
→ runner_factory 创建子 AgentRunner
→ 子 Agent 独立 history 执行
→ 返回精简结果给主 Agent
```

该模式不写入子 Agent 独立 TreeSession，主 Agent 只会把该工具调用和工具结果写入自己的 TreeSession。

### spawn_teammate

| 项 | 内容 |
|---|---|
| 工具类 | `src/prismax/tools/team.py::SpawnTeammateTool` |
| 管理器 | `src/prismax/team.py::TeammateManager` |
| 消息总线 | `src/prismax/team.py::MessageBus` |
| 注册位置 | `AgentApp._build_registry()` |

`TeammateManager.spawn()` 会创建后台线程执行 `_teammate_loop()`。

TeamMate 当前具备：

| 能力 | 实现 |
|---|---|
| 独立 session | `.team/{name}/sessions`，由 `TreeSessionManager` 管理。 |
| 独立 memory | `.team/{name}/memory`，由 `MemoryStore` 管理。 |
| 独立 inbox | `.team/inbox/{name}.jsonl`，由 `MessageBus` 管理。 |
| 独立运行上下文 | `_teammate_loop()` 内部创建 `RuntimeContextBuilder`。 |
| 向 lead 回报 | `SendMessageTool` / `MessageBus.send()`。 |

### inbox / send_message / read_inbox

| 功能 | 代码 |
|---|---|
| 发送消息 | `MessageBus.send()` |
| 读取并清空 inbox | `MessageBus.read_inbox()` |
| 广播 | `MessageBus.broadcast()` |
| 工具封装 | `src/prismax/tools/team.py::SendMessageTool`、`ReadInboxTool`、`BroadcastTool` |

## 14. MCP 工具系统源码说明

### MCP client 初始化

`AgentApp.__init__()` 创建：

```python
self.mcp = MCPClientManager(self.root / "mcp_servers.json")
```

`AgentApp._build_registry()` 中调用：

```python
self.mcp.start()
for tool in self.mcp.tools():
    registry.register(tool)
```

### MCP server 配置读取

配置文件：`mcp_servers.json`。

读取函数：`src/prismax/mcp_bridge.py::MCPClientManager._load_specs()`。

支持：

- `stdio`
- `streamable_http`
- 环境变量插值 `${VAR}`

### Tool Registry

`src/prismax/tools/registry.py::ToolRegistry` 负责：

| 函数 | 作用 |
|---|---|
| `register()` | 注册工具。 |
| `get()` | 按名称获取工具。 |
| `names()` | 列出工具名。 |
| `definitions()` | 转为模型可用 tool schema。 |
| `execute()` | 参数转换、校验、执行工具。 |

### Tool Call 执行流程

```text
LLM 返回 tool_use
→ AgentRunner.step()
→ _execute_tool_blocks()
→ ToolRegistry.execute()
→ Tool.execute()
→ 返回 tool_result
→ on_tool_result 回调
→ TreeSessionManager.append_tool_result()
```

MCP 远端工具会被包装成 `MCPToolAdapter`，其 `execute()` 调用 `MCPClientManager.call_tool()`。

### Tool Result 是否写入 Event Log / Working Context

是。`AgentApp.ask()` 传入 `record_tool_result()` 回调，调用：

```python
self.tree.append_tool_result(self.session_id, result)
```

随后 `WorkingSetBuilder` 会从 active branch 中寻找最近的 `ToolResultEntry`，放入 `recent_tool_result`。

当前差距：MCP 当前只暴露 tools，`resources` 和 `prompts` 尚未映射进统一上下文或工具系统。

## 15. 主要数据流说明

### 用户输入到模型输出的数据流

```text
User Input
→ src/prismax/cli.py 判断 Slash Command 或普通输入
→ AgentApp.ask()
→ TreeSessionManager.append_message()
→ RuntimeContextBuilder.build()
→ WorkingSetBuilder.build()
→ ContextBuilder.build()
→ TreeSessionManager.buildModelContext()
→ AgentRunner.step()
→ LLM
→ Tool Call
→ ToolRegistry.execute()
→ Tool Result
→ TreeSessionManager.append_tool_call() / append_tool_result()
→ 下一轮 LLM 或最终 Response
→ TreeSessionManager.append_message()
```

### TGM 记忆演化数据流

```text
TreeSession / Event Log (sessiontrees/*.jsonl)
→ Active Branch Context
→ Working Set
→ Compaction
→ CompactionEntry / BranchSummaryEntry
→ Episode Memory
→ SessionMemoryCommitter
→ LlmMemoryExtractor
→ ContextFS session archive / memory object
→ Wiki Knowledge Base
→ Local Semantic Vector Index
→ MemoryGraph
→ Runtime Recall
→ Working Set
→ 下一轮模型推理
```

## 16. 当前实现与技术报告书的差距

| 设计目标 | 当前代码状态 | 是否完成 | 建议修改 |
|---|---|---|---|
| TreeSession | `TreeSessionManager` 支持 parentId、active leaf、jump/fork/clone/label、JSONL replay。 | 已完成 | 后续可优化 ID 可读性和树调试界面。 |
| Active Branch Context | `buildModelContext()` 只基于 active branch 构造上下文。 | 已完成 | 可增加更细粒度的上下文预算控制。 |
| Working Set | `WorkingSetBuilder` 汇总 active branch、todo、最近工具结果、episode、runtime recall。 | 部分完成 | 当前 Working Set 主要注入 system prompt，尚未形成更强 schema/预算策略。 |
| Event Log | `sessiontrees/*.jsonl` append-only，metadata 有事件语义。 | 部分完成 | 还不是独立事件总线；todo、team 状态等不能完整从事件恢复。 |
| Experience Replay | `loadSession()` 可 replay TreeSession 和 active leaf。 | 部分完成 | 可扩展为完整 Runtime State replay。 |
| Compaction | `/compact` 生成 `CompactionEntry`，支持 LLM 摘要和保留最近上下文。 | 已完成主体 | 自动阶段触发和摘要质量校验仍可增强。 |
| Episode Memory | `CompactionEntry`、`BranchSummaryEntry` 对应阶段记忆。 | 部分完成 | Episode 没有单独统一存储模型，主要在 TreeSession 内。 |
| Semantic Knowledge | `ContextFS`、`KnowledgeObject`、`WikiKnowledgeBase`、`LocalSemanticVectorIndex` 已存在。 | 部分完成 | 缺少知识冲突治理、版本化、人工编辑后的反向索引更新。 |
| Wiki Knowledge Base | `memory/Wiki/*` 可写 Markdown 知识页。 | 部分完成 | 当前读取和维护 API 较轻，front matter 使用 JSON 而非 YAML。 |
| Vector Index | `semantic_index.jsonl` 本地 token overlap 索引。 | 部分完成 | 没有真实 embedding，也没有 ANN/向量数据库。 |
| MemoryGraph | `MemoryGraph` 支持 derived_from、supports、updates、contradicts、related、uses_tool 等关系。 | 已完成基础 | 可增加冲突检测、关系解释和图可视化。 |
| Branch-safe Recall | `_rank_branch_safe()` 按 active branch、session、project、trust score 加权。 | 部分完成 | 还不是完整策略引擎，缺少失效和跨分支隔离规则配置。 |
| Multi-Agent Team | `dispatch_subagent` 和 `spawn_teammate` 都已实现；TeamMate 有独立 session/memory/inbox。 | 部分完成 | 持久 TeamMate 的长期自治、调度和监控仍轻量。 |
| MCP Tool System | `MCPClientManager` 支持 stdio/HTTP 工具接入并注册到 ToolRegistry。 | 已完成基础 | MCP resources/prompts 尚未映射。 |
| Tool Result 外置化 | 工具结果写入 TreeSession，并进入 Working Set 最近工具结果。 | 部分完成 | 大型工具结果仍可进一步外置到 raw/context 层。 |
| Slash Runtime | CLI 中支持主要 slash commands。 | 已完成基础 | 目前是 if 链，后续可抽象为命令注册表。 |

## 17. 新开发者阅读源码建议

推荐阅读顺序：

1. 先看 `pyproject.toml`，确认命令入口 `prismax` 和 `prismax-web`。
2. 看 `src/prismax/cli.py`，理解 CLI 如何接收输入和分发 Slash Command。
3. 看 `src/prismax/loop.py`，理解 `AgentApp` 如何装配模型、工具、会话树、记忆和 MCP。
4. 看 `src/prismax/runner.py`，理解 LLM 调用、工具调用、多轮循环和工具结果回注。
5. 看 `src/prismax/tree_session.py`，理解 JSONL 会话树、active branch、jump/fork/clone、compaction。
6. 看 `src/prismax/working_set.py`、`src/prismax/context.py`、`src/prismax/context_backend.py`，理解 Working Set 和 Runtime Recall。
7. 看 `src/prismax/memory.py`、`src/prismax/contextfs.py`、`src/prismax/knowledge.py`、`src/prismax/memory_graph.py`，理解长期记忆、Wiki 知识库、语义索引和关系图。
8. 看 `src/prismax/tools/`，理解内置工具的接口、参数校验和注册。
9. 看 `src/prismax/mcp_bridge.py`，理解 MCP 工具如何接入。
10. 看 `src/prismax/team.py`、`src/prismax/tools/dispatch.py`、`src/prismax/tools/team.py`，理解多智能体。
11. 最后看 `tests/`，用测试反推关键行为和边界。

## 18. 总结

当前 PrismaX 代码已经形成一个可运行的 TGM Agent Runtime：`AgentApp` 负责装配，`AgentRunner` 负责模型和工具循环，`TreeSessionManager` 负责树状任务经历和 active branch，上下文由 `WorkingSetBuilder` 和 `RuntimeContextBuilder` 动态构建，长期知识通过 `MemoryStore`、`ContextFS`、`WikiKnowledgeBase`、`LocalSemanticVectorIndex` 和 `MemoryGraph` 沉淀与召回。

核心亮点是：会话事实源不再是线性聊天数组，而是 `sessiontrees/*.jsonl` 会话树；模型上下文基于 active branch 构建；压缩结果可以进入长期记忆与 Wiki 知识库；工具结果和多智能体协作也被纳入统一运行链路。

后续改造重点包括：把 Event Log 从“JSONL 条目 + metadata 语义”进一步升级为完整可 replay 的 Runtime Event System；强化 Working Set 预算和 schema；完善 Branch-safe Recall 策略；让 Wiki 知识库具备更强的更新、冲突治理和可视化能力；扩展 MCP resources/prompts 映射。


