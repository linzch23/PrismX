# my_agent2

`my_agent2` is a compact, general-purpose Python agent inspired by
`TheSyart/claude-agent-examples`, but with the teaching-specific roleplay removed
and the project packaged for `uv`.

It includes:

- a provider adapter for DeepSeek, Anthropic, and OpenAI-compatible chat APIs
- streaming assistant text in the main CLI conversation
- MCP tools from stdio and Streamable HTTP MCP servers
- workspace file tools: `read_file`, `write_file`, `edit_file`, `glob`, `grep`
- command and web fetch tools
- persistent conversation logs and lightweight long-term memory
- automatic history compression when context grows large
- a todo tool for explicit task planning
- loadable skills from `skills/{name}/SKILL.md`
- generic subagents for isolated research, analysis, coding, and review
- persistent multi-agent team collaboration with named teammates and inboxes
- parallel execution for read-only tools and independent subagent calls

## Quick Start

```bash
uv sync
cp .env.example .env
# edit .env and set DEEPSEEK_API_KEY

uv run my-agent2
```

On this Mac, the most reliable local command is:

```bash
./run.sh
```

`run.sh` resolves the project directory, exports `PYTHONPATH`, changes into the
repo, and then runs the virtualenv Python entrypoint. This avoids terminal
current-directory issues and editable-install import issues on this Mac.

Default `.env` settings use DeepSeek:

```bash
MY_AGENT_PROVIDER=deepseek
MY_AGENT_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com
MY_AGENT_MAX_CONTEXT_TOKENS=64000
MY_AGENT_COMPACT_THRESHOLD=0.7
MY_AGENT_COMPACT_KEEP_MESSAGES=8
MY_AGENT_STARTUP_COMPACTION=0
```

## MCP Tools

`my_agent2` can connect to external MCP servers and expose their tools to the
agent. Configure servers in `mcp_servers.json` at the project root:

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

`transport` may be omitted when `command` or `url` is present. MCP tool names are
registered as `mcp_{server}_{tool}` with unsafe characters replaced by `_`.
This first MCP integration exposes tools only; MCP resources and prompts are not
mapped yet.

Useful commands inside the CLI:

- `/help` - show commands
- `/tools` - list registered tools
- `/todos` - show the current todo list
- `/memory` - show long-term memory
- `/mcp` - show MCP server status and discovered MCP tools
- `/compact` - force conversation history compression
- `/team` - show persistent teammate status
- `/inbox` - read and clear the lead inbox
- `/tree [--filter default|no-tools|user-only|labeled-only|all]` - show the JSONL tree session
- `/jump ID` - move the active leaf to an existing entry
- `/fork ID` - move the active leaf to an existing entry; the next input creates a sibling branch
- `/clone` - clone the active branch into a new session file and switch to it
- `/label ID LABEL` - attach a label to a tree entry
- `/exit` - quit

Tree sessions are persisted as append-only JSONL files in `sessions/`. The JSONL
file is the source of truth; in-memory indexes are rebuilt by replaying it.
`/compact` writes a compaction entry to the active branch and keeps the original
entries in the file. Legacy `memory/history.jsonl` startup compaction is disabled
by default; set `MY_AGENT_STARTUP_COMPACTION=1` only if you want startup to call
the model and archive old memory logs.

## Project Layout

```text
src/my_agent2/
  cli.py              CLI entry point
  loop.py             application wiring
  runner.py           model/tool execution loop
  compactor.py        history compression
  team.py             persistent teammate manager and inbox bus
  memory.py           logs and long-term notes
  skills.py           skill loader
  context.py          system prompt builder
  tools/              tool implementations
  subagents/          generic subagent registry
templates/
  system.md           main agent prompt
  subagents/*.md      role prompts
skills/
  summarize/SKILL.md  example skill
```

## Notes

By default, file tools are scoped to the configured workspace. Relative paths are
resolved from `MY_AGENT_WORKSPACE` or the current directory.
