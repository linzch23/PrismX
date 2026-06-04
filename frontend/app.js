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
  state.activeTreeId = payload.activeTreeId || state.sessionTrees[0]?.id || null;
  const activeTree = getActiveTree();
  state.activeSessionId = payload.activeSessionId || activeTree?.activeSessionId || activeTree?.rootSessionId || null;
  state.sessionMessages = payload.sessionMessages || {};
  state.treeMemoryItems = payload.treeMemoryItems || [];
  state.longTermKnowledgeItems = payload.longTermKnowledgeItems || [];
}

function render() {
  nodes.app.replaceChildren(
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
  );
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
      el("span", { class: `status-badge ${state.loading ? "" : "live"}` }, state.loading ? "loading" : "live API"),
      iconButton("Refresh", "Refresh workspace", () => loadWorkspace()),
      button("Run Agent", "primary", () => focusComposer(), state.sending),
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
  if (!getActiveTree() || !getActiveSession()) {
    return el("section", { class: "workspace-view empty-view" }, [
      el("h1", {}, "No Session Tree"),
      el("p", {}, "Create a project or Session Tree to start working."),
    ]);
  }
  if (state.activeTab === "tree") return TreeWorkspace();
  if (state.activeTab === "memory") return MemoryWorkspace();
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
  return el("section", { class: "workspace-view memory-workspace" }, [
    TitleRow("Tree-Guided Memory Layer", "Memory Recall", []),
    el("div", { class: "memory-grid" }, [
      ContextCard("Active Path Context", path.map((session, index) =>
        `${index + 1}. ${session.title} / ${getMessagesForSession(session.id).length} messages`
      )),
      ContextCard("Tree Memory Recall", memoryItems.length ? memoryItems.map(renderMemoryLine) : ["No tree memory items for this tree yet."]),
      ContextCard("Long-term Knowledge Recall", knowledge.map((item) => item.content || item.title)),
      ContextCard("Working Context Preview", [
        `Active Path Sessions: ${stats.activePathSessions}`,
        `Active Path Messages: ${stats.activePathMessages}`,
        `Tree Memory Items: ${stats.treeMemoryItems}`,
        `Current Session Messages: ${stats.currentSessionMessages}`,
        `Long-term Knowledge Items: ${stats.longTermKnowledgeItems}`,
      ]),
    ]),
  ]);
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

function TitleRow(eyebrow, title, actions) {
  return el("div", { class: "workspace-title-row" }, [
    el("div", {}, [el("p", { class: "eyebrow" }, eyebrow), el("h1", {}, title)]),
    actions.length ? el("div", { class: "title-actions" }, actions) : null,
  ]);
}

function EmptyState(text) {
  return el("div", { class: "empty-state" }, text);
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
    name = prompt("Project name", "New Project")?.trim() || "";
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
  const name = prompt("Rename Project", projectName(project))?.trim();
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
  if (!confirm(message)) return;
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
  const title = prompt("Session Tree title", "New Session Tree");
  if (!title) return;
  applyWorkspace(await apiPost("/api/session-trees", { projectId: project.id, title }));
  render();
}

async function renameSessionTree(treeId) {
  const tree = state.sessionTrees.find((item) => item.id === treeId);
  if (!tree) return;
  const title = prompt("Rename Session Tree", tree.title)?.trim();
  if (!title || title === tree.title) return;
  applyWorkspace(await apiPatch(`/api/session-trees/${encodeURIComponent(treeId)}`, { title }));
  render();
}

async function deleteSessionTree(treeId) {
  const tree = state.sessionTrees.find((item) => item.id === treeId);
  if (!tree) return;
  if (!confirm("Delete this session tree and all its sessions?")) return;
  applyWorkspace(await apiDelete(`/api/session-trees/${encodeURIComponent(treeId)}`));
  render();
}

async function createChildSession(parentId) {
  const tree = getActiveTree();
  if (!tree || !parentId) return;
  const title = prompt("Child Session title", "New Session");
  if (!title) return;
  applyWorkspace(await apiPost("/api/session-nodes", { treeId: tree.id, parentId, title }));
  state.activeTab = "chat";
  render();
}

async function renameSession(sessionId) {
  const session = getSessionById(sessionId);
  if (!session) return;
  const title = prompt("Rename Session", session.title)?.trim();
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
  if (descendantCount > 0 && !confirm(`Delete this Session and ${descendantCount} child Session(s)?`)) return;
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
  return `${item.type || "finding"} / ${item.sourceSessionId || "tree"} / ${item.content}`;
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
