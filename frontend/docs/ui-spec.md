# PrismX Session Tree Workbench UI Spec

## Information Architecture

The web UI is a PrismX Agent workspace built around Session trees.

- A Session Tree is a task tree made of Session nodes.
- A Session node is a complete backend session and owns its messages.
- Messages are content inside a Session; they are not tree nodes.
- Chat, Tree, and Memory read from one shared workspace state.

## Layout

- Header: PrismX identity, active Session label, refresh, and agent entry.
- Sidebar: projects, each project's Session Trees, and creation actions.
- Workspace tabs: Chat, Tree, Memory.

## Chat

The Chat tab renders the active Session.

- Title comes from the active Session node.
- Message list comes from that Session's JSONL records.
- Sending a message targets the active Session id.
- New Child Session creates a real backend session and links it under the active Session node.

## Tree

The Tree tab visualizes Session nodes.

- Nodes grow left to right.
- Each node shows title, status, and message count.
- Selecting a node updates activeSessionId.
- Nodes support pan, zoom, drag-position persistence, rename, child creation, and delete.
- Root Session nodes cannot be deleted.
- Deleting a non-root node removes its subtree and backend session files.

## Memory

The Memory tab is derived from active workspace state.

- Active Path Context is computed from root Session to active Session.
- Tree Memory Recall filters memory items against the active tree's sessions.
- Long-term Knowledge Recall uses real knowledge items when available and context-aware examples otherwise.
- Working Context Preview counts active path sessions, tree memory items, active session messages, and knowledge items.

## API Boundary

The browser uses `/api/workspace` as its primary hydration endpoint.

- Workspace metadata persists project/tree/node relationships and node positions.
- Existing `sessiontrees/*.jsonl` files remain the source of truth for messages.
- Legacy entry-tree endpoints remain available for compatibility but are not the main UI model.
