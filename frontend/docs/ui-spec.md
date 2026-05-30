# PrismaX Coding Agent UI Spec

## Information Architecture

The UI is a task-first coding agent workspace, not a traditional chat surface.

- TopBar owns task identity, primary tabs, run status, and access to hidden diagnostics.
- Run Timeline is the primary surface for agent progress and action evidence.
- Workbench is the secondary surface for reviewing artifacts produced by the run.
- Session Tree is hidden in a drawer because it is a navigation/debug tool, not the main workflow.
- Inspector is hidden by default and exposes trace, context, memory, and raw JSON only when requested.

## Run Timeline

Run Timeline presents the agent as a sequence of execution steps.

Stable fields for API-backed data:

- `id`
- `title`
- `status`: `pending`, `running`, `done`, or `error`
- `time` or worked-time label
- `summary`
- `details`
- `tools[]`
- `expanded`

Each tool item should keep:

- `name`
- `status`
- `input`
- `output`
- `duration`

## Workbench

Workbench uses tabs for artifacts and operational views:

- Agent: run overview and current next action.
- Changes: files touched by the run, with diff stats.
- Preview: iframe or empty state for live app preview.
- Code: read-only code preview.
- Tools: structured tool-call log and registered tool definitions.

The Workbench should not own conversation history. It should expose concrete outputs.

## Hidden Tree Drawer

The Tree Drawer is for branch-level inspection and future controls:

- inspect session nodes
- jump to an existing node
- fork from a node
- label a node

It remains hidden to keep the main workspace focused on execution rather than history topology.

## Hidden Inspector

Inspector has four panels:

- Trace: active leaf, included/excluded entries, token estimate, compaction state.
- Context: compact summary of what will enter the model context.
- Memory: long-term memory file surfaced by the API.
- Raw JSON: unmodified diagnostic payload for debugging.

These panels are intentionally off-canvas because they are diagnostic surfaces.

## API Integration Boundary

The server maps `sessions/*.jsonl` into this UI shape without making the browser parse JSONL directly:

- JSONL message/tool entries become `RunStep` objects.
- `tool_call` and `tool_result` attach to the relevant step.
- file write/edit tool calls populate Changes and Tools.
- node detail API populates the Raw JSON inspector.
- Tree Drawer keeps node fields stable: `id`, `parentId`, `type`, `label`, `preview`, `status`.
