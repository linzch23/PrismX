# PrismX

English | [中文](README.zh-CN.md)

PrismX is a local Python Agent workbench for long-running, multi-branch tasks.
It combines an Agent runtime, MCP-based environment access, and a Tree-Guided
Memory system so the Agent can manage history as a tree instead of one long
linear chat.

The Python package and CLI command are lowercase `prismx`.

## What PrismX Solves

Most Agent products work well for short conversations, but long tasks quickly
run into three problems:

- Linear history becomes noisy, because every trial, detour, and failed attempt
  competes for the same context window.
- Branches are isolated, so useful experience discovered in one branch is hard
  to reuse in sibling branches.
- Long-term memory is easy to pollute if every remembered note is treated as
  globally reusable knowledge.

PrismX is designed for tasks like:

- learning trees, such as moving from a `Prim` algorithm branch to a sibling
  `Kruskal` branch while reusing the shared minimum-spanning-tree conclusion;
- coding repair sessions, where a user says "continue fixing one more issue"
  and the Agent needs to recover the failed branch, evidence, test output, and
  relevant long-term patterns;
- project research, where local session context, tree-level findings, and
  cross-project knowledge need different lifetimes.

## Architecture

PrismX has three major layers:

- **Agent Runtime Layer**: Agent loop, slash commands, tool calling, subagents,
  and persistent agent team state.
- **Environment Interaction Layer**: local file/shell tools and external MCP
  servers.
- **Tree-Guided Memory Layer**: TreeSession, Tree Memory, Long-term Knowledge,
  and Runtime Recall.

## TGM 3.0: Tree-Guided Memory

TGM 3.0 keeps three memory layers with clear responsibilities:

- **Active Path Context**: vertical inheritance from the root SessionNode to the
  active SessionNode. It gives the active session its parent goals and decisions
  without injecting unrelated sibling conversations.
- **Tree Memory**: tree-local execution memory. It stores reusable experience
  inside the current Session Tree as `TraceEvent`, `Evidence`, `FoldedNode`, and
  `MemoryIndexItem`.
- **Long-term Knowledge**: cross-tree and cross-project knowledge. It must be
  traceable back to Tree Memory through `source_tree_id`, `source_fold_id`, and
  `source_evidence_ids`.

Runtime Recall is not a blind "load all memory" step. Before the model answers,
PrismX builds a `ContextPacket` through:

```text
current request
-> coarse reasoning
-> retrieval intent
-> Tree Memory recall
-> Evidence snippets
-> Long-term Knowledge recall
-> ContextPacket
```

This means `FoldedNode` gives the Agent a compact navigation layer, while
`Evidence` keeps the original material available for verification.

## Runtime Data Layout

New runtime data is written under `data/`:

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

Deprecated `memory/` and `sessiontrees/` directories may still appear as
compatibility fallbacks for older local data, but they are not the main TGM 3.0
write path.

## Quick Start

Install dependencies and create an environment file:

```bash
uv sync
cp .env.example .env
```

Edit `.env` and configure at least one model provider. A typical DeepSeek setup:

```bash
MY_AGENT_PROVIDER=deepseek
MY_AGENT_MODEL=deepseek-chat
DEEPSEEK_API_KEY=your_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
MY_AGENT_MAX_CONTEXT_TOKENS=64000
```

Start the CLI:

```bash
uv run prismx
```

Start the local Web workbench:

```bash
uv run prismx-web
```

The Web workbench listens on:

```text
http://127.0.0.1:8765
```

If the console script is unavailable, start the server module directly.

macOS / Linux:

```bash
PYTHONPATH=src uv run python -m prismx.server
```

Windows PowerShell:

```powershell
$env:PYTHONPATH="src"; uv run python -m prismx.server
```

The repository also provides helper scripts:

```bash
./run.sh
./run_web.sh
```

## Web Workbench

The Web workbench exposes the current PrismX workspace through four main tabs:

- **Chat**: talk to the active Session. Messages are stored in that Session,
  not as tree nodes.
- **Tree**: view and manage the Session Tree. Each node is a real backend
  SessionNode.
- **Memory**: inspect Active Path Context, Tree Memory, Evidence-backed folds,
  Long-term Knowledge, and Runtime Recall state.
- **Files**: read the selected browser workspace folder when the File System
  Access API is available.

Project workspace folders are browser handles. PrismX runtime data still lives
under `data/`; a selected user workspace folder is not used as PrismX's internal
storage directory.

## CLI Commands

Run `/help` in the CLI to print the current command list.

Basics:

```text
/help
/exit
```

Agent Runtime:

```text
/agent
/run
/team
/tools
/mcp
```

TreeSession:

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

TGM Memory:

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

Debug:

```text
/state
/debug
```

## Memory Tools

The `remember` tool writes new reusable information into Tree Memory by default.
Tree Memory can then be folded into a `FoldedNode`, retrieved inside the current
Session Tree, and promoted to Long-term Knowledge when it becomes stable or is
explicitly promoted.

Long-term Knowledge is not created as an untraceable free-form note. New
long-term entries must point back to their Tree Memory source:

```text
source_tree_id
source_fold_id
source_evidence_ids
```

This keeps global knowledge useful without losing provenance.

## MCP Tools

PrismX can connect to external MCP servers through `mcp_servers.json`.

Example:

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

If a server config provides `command` or `url`, `transport` can usually be
inferred. MCP tools are registered as `mcp_{server}_{tool}` with unsupported
characters replaced by `_`.

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

Run the Python test suite:

```bash
uv run python -m unittest discover tests
```

For frontend syntax checks:

```bash
node --check frontend/app.js
```

## Further Reading

- `docs/TGM3.0.md`: current Tree-Guided Memory design and implementation notes.
- `docs/TGM_FRONTEND_TEST_PLAN.md`: frontend and memory-system verification plan.

## Notes

File tools resolve relative paths against `MY_AGENT_WORKSPACE` or the current
working directory. Keep PrismX runtime data and user project workspace files
conceptually separate: PrismX writes its own state under `data/`, while the Web
Files tab only reads a user-selected browser workspace folder.
