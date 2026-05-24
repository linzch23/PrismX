const mockRun = {
  taskName: "Implement Coding Agent Web UI",
  meta: "mock run · /Users/ipsc_gummy/Desktop/agent/my_agent2",
  status: "running",
  activeTab: "agent",
  activeInspector: "trace",
  selectedTreeNode: "leaf-07",
  sessionId: "mock",
  sessions: [],
  lastUpdated: null,
  memory: "# Long-term Memory\n\n(mock fallback)",
  memoryExists: false,
  steps: [
    {
      id: "step-01",
      nodeId: "root-01",
      title: "Read product direction",
      status: "done",
      time: "09:41",
      summary: "Captured the target: OpenHands / Replit Agent / Devin style workflow.",
      details:
        "The default view should emphasize run execution and workbench state. Session Tree and raw trace stay behind explicit controls.",
      tools: [
        {
          id: "tool-01",
          name: "read_file",
          status: "done",
          output:
            "README.md\nsrc/my_agent2/loop.py\nsrc/my_agent2/tree_session.py\nfrontend/index.html",
        },
      ],
      expanded: true,
    },
    {
      id: "step-02",
      nodeId: "run-02",
      title: "Design shell layout",
      status: "done",
      time: "09:47",
      summary: "Replaced chat-first structure with a task-first command surface.",
      details:
        "TopBar owns task identity and navigation. Timeline owns agent execution. Workbench owns files, preview, code, and tool records.",
      tools: [],
      expanded: true,
    },
    {
      id: "step-03",
      nodeId: "tool-03",
      title: "Create run timeline",
      status: "running",
      time: "09:52",
      summary: "Rendering collapsible steps with status, tool output, and compact evidence.",
      details:
        "Mock RunStep data is used for this version. The API-backed build maps JSONL message/tool entries into the same shape.",
      tools: [
        {
          id: "tool-03",
          name: "edit_file",
          status: "running",
          output:
            "frontend/index.html\nfrontend/styles.css\nfrontend/app.js\n\nStatus: replacing static prototype.",
        },
      ],
      expanded: true,
    },
    {
      id: "step-04",
      nodeId: "leaf-07",
      title: "Wire hidden tree and inspector",
      status: "pending",
      time: "next",
      summary: "Keep jump / fork / label and trace details off the default screen.",
      details: "Drawer actions stay read-only until the API write path is intentionally enabled.",
      tools: [],
      expanded: false,
    },
  ],
  changes: [
    { path: "frontend/index.html", type: "modified", additions: 84, deletions: 90 },
    { path: "frontend/styles.css", type: "modified", additions: 520, deletions: 390 },
    { path: "frontend/app.js", type: "modified", additions: 380, deletions: 320 },
    { path: "src/my_agent2/server.py", type: "added", additions: 375, deletions: 0 },
  ],
  preview: {
    url: "http://127.0.0.1:8765",
    title: "Local workbench preview",
  },
  codeFiles: [
    {
      path: "frontend/app.js",
      language: "js",
      content: `const runStep = {
  title: "Create run timeline",
  status: "running",
  tools: [{ name: "edit_file", status: "running" }]
};

renderTimeline(run.steps);
renderWorkbench(run.activeTab);`,
    },
    {
      path: "src/my_agent2/server.py",
      language: "py",
      content: `def _tree_payload(app, *, filter_mode="default"):
    session = app.tree.sessions[app.session_id]
    return {
        "activeLeafId": session.activeLeafId,
        "nodes": nodes,
        "debug": app.tree.debugBuildModelContext(app.session_id),
    }`,
    },
  ],
  tools: [
    { id: "tool-01", name: "read_file", status: "done", duration: "42ms", target: "README.md" },
    { id: "tool-02", name: "rg", status: "done", duration: "18ms", target: "src/my_agent2" },
    { id: "tool-03", name: "edit_file", status: "running", duration: "active", target: "frontend/" },
  ],
  tree: [
    { id: "root-01", parentId: null, type: "message", label: "task", preview: "Build web UI" },
    { id: "run-02", parentId: "root-01", type: "message", label: "plan", preview: "Design agent shell" },
    { id: "tool-03", parentId: "run-02", type: "tool_result", label: "", preview: "Read project files" },
    { id: "leaf-07", parentId: "tool-03", type: "message", label: "active", preview: "Implement mock UI" },
    { id: "branch-04", parentId: "run-02", type: "message", label: "alt", preview: "Earlier tree-first prototype" },
  ],
  trace: {
    activeLeafId: "leaf-07",
    includedEntryIds: ["root-01", "run-02", "tool-03", "leaf-07"],
    excludedEntryIds: ["branch-04"],
    estimatedTokens: 1820,
    compactionApplied: false,
  },
  raw: {},
};

const ui = {
  tab: "agent",
  selectedStepId: "step-03",
  selectedTreeNodeId: mockRun.selectedTreeNode,
  inspectorPanel: "trace",
};

const state = {
  run: cloneMockRun(),
  apiMode: false,
  loading: false,
  sending: false,
  selectedNodeDetail: null,
};

const $ = (selector) => document.querySelector(selector);

const nodes = {
  taskName: $("#task-name"),
  taskMeta: $("#task-meta"),
  visibleTaskTitle: $("#visible-task-title"),
  agentCount: $("#agent-count"),
  usageLabel: $("#usage-label"),
  usagePercent: $("#usage-percent"),
  usageMeterFill: $("#usage-meter-fill"),
  metadataSource: $("#metadata-source"),
  metadataUpdated: $("#metadata-updated"),
  status: $("#run-status"),
  tabs: [...document.querySelectorAll(".top-tab")],
  timeline: $("#timeline"),
  runSummary: $("#run-summary"),
  workbenchTitle: $("#workbench-title"),
  workbenchSubtitle: $("#workbench-subtitle"),
  workbenchContent: $("#workbench-content"),
  composer: $("#composer"),
  composerInput: $("#composer-input"),
  collapseAll: $("#collapse-all"),
  expandAll: $("#expand-all"),
  openTree: $("#open-tree"),
  closeTree: $("#close-tree"),
  treeDrawer: $("#tree-drawer"),
  treeContent: $("#tree-content"),
  treeActive: $("#tree-active"),
  backdrop: $("#drawer-backdrop"),
  openInspector: $("#open-inspector"),
  closeInspector: $("#close-inspector"),
  inspector: $("#inspector"),
  inspectorTabs: [...document.querySelectorAll(".inspector-tab")],
  inspectorContent: $("#inspector-content"),
  toast: $("#toast"),
};

function cloneMockRun() {
  return JSON.parse(JSON.stringify(mockRun));
}

function currentRun() {
  return state.run || mockRun;
}

async function loadRealData() {
  state.loading = true;
  render();
  try {
    const sessionsPayload = await apiGet("/api/sessions");
    const sessions = normalizeSessions(sessionsPayload.sessions);
    const selected = selectRecentSession(sessions, sessionsPayload.activeSessionId);
    if (!selected) {
      throw new Error("no sessions found");
    }

    const sessionId = selected.id;
    const [runsPayload, treePayload, memoryPayload, toolsPayload] = await Promise.all([
      apiGet(`/api/sessions/${encodeURIComponent(sessionId)}/runs`),
      apiGet(`/api/sessions/${encodeURIComponent(sessionId)}/tree`),
      apiGet("/api/memory"),
      apiGet("/api/tools"),
    ]);

    state.run = buildRunFromApi({
      selected,
      sessions,
      runsPayload,
      treePayload,
      memoryPayload,
      toolsPayload,
    });
    state.apiMode = true;
    ui.selectedTreeNodeId = state.run.selectedTreeNode;
  } catch (error) {
    state.run = cloneMockRun();
    state.run.meta += ` · API fallback: ${error.message}`;
    state.apiMode = false;
    showToast(`Using mock fallback: ${error.message}`);
  } finally {
    state.loading = false;
    render();
  }
}

async function apiGet(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}`);
  }
  return response.json();
}

async function apiPost(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || `${path} returned ${response.status}`);
  }
  return data;
}

function normalizeSessions(rawSessions) {
  if (!Array.isArray(rawSessions)) return [];
  return rawSessions
    .map((item) => {
      if (typeof item === "string") {
        return { id: item, updatedAt: null, recordCount: null, activeLeafId: null };
      }
      return {
        id: String(item.id || ""),
        title: item.title || null,
        updatedAt: item.updatedAt || null,
        createdAt: item.createdAt || null,
        recordCount: item.recordCount ?? null,
        activeLeafId: item.activeLeafId || null,
      };
    })
    .filter((item) => item.id);
}

function selectRecentSession(sessions, activeSessionId) {
  if (!sessions.length) return null;
  const sorted = [...sessions].sort((a, b) => {
    const at = Date.parse(a.updatedAt || a.createdAt || "") || 0;
    const bt = Date.parse(b.updatedAt || b.createdAt || "") || 0;
    if (at !== bt) return at - bt;
    return a.id.localeCompare(b.id);
  });
  return sorted.at(-1) || sessions.find((item) => item.id === activeSessionId) || sessions[0];
}

function buildRunFromApi({ selected, sessions, runsPayload, treePayload, memoryPayload, toolsPayload }) {
  const steps = (runsPayload.runs || []).map((step, index) =>
    normalizeRunStep(step, index, runsPayload.runs.length),
  );
  const tree = (treePayload.nodes || []).map(normalizeTreeNode);
  const selectedTreeNode =
    selected.activeLeafId ||
    tree.find((node) => node.status === "active")?.id ||
    tree.at(-1)?.id ||
    "";
  const toolEvents = (runsPayload.toolEvents || []).map(normalizeToolEvent);
  const toolDefinitions = normalizeToolDefinitions(toolsPayload.tools);
  const tools = toolEvents.length ? toolEvents : toolDefinitions;
  const changes = (runsPayload.fileChanges || []).map(normalizeFileChange);
  const trace = {
    activeLeafId: selectedTreeNode,
    includedEntryIds: tree.map((node) => node.id),
    excludedEntryIds: [],
    estimatedTokens: 0,
    compactionApplied: steps.some((step) => step.kind === "checkpoint"),
  };

  return {
    taskName: selected.title || `Session ${selected.id}`,
    meta: `real JSONL · ${selected.id} · ${selected.recordCount ?? tree.length} records`,
    status: "done",
    sessionId: selected.id,
    sessions,
    lastUpdated: selected.updatedAt || selected.createdAt || null,
    selectedTreeNode,
    steps,
    changes,
    preview: {
      url: window.location.origin || "http://127.0.0.1:8765",
      title: "Local workbench preview",
    },
    codeFiles: [
      {
        path: `sessions/${selected.id}.jsonl`,
        language: "jsonl",
        content: "Use the Raw JSON inspector to inspect records for this read-only session.",
      },
    ],
    tools,
    toolDefinitions,
    tree,
    trace,
    memory: memoryPayload.memory || "",
    memoryExists: Boolean(memoryPayload.exists),
    raw: {
      session: selected,
      runs: runsPayload,
      tree: treePayload,
      memory: memoryPayload,
      tools: toolsPayload,
    },
  };
}

function normalizeRunStep(step, index, total) {
  const toolCalls = Array.isArray(step.toolCalls) ? step.toolCalls.map(normalizeStepTool) : [];
  return {
    id: step.id || `step-${index + 1}`,
    nodeId: step.nodeId || step.id || "",
    kind: step.kind || "assistant",
    title: step.title || capitalize(step.kind || "step"),
    status: normalizeStatus(step.status),
    time: formatTime(step.createdAt),
    summary: step.summary || "(no summary)",
    details: step.output || step.summary || "",
    tools: toolCalls,
    expanded: index >= Math.max(total - 4, 0),
    raw: step,
  };
}

function normalizeStepTool(tool) {
  return {
    id: tool.id || tool.name || "tool",
    name: tool.name || "tool",
    status: normalizeStatus(tool.status),
    input: tool.input || {},
    output: tool.output || "(no output yet)",
  };
}

function normalizeTreeNode(node) {
  return {
    id: node.id,
    parentId: node.parentId || null,
    type: node.type || "node",
    label: node.label || "",
    status: node.status || "normal",
    preview: node.preview || "",
    children: Array.isArray(node.children) ? node.children : [],
    raw: node,
  };
}

function normalizeToolEvent(tool) {
  return {
    id: tool.id || tool.toolUseId || tool.name,
    name: tool.name || "tool",
    status: normalizeStatus(tool.status),
    duration: formatTime(tool.createdAt),
    target: tool.target || summarizeInput(tool.input),
    output: tool.output || "",
  };
}

function normalizeToolDefinitions(tools) {
  if (!Array.isArray(tools)) return [];
  return tools.map((tool) => ({
    id: tool.name || tool,
    name: tool.name || String(tool),
    status: "done",
    duration: "available",
    target: tool.description || "registered tool",
    output: tool.description || "",
  }));
}

function normalizeFileChange(change) {
  return {
    path: change.path || "(unknown)",
    type: change.type || "modified",
    additions: change.additions ?? 0,
    deletions: change.deletions ?? 0,
  };
}

function normalizeStatus(status) {
  if (status === "running" || status === "error" || status === "pending") return status;
  return "done";
}

function summarizeInput(input) {
  if (!input || typeof input !== "object") return "";
  return input.path || input.command || input.url || input.pattern || "";
}

function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatDateTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString([], {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function render() {
  const run = currentRun();
  nodes.taskName.textContent = run.taskName;
  nodes.visibleTaskTitle.textContent = run.taskName;
  nodes.taskMeta.textContent = state.loading ? `${run.meta} · loading` : run.meta;
  nodes.agentCount.textContent = String(run.tools.length || 1);
  nodes.usageLabel.textContent = state.apiMode ? "Session" : "Fallback";
  nodes.usagePercent.textContent = `${run.steps.length} steps`;
  nodes.usageMeterFill.style.width = `${Math.min(100, Math.max(8, run.steps.length * 2))}%`;
  nodes.metadataSource.textContent = state.apiMode
    ? `JSONL source: sessions/${run.sessionId}.jsonl`
    : "Mock fallback data source";
  nodes.metadataUpdated.textContent = run.lastUpdated
    ? `Last record: ${formatDateTime(run.lastUpdated)}`
    : "Waiting for latest record";
  nodes.status.className = `status-button ${run.status}`;
  const statusText = state.sending ? "sending" : state.apiMode ? "real data" : run.status;
  nodes.status.innerHTML = `<span></span> ${capitalize(statusText)}`;
  nodes.tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === ui.tab));
  nodes.inspectorTabs.forEach((tab) =>
    tab.classList.toggle("active", tab.dataset.panel === ui.inspectorPanel),
  );
  renderTimeline();
  renderWorkbench();
  renderTreeDrawer();
  renderInspector();
}

function renderTimeline() {
  const run = currentRun();
  const done = run.steps.filter((step) => step.status === "done").length;
  const running = run.steps.filter((step) => step.status === "running").length;
  nodes.runSummary.textContent = `${done} done · ${running} running · ${run.steps.length} steps`;
  nodes.timeline.replaceChildren(...run.steps.map(renderStep));
}

function renderStep(step, index) {
  const article = document.createElement("article");
  article.className = `run-step ${step.status} ${step.expanded ? "expanded" : ""}`;
  const button = document.createElement("button");
  button.className = "step-toggle";
  button.setAttribute("aria-expanded", String(step.expanded));
  button.innerHTML = `
    <span class="step-rail"><span class="step-index">${index + 1}</span></span>
    <span class="step-main">
      <span class="step-topline">
        <span class="step-title">${escapeHtml(step.title)}</span>
        <span class="step-time">${escapeHtml(step.time)}</span>
      </span>
      <span class="step-summary">${escapeHtml(step.summary)}</span>
    </span>
    <span class="step-state">${escapeHtml(step.status)}</span>
  `;
  button.addEventListener("click", () => {
    step.expanded = !step.expanded;
    renderTimeline();
  });
  article.appendChild(button);

  if (step.expanded) {
    const body = document.createElement("div");
    body.className = "step-body";
    body.appendChild(paragraph(step.details));
    if (step.tools.length) {
      body.appendChild(toolOutputList(step.tools));
    }
    article.appendChild(body);
  }
  return article;
}

function toolOutputList(tools) {
  const wrap = document.createElement("div");
  wrap.className = "tool-output-list";
  for (const tool of tools) {
    const details = document.createElement("details");
    details.className = `tool-output ${tool.status}`;
    details.open = tool.status === "running";
    details.innerHTML = `
      <summary>
        <span>${escapeHtml(tool.name)}</span>
        <span>${escapeHtml(tool.status)}</span>
      </summary>
      <pre>${escapeHtml(tool.output)}</pre>
    `;
    wrap.appendChild(details);
  }
  return wrap;
}

function renderWorkbench() {
  const run = currentRun();
  const titleMap = {
    agent: ["Agent", "current run workspace"],
    changes: ["Changes", "files touched by this run"],
    preview: ["Preview", run.preview.url],
    code: ["Code", run.codeFiles[0]?.path || "session"],
    tools: ["Tools", `${run.tools.length} tool calls`],
  };
  const [title, subtitle] = titleMap[ui.tab] || titleMap.agent;
  nodes.workbenchTitle.textContent = title;
  nodes.workbenchSubtitle.textContent = subtitle;
  if (ui.tab === "agent") renderAgentPanel();
  if (ui.tab === "changes") renderChangesPanel();
  if (ui.tab === "preview") renderPreviewPanel();
  if (ui.tab === "code") renderCodePanel();
  if (ui.tab === "tools") renderToolsPanel();
}

function renderAgentPanel() {
  const run = currentRun();
  nodes.workbenchContent.replaceChildren(
    metricGrid([
      ["Session", run.sessionId || "mock"],
      ["Steps", String(run.steps.length)],
      ["Changed", String(run.changes.length)],
      ["Tools", String(run.tools.length)],
    ]),
    sectionBlock("Current Step", run.steps.find((step) => step.status === "running")?.summary || run.steps.at(-1)?.summary || ""),
    sectionBlock("Data Source", state.apiMode ? "Live API session data." : "Mock fallback data."),
  );
}

function renderChangesPanel() {
  const run = currentRun();
  if (!run.changes.length) {
    nodes.workbenchContent.replaceChildren(sectionBlock("Changes", "No file changes detected yet."));
    return;
  }
  const list = document.createElement("div");
  list.className = "changes-list";
  for (const change of run.changes) {
    const row = document.createElement("button");
    row.className = `change-row ${change.type}`;
    row.innerHTML = `
      <span class="file-dot"></span>
      <span class="file-main">
        <span>${escapeHtml(change.path)}</span>
        <span>${escapeHtml(change.type)}</span>
      </span>
      <span class="diff-stat">+${escapeHtml(change.additions)} -${escapeHtml(change.deletions)}</span>
    `;
    row.addEventListener("click", () => {
      ui.tab = "code";
      render();
    });
    list.appendChild(row);
  }
  nodes.workbenchContent.replaceChildren(list);
}

function renderPreviewPanel() {
  const run = currentRun();
  const frame = document.createElement("div");
  frame.className = "preview-frame";
  frame.innerHTML = `
    <div class="preview-toolbar">
      <span></span><span></span><span></span>
      <div>${escapeHtml(run.preview.url)}</div>
    </div>
    <div class="preview-empty">
      <strong>${escapeHtml(run.preview.title)}</strong>
      <p>${escapeHtml(state.apiMode ? "Live API is serving this workbench." : "API unavailable; mock preview is active.")}</p>
    </div>
  `;
  nodes.workbenchContent.replaceChildren(frame);
}

function renderCodePanel() {
  const run = currentRun();
  const file = run.codeFiles[0] || { path: "session", language: "text", content: "" };
  const wrap = document.createElement("div");
  wrap.className = "code-view";
  wrap.innerHTML = `
    <div class="code-head">
      <span>${escapeHtml(file.path)}</span>
      <span>${escapeHtml(file.language)}</span>
    </div>
    <pre>${escapeHtml(file.content)}</pre>
  `;
  nodes.workbenchContent.replaceChildren(wrap);
}

function renderToolsPanel() {
  const run = currentRun();
  const definitions = Array.isArray(run.toolDefinitions) ? run.toolDefinitions : [];
  if (!run.tools.length && !definitions.length) {
    nodes.workbenchContent.replaceChildren(sectionBlock("Tools", "No tool calls detected yet."));
    return;
  }

  const panel = document.createElement("div");
  panel.className = "tools-directory";

  const search = document.createElement("label");
  search.className = "tool-search";
  search.innerHTML = `
    <input aria-label="Search tools" placeholder="Search for tools and files..." />
  `;
  panel.appendChild(search);

  if (definitions.length) {
    const directory = document.createElement("section");
    directory.className = "tool-directory-section";
    directory.innerHTML = `<h3>Available tools</h3>`;
    for (const tool of definitions) {
      const row = document.createElement("button");
      row.className = "directory-tool-row";
      row.innerHTML = `
        <span class="directory-tool-icon">${escapeHtml(tool.name.slice(0, 2) || "tl")}</span>
        <span class="directory-tool-main">
          <span>${escapeHtml(tool.name)}</span>
          <span>${escapeHtml(tool.target || tool.output || "registered tool")}</span>
        </span>
      `;
      directory.appendChild(row);
    }
    panel.appendChild(directory);
  }

  const table = document.createElement("section");
  table.className = "tool-call-strip";
  table.innerHTML = `<h3>Recent tool calls</h3>`;
  for (const tool of run.tools) {
    const row = document.createElement("div");
    row.className = `tool-row ${tool.status}`;
    row.innerHTML = `
      <span class="status-dot"></span>
      <span>${escapeHtml(tool.name)}</span>
      <span>${escapeHtml(tool.target)}</span>
      <span>${escapeHtml(tool.duration)}</span>
    `;
    table.appendChild(row);
  }
  panel.appendChild(table);
  nodes.workbenchContent.replaceChildren(panel);
}

function renderTreeDrawer() {
  const run = currentRun();
  nodes.treeActive.textContent = `active leaf ${run.selectedTreeNode || "(none)"}`;
  const byParent = new Map();
  for (const item of run.tree) {
    const key = item.parentId || "root";
    if (!byParent.has(key)) byParent.set(key, []);
    byParent.get(key).push(item);
  }
  const root = document.createElement("div");
  root.className = "drawer-tree";
  for (const node of byParent.get("root") || []) {
    root.appendChild(renderTreeNode(node, byParent, 0));
  }
  nodes.treeContent.replaceChildren(root);
}

function renderTreeNode(node, byParent, depth) {
  const wrap = document.createElement("div");
  wrap.className = "drawer-tree-item";
  const button = document.createElement("button");
  button.className = node.id === ui.selectedTreeNodeId ? "selected" : "";
  button.style.setProperty("--indent", `${depth * 18}px`);
  button.innerHTML = `
    <span class="node-kind ${escapeAttr(node.type)}"></span>
    <span class="drawer-node-main">
      <span>${escapeHtml(node.id)} · ${escapeHtml(node.type)}</span>
      <span>${escapeHtml(node.preview)}</span>
    </span>
    <span>${escapeHtml(node.status === "active" ? "active" : node.label || "")}</span>
  `;
  button.addEventListener("click", () => selectTreeNode(node));
  wrap.appendChild(button);
  const actions = document.createElement("div");
  actions.className = "tree-actions";
  actions.style.setProperty("--indent", `${depth * 18 + 20}px`);
  actions.append(
    smallAction("Jump", () => readOnlyAction(`jump ${node.id}`)),
    smallAction("Fork", () => readOnlyAction(`fork ${node.id}`)),
    smallAction("Label", () => readOnlyAction(`label ${node.id}`)),
  );
  wrap.appendChild(actions);
  for (const child of byParent.get(node.id) || []) {
    wrap.appendChild(renderTreeNode(child, byParent, depth + 1));
  }
  return wrap;
}

async function selectTreeNode(node) {
  ui.selectedTreeNodeId = node.id;
  state.selectedNodeDetail = node.raw || node;
  renderTreeDrawer();
  renderInspector();
  if (!state.apiMode || !currentRun().sessionId) return;
  try {
    state.selectedNodeDetail = await apiGet(
      `/api/sessions/${encodeURIComponent(currentRun().sessionId)}/node/${encodeURIComponent(node.id)}`,
    );
    renderInspector();
  } catch (error) {
    showToast(`Node detail unavailable: ${error.message}`);
  }
}

function renderInspector() {
  const run = currentRun();
  if (ui.inspectorPanel === "trace") {
    nodes.inspectorContent.replaceChildren(
      metricGrid([
        ["Active", run.trace.activeLeafId || "(none)"],
        ["Included", String(run.trace.includedEntryIds.length)],
        ["Excluded", String(run.trace.excludedEntryIds.length)],
        ["Tokens", String(run.trace.estimatedTokens)],
      ]),
      codeBlock(run.trace),
    );
  }
  if (ui.inspectorPanel === "context") {
    nodes.inspectorContent.replaceChildren(
      sectionBlock("Context Window", run.trace.includedEntryIds.join(" -> ") || "(empty)"),
      sectionBlock("Compaction", String(run.trace.compactionApplied)),
    );
  }
  if (ui.inspectorPanel === "memory") {
    nodes.inspectorContent.replaceChildren(
      run.memoryExists ? codeBlock(run.memory) : sectionBlock("Memory", "No memory file found."),
    );
  }
  if (ui.inspectorPanel === "raw") {
    nodes.inspectorContent.replaceChildren(codeBlock(state.selectedNodeDetail || run.raw || run));
  }
}

function metricGrid(items) {
  const grid = document.createElement("div");
  grid.className = "metric-grid";
  for (const [label, value] of items) {
    const item = document.createElement("div");
    item.className = "metric";
    item.innerHTML = `<span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>`;
    grid.appendChild(item);
  }
  return grid;
}

function sectionBlock(title, body) {
  const block = document.createElement("section");
  block.className = "section-block";
  block.innerHTML = `<h3>${escapeHtml(title)}</h3><p>${escapeHtml(body)}</p>`;
  return block;
}

function paragraph(text) {
  const p = document.createElement("p");
  p.className = "step-detail";
  p.textContent = text;
  return p;
}

function codeBlock(value) {
  const pre = document.createElement("pre");
  pre.className = "json-block";
  pre.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return pre;
}

function smallAction(label, handler) {
  const button = document.createElement("button");
  button.textContent = label;
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    handler();
  });
  return button;
}

function setDrawer(open) {
  nodes.treeDrawer.classList.toggle("open", open);
  nodes.treeDrawer.setAttribute("aria-hidden", String(!open));
  nodes.backdrop.hidden = !open && !nodes.inspector.classList.contains("open");
}

function setInspector(open) {
  nodes.inspector.classList.toggle("open", open);
  nodes.inspector.setAttribute("aria-hidden", String(!open));
  nodes.backdrop.hidden = !open && !nodes.treeDrawer.classList.contains("open");
}

function readOnlyAction(message) {
  showToast(`Read-only V2: ${message} is not enabled.`);
}

function showToast(message) {
  nodes.toast.textContent = message;
  nodes.toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    nodes.toast.hidden = true;
  }, 2200);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function escapeAttr(value) {
  return String(value ?? "").replace(/[^a-zA-Z0-9_-]/g, "_");
}

function capitalize(value) {
  const text = String(value || "");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

nodes.tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    ui.tab = tab.dataset.tab;
    render();
  });
});

nodes.inspectorTabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    ui.inspectorPanel = tab.dataset.panel;
    render();
  });
});

nodes.collapseAll.addEventListener("click", () => {
  currentRun().steps.forEach((step) => {
    step.expanded = false;
  });
  renderTimeline();
});

nodes.expandAll.addEventListener("click", () => {
  currentRun().steps.forEach((step) => {
    step.expanded = true;
  });
  renderTimeline();
});

nodes.composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  const value = nodes.composerInput.value.trim();
  if (!value || state.sending) return;
  if (state.apiMode) {
    state.sending = true;
    render();
    try {
      await apiPost("/api/chat", { message: value });
      nodes.composerInput.value = "";
      showToast("Sent to /api/chat; session reloaded.");
      await loadRealData();
    } catch (error) {
      showToast(`Send failed: ${error.message}`);
    } finally {
      state.sending = false;
      render();
    }
    return;
  }
  currentRun().steps.push({
    id: `step-${String(currentRun().steps.length + 1).padStart(2, "0")}`,
    nodeId: "",
    title: value,
    status: "pending",
    time: "queued",
    summary: "Queued in mock mode.",
    details: "The API-backed build is read-only in V2.",
    tools: [],
    expanded: true,
  });
  nodes.composerInput.value = "";
  render();
});

nodes.openTree.addEventListener("click", () => setDrawer(true));
nodes.closeTree.addEventListener("click", () => setDrawer(false));
nodes.openInspector.addEventListener("click", () => setInspector(true));
nodes.closeInspector.addEventListener("click", () => setInspector(false));
nodes.backdrop.addEventListener("click", () => {
  setDrawer(false);
  setInspector(false);
});

render();
loadRealData();
