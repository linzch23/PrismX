# Capability Parity With claude-agent-examples

This document tracks the original repository's core capabilities against the
generic `my_agent2` implementation.

| Original capability | claude-agent-examples | my_agent2 status | my_agent2 location | Notes |
|---|---|---:|---|---|
| CLI entrypoint | `agent.py`, `agent/loop.py` | Done | `src/my_agent2/cli.py`, `src/my_agent2/loop.py` | Packaged with `uv` via `pyproject.toml`. |
| Model client | Anthropic client directly in loop | Done, generalized | `src/my_agent2/model_client.py` | Supports `deepseek`, `anthropic`, and `openai-compatible`. |
| Tool-use runner | `agent/runner.py` | Done | `src/my_agent2/runner.py` | Uses provider-neutral blocks and supports parallel safe tool calls. |
| Tool registry and validation | `agent/tools/base.py`, `registry.py`, `schema.py` | Done | `src/my_agent2/tools/base.py`, `registry.py` | Simpler schema helpers; validates basic JSON schema types. |
| Shell tool | `run_command` | Done | `src/my_agent2/tools/shell.py` | Workspace-scoped cwd, timeout support. |
| Web fetch tool | `web_fetch` | Done | `src/my_agent2/tools/web.py` | Text/raw extraction. |
| File read/write/edit | `read_file`, `write_file`, `edit_file` | Done | `src/my_agent2/tools/filesystem.py` | Workspace escape protection added. Original edit matching is richer. |
| Search tools | `glob`, `grep` | Done | `src/my_agent2/tools/filesystem.py` | Basic glob/regex search. Original has more pagination/type filters. |
| Todo planning | `update_todos`, `TodoStore` | Done | `src/my_agent2/tools/state.py` | Same complete-list update model and single `in_progress` rule. |
| Skills loader | `agent/skills.py`, `load_skill` | Done | `src/my_agent2/skills.py`, `tools/state.py` | Supports nested `SKILL.md`, summaries, `always: true`, and fallback frontmatter parsing before dependencies are installed. |
| Built-in skills | `skills/*` | Partial | `skills/summarize/SKILL.md` | Only a generic summarize skill is bundled; original has clawhub/github/weather/etc. |
| System prompt builder | `agent/context.py`, `templates/*` | Done, generalized | `src/my_agent2/context.py`, `templates/system.md` | Removes original roleplay and injects memory, user profile, skills. |
| Long-term memory | `memory/MEMORY.md` | Done | `src/my_agent2/memory.py` | Writes `memory/MEMORY.md`. |
| User profile memory | `templates/USER.md` | Done | `templates/USER.md`, `MemoryStore.read_user/write_user` | Updated by compaction. |
| Episode memory | `memory/YYYY-MM-DD.md` | Done | `MemoryStore.append_episode` | UTC+8 daily episode files. |
| Raw history log | `memory/history.jsonl` | Done | `MemoryStore.append_history` | User/final assistant history is logged. |
| Startup archive | `load_unarchived_history`, `compact_startup` | Done | `MemoryStore.load_unarchived_history`, `HistoryCompactor.compact_startup` | Archives unmarked prior-session turns before system prompt construction. |
| Automatic history compression | `Compactor`, `TokenTracker.should_compact` | Done | `src/my_agent2/compactor.py`, `runner.py`, `memory.py` | Triggers by token threshold or history length fallback. |
| Token log | `memory/tokens.jsonl` | Done | `TokenLog` | Records provider-neutral input/output token fields using UTC+8 timestamps. |
| Token aggregations | `stats_by_date`, `stats_by_model` | Done | `TokenLog.stats_by_date`, `stats_by_model` | Basic aggregation supported. |
| One-shot subagents | `dispatch_subagent` | Done, generalized | `src/my_agent2/subagents`, `tools/dispatch.py` | Generic roles: researcher, analyst, coder, reviewer. |
| Subagent tool whitelist | `agent/subagents/registry.py` | Done | `src/my_agent2/subagents/registry.py` | Security settings live in code, not prompt templates. |
| Parallel subagent dispatch | runner safe tool batching | Done | `runner.py`, `DispatchSubagentTool.concurrency_safe` | Independent dispatch calls can run in parallel. |
| Persistent agent team | `agent/team.py` | Done | `src/my_agent2/team.py` | Named teammates, persistent config, inboxes, threads. |
| Team tools | `spawn/list/send/read/broadcast` | Done | `src/my_agent2/tools/team.py` | Registered for lead and teammate agents. |
| Team CLI helpers | `/team`, `/inbox` | Done | `src/my_agent2/cli.py` | Mirrors original operational shortcuts. |
| Runtime dirs ignored | `memory/`, `.team/` | Done | `.gitignore` | Prevents generated state from being committed. |
| Teaching examples | `build-agent-example/*` | Not ported | N/A | `my_agent2` is the productized generic agent, not the teaching series. |
| PPT course material | `ppt/*` | Not ported | N/A | Out of scope for the generic implementation. |

## Remaining Gaps

- File search and edit tools are functional but less feature-rich than the
  original implementation. The original `grep/glob` support more filters and
  pagination, and `edit_file` has more fuzzy matching.
- Bundled skills are intentionally minimal. Add generic skills as the project
  direction becomes clearer instead of copying every original role-specific skill.
- No integration test hits a real DeepSeek/Anthropic API in this environment
  because dependencies and `uv` are not available here.

## Current Verification

- `python3 -m compileall src`
- Smoke tests for:
  - file tools and todo tool
  - provider-neutral tool-call conversion
  - history compaction with a fake model
  - three-tier memory writes: `MEMORY.md`, `USER.md`, and daily episode files
  - startup compaction marker behavior
  - always-active skills and system prompt injection
  - message bus and team tools
  - spawning a teammate thread with a fake model
