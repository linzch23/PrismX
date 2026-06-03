const mockProjects = [
  {
    id: "p1",
    name: "智能体开发大赛",
    trees: [
      { id: "t1", name: "PrismX 技术设计" },
      { id: "t2", name: "前端工作台设计" },
      { id: "t3", name: "TGM 记忆机制" },
    ],
  },
  {
    id: "p2",
    name: "操作系统实验",
    trees: [{ id: "t4", name: "线程调度实验" }],
  },
];

const sessionTree = {
  id: "root",
  name: "PrismX 项目设计",
  status: "active",
  memoryCount: 7,
  children: [
    {
      id: "runtime",
      name: "Agent Runtime",
      status: "running",
      memoryCount: 3,
      children: [
        { id: "loop", name: "Agent Loop", status: "ready", memoryCount: 2, children: [] },
        { id: "team", name: "Agent Team", status: "ready", memoryCount: 1, children: [] },
      ],
    },
    {
      id: "mcp",
      name: "MCP 环境交互层",
      status: "ready",
      memoryCount: 2,
      children: [],
    },
    {
      id: "tgm",
      name: "Tree-Guided Memory",
      status: "active",
      memoryCount: 4,
      children: [
        { id: "treesession", name: "TreeSession", status: "ready", memoryCount: 1, children: [] },
        { id: "treememory", name: "Tree Memory", status: "active", memoryCount: 4, children: [] },
        { id: "longterm", name: "Long-term Knowledge", status: "ready", memoryCount: 2, children: [] },
      ],
    },
  ],
};

const demoRun = {
  sessionId: "demo",
  title: "前端工作台设计",
  meta: "mock fallback",
  activeLeafId: "treememory",
  messages: [
    {
      id: "m1",
      role: "user",
      time: "09:41",
      text: "请把 PrismX 的前端改造成类似 Codex App 的 Agent 工作台。",
      tools: [],
    },
    {
      id: "m2",
      role: "assistant",
      time: "09:42",
      text: "我会把工作台拆成 Chat、Tree、Memory 三个主视图，并突出 Agent Runtime、MCP 环境交互层和 Tree-Guided Memory Layer。",
      tools: [
        {
          id: "tool-1",
          name: "search_context",
          status: "done",
          input: { query: "PrismX TGM frontend" },
          output: "命中 Tree-Guided Memory、TreeSession、MemoryGraph 相关上下文。",
        },
        {
          id: "tool-2",
          name: "mcp_filesystem_read",
          status: "done",
          input: { path: "frontend/app.js" },
          output: "读取现有静态前端结构。",
        },
      ],
    },
    {
      id: "m3",
      role: "assistant",
      time: "09:46",
      text: "当前节点处于 Tree Memory 设计分支，运行时上下文会沿 active path 继承，并召回树内经验与长期知识。",
      tools: [
        {
          id: "tool-3",
          name: "remember",
          status: "done",
          input: { category: "decisions", title: "TGM workspace direction" },
          output: "Remembered: tree://prismx/frontend-workspace",
        },
      ],
    },
  ],
  tree: [],
  contextObjects: [
    {
      uri: "tree://prismx/tgm/frontend",
      context_type: "tree-memory",
      title: "前端工作台设计",
      overview: "工作台主视图应同时呈现对话、会话树和记忆召回。",
      trust_score: 0.92,
    },
  ],
  memory: "",
};

const state = {
  apiMode: false,
  activeTab: "chat",
  activeProjectId: "p1",
  activeTreeId: "t2",
  activeConceptNodeId: "treememory",
  run: structuredClone(demoRun),
  sessions: [],
  projects: structuredClone(mockProjects),
  contextObjects: [],
  memoryObjects: [],
  tools: [],
  mcpReport: "",
  sending: false,
};

const nodes = {
  app: document.querySelector("#app"),
  toast: document.querySelector("#toast"),
};

async function init() {
  renderAppLayout();
  await loadData();
}

// AppLayout owns API hydration and routes every visual component through shared state.
async function loadData() {
  try {
    const sessionsPayload = await apiGet("/api/sessions");
    const sessions = normalizeSessionSummaries(sessionsPayload.sessions || [], sessionsPayload.activeSessionId);
    const selected = pickSession(sessions, sessionsPayload.activeSessionId);
    if (!selected) throw new Error("no sessions found");

    const sessionId = selected.id;
    const [runsPayload, treePayload, contextPayload, memoryPayload, toolsPayload, mcpPayload] = await Promise.all([
      apiGet(`/api/sessions/${encodeURIComponent(sessionId)}/runs`),
      apiGet(`/api/sessions/${encodeURIComponent(sessionId)}/tree`),
      apiGet("/api/context?limit=200").catch(() => ({ objects: [] })),
      apiGet("/api/memory").catch(() => ({ objects: [] })),
      apiGet("/api/tools").catch(() => ({ tools: [] })),
      apiGet("/api/mcp").catch(() => ({ report: "" })),
    ]);

    state.apiMode = true;
    state.sessions = sessions;
    state.run = normalizeApiRun({ selected, runsPayload, treePayload });
    state.contextObjects = Array.isArray(contextPayload.objects) ? contextPayload.objects : [];
    state.memoryObjects = Array.isArray(memoryPayload.objects) ? memoryPayload.objects : [];
    state.tools = Array.isArray(toolsPayload.tools) ? toolsPayload.tools : [];
    state.mcpReport = typeof mcpPayload.report === "string" ? mcpPayload.report : JSON.stringify(mcpPayload.report || "");
    state.projects = buildProjectsFromSessions(sessions);
    state.activeTreeId = selected.id;
  } catch (error) {
    state.apiMode = false;
    state.sessions = demoSessions();
    state.run = structuredClone(demoRun);
    state.contextObjects = demoRun.contextObjects;
    state.memoryObjects = demoRun.contextObjects;
    state.tools = [
      { name: "search_context" },
      { name: "read_context" },
      { name: "show_context_links" },
      { name: "remember" },
      { name: "mcp_filesystem_read" },
    ];
    state.mcpReport = "filesystem: ready\nshell: ready";
    state.projects = buildProjectsFromSessions(state.sessions);
    showToast(`使用演示数据：${error.message}`);
  }
  renderAppLayout();
}

function renderAppLayout() {
  nodes.app.replaceChildren(
    Header(),
    el("div", { class: "workspace-shell" }, [
      ProjectSidebar(),
      el("main", { class: "workspace-main" }, [WorkspaceTabs(), activeWorkspace()]),
    ]),
  );
}

function Header() {
  const statusText = state.apiMode ? "real API" : "demo data";
  return el("header", { class: "top-header" }, [
    el("div", { class: "brand-block" }, [
      el("div", { class: "brand-mark", "aria-hidden": "true" }, "PX"),
      el("div", {}, [
        el("strong", {}, "PrismX"),
        el("span", {}, "Agent Runtime · MCP · Tree-Guided Memory"),
      ]),
    ]),
    el("div", { class: "header-actions" }, [
      el("span", { class: `status-badge ${state.apiMode ? "live" : ""}` }, statusText),
      button("Run Agent", "primary", () => focusComposer()),
      button("Settings", "ghost", () => showToast("Settings 入口预留中")),
      el("div", { class: "avatar", title: "PrismX user" }, "P"),
    ]),
  ]);
}

function ProjectSidebar() {
  return el("aside", { class: "project-sidebar", "aria-label": "Project management" }, [
    el("div", { class: "sidebar-head" }, [
      el("div", {}, [el("p", { class: "eyebrow" }, "Workspace"), el("h2", {}, "Projects")]),
      button("+", "icon", () => showToast("New Project 为前端占位，后端暂无 project model")),
    ]),
    el("label", { class: "search-box" }, [
      el("span", {}, "Search projects"),
      el("input", { type: "search", placeholder: "Search projects" }),
    ]),
    el("div", { class: "sidebar-actions" }, [
      button("New Project", "secondary", () => showToast("New Project 为前端占位，后端暂无 project model")),
      button("New Session Tree", "secondary accent", () => createNewSessionTree()),
    ]),
    el("nav", { class: "project-list" }, state.projects.map((project) => ProjectTreeItem(project))),
  ]);
}

// ProjectTreeItem renders mock projects while real sessions are mapped into the active PrismX project.
function ProjectTreeItem(project) {
  const isActiveProject = project.id === state.activeProjectId;
  return el("section", { class: `project-item ${isActiveProject ? "active" : ""}` }, [
    el("button", {
      class: "project-button",
      type: "button",
      onclick: () => {
        state.activeProjectId = project.id;
        renderAppLayout();
      },
    }, [
      el("span", { class: "project-dot" }),
      el("strong", {}, project.name),
      el("em", {}, String(project.trees.length)),
    ]),
    el("div", { class: "tree-list" }, project.trees.map((tree) => {
      const selected = isActiveProject && tree.id === state.activeTreeId;
      return el("button", {
        class: `tree-link ${selected ? "selected" : ""}`,
        type: "button",
        onclick: () => selectTree(project.id, tree.id),
      }, [
        el("span", {}, "Session Tree"),
        el("strong", {}, tree.name),
      ]);
    })),
  ]);
}

function WorkspaceTabs() {
  const tabs = [
    ["chat", "Chat"],
    ["tree", "Tree"],
    ["memory", "Memory"],
  ];
  return el("section", { class: "workspace-tabs", "aria-label": "Workspace tabs" }, tabs.map(([id, label]) =>
    el("button", {
      class: `workspace-tab ${state.activeTab === id ? "active" : ""}`,
      type: "button",
      onclick: () => {
        state.activeTab = id;
        renderAppLayout();
      },
    }, label),
  ));
}

function activeWorkspace() {
  if (state.activeTab === "tree") return TreeWorkspace();
  if (state.activeTab === "memory") return MemoryWorkspace();
  return ChatWorkspace();
}

function ChatWorkspace() {
  const currentNode = findSessionNode(sessionTree, state.activeConceptNodeId) || sessionTree;
  return el("section", { class: "workspace-view chat-workspace" }, [
    el("div", { class: "workspace-title-row" }, [
      el("div", {}, [
        el("p", { class: "eyebrow" }, "Agent Runtime"),
        el("h1", {}, currentTreeName()),
        el("span", { class: "subtle" }, `Current node: ${currentNode.name}`),
      ]),
      el("div", { class: "architecture-strip" }, [
        layerPill("Agent Runtime", "runtime"),
        layerPill("MCP 环境交互层", "mcp"),
        layerPill("Tree-Guided Memory Layer", "memory"),
      ]),
    ]),
    el("div", { class: "message-list" }, state.run.messages.map((message) => MessageCard(message))),
    CommandInput(),
  ]);
}

function MessageCard(message) {
  const isAssistant = message.role !== "user";
  return el("article", { class: `message-card ${message.role}` }, [
    el("div", { class: "message-meta" }, [
      el("span", {}, isAssistant ? "Agent" : "User"),
      el("time", {}, message.time || ""),
    ]),
    el("p", {}, message.text || "(empty)"),
    message.tools?.length
      ? el("div", { class: "tool-chip-row" }, message.tools.map((tool) => ToolChip(tool)))
      : null,
  ]);
}

function ToolChip(tool) {
  return el("button", {
    class: `tool-chip ${toolKind(tool)}`,
    type: "button",
    title: tool.output || tool.name,
    onclick: () => showToast(`${tool.name}: ${tool.status || "done"}`),
  }, `${tool.name} · ${tool.status || "done"}`);
}

// CommandInput keeps slash command hints close to the composer and sends through the existing stream API.
function CommandInput() {
  return el("form", { class: "command-input", id: "composer", onsubmit: sendComposerMessage }, [
    el("div", { class: "command-hints" }, ["/agent", "/team", "/mcp", "/memory", "/branch"].map((item) =>
      el("button", {
        type: "button",
        onclick: () => insertCommand(item),
      }, item),
    )),
    el("div", { class: "composer-row" }, [
      el("textarea", {
        id: "composer-input",
        rows: "3",
        placeholder: "Tell PrismX what to do in this Session node...",
        disabled: state.sending ? "disabled" : null,
      }),
      el("button", {
        id: "send-button",
        class: "send-button",
        type: "submit",
        disabled: state.sending ? "disabled" : null,
      }, state.sending ? "Sending" : "Send"),
    ]),
  ]);
}

function TreeWorkspace() {
  return el("section", { class: "workspace-view tree-workspace" }, [
    el("div", { class: "workspace-title-row" }, [
      el("div", {}, [
        el("p", { class: "eyebrow" }, "Tree-Guided Memory Layer"),
        el("h1", {}, "Session Tree"),
        el("span", { class: "subtle" }, "节点代表 Session，而不是单条 Message。"),
      ]),
      button("New Child Session", "primary", () => showToast("子会话创建入口预留中")),
    ]),
    el("div", { class: "session-tree-board" }, [
      SessionNode(sessionTree, 0),
    ]),
  ]);
}

// SessionNode recursively renders a left-to-right concept tree with lightweight controls.
function SessionNode(node, depth) {
  const selected = node.id === state.activeConceptNodeId;
  return el("div", { class: "session-node-column" }, [
    el("div", {
      class: `session-node depth-${depth} ${selected ? "selected" : ""}`,
      onclick: () => {
        state.activeConceptNodeId = node.id;
        renderAppLayout();
      },
    }, [
      el("div", { class: "node-head" }, [
        el("span", { class: `node-status ${node.status || "ready"}` }, node.status || "ready"),
        el("div", { class: "node-actions" }, [
          nodeAction("+", () => showToast(`New child under ${node.name}`)),
          nodeAction("Rename", () => showToast(`Rename ${node.name} 入口预留中`)),
          nodeAction("Delete", () => showToast(`Delete ${node.name} 入口预留中`)),
        ]),
      ]),
      el("strong", {}, node.name),
      el("span", { class: "node-memory" }, `${node.memoryCount || 0} memories`),
    ]),
    node.children?.length
      ? el("div", { class: "session-children" }, node.children.map((child) => SessionNode(child, depth + 1)))
      : null,
  ]);
}

function MemoryWorkspace() {
  const stats = memoryStats();
  return el("section", { class: "workspace-view memory-workspace" }, [
    el("div", { class: "workspace-title-row" }, [
      el("div", {}, [
        el("p", { class: "eyebrow" }, "Tree-Guided Memory Layer"),
        el("h1", {}, "Memory Recall"),
        el("span", { class: "subtle" }, "TGM 将 active path、树内经验和长期知识组合成工作上下文。"),
      ]),
    ]),
    el("div", { class: "memory-grid" }, [
      ContextCard("Active Path Context", [
        "PrismX 项目设计",
        "→ Tree-Guided Memory",
        "→ Tree Memory",
      ]),
      ContextCard("Tree Memory Recall", [
        "- PrismX 的主要创新是 TGM",
        "- TreeSession 负责纵向上下文继承",
        "- Tree Memory 负责树内横向经验共享",
        "- Long-term Knowledge 负责跨项目知识复用",
      ]),
      ContextCard("Long-term Knowledge Recall", [
        "- Agent 框架通常包含 Runtime、Tool System、Memory System",
        "- MCP 用于连接外部环境和工具",
      ]),
      ContextCard("Working Context Preview", [
        `Active Path Sessions: ${stats.activePathSessions}`,
        `Tree Memory Items: ${stats.treeMemoryItems}`,
        `Long-term Knowledge Items: ${stats.longTermKnowledgeItems}`,
        `MCP Tools Available: ${stats.mcpToolsAvailable}`,
      ]),
    ]),
  ]);
}

function ContextCard(title, lines) {
  return el("article", { class: "context-card" }, [
    el("h2", {}, title),
    el("div", { class: "context-lines" }, lines.map((line) => el("p", {}, line))),
  ]);
}

async function sendComposerMessage(event) {
  event.preventDefault();
  const textarea = document.querySelector("#composer-input");
  const message = textarea?.value.trim();
  if (!message || state.sending) return;

  if (!state.apiMode) {
    state.run.messages.push({
      id: crypto.randomUUID(),
      role: "user",
      time: "queued",
      text: message,
      tools: [],
    });
    textarea.value = "";
    renderAppLayout();
    showToast("演示模式：消息已加入本地 Chat。启动 Web API 后会发送到 /api/chat/stream。");
    return;
  }

  state.sending = true;
  const userId = crypto.randomUUID();
  const assistantId = crypto.randomUUID();
  state.run.messages.push({ id: userId, role: "user", time: "now", text: message, tools: [] });
  state.run.messages.push({ id: assistantId, role: "assistant", time: "now", text: "", tools: [] });
  textarea.value = "";
  renderAppLayout();

  try {
    await sendChatStream(message, assistantId);
    await loadData();
  } catch (error) {
    showToast(`发送失败：${error.message}`);
  } finally {
    state.sending = false;
    renderAppLayout();
  }
}

async function sendChatStream(message, assistantId) {
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { Accept: "text/event-stream", "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!response.ok || !response.body) throw new Error(`/api/chat/stream ${response.status}`);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) handleSseEvent(part, assistantId);
  }
}

function handleSseEvent(chunk, assistantId) {
  const eventMatch = chunk.match(/^event:\s*(.+)$/m);
  const dataLines = [...chunk.matchAll(/^data:\s?(.*)$/gm)].map((match) => match[1]);
  const event = eventMatch?.[1] || "message";
  const payload = parseJson(dataLines.join("\n"));
  const assistant = state.run.messages.find((message) => message.id === assistantId);
  if (!assistant) return;

  if (event === "delta") {
    assistant.text += payload.text || "";
    renderAppLayout();
  }
  if (event === "tool_call") {
    assistant.tools.push(normalizeTool(payload, assistantId));
    renderAppLayout();
  }
  if (event === "tool_result") {
    const toolUseId = payload.tool_use_id || payload.id;
    const tool = assistant.tools.find((item) => item.id === toolUseId);
    if (tool) {
      tool.status = "done";
      tool.output = payload.content || payload.output || "";
    }
    renderAppLayout();
  }
}

async function createNewSessionTree() {
  if (!state.apiMode) {
    showToast("演示模式：New Session Tree 需要 Web API。");
    return;
  }
  try {
    await apiPost("/api/sessions", { title: "New Session Tree" });
    await loadData();
    showToast("已创建新的 Session Tree");
  } catch (error) {
    showToast(`创建失败：${error.message}`);
  }
}

async function selectTree(projectId, treeId) {
  state.activeProjectId = projectId;
  state.activeTreeId = treeId;
  const realSession = state.sessions.find((session) => session.id === treeId);
  if (!realSession || !state.apiMode) {
    renderAppLayout();
    return;
  }
  try {
    await apiPost("/api/sessions/select", { sessionId: treeId });
    await loadData();
  } catch (error) {
    showToast(`切换 session 失败：${error.message}`);
  }
}

function buildProjectsFromSessions(sessions) {
  const realTrees = sessions.length
    ? sessions.map((session) => ({ id: session.id, name: session.title || `Session ${shortId(session.id)}` }))
    : mockProjects[0].trees;
  return [
    { id: "p1", name: "智能体开发大赛", trees: realTrees },
    mockProjects[1],
  ];
}

function normalizeApiRun({ selected, runsPayload, treePayload }) {
  const steps = Array.isArray(runsPayload.runs) ? runsPayload.runs : [];
  const toolEvents = Array.isArray(runsPayload.toolEvents) ? runsPayload.toolEvents : [];
  const messages = steps
    .filter((step) => step.kind === "user" || step.kind === "assistant")
    .map((step) => ({
      id: step.id || crypto.randomUUID(),
      role: step.kind === "user" ? "user" : "assistant",
      time: formatTime(step.createdAt),
      text: step.output || step.summary || "",
      tools: (step.toolCalls || []).map((tool) => normalizeTool(tool, step.id)),
    }));

  if (!messages.length) {
    messages.push({
      id: "empty",
      role: "assistant",
      time: "",
      text: "当前 Session Tree 暂无对话。可以在底部输入任务，让 Agent 在当前节点中工作。",
      tools: toolEvents.map((tool) => normalizeTool(tool, "tool-events")),
    });
  }

  return {
    sessionId: selected.id,
    title: selected.title || `Session ${shortId(selected.id)}`,
    meta: `${selected.recordCount ?? steps.length} records`,
    activeLeafId: selected.activeLeafId || (treePayload.nodes || []).find((node) => node.status === "active")?.id || "",
    messages,
    tree: treePayload.nodes || [],
    contextObjects: [],
    memory: "",
  };
}

function normalizeSessionSummaries(sessions, activeSessionId) {
  return sessions
    .map((item) => (typeof item === "string" ? { id: item } : item))
    .filter((item) => item && item.id)
    .map((item) => ({
      id: String(item.id),
      title: item.title || `Session ${shortId(item.id)}`,
      recordCount: item.recordCount ?? 0,
      createdAt: item.createdAt || "",
      updatedAt: item.updatedAt || item.createdAt || "",
      activeLeafId: item.activeLeafId || "",
      active: item.id === activeSessionId,
    }))
    .sort((a, b) => String(b.updatedAt || "").localeCompare(String(a.updatedAt || "")));
}

function pickSession(sessions, activeSessionId) {
  return sessions.find((item) => item.id === activeSessionId) || sessions[0] || null;
}

function demoSessions() {
  return [{ id: "t2", title: "前端工作台设计", recordCount: 3, active: true }];
}

function currentTreeName() {
  const activeProject = state.projects.find((project) => project.id === state.activeProjectId);
  return activeProject?.trees.find((tree) => tree.id === state.activeTreeId)?.name || state.run.title || "Session Tree";
}

function memoryStats() {
  const treeMemoryItems = Math.max(
    4,
    state.memoryObjects.filter((item) => String(item.uri || "").startsWith("tree://")).length,
  );
  const longTermKnowledgeItems = Math.max(
    2,
    state.memoryObjects.filter((item) => String(item.uri || "").startsWith("mem://")).length,
  );
  return {
    activePathSessions: 3,
    treeMemoryItems,
    longTermKnowledgeItems,
    mcpToolsAvailable: Math.max(5, mcpToolCount()),
  };
}

function mcpToolCount() {
  const mcpTools = state.tools.filter((tool) => String(tool.name || tool).startsWith("mcp_")).length;
  if (mcpTools) return mcpTools;
  return (state.mcpReport.match(/\bready\b|\btool\b|mcp_/gi) || []).length;
}

function findSessionNode(node, id) {
  if (node.id === id) return node;
  for (const child of node.children || []) {
    const found = findSessionNode(child, id);
    if (found) return found;
  }
  return null;
}

function nodeAction(label, onClick) {
  return el("button", {
    type: "button",
    onclick: (event) => {
      event.stopPropagation();
      onClick();
    },
  }, label);
}

function button(label, variant, onClick) {
  return el("button", { class: `btn ${variant}`, type: "button", onclick: onClick }, label);
}

function layerPill(label, kind) {
  return el("span", { class: `layer-pill ${kind}` }, label);
}

function insertCommand(command) {
  const input = document.querySelector("#composer-input");
  if (!input) return;
  input.value = input.value ? `${input.value} ${command}` : `${command} `;
  input.focus();
}

function focusComposer() {
  state.activeTab = "chat";
  renderAppLayout();
  window.requestAnimationFrame(() => document.querySelector("#composer-input")?.focus());
}

async function apiGet(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`${path} ${response.status}`);
  return response.json();
}

async function apiPost(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `${path} ${response.status}`);
  return data;
}

function normalizeTool(tool, fallbackId) {
  return {
    id: tool.id || tool.toolUseId || `${fallbackId}-${tool.name || "tool"}`,
    name: tool.name || "tool",
    status: tool.status || "done",
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

function shortId(value) {
  return String(value || "").slice(0, 8);
}

function parseJson(value) {
  try {
    return JSON.parse(value || "{}");
  } catch {
    return {};
  }
}

function showToast(message) {
  nodes.toast.textContent = message;
  nodes.toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    nodes.toast.hidden = true;
  }, 2600);
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
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
