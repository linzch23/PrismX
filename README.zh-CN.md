# PrismX

[English](README.md) | 中文

PrismX 是一个本地运行的 Python Agent 工作台，面向长任务、多分支探索和持续性的项目上下文管理。
它结合了 Agent 运行时、基于 MCP 的环境访问能力，以及 Tree-Guided Memory 系统，让 Agent 可以把历史管理成一棵树，而不是一条越来越长的线性聊天记录。

Python 包名和 CLI 命令均为小写：`prismx`。

## PrismX 解决什么问题

大多数 Agent 产品在短对话里表现很好，但一旦任务变长，就会遇到三个典型问题：

- 线性历史会变得嘈杂，因为每一次尝试、绕路和失败都会挤进同一个上下文窗口。
- 分支之间相互隔离，一个分支中发现的有用经验很难被 sibling 分支复用。
- 长期记忆容易被污染，如果所有“记住”的内容都被当成全局知识，长期记忆会很快失去边界。

PrismX 更适合这类任务：

- 学习树，例如从 `Prim` 算法分支切到 sibling `Kruskal` 分支时，复用最小生成树的共享结论。
- 编程修复任务，例如用户说“继续修一个问题”时，Agent 需要找回失败分支、证据、测试输出和相关长期模式。
- 项目研究任务，其中当前会话上下文、树内发现和跨项目知识需要不同的生命周期。

## 系统架构

PrismX 有三层核心架构：

- **Agent Runtime Layer**：Agent Loop、Slash 命令、工具调用、Subagent 和持久化 Agent Team 状态。
- **Environment Interaction Layer**：本地文件 / shell 工具，以及外部 MCP server。
- **Tree-Guided Memory Layer**：TreeSession、Tree Memory、Long-term Knowledge 和 Runtime Recall。

## TGM 3.0：Tree-Guided Memory

TGM 3.0 保留三层记忆，并让每一层承担清晰职责：

- **Active Path Context**：从 root SessionNode 到当前 active SessionNode 的纵向继承上下文。它让当前会话继承父节点目标和决策，同时不会注入无关 sibling 对话。
- **Tree Memory**：当前树内的执行记忆。它把当前 Session Tree 中可复用的经验保存为 `TraceEvent`、`Evidence`、`FoldedNode` 和 `MemoryIndexItem`。
- **Long-term Knowledge**：跨树、跨项目的长期知识。它必须能追溯回 Tree Memory，包含 `source_tree_id`、`source_fold_id` 和 `source_evidence_ids`。

Runtime Recall 不是盲目“加载所有记忆”。在模型回答前，PrismX 会按下面流程构建 `ContextPacket`：

```text
current request
-> coarse reasoning
-> retrieval intent
-> Tree Memory recall
-> Evidence snippets
-> Long-term Knowledge recall
-> ContextPacket
```

也就是说，`FoldedNode` 提供紧凑的历史导航层，而 `Evidence` 保留可验证的原始材料。

## 运行时数据结构

新的运行时数据写入 `data/`：

```text
data/
  workspace.json
  sessions/
    {tree_id}/
      tree.json
      sessions/
        {session_id}.jsonl
  tree_memory/
    {tree_id}/
      trace_events.jsonl
      folded_nodes.jsonl
      memory_index.jsonl
      tree_state.json
      evidence/
  knowledge/
    MEMORY.md
    memories/
      user/
      feedback/
      project/
      reference/
      pattern/
    graph/
      nodes.jsonl
      edges.jsonl
    promotion_log.jsonl
```

旧的 `memory/` 和 `sessiontrees/` 目录可能仍作为历史本地数据的兼容 fallback 出现，但它们不是 TGM 3.0 的主要写入路径。

## 快速开始

安装依赖并创建环境变量文件：

```bash
uv sync
cp .env.example .env
```

编辑 `.env`，至少配置一个模型提供商。一个典型的 DeepSeek 配置如下：

```bash
MY_AGENT_PROVIDER=deepseek
MY_AGENT_MODEL=deepseek-chat
DEEPSEEK_API_KEY=your_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
MY_AGENT_MAX_CONTEXT_TOKENS=64000
```

启动 CLI：

```bash
uv run prismx
```

启动本地 Web 工作台：

```bash
uv run prismx-web
```

Web 工作台默认监听：

```text
http://127.0.0.1:8765
```

如果 console script 不可用，可以直接以模块方式启动 server。

macOS / Linux：

```bash
PYTHONPATH=src uv run python -m prismx.server
```

Windows PowerShell：

```powershell
$env:PYTHONPATH="src"; uv run python -m prismx.server
```

仓库也提供了辅助脚本：

```bash
./run.sh
./run_web.sh
```

## Web Workbench

Web 工作台通过四个主要标签页展示当前 PrismX workspace：

- **Chat**：和 active Session 对话。消息保存在该 Session 内，而不是作为树节点保存。
- **Tree**：查看和管理 Session Tree。每个节点都是一个真实的后端 SessionNode。
- **Memory**：查看 Active Path Context、Tree Memory、基于 Evidence 的折叠记忆、Long-term Knowledge 和 Runtime Recall 状态。
- **Files**：当浏览器支持 File System Access API 时，读取用户选择的 workspace 文件夹。

Project workspace 文件夹是浏览器侧的目录句柄。PrismX 自身运行时数据仍写入 `data/`；用户选择的 workspace 文件夹不会被当作 PrismX 的内部存储目录。

## CLI Commands

在 CLI 中输入 `/help` 可以打印当前命令列表。

Basics：

```text
/help
/exit
```

Agent Runtime：

```text
/agent
/run
/team
/tools
/mcp
```

TreeSession：

```text
/tree
/tree list
/tree new NAME
/tree rename ID NAME
/tree delete ID

/session
/session new NAME
/session rename ID NAME
/session delete ID

/switch ID
```

TGM Memory：

```text
/path
/memory
/memory add TYPE CONTENT
/memory delete ID
/memory fold
/memory retrieve QUERY
/memory promote FOLD_ID --type pattern
/memory evidence EVIDENCE_ID
/memory rollback FOLD_ID
/memory status

/recall
/working-context
/knowledge
```

Debug：

```text
/state
/debug
```

## Memory Tools

`remember` 工具默认会把新的可复用信息写入 Tree Memory。之后 Tree Memory 可以被折叠为 `FoldedNode`，在当前 Session Tree 内被检索，并在稳定或被显式提升时晋升为 Long-term Knowledge。

Long-term Knowledge 不会作为不可追溯的自由文本笔记直接产生。新的长期知识必须指向它的 Tree Memory 来源：

```text
source_tree_id
source_fold_id
source_evidence_ids
```

这样可以让全局知识保持有用，同时不丢失来源。

## MCP Tools

PrismX 可以通过 `mcp_servers.json` 连接外部 MCP server。

示例：

```json
{
  "mcpServers": {
    "filesystem": {
      "transport": "stdio",
      "command": "uvx",
      "args": ["mcp-server-filesystem", "."],
      "env": {
        "SOME_TOKEN": "${SOME_TOKEN}"
      }
    },
    "local_http": {
      "transport": "streamable_http",
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer ${MCP_TOKEN}"
      }
    }
  }
}
```

如果 server 配置提供了 `command` 或 `url`，通常可以推断出 `transport`。MCP 工具会以 `mcp_{server}_{tool}` 的形式注册，不支持的字符会被替换为 `_`。

## Project Structure

```text
src/prismx/
  cli.py                  CLI entrypoint and slash commands
  server.py               local Web/API server
  loop.py                 AgentApp assembly and Agent loop integration
  runner.py               model and tool-calling loop
  workspace.py            project, SessionTree, and SessionNode metadata
  tree_session.py         session JSONL persistence and session history
  tree_memory.py          TGM 3.0 TraceEvent, Evidence, FoldedNode, retrieval
  runtime_recall.py       Active Path + Tree Memory + Long-term recall builder
  memory.py               traceable Long-term Knowledge store
  working_set.py          working context assembly
  team.py                 persistent teammate state
  skills.py               skill loader
  tools/                  built-in tool implementations
  subagents/              subagent registry

frontend/
  index.html
  app.js
  styles.css

docs/
  TGM3.0.md
  TGM_FRONTEND_TEST_PLAN.md
```

## Tests

运行 Python 测试套件：

```bash
uv run python -m unittest discover tests
```

运行前端语法检查：

```bash
node --check frontend/app.js
```

## Further Reading

- `docs/TGM3.0.md`：当前 Tree-Guided Memory 设计和实现说明。
- `docs/TGM_FRONTEND_TEST_PLAN.md`：前端与记忆系统验证计划。

## Notes

文件工具会基于 `MY_AGENT_WORKSPACE` 或当前工作目录解析相对路径。请把 PrismX 运行时数据和用户项目 workspace 文件在概念上区分开：PrismX 会把自身状态写入 `data/`，而 Web Files 标签页只读取用户在浏览器中选择的 workspace 文件夹。
