const MIN_SIDEBAR_WIDTH = 240;
const MAX_SIDEBAR_WIDTH = 480;
const DEFAULT_SIDEBAR_WIDTH = 300;
const SIDEBAR_STORAGE_KEY = "prismx.sidebarWidth";

const state = {
  loading: true,
  sending: false,
  activeTab: "chat",
  projects: [],
  sessionTrees: [],
  activeProjectId: null,
  activeTreeId: null,
  activeSessionId: null,
  sessionMessages: {},
  treeMemoryItems: [],
  longTermKnowledgeItems: [],
  treeView: { x: 0, y: 0, scale: 1 },
  drag: null,
  abortController: null,
  renderQueued: false,
  pendingMessageScroll: null,
  workspaceHandles: new Map(),
  files: { projectId: null, loading: false, error: "", tree: null, needsReconnect: false },
  sidebarWidth: readSidebarWidth(),
  resizingSidebar: false,
  modal: null,
  // TGM interactive state
  memorySearchQuery: "",
  memorySearchResults: null,
  rollbackPlan: null,
  expandedItems: new Set(),
  evidenceList: [],
  evidenceLoading: false,
  evidenceError: "",
  evidenceModal: null,
  memoryStatus: null,
  debugData: null,
  debugLoading: false,
  recallData: null,
  recallLoading: false,
  traceData: null,
  traceLoading: false,
  traceExpanded: new Set(),
  graphData: null,
  graphLoading: false,
  graphView: { x: 0, y: 0, scale: 1 },
};

const WORKSPACE_DB = "prismx-workspaces";
const WORKSPACE_STORE = "handles";
const FILE_TREE_MAX_DEPTH = 2;
const FILE_TREE_MAX_ITEMS = 200;
const NODE_WIDTH = 260;
const NODE_HEIGHT = 112;
const HORIZONTAL_GAP = 170;
const VERTICAL_GAP = 72;
const TREE_PADDING = 56;

const nodes = {
  app: document.querySelector("#app"),
  toast: document.querySelector("#toast"),
};

async function init() {
  window.addEventListener("keydown", handleGlobalKeydown);
  render();
  await loadWorkspace();
}

async function loadWorkspace() {
  state.loading = true;
  render();
  try {
    const payload = await apiGet("/api/workspace");
    applyWorkspace(payload);
  } catch (error) {
    showToast(`Unable to load workspace: ${error.message}`);
  } finally {
    state.loading = false;
    render();
  }
}

function applyWorkspace(payload) {
  state.projects = (payload.projects || []).map(normalizeProject);
  state.sessionTrees = payload.sessionTrees || [];
  state.activeProjectId = payload.activeProjectId || state.projects[0]?.id || null;
  const newTreeId = payload.activeTreeId || state.sessionTrees[0]?.id || null;
  if (newTreeId !== state.activeTreeId) {
    state.evidenceList = [];
    state.memoryStatus = null;
  }
  state.activeTreeId = newTreeId;
  const activeTree = getActiveTree();
  state.activeSessionId = payload.activeSessionId || activeTree?.activeSessionId || activeTree?.rootSessionId || null;
  state.sessionMessages = payload.sessionMessages || {};
  state.treeMemoryItems = payload.treeMemoryItems || [];
  state.longTermKnowledgeItems = payload.longTermKnowledgeItems || [];
}

function render() {
  const children = [
    Header(),
    el("div", {
      class: `workspace-shell ${state.resizingSidebar ? "resizing" : ""}`,
      style: `grid-template-columns: ${state.sidebarWidth}px 4px minmax(0, 1fr);`,
    }, [
      ProjectSidebar(),
      el("div", {
        class: "sidebar-resizer",
        role: "separator",
        "aria-orientation": "vertical",
        title: "Resize sidebar",
        onmousedown: startSidebarResize,
      }),
      el("main", { class: "workspace-main" }, [WorkspaceTabs(), activeWorkspace()]),
    ]),
  ];
  if (state.modal) children.push(ModalHost());
  nodes.app.replaceChildren(...children);
}

function scheduleRender() {
  if (state.renderQueued) return;
  state.renderQueued = true;
  window.requestAnimationFrame(() => {
    state.renderQueued = false;
    render();
    restoreMessageScroll(state.pendingMessageScroll);
    state.pendingMessageScroll = null;
  });
}

function renderPreservingMessageScroll() {
  state.pendingMessageScroll = state.pendingMessageScroll || captureMessageScroll();
  scheduleRender();
}

function normalizeProject(project) {
  const name = String(project.name || project.title || "Untitled Project");
  return {
    ...project,
    name,
    title: String(project.title || name),
    treeIds: project.treeIds || [],
    workspaceName: project.workspaceName || "",
    workspaceDisplayPath: project.workspaceDisplayPath || "",
  };
}

function projectName(project) {
  return project?.name || project?.title || "Untitled Project";
}

function projectWorkspaceLabel(project) {
  return project?.workspaceDisplayPath || project?.workspaceName || "";
}

function Header() {
  const activeProject = getActiveProject();
  const activeSession = getActiveSession();
  const workspace = projectWorkspaceLabel(activeProject) || "No workspace folder";
  return el("header", { class: "top-header" }, [
    el("div", { class: "brand-block" }, [
      el("div", { class: "brand-mark", "aria-hidden": "true" }, "PX"),
      el("div", {}, [
        el("strong", {}, "PrismX"),
        el("span", {}, `Project: ${projectName(activeProject)} / Workspace: ${workspace} / Active Session: ${activeSession?.title || "-"}`),
      ]),
    ]),
    el("div", { class: "header-actions" }, [
      el("button", {
        class: `status-badge api-status ${state.loading ? "" : "live"}`,
        type: "button",
        onclick: () => openApiStatusModal(),
      }, state.loading ? "syncing" : "API Connected"),
      iconButton("Refresh", "Refresh workspace", () => loadWorkspace()),
      button("Settings", "", () => openSettingsModal()),
      el("div", { class: "avatar", title: "PrismX user" }, "P"),
    ]),
  ]);
}

function ProjectSidebar() {
  const activeProject = getActiveProject() || state.projects[0];
  return el("aside", { class: "project-sidebar", "aria-label": "Project management" }, [
    el("div", { class: "sidebar-head" }, [
      el("div", {}, [el("p", { class: "eyebrow" }, "Workspace"), el("h2", {}, "Projects")]),
      iconButton("+", "New project", () => createProject()),
    ]),
    el("div", { class: "sidebar-actions" }, [
      button("New Project", "secondary", () => createProject()),
      button("New Session Tree", "secondary accent", () => createSessionTree(activeProject?.id)),
    ]),
    el("nav", { class: "project-list" }, state.projects.map((project) => ProjectItem(project))),
  ]);
}

function ProjectItem(project) {
  const active = project.id === state.activeProjectId;
  const trees = (project.treeIds || [])
    .map((treeId) => state.sessionTrees.find((tree) => tree.id === treeId))
    .filter(Boolean);
  return el("section", { class: `project-item ${active ? "active" : ""}` }, [
    el("div", {
      class: "project-button",
      onclick: () => {
        state.activeProjectId = project.id;
        const firstTree = trees[0];
        if (firstTree) selectSession(firstTree.activeSessionId || firstTree.rootSessionId);
        else {
          render();
          if (state.activeTab === "files") loadFilesForActiveProject();
        }
      },
    }, [
      el("span", { class: "project-dot" }),
      el("span", { class: "project-copy" }, [
        el("strong", {}, projectName(project)),
        projectWorkspaceLabel(project) ? el("small", {}, projectWorkspaceLabel(project)) : null,
      ]),
      el("em", {}, String(trees.length)),
      projectRowAction("+", "New Session Tree", () => createSessionTree(project.id)),
      projectRowAction("R", "Rename Project", () => renameProject(project.id)),
      projectRowAction("X", "Delete Project", () => deleteProject(project.id)),
    ]),
    el("div", { class: "tree-list" }, trees.map((tree) => TreeLink(project, tree))),
  ]);
}

function TreeLink(project, tree) {
  const selected = project.id === state.activeProjectId && tree.id === state.activeTreeId;
  const activeSession = findSessionInTree(tree, tree.activeSessionId);
  return el("div", {
    class: `tree-link ${selected ? "selected" : ""}`,
    onclick: () => selectSession(tree.activeSessionId || tree.rootSessionId),
  }, [
    el("div", { class: "tree-link-copy" }, [
      el("span", {}, "Session Tree"),
      el("strong", {}, tree.title || "Untitled Tree"),
      activeSession ? el("small", {}, activeSession.title) : null,
    ]),
    el("div", { class: "tree-row-actions" }, [
      projectRowAction("R", "Rename Session Tree", () => renameSessionTree(tree.id)),
      projectRowAction("X", "Delete Session Tree", () => deleteSessionTree(tree.id)),
    ]),
  ]);
}

function WorkspaceTabs() {
  return el("section", { class: "workspace-tabs", "aria-label": "Workspace tabs" }, [
    tabButton("chat", "Chat"),
    tabButton("tree", "Tree"),
    tabButton("memory", "Memory"),
    tabButton("evidence", "Evidence"),
    tabButton("debug", "Debug"),
    tabButton("trace", "Trace"),
    tabButton("graph", "Graph"),
    tabButton("files", "Files"),
  ]);
}

function tabButton(id, label) {
  return el("button", {
    class: `workspace-tab ${state.activeTab === id ? "active" : ""}`,
    type: "button",
    onclick: () => {
      state.activeTab = id;
      render();
      if (id === "files") loadFilesForActiveProject();
    },
  }, label);
}

function activeWorkspace() {
  if (state.loading) return el("section", { class: "workspace-view empty-view" }, "Loading PrismX workspace...");
  if (state.activeTab === "files") return FilesWorkspace();
  if (state.activeTab === "graph") {
    if (!state.graphData && !state.graphLoading) {
      setTimeout(() => loadGraphData(), 0);
    }
    return GraphWorkspace();
  }
  if (!getActiveTree() || !getActiveSession()) {
    return el("section", { class: "workspace-view empty-view" }, [
      el("h1", {}, "No Session Tree"),
      el("p", {}, "Create a project or Session Tree to start working."),
    ]);
  }
  if (state.activeTab === "tree") return TreeWorkspace();
  if (state.activeTab === "memory") return MemoryWorkspace();
  if (state.activeTab === "evidence") {
    if (state.evidenceList.length === 0 && !state.evidenceLoading && !state.memoryStatus) {
      loadEvidenceList();
    }
    return EvidenceWorkspace();
  }
  if (state.activeTab === "debug") {
    if (!state.debugData && !state.debugLoading) {
      setTimeout(() => loadDebugData(), 0);
    }
    return DebugWorkspace();
  }
  if (state.activeTab === "trace") {
    if (!state.traceData && !state.traceLoading) {
      setTimeout(() => loadTraceData(), 0);
    }
    return TraceWorkspace();
  }
  return ChatWorkspace();
}

function ChatWorkspace() {
  const session = getActiveSession();
  const messages = getActiveMessages();
  return el("section", { class: "workspace-view chat-workspace" }, [
    el("div", { class: "chat-column" }, [
      TitleRow("Agent Runtime", session.title, [
        el("span", { class: `node-status ${session.status}` }, session.status),
        button("New Child Session", "primary", () => createChildSession(session.id)),
      ]),
      el("div", { class: "session-context-row" }, [
        infoPill("Project", projectName(getActiveProject())),
        infoPill("Tree", getActiveTree()?.title || "-"),
        infoPill("Messages", String(messages.length)),
      ]),
      el("div", { class: "messages-scroll-area message-list" }, messages.length
        ? messages.map((message) => MessageCard(message))
        : [EmptyState("This Session has no messages yet.")]),
      CommandInput(),
    ]),
  ]);
}

function MessageCard(message) {
  const role = message.role || message.kind || "assistant";
  return el("article", { class: `message-card ${role}` }, [
    el("div", { class: "message-meta" }, [
      el("span", {}, role === "user" ? "User" : "Agent"),
      el("time", {}, formatTime(message.createdAt)),
    ]),
    el("p", {}, message.output || message.summary || message.text || "(empty)"),
    message.toolCalls?.length
      ? el("div", { class: "tool-chip-row" }, message.toolCalls.map((tool) => ToolChip(tool)))
      : null,
  ]);
}

function ToolChip(tool) {
  return el("button", {
    class: `tool-chip ${toolKind(tool)}`,
    type: "button",
    title: tool.output || tool.name,
    onclick: () => showToast(`${tool.name}: ${tool.status || "done"}`),
  }, `${tool.name} / ${tool.status || "done"}`);
}

function CommandInput() {
  return el("form", { class: "command-input", id: "composer", onsubmit: sendComposerMessage }, [
    el("div", { class: "command-hints" }, ["/help", "/tools", "/memory", "/tree"].map((item) =>
      el("button", { type: "button", onclick: () => insertCommand(item) }, item),
    )),
    el("div", { class: "composer-row" }, [
      el("textarea", {
        id: "composer-input",
        rows: "3",
        placeholder: "Tell PrismX what to do in this Session...",
      }),
      el("button", {
        id: "send-button",
        class: "send-button",
        type: state.sending ? "button" : "submit",
        onclick: state.sending ? stopGeneration : null,
      }, state.sending ? "Stop" : "Send"),
    ]),
  ]);
}

function TreeWorkspace() {
  const tree = getActiveTree();
  const sessions = tree.sessions || [];
  const activeId = state.activeSessionId;
  const layout = layoutSessionTree(sessions, tree.rootSessionId);
  const activePathIds = new Set(getActivePath(activeId).map((session) => session.id));
  return el("section", { class: "workspace-view tree-workspace" }, [
    TitleRow("Tree-Guided Memory Layer", "Session Tree", [
      button("New Child Session", "primary", () => createChildSession(activeId)),
    ]),
    el("div", {
      class: "tree-canvas",
      onpointerdown: startCanvasPan,
      onpointermove: movePointer,
      onpointerup: endPointer,
      onpointerleave: endPointer,
      onwheel: zoomCanvas,
    }, [
      el("div", {
        class: "tree-plane",
        style: [
          `width: ${layout.width}px`,
          `height: ${layout.height}px`,
          `transform: translate(${state.treeView.x}px, ${state.treeView.y}px) scale(${state.treeView.scale})`,
        ].join("; "),
      }, [
        el("svg", {
          class: "tree-edges",
          width: String(layout.width),
          height: String(layout.height),
        }, layout.edges.map((edge) => TreeEdge(edge, activePathIds))),
        ...layout.nodes.map((session) => SessionNodeCard(session, activePathIds)),
      ]),
    ]),
  ]);
}

function TreeEdge(edge, activePathIds) {
  const a = { x: edge.parent.x + NODE_WIDTH, y: edge.parent.y + NODE_HEIGHT / 2 };
  const b = { x: edge.child.x, y: edge.child.y + NODE_HEIGHT / 2 };
  const mid = (a.x + b.x) / 2;
  const active = activePathIds.has(edge.parent.id) && activePathIds.has(edge.child.id);
  return el("path", {
    class: active ? "active" : "",
    fill: "none",
    stroke: active ? "#6366F1" : "#CBD5E1",
    "stroke-linecap": "round",
    "stroke-width": active ? "3" : "2",
    opacity: active ? "1" : "0.7",
    d: `M ${a.x} ${a.y} C ${mid} ${a.y}, ${mid} ${b.y}, ${b.x} ${b.y}`,
  });
}

function SessionNodeCard(session, activePathIds) {
  const active = session.id === state.activeSessionId;
  const inPath = activePathIds.has(session.id);
  const root = session.id === getActiveTree()?.rootSessionId;
  return el("article", {
    class: `session-card ${inPath ? "path" : ""} ${active ? "selected" : ""}`,
    style: `left: ${session.x}px; top: ${session.y}px;`,
    onclick: (event) => {
      event.stopPropagation();
      selectSession(session.id);
    },
    ondblclick: (event) => {
      event.stopPropagation();
      renameSession(session.id);
    },
  }, [
    el("div", { class: "node-head" }, [
      el("span", { class: `node-status ${session.status}` }, session.status || "idle"),
      el("div", { class: "node-actions" }, [
        nodeAction("+", "New child", () => createChildSession(session.id)),
        nodeAction("R", "Rename", () => renameSession(session.id)),
        nodeAction("X", root ? "Root cannot be deleted" : "Delete", () => deleteSession(session.id), root),
      ]),
    ]),
    el("strong", {}, session.title || "Untitled Session"),
    el("span", { class: "node-memory" }, `${getMessagesForSession(session.id).length} messages`),
  ]);
}

function MemoryWorkspace() {
  const path = getActivePath();
  const memoryItems = getTreeMemoryForActiveTree();
  const knowledge = getKnowledgeForActiveContext();
  const stats = getWorkingContextStats();
  const results = state.memorySearchResults !== null ? state.memorySearchResults : memoryItems;

  return el("section", { class: "workspace-view memory-workspace" }, [
    TitleRow("Tree-Guided Memory Layer", "Knowledge Space", [
      button("Fold Recent", "primary", () => executeMemoryFold()),
    ]),
    el("div", { class: "memory-toolbar" }, [
      el("div", { class: "memory-search" }, [
        el("input", {
          type: "text",
          class: "memory-search-input",
          placeholder: "Search tree memory...",
          value: state.memorySearchQuery,
          oninput: (event) => {
            state.memorySearchQuery = event.target.value;
            if (!state.memorySearchQuery.trim()) {
              state.memorySearchResults = null;
              render();
            }
          },
          onkeydown: (event) => {
            if (event.key === "Enter") executeMemorySearch();
          },
        }),
        button("Search", "secondary", () => executeMemorySearch()),
        state.memorySearchResults !== null
          ? button("Clear", "secondary", () => {
              state.memorySearchQuery = "";
              state.memorySearchResults = null;
              render();
            })
          : null,
      ]),
    ]),
    el("div", { class: "memory-grid" }, [
      ContextCard("Active Path Context", path.map((session, index) =>
        `${index + 1}. ${session.title} / ${getMessagesForSession(session.id).length} messages`
      )),
      el("article", { class: "context-card memory-items-card" }, [
        el("div", { class: "context-card-head" }, [
          el("h2", {}, "Tree Memory Recall"),
          el("span", { class: "context-count" }, String(results.length)),
        ]),
        el("div", { class: "context-lines memory-items-list" },
          results.length
            ? results.map((item) => MemoryItemCard(item))
            : [el("p", {}, state.memorySearchResults !== null ? "No matching tree memory items." : "No tree memory items for this tree yet.")]
        ),
      ]),
      ContextCard("Long-term Knowledge Recall", knowledge.length ? knowledge.map(renderKnowledgeLine) : ["No long-term knowledge items yet."]),
      ContextCard("Working Context Preview", [
        `Active Path Sessions: ${stats.activePathSessions}`,
        `Active Path Messages: ${stats.activePathMessages}`,
        `Tree Memory Items: ${stats.treeMemoryItems}`,
        `Current Session Messages: ${stats.currentSessionMessages}`,
        `Long-term Knowledge Items: ${stats.longTermKnowledgeItems}`,
      ]),
    ]),
    state.rollbackPlan ? RollbackPlanModal(state.rollbackPlan) : null,
  ]);
}

function EvidenceWorkspace() {
  const tree = getActiveTree();
  const loading = state.evidenceLoading;
  const items = state.evidenceList;
  const modal = state.evidenceModal;

  return el("section", { class: "workspace-view evidence-workspace" }, [
    TitleRow("Evidence Layer", "Execution Evidence", [
      button("Refresh", "secondary", () => loadEvidenceList()),
    ]),
    el("div", { class: "session-context-row" }, [
      infoPill("Tree", tree?.title || "-"),
      infoPill("Evidence Items", String(items.length)),
    ]),
    loading
      ? EmptyState("Loading evidence...")
      : state.evidenceError
        ? EmptyState(state.evidenceError)
        : items.length
          ? el("div", { class: "evidence-list" }, items.map((ev) => EvidenceCard(ev)))
          : EmptyState("No evidence recorded for this session tree yet. Evidence is created when the agent runs tools or encounters errors."),
    modal ? EvidenceViewModal(modal) : null,
  ]);
}

function EvidenceCard(ev) {
  return el("div", {
    class: `evidence-card type-${ev.evidenceType || ev.evidence_type || "note"}`,
    onclick: () => openEvidenceView(ev),
    title: "Click to view content",
  }, [
    el("span", { class: "evidence-type-badge" }, ev.evidenceType || ev.evidence_type || "note"),
    el("strong", {}, ev.title || ev.path || ev.id),
    ev.createdAt ? el("time", {}, formatTime(ev.createdAt)) : null,
  ]);
}

function EvidenceViewModal(ev) {
  return el("div", {
    class: "modal-backdrop",
    onclick: (event) => { if (event.target === event.currentTarget) closeEvidenceView(); },
  }, [
    el("section", { class: "modal-card evidence-modal", role: "dialog", "aria-modal": "true" }, [
      el("div", { class: "modal-head" }, [
        el("div", {}, [
          el("p", { class: "eyebrow" }, `Evidence / ${ev.evidenceType || ev.evidence_type}`),
          el("h2", {}, ev.title || ev.path || "Evidence Detail"),
        ]),
        iconButton("X", "Close", () => closeEvidenceView()),
      ]),
      el("div", { class: "modal-body evidence-body" }, [
        el("div", { class: "evidence-meta" }, [
          el("span", {}, `ID: ${ev.id}`),
          ev.sourceEventId ? el("span", {}, `Source Event: ${ev.sourceEventId}`) : null,
          ev.createdAt ? el("span", {}, formatTime(ev.createdAt)) : null,
        ].filter(Boolean)),
        el("pre", { class: "evidence-content" }, ev._content || "(empty)"),
      ]),
      el("div", { class: "modal-actions" }, [
        button("Close", "secondary", () => closeEvidenceView()),
      ]),
    ]),
  ]);
}

async function loadEvidenceList() {
  state.evidenceLoading = true;
  state.evidenceError = "";
  render();
  try {
    const status = await apiGet("/api/memory/status");
    state.memoryStatus = status;
    const tree = getActiveTree();
    const treeId = status.treeId || status.tree_id || tree?.id || state.activeTreeId;
    if (!treeId) {
      state.evidenceList = [];
      state.evidenceError = "No active session tree";
    } else {
      const evidenceData = status.evidence_items || status.evidence;
      const evidenceList = Array.isArray(evidenceData) ? evidenceData : [];
      state.evidenceList = evidenceList.map(function(ev) {
        return typeof ev === "string" ? { id: ev, evidenceType: "note", title: ev } : ev;
      });
    }
  } catch (err) {
    state.evidenceError = "Failed to load evidence: " + err.message;
    state.evidenceList = [];
  } finally {
    state.evidenceLoading = false;
    render();
  }
}

async function openEvidenceView(ev) {
  try {
    const result = await apiGet("/api/memory/evidence/" + encodeURIComponent(ev.id));
    state.evidenceModal = { ...ev, _content: result.content || "(no content)" };
  } catch (err) {
    state.evidenceModal = { ...ev, _content: "(failed to load: " + err.message + ")" };
  }
  render();
}

function closeEvidenceView() {
  state.evidenceModal = null;
  render();
}

async function loadDebugData() {
  state.debugLoading = true;
  state.recallLoading = true;
  render();
  try {
    var _a = await Promise.all([
      apiGet("/api/context/debug"),
      apiGet("/api/memory/promotion-log").catch(function() { return { entries: [] }; }),
      apiGet("/api/context/runtime-recall").catch(function() { return { available: false, reason: "API unavailable" }; }),
    ]);
    var debugData = _a[0];
    var promoData = _a[1];
    var recallData = _a[2];
    state.debugData = Object.assign({}, debugData, { promotionLog: promoData.entries || [] });
    state.recallData = recallData;
  } catch (err) {
    showToast("Failed to load debug data: " + err.message);
    state.debugData = { error: err.message };
    state.recallData = { available: false, reason: err.message };
  } finally {
    state.debugLoading = false;
    state.recallLoading = false;
    render();
  }
}

function DebugWorkspace() {
  const data = state.debugData;
  const loading = state.debugLoading;
  const recall = state.recallData;
  const recallLoading = state.recallLoading;

  return el("section", { class: "workspace-view debug-workspace" }, [
    TitleRow("Runtime Recall", "Context Debug", [
      button("Refresh", "secondary", () => loadDebugData()),
    ]),
    // ── Runtime Recall Panel ──
    recallLoading
      ? EmptyState("Loading runtime recall data...")
      : recall && recall.available
        ? el("div", { class: "recall-panel" }, [
            RecallCoarseCard(recall),
            RecallIntentCard(recall),
            RecallResultsCard(recall),
            RecallRenderedCard(recall),
          ])
        : (recall && !recall.available)
          ? el("div", { class: "recall-panel recall-unavailable" }, [
              el("p", { class: "recall-empty-note" }, "Runtime Recall data not yet available. Send a message to trigger the TGM recall pipeline."),
              recall.reason ? el("p", { class: "recall-empty-reason" }, "Reason: " + recall.reason) : null,
            ])
          : null,
    // ── Context Debug Grid ──
    loading
      ? EmptyState("Loading context debug data...")
      : !data
        ? EmptyState("Click Refresh to load context debug data.")
        : data.error
          ? EmptyState("Error: " + data.error)
          : el("div", { class: "debug-grid" }, [
              DebugSummaryCard(data),
              DebugEntriesCard("Active Path Entries", data.activePathEntryIds || [], data.contextLayers || {}),
              DebugEntriesCard("Included Entries", data.includedEntryIds || [], data.contextLayers || {}),
              DebugExcludedCard(data.excludedEntryIds || [], data.excludedReason || {}, data.contextLayers || {}),
              DebugPromotionCard(data.promotionLog || []),
              data.siblingBranchEntryIds && data.siblingBranchEntryIds.length > 0
                ? DebugEntriesCard("Sibling Branch Entries", data.siblingBranchEntryIds, data.contextLayers || {})
                : null,
            ].filter(Boolean)),
  ]);
}

function DebugSummaryCard(data) {
  return el("article", { class: "context-card debug-card" }, [
    el("div", { class: "context-card-head" }, [
      el("h2", {}, "Context Summary"),
      el("span", { class: "context-count" }, "4"),
    ]),
    el("div", { class: "debug-summary-grid" }, [
      DebugSummaryRow("Active Leaf ID", data.activeLeafId || "-"),
      DebugSummaryRow("Estimated Tokens", String(data.estimatedTokens ?? 0)),
      DebugSummaryRow("Compaction Applied", data.compactionApplied ? "Yes" : "No", data.compactionApplied),
      DebugSummaryRow("Branch Summary", data.branchSummaryApplied ? "Yes" : "No", data.branchSummaryApplied),
    ]),
  ]);
}

function DebugSummaryRow(label, value, positive) {
  return el("div", { class: "debug-summary-row" }, [
    el("span", { class: "debug-summary-label" }, label),
    el("span", {
      class: "debug-summary-value" + (positive !== null && positive !== undefined ? (positive ? " status-included" : " status-excluded") : ""),
    }, value),
  ]);
}

function DebugEntriesCard(title, entryIds, contextLayers) {
  return el("article", { class: "context-card debug-card" }, [
    el("div", { class: "context-card-head" }, [
      el("h2", {}, title),
      el("span", { class: "context-count" }, String(entryIds.length)),
    ]),
    el("div", { class: "debug-entries-list" },
      entryIds.length
        ? entryIds.map(function(id) { return DebugEntryRow(id, contextLayers[id] || "-"); })
        : [el("p", { class: "debug-empty-note" }, "No entries.")]
    ),
  ]);
}

function DebugEntryRow(entryId, layer) {
  return el("div", { class: "debug-entry" }, [
    el("code", { class: "debug-entry-id" }, entryId),
    el("span", { class: "layer-badge" }, layer),
  ]);
}

function DebugExcludedCard(entryIds, reasons, contextLayers) {
  return el("article", { class: "context-card debug-card" }, [
    el("div", { class: "context-card-head" }, [
      el("h2", {}, "Excluded Entries"),
      el("span", { class: "context-count context-count-excluded" }, String(entryIds.length)),
    ]),
    el("div", { class: "debug-entries-list" },
      entryIds.length
        ? entryIds.map(function(id) { return DebugExcludedRow(id, reasons[id] || "unknown", contextLayers[id] || "-"); })
        : [el("p", { class: "debug-empty-note" }, "No excluded entries.")]
    ),
  ]);
}

function DebugExcludedRow(entryId, reason, layer) {
  return el("div", { class: "debug-entry excluded" }, [
    el("code", { class: "debug-entry-id" }, entryId),
    el("span", { class: "layer-badge" }, layer),
    el("span", { class: "reason-badge", title: reason }, reason),
  ]);
}

function DebugPromotionCard(entries) {
  return el("article", { class: "context-card debug-card" }, [
    el("div", { class: "context-card-head" }, [
      el("h2", {}, "Promotion Log"),
      el("span", { class: "context-count" }, String(entries.length)),
    ]),
    el("div", { class: "debug-entries-list" },
      entries.length
        ? entries.map(function(entry) { return DebugPromotionEntry(entry); })
        : [el("p", { class: "debug-empty-note" }, "No promotions recorded yet.")]
    ),
  ]);
}

function DebugPromotionEntry(entry) {
  var time = entry.timestamp || entry.created_at || entry.createdAt || "";
  var foldId = entry.fold_id || entry.foldId || "-";
  var type = entry.type || entry.memory_type || "unknown";
  var uri = entry.uri || entry.result_uri || "";
  var sourceTreeId = entry.tree_id || entry.source_tree_id || entry.sourceTreeId || "-";

  return el("div", { class: "debug-entry" }, [
    el("time", { class: "debug-entry-time" }, formatTime(time)),
    el("code", { class: "debug-entry-id" }, foldId),
    el("span", { class: "memory-type-badge type-" + type }, type),
    uri ? el("span", { class: "layer-badge", title: uri }, uri.length > 50 ? uri.slice(0, 48) + ".." : uri) : null,
    el("span", { class: "layer-badge" }, "tree: " + sourceTreeId),
  ].filter(Boolean));
}

// ═══════════════════════════════════════════
// Runtime Recall Debug Cards
// ═══════════════════════════════════════════

function RecallCoarseCard(recall) {
  var needsRetrieval = recall.needs_retrieval;
  var reason = recall.coarse_reasoning || "(no reasoning recorded)";
  return el("article", { class: "context-card recall-card recall-coarse" }, [
    el("div", { class: "context-card-head" }, [
      el("h2", {}, "1. Coarse Reasoning"),
      el("span", {
        class: "recall-decision-badge " + (needsRetrieval ? "needs-yes" : "needs-no"),
      }, needsRetrieval ? "NEEDS RETRIEVAL" : "SKIP RETRIEVAL"),
    ]),
    el("div", { class: "recall-reason" }, [
      el("strong", {}, "Query: "),
      el("span", {}, recall.query || "-"),
    ]),
    el("div", { class: "recall-reason" }, [
      el("strong", {}, "Decision: "),
      el("span", {}, reason),
    ]),
  ]);
}

function RecallIntentCard(recall) {
  var intent = recall.retrieval_intent;
  if (!intent) {
    return el("article", { class: "context-card recall-card recall-intent" }, [
      el("div", { class: "context-card-head" }, [
        el("h2", {}, "2. Retrieval Intent"),
        el("span", { class: "context-count" }, "SKIPPED"),
      ]),
      el("p", { class: "recall-empty-note" }, "Coarse reasoning determined retrieval was not needed."),
    ]);
  }
  return el("article", { class: "context-card recall-card recall-intent" }, [
    el("div", { class: "context-card-head" }, [
      el("h2", {}, "2. Retrieval Intent"),
      el("span", { class: "context-count" }, "GENERATED"),
    ]),
    el("div", { class: "recall-intent-grid" }, [
      RecallIntentField("Query", intent.query),
      RecallIntentField("Keywords", (intent.keywords || []).join(", ") || "-"),
      RecallIntentField("Node Types", (intent.node_types || []).join(", ") || "(all)"),
      RecallIntentField("Statuses", (intent.statuses || []).join(", ") || "-"),
      RecallIntentField("Needs Evidence", intent.needs_evidence ? "Yes" : "No"),
      RecallIntentField("Limit", String(intent.limit || 5)),
    ]),
  ]);
}

function RecallIntentField(label, value) {
  return el("div", { class: "recall-intent-field" }, [
    el("span", { class: "recall-intent-label" }, label),
    el("span", { class: "recall-intent-value" }, value),
  ]);
}

function RecallResultsCard(recall) {
  var treeCount = recall.tree_memory_count || 0;
  var evidenceCount = recall.evidence_snippets_count || 0;
  var longCount = recall.long_term_count || 0;
  var treeItems = recall.tree_memory_items || [];
  var evidenceItems = recall.evidence_snippets || [];
  var longItems = recall.long_term_items || [];

  return el("article", { class: "context-card recall-card recall-results" }, [
    el("div", { class: "context-card-head" }, [
      el("h2", {}, "3. ContextPacket Overview"),
      el("span", { class: "context-count" }, (treeCount + evidenceCount + longCount) + " total"),
    ]),
    el("div", { class: "recall-results-grid" }, [
      el("div", { class: "recall-layer" }, [
        el("span", { class: "recall-layer-head" }, "Tree Memory (" + treeCount + ")"),
        treeCount
          ? el("div", { class: "recall-layer-items" }, treeItems.slice(0, 5).map(function(item) {
              return el("div", { class: "recall-layer-item" }, [
                el("code", {}, item.uri || "-"),
                el("span", {}, (item.title || "").slice(0, 80)),
              ]);
            }))
          : el("p", { class: "recall-empty-note" }, "No tree memory items recalled."),
      ]),
      el("div", { class: "recall-layer" }, [
        el("span", { class: "recall-layer-head" }, "Evidence Snippets (" + evidenceCount + ")"),
        evidenceCount
          ? el("div", { class: "recall-layer-items" }, evidenceItems.slice(0, 5).map(function(item) {
              return el("div", { class: "recall-layer-item" }, [
                el("code", {}, item.uri || "-"),
                el("span", {}, (item.snippet || item.title || "").slice(0, 120)),
              ]);
            }))
          : el("p", { class: "recall-empty-note" }, "No evidence snippets recalled."),
      ]),
      el("div", { class: "recall-layer" }, [
        el("span", { class: "recall-layer-head" }, "Long-term Knowledge (" + longCount + ")"),
        longCount
          ? el("div", { class: "recall-layer-items" }, longItems.slice(0, 5).map(function(item) {
              return el("div", { class: "recall-layer-item" }, [
                el("code", {}, item.uri || "-"),
                el("span", {}, (item.title || "").slice(0, 80)),
              ]);
            }))
          : el("p", { class: "recall-empty-note" }, "No long-term knowledge items recalled."),
      ]),
    ]),
  ]);
}

function RecallRenderedCard(recall) {
  var rendered = recall.rendered;
  if (!rendered) return null;
  return el("article", { class: "context-card recall-card recall-rendered" }, [
    el("div", { class: "context-card-head" }, [
      el("h2", {}, "4. Rendered Context (injected into model)"),
      el("span", { class: "context-count" }, (rendered.length > 400 ? "truncated" : "full")),
    ]),
    el("pre", { class: "recall-rendered-content" }, rendered),
  ]);
}

async function loadTraceData() {
  state.traceLoading = true;
  render();
  try {
    const status = await apiGet("/api/memory/status");
    state.traceData = status;
    state.memoryStatus = status;
  } catch (err) {
    showToast("Failed to load trace data: " + err.message);
    state.traceData = { error: err.message };
  } finally {
    state.traceLoading = false;
    render();
  }
}

function TraceWorkspace() {
  const data = state.traceData;
  const loading = state.traceLoading;

  if (loading) {
    return el("section", { class: "workspace-view trace-workspace" }, [
      TitleRow("Execution Trace", "Timeline", [button("Refresh", "secondary", () => loadTraceData())]),
      EmptyState("Loading trace events..."),
    ]);
  }
  if (!data) {
    return el("section", { class: "workspace-view trace-workspace" }, [
      TitleRow("Execution Trace", "Timeline", [button("Refresh", "secondary", () => loadTraceData())]),
      EmptyState("Click Refresh to load the execution trace timeline."),
    ]);
  }
  if (data.error) {
    return el("section", { class: "workspace-view trace-workspace" }, [
      TitleRow("Execution Trace", "Timeline", [button("Refresh", "secondary", () => loadTraceData())]),
      EmptyState("Error: " + data.error),
    ]);
  }

  const items = data.evidence_items || [];
  const traceEvents = data.traceEvents || items.length;
  const foldedNodes = data.foldedNodes || 0;
  const sorted = items.slice().sort(function(a, b) {
    return (a.createdAt || "").localeCompare(b.createdAt || "");
  });

  return el("section", { class: "workspace-view trace-workspace" }, [
    TitleRow("Execution Trace", "Timeline", [button("Refresh", "secondary", () => loadTraceData())]),
    el("div", { class: "session-context-row" }, [
      infoPill("Trace Events", String(traceEvents)),
      infoPill("Folded Nodes", String(foldedNodes)),
      infoPill("Evidence Items", String(items.length)),
    ]),
    sorted.length
      ? el("div", { class: "trace-timeline" }, sorted.map(function(ev) { return TraceEntry(ev); }))
      : EmptyState("No trace events recorded yet."),
  ]);
}

function traceEventKind(evidenceType) {
  switch (evidenceType) {
    case "error_log": return "ERROR";
    case "command_output": return "TOOL_RESULT";
    case "code_snippet": return "TOOL_RESULT";
    default: return "ASSISTANT";
  }
}

function traceBadgeStyle(kind) {
  switch (kind) {
    case "ERROR": return "background: var(--red);";
    case "TOOL_RESULT": return "background: var(--prism-cyan);";
    case "TOOL_CALL": return "background: var(--amber);";
    case "USER": return "background: var(--prism-indigo);";
    default: return "background: var(--green);";
  }
}

function TraceEntry(ev) {
  var kind = traceEventKind(ev.evidenceType || ev.evidence_type);
  var badgeStyle = traceBadgeStyle(kind);
  var expanded = state.traceExpanded.has(ev.id);

  return el("div", { class: "trace-entry" }, [
    el("div", { class: "trace-dot", style: badgeStyle }),
    el("div", { class: "trace-card" }, [
      el("div", { class: "trace-card-head", onclick: function() { toggleTraceEntry(ev.id); } }, [
        el("time", { class: "trace-time" }, formatTime(ev.createdAt)),
        el("span", { class: "trace-type-badge", style: badgeStyle }, kind),
        el("strong", { class: "trace-title" }, ev.title || ev.path || ev.id),
        el("span", { class: "trace-expand" }, expanded ? "▲" : "▼"),
      ]),
      expanded ? el("div", { class: "trace-card-body" }, [
        el("div", { class: "evidence-meta" }, [
          el("span", {}, "ID: " + (ev.id || "-")),
          ev.sourceEventId ? el("span", { class: "trace-source-link", title: "Click to load source evidence", onclick: function(event) { event.stopPropagation(); openEvidenceView({ id: ev.sourceEventId }); } }, "Source: " + ev.sourceEventId) : null,
          ev.sourceEventId ? el("span", { class: "trace-fold-badge" }, "FOLDED") : null,
        ]),
        ev._content !== undefined
          ? el("pre", { class: "trace-content" }, ev._content || "(empty)")
          : el("p", { class: "trace-loading" }, "Loading..."),
      ]) : null,
    ]),
  ]);
}

async function toggleTraceEntry(evId) {
  if (state.traceExpanded.has(evId)) {
    state.traceExpanded.delete(evId);
    render();
    return;
  }
  state.traceExpanded.add(evId);
  render();
  var status = state.traceData;
  var items = status ? (status.evidence_items || []) : [];
  var item = null;
  for (var i = 0; i < items.length; i++) {
    if (items[i].id === evId) { item = items[i]; break; }
  }
  if (item && item._content === undefined) {
    try {
      var result = await apiGet("/api/memory/evidence/" + encodeURIComponent(evId));
      item._content = result.content || "(no content)";
    } catch (err) {
      item._content = "(failed to load: " + err.message + ")";
    }
    render();
  }
}

function FilesWorkspace() {
  const project = getActiveProject();
  const workspace = projectWorkspaceLabel(project);
  const files = state.files;
  const canPickDirectory = "showDirectoryPicker" in window;
  const needsLoad = project && files.projectId !== project.id && !files.loading;
  if (needsLoad) window.setTimeout(() => loadFilesForActiveProject(), 0);

  return el("section", { class: "workspace-view files-workspace" }, [
    TitleRow("Workspace Directory", "Files", [
      button("Reconnect Workspace", "secondary", () => reconnectWorkspace(project?.id), !project || !canPickDirectory),
    ]),
    el("div", { class: "session-context-row" }, [
      infoPill("Project", projectName(project)),
      infoPill("Workspace", workspace || "Not connected"),
    ]),
    !canPickDirectory
      ? EmptyState("This browser does not support the File System Access API.")
      : files.loading
        ? EmptyState("Reading workspace folder...")
        : files.error
          ? el("div", { class: "empty-state" }, [
            el("p", {}, files.error),
            button("Reconnect Workspace", "primary", () => reconnectWorkspace(project?.id), !project),
          ])
          : files.tree
            ? FileTree(files.tree)
            : el("div", { class: "empty-state" }, [
              el("p", {}, "No workspace folder is connected for this project."),
              button("Reconnect Workspace", "primary", () => reconnectWorkspace(project?.id), !project),
            ]),
  ]);
}

function FileTree(root) {
  return el("div", { class: "file-tree-panel" }, [
    el("div", { class: "file-tree-root" }, root.name),
    FileTreeList(root.children || []),
  ]);
}

function FileTreeList(items) {
  return el("ul", { class: "file-tree-list" }, items.map((item) =>
    el("li", { class: `file-tree-item ${item.kind}` }, [
      el("span", {}, `${item.kind === "directory" ? "folder" : "file"} / ${item.name}`),
      item.children?.length ? FileTreeList(item.children) : null,
    ]),
  ));
}

function ContextCard(title, lines) {
  return el("article", { class: "context-card" }, [
    el("h2", {}, title),
    el("div", { class: "context-lines" }, (lines.length ? lines : ["-"]).map((line) => el("p", {}, line))),
  ]);
}

function MemoryItemCard(item) {
  const itemId = item.foldId || item.id;
  const expanded = state.expandedItems.has(itemId);
  const memType = item.type || "finding";
  const status = item.status || "active";
  const reuse = item.reuseCount || 0;
  const confidence = Number(item.confidence || 0).toFixed(2);
  const heat = Math.min(reuse, 10);

  return el("div", { class: `memory-item ${expanded ? "expanded" : ""}` }, [
    el("div", { class: "memory-item-row", onclick: () => toggleMemoryItem(itemId) }, [
      el("span", { class: `memory-type-badge type-${memType}` }, memType),
      el("span", { class: "memory-item-content" }, item.content || item.title || itemId),
      el("span", { class: "memory-item-meta" }, [
        el("span", { class: `memory-status status-${status}` }, status),
        reuse > 0 ? el("span", {
          class: "memory-heat",
          style: `--heat: ${Math.min(heat / 10, 1)}; opacity: ${0.3 + Math.min(heat / 10, 1) * 0.7}`,
          title: `Reused ${reuse} times`,
        }, "\u{1F525} " + reuse) : null,
        el("span", {}, "conf " + confidence),
        item.promoted ? el("span", { class: "memory-promoted-badge" }, "promoted") : null,
      ].filter(Boolean)),
      el("span", { class: "memory-item-expand" }, expanded ? "▲" : "▼"),
    ]),
    expanded ? el("div", { class: "memory-item-detail" }, [
      el("div", { class: "memory-item-detail-meta" }, [
        el("span", {}, "ID: " + itemId),
        el("span", {}, "Type: " + memType),
        el("span", {}, "Status: " + status),
        el("span", {}, "Confidence: " + confidence),
        el("span", {}, "Reuse: " + reuse),
        item.sourceSessionId ? el("span", {}, "Source Session: " + item.sourceSessionId) : null,
      ].filter(Boolean)),
      item.evidenceIds && item.evidenceIds.length
        ? el("div", { class: "memory-item-evidence" }, [
            el("strong", {}, "Evidence:"),
            ...item.evidenceIds.map(function(eid) {
              return el("span", {
                class: "evidence-link",
                onclick: function(ev) { ev.stopPropagation(); openEvidenceView({ id: eid }); },
              }, eid);
            }),
          ])
        : null,
      el("div", { class: "memory-item-actions" }, [
        !item.promoted
          ? button("Promote", "primary", function(ev) { ev.stopPropagation(); executeMemoryPromote(item); })
          : null,
        status === "failed" || status === "partial" || memType === "failure" || memType === "partial_fix"
          ? button("Rollback", "secondary", function(ev) { ev.stopPropagation(); executeMemoryRollback(item); })
          : null,
      ]),
    ]) : null,
  ]);
}

function toggleMemoryItem(itemId) {
  if (state.expandedItems.has(itemId)) {
    state.expandedItems.delete(itemId);
  } else {
    state.expandedItems.add(itemId);
  }
  render();
}

function RollbackPlanModal(plan) {
  return el("div", {
    class: "modal-backdrop",
    onclick: (event) => { if (event.target === event.currentTarget) closeRollbackPlan(); },
  }, [
    el("section", { class: "modal-card rollback-modal", role: "dialog", "aria-modal": "true" }, [
      el("div", { class: "modal-head" }, [
        el("div", {}, [
          el("p", { class: "eyebrow" }, "Rollback Plan"),
          el("h2", {}, plan.itemTitle || plan.foldId || "Rollback"),
        ]),
        iconButton("X", "Close", () => closeRollbackPlan()),
      ]),
      el("div", { class: "modal-body" }, [
        plan.risk ? el("div", { class: "rollback-risk" }, [
          el("strong", {}, "Risk: "),
          el("span", {}, plan.risk),
        ]) : null,
        plan.related_files && plan.related_files.length ? el("div", { class: "rollback-section" }, [
          el("h3", {}, "Related Files"),
          el("ul", {}, plan.related_files.map(function(f) { return el("li", {}, f); })),
        ]) : null,
        plan.evidence_refs && plan.evidence_refs.length ? el("div", { class: "rollback-section" }, [
          el("h3", {}, "Evidence References"),
          el("ul", {}, plan.evidence_refs.map(function(ref) { return el("li", {}, ref); })),
        ]) : null,
        plan.suggested_steps && plan.suggested_steps.length ? el("div", { class: "rollback-section" }, [
          el("h3", {}, "Suggested Steps"),
          el("ol", {}, plan.suggested_steps.map(function(step) { return el("li", {}, step); })),
        ]) : null,
      ]),
      el("div", { class: "modal-actions" }, [
        button("Close", "secondary", () => closeRollbackPlan()),
      ]),
    ]),
  ]);
}

async function executeMemoryFold() {
  try {
    const title = "Fold " + new Date().toLocaleTimeString();
    const result = await apiPost("/api/memory/fold", { title: title });
    if (result.workspace) applyWorkspace(result.workspace);
    showToast(result.fold ? "Memory folded: " + (result.fold.title || result.fold.id) : "Fold completed");
  } catch (err) {
    showToast("Fold failed: " + err.message);
  }
}

async function executeMemorySearch() {
  const query = state.memorySearchQuery.trim();
  if (!query) {
    state.memorySearchResults = null;
    render();
    return;
  }
  try {
    const result = await apiPost("/api/memory/retrieve", { query: query, limit: 20 });
    state.memorySearchResults = result.items || [];
  } catch (err) {
    showToast("Search failed: " + err.message);
    state.memorySearchResults = [];
  }
  render();
}

async function executeMemoryPromote(item) {
  const foldId = item.foldId || item.id;
  if (!foldId) {
    showToast("No fold ID available for promotion");
    return;
  }
  try {
    const result = await apiPost("/api/memory/promote", { foldId: foldId, type: "pattern" });
    if (result.workspace) applyWorkspace(result.workspace);
    showToast(result.uri ? "Promoted: " + result.uri : "Promotion completed");
  } catch (err) {
    showToast("Promote failed: " + err.message);
  }
}

async function executeMemoryRollback(item) {
  const foldId = item.foldId || item.id;
  if (!foldId) {
    showToast("No fold ID available for rollback");
    return;
  }
  try {
    const plan = await apiPost("/api/memory/rollback-plan", { foldId: foldId });
    state.rollbackPlan = { ...plan, foldId: foldId, itemTitle: item.content || item.title || foldId };
    render();
  } catch (err) {
    showToast("Rollback failed: " + err.message);
  }
}

function closeRollbackPlan() {
  state.rollbackPlan = null;
  render();
}

function TitleRow(eyebrow, title, actions) {
  return el("div", { class: "workspace-title-row" }, [
    el("div", {}, [el("p", { class: "eyebrow" }, eyebrow), el("h1", {}, title)]),
    actions.length ? el("div", { class: "title-actions" }, actions) : null,
  ]);
}

function EmptyState(text) {
  return el("div", { class: "empty-state" }, text);
}

function ModalHost() {
  const modal = state.modal;
  if (!modal) return null;
  return el("div", {
    class: "modal-backdrop",
    onclick: (event) => {
      if (event.target === event.currentTarget) closeModal(null);
    },
  }, [
    el("section", { class: "modal-card", role: "dialog", "aria-modal": "true", "aria-labelledby": "modal-title" }, [
      el("div", { class: "modal-head" }, [
        el("div", {}, [
          el("p", { class: "eyebrow" }, modal.eyebrow || "PrismX"),
          el("h2", { id: "modal-title" }, modal.title),
        ]),
        iconButton("X", "Close", () => closeModal(null)),
      ]),
      modal.type === "input" ? InputModalBody(modal) : InfoModalBody(modal),
      el("div", { class: "modal-actions" }, [
        modal.cancelLabel ? button(modal.cancelLabel, "secondary", () => closeModal(null)) : null,
        modal.type === "input"
          ? button(modal.confirmLabel || "Save", "primary", () => submitInputModal())
          : modal.confirmLabel
            ? button(modal.confirmLabel, modal.danger ? "danger" : "primary", () => closeModal(true))
            : null,
      ]),
    ]),
  ]);
}

function InputModalBody(modal) {
  return el("div", { class: "modal-body" }, [
    modal.body ? el("p", {}, modal.body) : null,
    el("input", {
      id: "modal-input",
      class: "modal-input",
      value: modal.initialValue || "",
      placeholder: modal.placeholder || "",
      onkeydown: (event) => {
        if (event.key === "Enter") submitInputModal();
      },
    }),
  ]);
}

function InfoModalBody(modal) {
  const body = Array.isArray(modal.body) ? modal.body : [modal.body].filter(Boolean);
  return el("div", { class: "modal-body" }, body.map((item) =>
    typeof item === "string" ? el("p", {}, item) : item
  ));
}

function openInputModal({ title, body = "", initialValue = "", placeholder = "", confirmLabel = "Save", cancelLabel = "Cancel" }) {
  return openModal({ type: "input", title, body, initialValue, placeholder, confirmLabel, cancelLabel });
}

function openConfirmModal({ title, body, confirmLabel = "Delete", cancelLabel = "Cancel", danger = false }) {
  return openModal({ type: "confirm", title, body, confirmLabel, cancelLabel, danger });
}

function openInfoModal({ title, body, confirmLabel = "Close" }) {
  return openModal({ type: "info", title, body, confirmLabel, cancelLabel: "" });
}

function openModal(modal) {
  return new Promise((resolve) => {
    state.modal = { ...modal, resolve };
    render();
    window.requestAnimationFrame(() => document.querySelector("#modal-input")?.focus());
  });
}

function closeModal(result) {
  const modal = state.modal;
  state.modal = null;
  render();
  if (modal?.resolve) modal.resolve(result);
}

function submitInputModal() {
  const value = document.querySelector("#modal-input")?.value.trim() || "";
  if (!value) return;
  closeModal(value);
}

function handleGlobalKeydown(event) {
  if (event.key === "Escape" && state.modal) closeModal(null);
}

function openApiStatusModal() {
  const tree = getActiveTree();
  const session = getActiveSession();
  return openInfoModal({
    title: state.loading ? "API Syncing" : "API Connected",
    body: [
      detailRow("Connection", state.loading ? "Syncing workspace" : "Connected"),
      detailRow("Project", projectName(getActiveProject())),
      detailRow("Session Tree", tree?.title || "-"),
      detailRow("Active Session", session?.title || "-"),
      detailRow("Tree Memory", `${getTreeMemoryForActiveTree().length} items`),
      detailRow("Long-term Knowledge", `${state.longTermKnowledgeItems.length} items`),
      detailRow("Workspace Sessions", `${tree?.sessions?.length || 0} sessions`),
    ],
  });
}

function openSettingsModal() {
  return openInfoModal({
    title: "Settings",
    body: [
      detailRow("Model", "Managed by PrismX runtime"),
      detailRow("Memory", "Active Path, Tree Memory, Long-term Knowledge"),
      detailRow("Workspace", projectWorkspaceLabel(getActiveProject()) || "Not connected"),
      detailRow("Theme", "Prism Light"),
      detailRow("MCP", "Available through runtime tools"),
    ],
  });
}

function detailRow(label, value) {
  return el("div", { class: "modal-detail-row" }, [
    el("span", {}, label),
    el("strong", {}, value),
  ]);
}

async function createProject() {
  let handle = null;
  let name = "";
  if ("showDirectoryPicker" in window) {
    try {
      handle = await window.showDirectoryPicker();
      name = handle.name || "New Project";
    } catch (error) {
      if (error.name === "AbortError") return;
      showToast(`Unable to select workspace: ${error.message}`);
      return;
    }
  } else {
    name = await openInputModal({
      title: "New Project",
      body: "Name this project. Folder selection is unavailable in this browser.",
      initialValue: "New Project",
      confirmLabel: "Create",
    }) || "";
    if (!name) return;
    showToast("This browser does not support folder selection. Project created without a workspace folder.");
  }

  const payload = await apiPost("/api/projects", {
    name,
    title: name,
    workspaceName: handle?.name || "",
    workspaceDisplayPath: handle?.name || "",
  });
  applyWorkspace(payload);
  if (handle && state.activeProjectId) {
    state.workspaceHandles.set(state.activeProjectId, handle);
    try {
      await saveWorkspaceHandle(state.activeProjectId, handle);
    } catch (error) {
      showToast(`Workspace folder is connected for this tab, but could not be saved: ${error.message}`);
    }
  }
  render();
  if (state.activeTab === "files") loadFilesForActiveProject();
}

async function renameProject(projectId) {
  const project = state.projects.find((item) => item.id === projectId);
  if (!project) return;
  const name = await openInputModal({
    title: "Rename Project",
    initialValue: projectName(project),
    confirmLabel: "Save",
  });
  if (!name || name === projectName(project)) return;
  applyWorkspace(await apiPatch(`/api/projects/${encodeURIComponent(projectId)}`, { name, title: name }));
  render();
}

async function deleteProject(projectId) {
  const project = state.projects.find((item) => item.id === projectId);
  if (!project) return;
  const hasTrees = (project.treeIds || []).length > 0;
  const message = hasTrees
    ? "This project contains session trees. Delete the entire project?"
    : "Delete this project?";
  if (!(await openConfirmModal({
    title: "Delete Project?",
    body: `${message} This action cannot be undone.`,
    confirmLabel: "Delete",
    danger: true,
  }))) return;
  applyWorkspace(await apiDelete(`/api/projects/${encodeURIComponent(projectId)}`));
  state.workspaceHandles.delete(projectId);
  render();
}

async function reconnectWorkspace(projectId) {
  const project = state.projects.find((item) => item.id === projectId) || getActiveProject();
  if (!project || !("showDirectoryPicker" in window)) return;
  let handle = null;
  try {
    handle = await window.showDirectoryPicker();
  } catch (error) {
    if (error.name !== "AbortError") showToast(`Unable to select workspace: ${error.message}`);
    return;
  }
  state.workspaceHandles.set(project.id, handle);
  try {
    await saveWorkspaceHandle(project.id, handle);
  } catch (error) {
    showToast(`Workspace folder is connected for this tab, but could not be saved: ${error.message}`);
  }
  applyWorkspace(await apiPatch(`/api/projects/${encodeURIComponent(project.id)}`, {
    workspaceName: handle.name || "",
    workspaceDisplayPath: handle.name || "",
  }));
  render();
  loadFilesForActiveProject();
}

async function loadFilesForActiveProject() {
  const project = getActiveProject();
  if (!project) return;
  if (!("showDirectoryPicker" in window)) {
    state.files = {
      projectId: project.id,
      loading: false,
      error: "This browser does not support the File System Access API.",
      tree: null,
      needsReconnect: true,
    };
    render();
    return;
  }

  state.files = { projectId: project.id, loading: true, error: "", tree: null, needsReconnect: false };
  render();
  try {
    const handle = await getWorkspaceHandle(project.id);
    if (!handle) {
      state.files = { projectId: project.id, loading: false, error: "", tree: null, needsReconnect: true };
      render();
      return;
    }
    const permitted = await ensureReadPermission(handle);
    if (!permitted) {
      state.files = {
        projectId: project.id,
        loading: false,
        error: "Workspace permission is unavailable. Reconnect the workspace folder.",
        tree: null,
        needsReconnect: true,
      };
      render();
      return;
    }
    const counter = { count: 0 };
    const children = await readDirectoryTree(handle, 0, counter);
    state.files = {
      projectId: project.id,
      loading: false,
      error: "",
      tree: { name: handle.name || projectWorkspaceLabel(project) || projectName(project), kind: "directory", children },
      needsReconnect: false,
    };
  } catch (error) {
    state.files = {
      projectId: project.id,
      loading: false,
      error: `Unable to read workspace folder: ${error.message}`,
      tree: null,
      needsReconnect: true,
    };
  }
  render();
}

async function getWorkspaceHandle(projectId) {
  if (state.workspaceHandles.has(projectId)) return state.workspaceHandles.get(projectId);
  const handle = await loadWorkspaceHandle(projectId);
  if (handle) state.workspaceHandles.set(projectId, handle);
  return handle;
}

async function ensureReadPermission(handle) {
  if (!handle?.queryPermission) return true;
  const options = { mode: "read" };
  if ((await handle.queryPermission(options)) === "granted") return true;
  if (!handle.requestPermission) return false;
  return (await handle.requestPermission(options)) === "granted";
}

async function readDirectoryTree(handle, depth, counter) {
  if (depth >= FILE_TREE_MAX_DEPTH || counter.count >= FILE_TREE_MAX_ITEMS) return [];
  const entries = [];
  for await (const entry of handle.values()) {
    if (counter.count >= FILE_TREE_MAX_ITEMS) break;
    entries.push(entry);
  }
  entries.sort((a, b) => {
    if (a.kind !== b.kind) return a.kind === "directory" ? -1 : 1;
    return a.name.localeCompare(b.name);
  });
  const items = [];
  for (const entry of entries) {
    if (counter.count >= FILE_TREE_MAX_ITEMS) break;
    counter.count += 1;
    const item = { name: entry.name, kind: entry.kind };
    if (entry.kind === "directory") item.children = await readDirectoryTree(entry, depth + 1, counter);
    items.push(item);
  }
  return items;
}

function openWorkspaceDb() {
  return new Promise((resolve, reject) => {
    if (!("indexedDB" in window)) {
      reject(new Error("IndexedDB is unavailable"));
      return;
    }
    const request = indexedDB.open(WORKSPACE_DB, 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore(WORKSPACE_STORE);
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error("Unable to open workspace database"));
  });
}

async function saveWorkspaceHandle(projectId, handle) {
  const db = await openWorkspaceDb();
  await idbRequest(db.transaction(WORKSPACE_STORE, "readwrite").objectStore(WORKSPACE_STORE).put(handle, projectId));
  db.close();
}

async function loadWorkspaceHandle(projectId) {
  try {
    const db = await openWorkspaceDb();
    const handle = await idbRequest(db.transaction(WORKSPACE_STORE, "readonly").objectStore(WORKSPACE_STORE).get(projectId));
    db.close();
    return handle || null;
  } catch {
    return null;
  }
}

function idbRequest(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error("IndexedDB request failed"));
  });
}

async function createSessionTree(projectId) {
  const project = state.projects.find((item) => item.id === projectId) || getActiveProject() || state.projects[0];
  if (!project) return;
  const title = await openInputModal({
    title: "New Session Tree",
    initialValue: "New Session Tree",
    confirmLabel: "Create",
  });
  if (!title) return;
  applyWorkspace(await apiPost("/api/session-trees", { projectId: project.id, title }));
  render();
}

async function renameSessionTree(treeId) {
  const tree = state.sessionTrees.find((item) => item.id === treeId);
  if (!tree) return;
  const title = await openInputModal({
    title: "Rename Session Tree",
    initialValue: tree.title,
    confirmLabel: "Save",
  });
  if (!title || title === tree.title) return;
  applyWorkspace(await apiPatch(`/api/session-trees/${encodeURIComponent(treeId)}`, { title }));
  render();
}

async function deleteSessionTree(treeId) {
  const tree = state.sessionTrees.find((item) => item.id === treeId);
  if (!tree) return;
  if (!(await openConfirmModal({
    title: "Delete Session Tree?",
    body: "This will delete the session tree and all of its sessions. This action cannot be undone.",
    confirmLabel: "Delete",
    danger: true,
  }))) return;
  applyWorkspace(await apiDelete(`/api/session-trees/${encodeURIComponent(treeId)}`));
  render();
}

async function createChildSession(parentId) {
  const tree = getActiveTree();
  if (!tree || !parentId) return;
  const title = await openInputModal({
    title: "New Child Session",
    initialValue: "New Session",
    confirmLabel: "Create",
  });
  if (!title) return;
  applyWorkspace(await apiPost("/api/session-nodes", { treeId: tree.id, parentId, title }));
  state.activeTab = "chat";
  render();
}

async function renameSession(sessionId) {
  const session = getSessionById(sessionId);
  if (!session) return;
  const title = await openInputModal({
    title: "Rename Session",
    initialValue: session.title,
    confirmLabel: "Save",
  });
  if (!title || title === session.title) return;
  applyWorkspace(await apiPatch(`/api/session-nodes/${encodeURIComponent(sessionId)}`, { title }));
  render();
}

async function deleteSession(sessionId) {
  const session = getSessionById(sessionId);
  const tree = getActiveTree();
  if (!session || !tree) return;
  if (session.id === tree.rootSessionId) {
    showToast("Root session cannot be deleted");
    return;
  }
  const descendantCount = collectDescendantIds(session.id).length - 1;
  const body = descendantCount > 0
    ? `Delete this Session and ${descendantCount} child Session(s)? This action cannot be undone.`
    : "Delete this Session? This action cannot be undone.";
  if (!(await openConfirmModal({
    title: "Delete Session?",
    body,
    confirmLabel: "Delete",
    danger: true,
  }))) return;
  applyWorkspace(await apiDelete(`/api/session-nodes/${encodeURIComponent(sessionId)}`));
  render();
}

async function selectSession(sessionId) {
  if (!sessionId) return;
  applyWorkspace(await apiPost(`/api/session-nodes/${encodeURIComponent(sessionId)}/select`, {}));
  render();
  if (state.activeTab === "files") loadFilesForActiveProject();
}

async function sendComposerMessage(event) {
  event.preventDefault();
  const textarea = document.querySelector("#composer-input");
  const message = textarea?.value.trim();
  if (!message || state.sending || !state.activeSessionId) return;

  state.sending = true;
  const controller = new AbortController();
  state.abortController = controller;
  const sessionId = state.activeSessionId;
  const userId = crypto.randomUUID();
  const assistantId = crypto.randomUUID();
  state.sessionMessages[sessionId] = [
    ...getMessagesForSession(sessionId),
    { id: userId, role: "user", createdAt: new Date().toISOString(), output: message, toolCalls: [] },
    { id: assistantId, role: "assistant", createdAt: new Date().toISOString(), output: "", toolCalls: [] },
  ];
  textarea.value = "";
  renderPreservingMessageScroll();

  try {
    await sendChatStream(message, sessionId, assistantId, controller, getWorkingContext(sessionId));
    const payload = await apiGet("/api/workspace");
    applyWorkspace(payload);
  } catch (error) {
    if (error.name === "AbortError" || controller.signal.aborted) {
      appendLocalMessage(sessionId, {
        id: crypto.randomUUID(),
        role: "system",
        createdAt: new Date().toISOString(),
        output: "Generation stopped by user.",
        toolCalls: [],
      });
    } else {
      showToast(`Send failed: ${error.message}`);
    }
  } finally {
    if (state.abortController === controller) state.abortController = null;
    state.sending = false;
    renderPreservingMessageScroll();
  }
}

function stopGeneration() {
  state.abortController?.abort();
}

function appendLocalMessage(sessionId, message) {
  state.sessionMessages[sessionId] = [...getMessagesForSession(sessionId), message];
}

async function sendChatStream(message, sessionId, assistantId, controller, workingContext) {
  const timeout = window.setTimeout(() => controller.abort(), 120000);
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { Accept: "text/event-stream", "Content-Type": "application/json" },
    body: JSON.stringify({ message, sessionId, workingContext }),
    signal: controller.signal,
  });
  if (!response.ok || !response.body) {
    window.clearTimeout(timeout);
    throw new Error(`/api/chat/stream ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";
      for (const part of parts) {
        const result = handleSseEvent(part, sessionId, assistantId);
        if (result.done) return;
        if (result.error) throw new Error(result.error);
      }
    }
  } finally {
    window.clearTimeout(timeout);
  }
}

function handleSseEvent(chunk, sessionId, assistantId) {
  const event = chunk.match(/^event:\s*(.+)$/m)?.[1] || "message";
  const dataLines = [...chunk.matchAll(/^data:\s?(.*)$/gm)].map((match) => match[1]);
  const payload = parseJson(dataLines.join("\n"));
  if (event === "done") return { done: true };
  if (event === "error") return { error: payload.error || "stream error" };
  const assistant = getMessagesForSession(sessionId).find((message) => message.id === assistantId);
  if (!assistant) return {};
  if (event === "delta") assistant.output = `${assistant.output || ""}${payload.text || ""}`;
  if (event === "tool_call") assistant.toolCalls = [...(assistant.toolCalls || []), normalizeTool(payload, assistantId)];
  if (event === "tool_result") {
    const tool = (assistant.toolCalls || []).find((item) => item.id === (payload.tool_use_id || payload.id));
    if (tool) {
      tool.status = "done";
      tool.output = payload.content || payload.output || "";
    }
  }
  renderPreservingMessageScroll();
  return {};
}

function readSidebarWidth() {
  try {
    return clamp(Number(localStorage.getItem(SIDEBAR_STORAGE_KEY)) || DEFAULT_SIDEBAR_WIDTH, MIN_SIDEBAR_WIDTH, MAX_SIDEBAR_WIDTH);
  } catch {
    return DEFAULT_SIDEBAR_WIDTH;
  }
}

function setSidebarWidth(width, persist = false) {
  state.sidebarWidth = clamp(Math.round(Number(width) || DEFAULT_SIDEBAR_WIDTH), MIN_SIDEBAR_WIDTH, MAX_SIDEBAR_WIDTH);
  if (persist) {
    try {
      localStorage.setItem(SIDEBAR_STORAGE_KEY, String(state.sidebarWidth));
    } catch {
      // Local storage can be unavailable in private or restricted browser contexts.
    }
  }
}

function startSidebarResize(event) {
  event.preventDefault();
  state.resizingSidebar = true;
  document.body.style.cursor = "col-resize";
  window.addEventListener("mousemove", moveSidebarResize);
  window.addEventListener("mouseup", endSidebarResize);
}

function moveSidebarResize(event) {
  if (!state.resizingSidebar) return;
  setSidebarWidth(event.clientX);
  render();
}

function endSidebarResize() {
  if (!state.resizingSidebar) return;
  state.resizingSidebar = false;
  document.body.style.cursor = "";
  setSidebarWidth(state.sidebarWidth, true);
  window.removeEventListener("mousemove", moveSidebarResize);
  window.removeEventListener("mouseup", endSidebarResize);
  render();
}

function isNearBottom(element) {
  if (!element) return true;
  return element.scrollHeight - element.scrollTop - element.clientHeight < 80;
}

function captureMessageScroll() {
  const element = document.querySelector(".messages-scroll-area");
  if (!element) return null;
  return {
    scrollTop: element.scrollTop,
    wasNearBottom: isNearBottom(element),
  };
}

function restoreMessageScroll(snapshot) {
  if (!snapshot) return;
  const element = document.querySelector(".messages-scroll-area");
  if (!element) return;
  if (snapshot.wasNearBottom) {
    element.scrollTop = element.scrollHeight;
  } else {
    element.scrollTop = snapshot.scrollTop;
  }
}

function startCanvasPan(event) {
  if (event.target.closest(".session-card")) return;
  state.drag = { type: "canvas", startX: event.clientX, startY: event.clientY, x: state.treeView.x, y: state.treeView.y };
  event.currentTarget.setPointerCapture(event.pointerId);
}

function movePointer(event) {
  if (!state.drag) return;
  if (state.drag.type === "canvas") {
    state.treeView.x = state.drag.x + event.clientX - state.drag.startX;
    state.treeView.y = state.drag.y + event.clientY - state.drag.startY;
    render();
  } else if (state.drag.type === "graph") {
    state.graphView.x = state.drag.x + event.clientX - state.drag.startX;
    state.graphView.y = state.drag.y + event.clientY - state.drag.startY;
    render();
  }
}

function endPointer() {
  state.drag = null;
}

function zoomCanvas(event) {
  event.preventDefault();
  const next = clamp(state.treeView.scale + (event.deltaY > 0 ? -0.08 : 0.08), 0.45, 1.8);
  state.treeView.scale = Math.round(next * 100) / 100;
  render();
}

function getActiveProject() {
  return state.projects.find((project) => project.id === state.activeProjectId) || null;
}

function getActiveTree() {
  return state.sessionTrees.find((tree) => tree.id === state.activeTreeId) || state.sessionTrees[0] || null;
}

function getActiveSession() {
  return getSessionById(state.activeSessionId);
}

function getSessionById(sessionId) {
  const tree = getActiveTree();
  return tree?.sessions?.find((session) => session.id === sessionId) || null;
}

function findSessionInTree(tree, sessionId) {
  return tree?.sessions?.find((session) => session.id === sessionId) || null;
}

function getMessagesForSession(sessionId) {
  return state.sessionMessages[sessionId] || [];
}

function getActiveMessages() {
  return getMessagesForSession(state.activeSessionId);
}

function getActivePath(activeSessionId = state.activeSessionId) {
  const path = [];
  let current = getSessionById(activeSessionId);
  while (current) {
    path.unshift(current);
    current = current.parentId ? getSessionById(current.parentId) : null;
  }
  return path;
}

function getSessionPath() {
  return getActivePath();
}

function getActivePathMessages(activeSessionId = state.activeSessionId) {
  return getActivePath(activeSessionId).flatMap((session) => getMessagesForSession(session.id));
}

function getWorkingContext(activeSessionId = state.activeSessionId) {
  const activePath = getActivePath(activeSessionId);
  const knowledge = getKnowledgeForActiveContext();
  return {
    activeProjectId: state.activeProjectId,
    activeTreeId: state.activeTreeId,
    activeSessionId,
    activePath: activePath.map((session) => ({
      id: session.id,
      title: session.title,
      parentId: session.parentId,
      messageCount: getMessagesForSession(session.id).length,
    })),
    activePathMessageCount: getActivePathMessages(activeSessionId).length,
    treeMemoryItemCount: getTreeMemoryForActiveTree().length,
    currentSessionMessageCount: getMessagesForSession(activeSessionId).length,
    longTermKnowledgeItemCount: knowledge.length,
  };
}

function getTreeMemoryForActiveTree() {
  const tree = getActiveTree();
  if (!tree) return [];
  const sessionIds = new Set((tree.sessions || []).map((session) => session.id));
  return state.treeMemoryItems.filter((item) => !item.sourceSessionId || sessionIds.has(item.sourceSessionId));
}

function getKnowledgeForActiveContext() {
  if (state.longTermKnowledgeItems.length) return state.longTermKnowledgeItems;
  const project = projectName(getActiveProject()) || "PrismX";
  const session = getActiveSession()?.title || "current Session";
  return [
    { title: "Project knowledge", content: `${project} uses Tree-Guided Memory to keep task context structured.` },
    { title: "Session knowledge", content: `${session} can recall active path, tree memory, and long-term knowledge.` },
  ];
}

function getWorkingContextStats() {
  return {
    activePathSessions: getActivePath().length,
    activePathMessages: getActivePathMessages().length,
    treeMemoryItems: getTreeMemoryForActiveTree().length,
    currentSessionMessages: getActiveMessages().length,
    longTermKnowledgeItems: getKnowledgeForActiveContext().length,
  };
}

function layoutSessionTree(sessions, rootSessionId) {
  const byId = new Map(sessions.map((session) => [session.id, { ...session, x: 0, y: 0 }]));
  const childrenByParent = new Map();
  sessions.forEach((session) => {
    if (!session.parentId || !byId.has(session.parentId)) return;
    if (!childrenByParent.has(session.parentId)) childrenByParent.set(session.parentId, []);
    childrenByParent.get(session.parentId).push(byId.get(session.id));
  });
  const roots = [];
  const configuredRoot = byId.get(rootSessionId);
  if (configuredRoot) roots.push(configuredRoot);
  sessions.forEach((session) => {
    if (!session.parentId && session.id !== rootSessionId) roots.push(byId.get(session.id));
  });
  if (!roots.length && sessions[0]) roots.push(byId.get(sessions[0].id));

  const ordered = [];
  let nextY = TREE_PADDING;
  let maxDepth = 0;

  function place(node, depth) {
    const children = (childrenByParent.get(node.id) || []).sort((a, b) => (a.createdAt || "").localeCompare(b.createdAt || ""));
    node.x = TREE_PADDING + depth * (NODE_WIDTH + HORIZONTAL_GAP);
    maxDepth = Math.max(maxDepth, depth);
    if (!children.length) {
      node.y = nextY;
      nextY += NODE_HEIGHT + VERTICAL_GAP;
    } else {
      children.forEach((child) => place(child, depth + 1));
      node.y = (children[0].y + children[children.length - 1].y) / 2;
    }
    ordered.push(node);
  }

  roots.forEach((root, index) => {
    if (index > 0) nextY += VERTICAL_GAP;
    place(root, 0);
  });

  const edges = [];
  ordered.forEach((node) => {
    (childrenByParent.get(node.id) || []).forEach((child) => edges.push({ parent: node, child }));
  });

  return {
    nodes: ordered,
    edges,
    width: TREE_PADDING * 2 + (maxDepth + 1) * NODE_WIDTH + maxDepth * HORIZONTAL_GAP,
    height: Math.max(nextY + TREE_PADDING, NODE_HEIGHT + TREE_PADDING * 2),
  };
}

function collectDescendantIds(sessionId) {
  const session = getSessionById(sessionId);
  if (!session) return [];
  return [sessionId, ...(session.children || []).flatMap((childId) => collectDescendantIds(childId))];
}

function renderMemoryLine(item) {
  const meta = [
    item.type || "finding",
    `reuse ${item.reuseCount ?? 0}`,
    `confidence ${Number(item.confidence || 0).toFixed(2)}`,
    item.status || "active",
    item.promoted ? "promoted" : "",
  ].filter(Boolean).join(" / ");
  return `${meta} / ${item.content}`;
}

function renderKnowledgeLine(item) {
  const segments = [];
  segments.push(el("span", { class: "knowledge-type-badge" }, item.type || "knowledge"));
  if (item.sourceTreeId) {
    segments.push(el("span", {
      class: "knowledge-link",
      title: "Click to switch to source tree",
      onclick: function() {
        const tree = state.sessionTrees.find(function(t) { return t.id === item.sourceTreeId; });
        if (tree) {
          selectSession(tree.activeSessionId || tree.rootSessionId);
        } else {
          showToast("Tree not found: " + item.sourceTreeId);
        }
      }
    }, "tree " + item.sourceTreeId));
  }
  if (item.sourceMemoryId) {
    segments.push(el("span", {
      class: "knowledge-link",
      title: "Click to copy memory ID",
      onclick: function() { showToast("Memory fold ID: " + item.sourceMemoryId); }
    }, "memory " + item.sourceMemoryId));
  }
  segments.push(el("span", { class: "knowledge-conf" }, Number(item.confidence || 0).toFixed(2)));
  if (item.status) {
    segments.push(el("span", { class: "knowledge-status" }, item.status));
  }
  segments.push(el("span", { class: "knowledge-content" }, item.content || item.title));
  return segments;
}

function infoPill(label, value) {
  return el("span", { class: "info-pill" }, `${label}: ${value}`);
}

function nodeAction(label, title, onClick, disabled = false) {
  return el("button", {
    type: "button",
    title,
    disabled: disabled ? "disabled" : null,
    onpointerdown: (event) => {
      event.stopPropagation();
    },
    onclick: (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (!disabled) onClick();
    },
  }, label);
}

function projectRowAction(label, title, onClick) {
  return el("button", {
    class: "project-row-action",
    type: "button",
    title,
    onpointerdown: (event) => {
      event.stopPropagation();
    },
    onclick: (event) => {
      event.preventDefault();
      event.stopPropagation();
      onClick();
    },
  }, label);
}

function button(label, variant, onClick, disabled = false) {
  return el("button", {
    class: `btn ${variant}`,
    type: "button",
    disabled: disabled ? "disabled" : null,
    onclick: disabled ? null : onClick,
  }, label);
}

function iconButton(label, title, onClick) {
  return el("button", { class: "btn icon", type: "button", title, onclick: onClick }, label);
}

function insertCommand(command) {
  const input = document.querySelector("#composer-input");
  if (!input) return;
  input.value = input.value ? `${input.value} ${command}` : `${command} `;
  input.focus();
}

function focusComposer() {
  state.activeTab = "chat";
  render();
  window.requestAnimationFrame(() => document.querySelector("#composer-input")?.focus());
}

async function apiGet(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`${path} ${response.status}`);
  return response.json();
}

async function apiPost(path, payload) {
  return apiJson(path, "POST", payload);
}

async function apiPatch(path, payload) {
  return apiJson(path, "PATCH", payload);
}

async function apiDelete(path) {
  const response = await fetch(path, { method: "DELETE", headers: { Accept: "application/json" } });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `${path} ${response.status}`);
  return data;
}

async function apiJson(path, method, payload) {
  const response = await fetch(path, {
    method,
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `${path} ${response.status}`);
  return data;
}

function normalizeTool(tool, fallbackId) {
  return {
    id: tool.id || tool.toolUseId || `${fallbackId}-${tool.name || "tool"}`,
    name: tool.name || "tool",
    status: tool.status || "running",
    input: tool.input || {},
    output: tool.output || "",
  };
}

function toolKind(tool) {
  const name = tool.name || "";
  if (/mcp/.test(name)) return "mcp";
  if (/memory|remember|context|graph/.test(name)) return "memory";
  if (/read|search|list/.test(name)) return "search";
  return "runtime";
}

function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function parseJson(value) {
  try {
    return JSON.parse(value || "{}");
  } catch {
    return {};
  }
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function showToast(message) {
  nodes.toast.textContent = message;
  nodes.toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    nodes.toast.hidden = true;
  }, 2800);
}

const GRAPH_TYPE_COLORS = {
  pattern: "#8b5cf6",
  decision: "#6366f1",
  constraint: "#ec4899",
  finding: "#10b981",
  tool: "#f59e0b",
  knowledge: "#06b6d4",
};
const GRAPH_NODE_RADIUS = 22;
const GRAPH_CANVAS_WIDTH = 1200;
const GRAPH_CANVAS_HEIGHT = 800;

function startGraphPan(event) {
  if (event.target.closest(".graph-node-circle")) return;
  state.drag = { type: "graph", startX: event.clientX, startY: event.clientY, x: state.graphView.x, y: state.graphView.y };
  event.currentTarget.setPointerCapture(event.pointerId);
}

function graphZoomCanvas(event) {
  event.preventDefault();
  const next = clamp(state.graphView.scale + (event.deltaY > 0 ? -0.08 : 0.08), 0.2, 2.5);
  state.graphView.scale = Math.round(next * 100) / 100;
  render();
}

async function loadGraphData() {
  state.graphLoading = true;
  render();
  try {
    const data = await apiGet("/api/knowledge/graph");
    if (data.nodes && data.nodes.length) {
      const positions = computeGraphLayout(data.nodes, data.edges || [], GRAPH_CANVAS_WIDTH, GRAPH_CANVAS_HEIGHT);
      data.nodes.forEach((node) => {
        const pos = positions.get(node.id);
        node._x = pos.x;
        node._y = pos.y;
      });
    }
    state.graphData = data;
  } catch (err) {
    showToast("Failed to load knowledge graph: " + err.message);
    state.graphData = { nodes: [], edges: [] };
  } finally {
    state.graphLoading = false;
    render();
  }
}

function computeGraphLayout(nodes, edges, width, height) {
  const positions = new Map();
  const centerX = width / 2;
  const centerY = height / 2;
  const initRadius = Math.min(width, height) * 0.28;

  nodes.forEach((node, i) => {
    const angle = (i / Math.max(nodes.length, 1)) * 2 * Math.PI + Math.random() * 0.4;
    positions.set(node.id, {
      x: centerX + Math.cos(angle) * initRadius + (Math.random() - 0.5) * 100,
      y: centerY + Math.sin(angle) * initRadius + (Math.random() - 0.5) * 100,
    });
  });

  const edgeMap = new Map();
  edges.forEach((edge) => {
    const key = [edge.source, edge.target].sort().join("||");
    if (!edgeMap.has(key)) {
      edgeMap.set(key, { source: edge.source, target: edge.target });
    }
  });
  const uniqueEdges = [...edgeMap.values()];

  const ITERATIONS = 60;
  const REPULSION = 8000;
  const ATTRACTION = 0.002;
  let damping = 0.88;

  for (let iter = 0; iter < ITERATIONS; iter++) {
    const forces = new Map();
    nodes.forEach((n) => forces.set(n.id, { fx: 0, fy: 0 }));

    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        const pa = positions.get(a.id), pb = positions.get(b.id);
        let dx = pa.x - pb.x;
        let dy = pa.y - pb.y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 1;
        if (dist < 15) dist = 15;
        const force = REPULSION / (dist * dist);
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        forces.get(a.id).fx += fx;
        forces.get(a.id).fy += fy;
        forces.get(b.id).fx -= fx;
        forces.get(b.id).fy -= fy;
      }
    }

    uniqueEdges.forEach((edge) => {
      const src = positions.get(edge.source);
      const tgt = positions.get(edge.target);
      if (!src || !tgt) return;
      let dx = tgt.x - src.x;
      let dy = tgt.y - src.y;
      let dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const force = dist * ATTRACTION;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      forces.get(edge.source).fx += fx;
      forces.get(edge.source).fy += fy;
      forces.get(edge.target).fx -= fx;
      forces.get(edge.target).fy -= fy;
    });

    nodes.forEach((node) => {
      const f = forces.get(node.id);
      const pos = positions.get(node.id);
      pos.x += f.fx * damping;
      pos.y += f.fy * damping;
      pos.x = clamp(pos.x, -200, width + 200);
      pos.y = clamp(pos.y, -200, height + 200);
    });

    damping *= 0.96;
  }

  return positions;
}

function GraphWorkspace() {
  const data = state.graphData;
  const loading = state.graphLoading;
  const typeColors = GRAPH_TYPE_COLORS;

  if (loading) {
    return el("section", { class: "workspace-view graph-workspace" }, [
      TitleRow("Knowledge Layer", "Knowledge Graph", [
        button("Refresh", "secondary", () => loadGraphData()),
      ]),
      EmptyState("Loading knowledge graph..."),
    ]);
  }

  if (!data || !data.nodes || !data.nodes.length) {
    return el("section", { class: "workspace-view graph-workspace" }, [
      TitleRow("Knowledge Layer", "Knowledge Graph", [
        button("Refresh", "secondary", () => loadGraphData()),
      ]),
      EmptyState("No knowledge graph data available yet. Promote tree memory items to build the graph."),
    ]);
  }

  const edgeLines = (data.edges || []).map((edge) => {
    const srcNode = data.nodes.find((n) => n.id === edge.source);
    const tgtNode = data.nodes.find((n) => n.id === edge.target);
    if (!srcNode || !tgtNode) return null;
    return { ...edge, x1: srcNode._x, y1: srcNode._y, x2: tgtNode._x, y2: tgtNode._y };
  }).filter(Boolean);

  const usedTypes = [...new Set(data.nodes.map((n) => n.type || "knowledge"))];
  const nodeCount = data.nodes.length;
  const edgeCount = (data.edges || []).length;
  const showLabels = nodeCount <= 40;

  return el("section", { class: "workspace-view graph-workspace" }, [
    TitleRow("Knowledge Layer", "Knowledge Graph", [
      el("span", { class: "graph-count-badge" }, `${nodeCount} nodes, ${edgeCount} edges`),
      button("Refresh", "secondary", () => loadGraphData()),
    ]),
    el("div", { class: "graph-legend" }, usedTypes.map((type) =>
      el("span", { class: "graph-legend-item" }, [
        el("span", { class: "graph-legend-dot", style: `background: ${typeColors[type] || typeColors.knowledge}` }),
        type,
      ])
    )),
    el("div", {
      class: "graph-canvas",
      onpointerdown: startGraphPan,
      onpointermove: movePointer,
      onpointerup: endPointer,
      onpointerleave: endPointer,
      onwheel: graphZoomCanvas,
    }, [
      el("div", {
        class: "graph-plane",
        style: [
          `width: ${GRAPH_CANVAS_WIDTH}px`,
          `height: ${GRAPH_CANVAS_HEIGHT}px`,
          `transform: translate(${state.graphView.x}px, ${state.graphView.y}px) scale(${state.graphView.scale})`,
        ].join("; "),
      }, [
        el("svg", {
          class: "graph-edges",
          width: String(GRAPH_CANVAS_WIDTH),
          height: String(GRAPH_CANVAS_HEIGHT),
        }, edgeLines.map((edge) => GraphEdge(edge))),
        ...data.nodes.map((node) => GraphNode(node, typeColors, showLabels)),
      ]),
    ]),
  ]);
}

function GraphEdge(edge) {
  const promoted = edge.relation === "promoted_to";
  return el("line", {
    x1: String(edge.x1),
    y1: String(edge.y1),
    x2: String(edge.x2),
    y2: String(edge.y2),
    class: `graph-edge ${promoted ? "edge-promoted" : "edge-derived"}`,
    stroke: promoted ? "#8b5cf6" : "#94a3b8",
    "stroke-width": promoted ? "2" : "1.5",
    "stroke-dasharray": promoted ? "none" : "5,3",
    opacity: "0.6",
  });
}

function GraphNode(node, typeColors, showLabel) {
  const color = typeColors[node.type] || typeColors.knowledge;
  const label = node.title || node.id || "Unknown";
  const displayLabel = label.length > 28 ? label.slice(0, 26) + "..." : label;

  return el("g", { class: "graph-node" }, [
    el("circle", {
      cx: String(node._x),
      cy: String(node._y),
      r: String(GRAPH_NODE_RADIUS),
      fill: color,
      stroke: "#fff",
      "stroke-width": "2.5",
      class: "graph-node-circle",
      style: "filter: drop-shadow(0 2px 6px rgba(0,0,0,0.15)); cursor: pointer;",
    }),
    el("title", {}, `${label}\nType: ${node.type || "knowledge"}\nConfidence: ${Number(node.confidence || 0).toFixed(2)}\nStatus: ${node.status || "active"}`),
    showLabel ? el("text", {
      x: String(node._x),
      y: String(node._y + GRAPH_NODE_RADIUS + 14),
      "text-anchor": "middle",
      class: "graph-node-label",
    }, displayLabel) : null,
    el("text", {
      x: String(node._x),
      y: String(node._y + 5),
      "text-anchor": "middle",
      class: "graph-node-type-label",
      style: "fill: #fff; font-size: 8px; font-weight: 700; pointer-events: none;",
    }, (node.type || "K").charAt(0).toUpperCase()),
  ]);
}

function normalizeTool(tool, fallbackId) {
  return {
    id: tool.id || tool.toolUseId || `${fallbackId}-${tool.name || "tool"}`,
    name: tool.name || "tool",
    status: tool.status || "running",
    input: tool.input || {},
    output: tool.output || "",
  };
}

function toolKind(tool) {
  const name = tool.name || "";
  if (/mcp/.test(name)) return "mcp";
  if (/memory|remember|context|graph/.test(name)) return "memory";
  if (/read|search|list/.test(name)) return "search";
  return "runtime";
}

function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function parseJson(value) {
  try {
    return JSON.parse(value || "{}");
  } catch {
    return {};
  }
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function showToast(message) {
  nodes.toast.textContent = message;
  nodes.toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    nodes.toast.hidden = true;
  }, 2800);
}

function el(tag, attrs = {}, children = []) {
  const svgTags = new Set(["svg", "path", "g", "line", "circle", "rect", "text"]);
  const node = svgTags.has(tag)
    ? document.createElementNS("http://www.w3.org/2000/svg", tag)
    : document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.setAttribute("class", value);
    else if (key === "style") node.setAttribute("style", value);
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  const list = Array.isArray(children) ? children : [children];
  for (const child of list) {
    if (child === null || child === undefined || child === false) continue;
    node.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

init();
