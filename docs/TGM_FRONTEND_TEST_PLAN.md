# TGM 前端交互测试规划

## 测试目标

通过一组精心编排的 Agent 交互，串联验证 TGM 2.0/3.0 全部功能板块，同时诊断前端可视化各环节的数据呈现是否完整，识别缺失的 UI 组件。

---

## 场景设定

**任务主题**：让 Agent 帮我设计一个"文件批量重命名 CLI 工具"

为什么选这个场景：
- 需要多轮分析（需求 → 技术选型 → 实现 → 调错 → 沉淀经验）
- 自然产生分支（不同方案对比）
- 会触发工具调用（生成 TraceEvent + Evidence）
- 有失败场景（方便测 Rollback）
- 最终形成可复用的 pattern（测试 Promote）

---

## 测试全景：数据流 × 前端可视化

```
┌───────────────┐    ┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│   Round 1-2   │    │   Round 3     │    │   Round 4     │    │   Round 5-6   │
│  Session Tree │───>│  Tree Memory  │───>│ Fold/Evidence │───>│  Promote +    │
│  创建+分支    │    │  写入+召回    │    │  /Rollback    │    │  Cross-Tree   │
└───────────────┘    └───────────────┘    └───────────────┘    └───────────────┘
        │                    │                    │                    │
        v                    v                    v                    v
   Tree 标签页          Memory 标签页        新增面板             Memory 标签页
   SessionNode卡片      ContextCard          Evidence查看器      Long-term面板
   Active Path高亮      Memory条目列表       FoldedNode详情      Knowledge Graph
```

---

## Round 1：创建项目 + 启动首次对话

### 操作步骤

1. 打开 PrismX 前端 `http://localhost:8765`
2. 侧边栏 → 点击 "New Project" → 选择工作区目录 → 命名为 `rename-tool`
3. 侧边栏 → 点击 "New Session Tree" → 命名为 `批量重命名工具开发`
4. 自动进入 Chat 标签页，root Session 已创建

### 对话内容

```
User: 我要开发一个文件批量重命名的 CLI 工具，帮我先整理一份需求清单，列出核心功能点和约束条件。
```

Agent 预期行为：
1. 分析需求，列出功能点（递归遍历、正则匹配、序号补零、预览模式、备份机制等）
2. 如果调用了搜索/文件工具 → 产生 `TraceEvent(tool_call + tool_result)` + Evidence
3. 回复内容记录为 `TraceEvent(assistant)` + Evidence(note)

### 前端验证

| 验证点 | 标签页 | 预期展示 |
|--------|--------|----------|
| Root SessionNode 出现 | Tree | 卡片显示 session 名称 + status 徽章 + 消息计数 |
| 消息卡片渲染 | Chat | 用户消息 + Agent 回复（含 tool chip 如果调用了工具） |
| info-pill 行显示 | Chat | `Project: rename-tool / Tree: 批量重命名工具开发 / Messages: 2` |

### 后端验证

```bash
# 确认 TraceEvent 写入
cat data/tree_memory/{tree_id}/trace_events.jsonl | wc -l
# 预期: >= 2 (user + assistant，如果调了工具则更多)

# 确认 Evidence 写入
ls data/tree_memory/{tree_id}/evidence/note/
# 预期: 有 .txt 文件
```

---

## Round 2：创建分支 — 验证 Session Tree 可视化 + Active Path

### 操作步骤

1. 切换到 **Tree 标签页**
2. 在 root SessionNode 上点击 **+** → 输入名称 `需求分析与约束` → Create
3. 点击该子节点切换到新 Session → 自动跳回 Chat 标签页
4. 回到 Tree 标签页，在 root 上再点 **+** → 输入名称 `技术选型` → Create

此时树结构：

```
批量重命名工具开发 (root)
├── 需求分析与约束
└── 技术选型
```

### 对话内容

**在 `需求分析与约束` Session 中：**

```
User: 基于 root 的需求，细化 5 条核心约束：
1. 必须跨平台（Windows/Linux/macOS）
2. 支持 dry-run 预览模式
3. 正则替换和序号补零两种模式
4. 支持递归遍历子目录
5. 重命名前校验文件名冲突

把这些约束记录下来。
```

**切换到 `技术选型` Session：**

```
User: 对比 Python pathlib vs os.path 两种方案实现这个工具，
重点比较：跨平台兼容性、API 易用性、性能。推荐一个方案。
```

### 前端验证

| 验证点 | 标签页 | 预期展示 |
|--------|--------|----------|
| 两个子节点在 root 下方排列 | Tree | 从左到右: root → (需求分析, 技术选型) 两列 |
| Active Path 高亮 | Tree | 当前选中节点的父链节点卡片有紫色边框（`.path` class），连线变粗变紫 |
| 点击不同子节点 | Tree | Active Path 连线动态切换 |
| 切换兄弟分支后聊天不互串 | Chat | `技术选型` 的聊天记录看不到 `需求分析` 的对话内容 |

### 后端验证

```bash
# 确认 SessionNode 写入
cat data/workspace.json | python -c "import sys,json; d=json.load(sys.stdin); print([n['title'] for n in d.get('sessionNodes',[])])"
# 预期: 包含 3 个 session

# 确认兄弟分支隔离 — 两个 session 的 JSONL 是独立的
ls data/sessions/{tree_id}/sessions/
```

---

## Round 3：Tree Memory 写入 + Runtime Recall 跨分支召回（TGM 核心）

### 对话内容

**在 `需求分析与约束` Session 中：**

```
User: /memory add finding 文件批量重命名必须支持正则匹配和序号补零两种模式，正则模式支持捕获组引用
```

预期：CLI 执行 `remember()` → `record_event → store_evidence → fold → write memory_index`

**然后同样在 `需求分析与约束` Session 中：**

```
User: /memory add constraint 跨平台兼容性是硬约束，所有路径操作必须使用 pathlib，禁止字符串拼接路径
```

**切换到 `技术选型` Session：**

```
User: 根据之前讨论的需求，比较 pathlib vs os.path，请引用已有约束作为判断依据。
```

### 前端验证（Memory 标签页）

| 验证点 | 子卡片 | 预期展示 |
|--------|--------|----------|
| Active Path 路径列表 | Active Path Context | `1. 批量重命名工具开发 / X messages`<br>`2. 技术选型 / Y messages` |
| Tree Memory 展示 | Tree Memory Recall | 显示两条记忆的 MemoryItemCard：<br>`finding / active / 🔥 0 / conf 0.80 / 文件批量重命名必须支持正则匹配...`<br>`constraint / active / 🔥 0 / conf 0.80 / 跨平台兼容性是硬约束...` |
| Long-term Knowledge | Long-term Knowledge Recall | 当前应为空或仅有先前存在的条目（含可点击的 sourceTreeId 追溯） |
| 统计面板 | Working Context Preview | Active Path Sessions: 2<br>Tree Memory Items: 2<br>... |
| **搜索框** | Memory 标签页顶部 `memory-toolbar` | 输入 query → 点击 Search → 调用 `/api/memory/retrieve` → Tree Memory Recall 卡片实时过滤 |
| **Fold 按钮** | Memory 标签页顶部 "Fold Recent" | 点击 → 调用 `/api/memory/fold` → 将最近 TraceEvent 折叠为 FoldedNode |
| **条目展开** | 点击 MemoryItemCard → 展开详情 | 显示：ID / Type / Status / Confidence / Reuse / Source Session / Evidence links / Promote 按钮 |

#### 五大核心能力验证

| # | 能力 | 本轮验证方式 |
|---|------|-------------|
| 2 | 检索意图生成 | 在"技术选型" Session 中发送"引用已有约束"，切换到 **Debug 标签页 → Runtime Recall 面板**，检查 Coarse Reasoning 是否判断 `needs_retrieval`，RetrievalIntent 是否生成了包含"constraint"关键词的搜索意图 |
| 4 | FoldedNode + Evidence | 在 Memory 标签页展开 Tree Memory 条目，查看 Evidence links 是否可点击并弹窗显示原始内容 |

### 后端验证（Runtime Recall）

```bash
# 检查 /api/chat/stream 的日志，看 Runtime Recall 是否命中 Tree Memory
# 验证 reuse_count 是否递增
cat data/tree_memory/{tree_id}/folded_nodes.jsonl | python -c "import sys,json; [print(json.loads(l)['reuse_count'], json.loads(l)['title']) for l in sys.stdin]"
```

**核心验证**：Agent 在 `技术选型` Session 中回复时能否引用 `需求分析` Session 中沉淀的 Tree Memory（如"跨平台兼容性硬约束"），而不是直接看到 `需求分析` 的原始聊天记录。

---

## Round 4：TraceEvent + Evidence + Fold + Rollback（TGM 3.0 新增）

### 操作步骤

1. 在 root Session 上新创建一个子分支 `实现与调试`
2. 在这个 Session 中让 Agent 实际写代码和运行

### 对话内容

```
User: 用推荐的技术方案实现这个 CLI 工具，先创建一个 Python 脚本，然后在一个测试目录里运行它试试。
```

Agent 预期行为：
1. Write 工具写文件 → `TraceEvent(tool_call)` + `Evidence(code_snippet)`
2. Run 工具执行命令 → `TraceEvent(tool_call)` + `Evidence(command_output)`
3. 如果执行出错 → `Evidence(error_log)`

### 验证 Fold

```
User: /memory fold
```

预期：将最近的 TraceEvent 折叠为一个 FoldedNode（如 `partial_fix` 状态）

### 验证 Rollback Plan

```
User: /memory rollback <fold_id>
```

### 前端验证

**当前已实现的 UI（TGM 3.0 完整）：**

| 组件 | 标签页 | 验证方式 |
|------|--------|----------|
| **Evidence 列表** | Evidence 标签页 | 展示所有 Evidence 卡片（含 type badge + title + time），点击 → Modal 显示完整内容 |
| **TraceEvent 时间线** | Trace 标签页 | 按时间线展示（彩色 dot + type badge + 可展开卡片），展开后显示 Source Event 链接 |
| **Fold 按钮** | Memory 标签页 "Fold Recent" | 点击后折叠最近 TraceEvent 为 FoldedNode |
| **Rollback 按钮** | Memory 标签页 → 展开 failure/partial 条目 | 点击 → 弹出 RollbackPlanModal（risk / related_files / evidence_refs / suggested_steps） |
| **Memory item Promote 按钮** | Memory 标签页 → 展开条目详情 | 对未 promoted 的条目显示 Promote 按钮 |

#### 五大核心能力验证

| # | 能力 | 本轮验证方式 |
|---|------|-------------|
| 3 | 动态执行记忆树 | 切换到 Trace 标签页查看 TraceEvent 时间线 → 点击 "Fold Recent" → 再次查看 Trace 标签页和 Memory 标签页，确认生成了新的 FoldedNode |
| 4 | FoldedNode + Evidence | 切换到 Evidence 标签页 → 点击 Evidence 卡片查看原始工具输出/错误日志 → 在 Memory 标签页展开 FoldedNode，确认 Evidence links 可点击 |

### 后端验证

```bash
# 检查 Evidence 文件
ls data/tree_memory/{tree_id}/evidence/command_outputs/
ls data/tree_memory/{tree_id}/evidence/error_logs/
ls data/tree_memory/{tree_id}/evidence/code_snippets/

# 检查 FoldedNode
cat data/tree_memory/{tree_id}/folded_nodes.jsonl | python -c "import sys,json; [print(json.loads(l)['node_type'], json.loads(l)['title']) for l in sys.stdin]"

# 测试 Rollback API
curl -X POST http://localhost:8000/api/memory/rollback-plan -H "Content-Type: application/json" -d '{"fold_id": "<id>"}'
```

---

## Round 5：Promote — Tree Memory → Long-term Knowledge 晋升

### 对话内容

**重复 3 次交互，让 reuse_count 达到 3：**

```
User: 之前关于文件重命名的约束条件是什么？提醒我一下。
User: 重新检查一下实现是否符合需求和约束。
User: 总结一下这个项目中积累的关键设计决策。
```

每次 Agent 回复时，Runtime Recall 应命中同一条 Tree Memory（跨平台约束、正则+序号双模式），`reuse_count` 每次 +1。

### 触发晋升

当某条 Tree Memory 的 `reuse_count >= 3`：

```
User: /memory promote <fold_id> --type pattern
```

预期：
- 写入 `data/knowledge/memories/pattern/{id}.md`
- 写入 `data/knowledge/graph/nodes.jsonl`
- 写入 `data/knowledge/graph/edges.jsonl`（relation=`promoted_to`）
- 写入 `data/knowledge/promotion_log.jsonl`
- FoldedNode 标记为 `promoted=true`
- `MEMORY.md` 更新索引

### 前端验证

**当前前端对 Long-term Knowledge 的展示**（Memory 标签页第 3 格）：

```
pattern / tree xxx / memory xxx / confidence 0.95 / active / 文件重命名必须支持正则和序号
```

**缺失的 UI：**

| 缺失组件 | 说明 |
|----------|------|
| **Knowledge Graph 可视化** | 当前只有文本行列表，无法展示 nodes + edges 的关系图 |
| **Promotion Log 时间线** | 什么时候、为什么晋升、来源追溯 |
| **Promote 操作按钮** | 在 Tree Memory 条目旁增加 Promote 按钮 |
| **source_tree_id / source_fold_id 可点击追溯** | 当前只显示为文本，无法跳转到源 FoldedNode 或源 Evidence |

### 后端验证

```bash
# 检查晋升结果
cat data/knowledge/MEMORY.md
cat data/knowledge/memories/pattern/*.md
cat data/knowledge/graph/nodes.jsonl
cat data/knowledge/graph/edges.jsonl
cat data/knowledge/promotion_log.jsonl
```

---

## Round 6：跨树 Long-term Knowledge 召回

### 操作步骤

1. 侧边栏 → New Session Tree → 命名 `另一个Python项目`
2. 在新 root Session 中对话

### 对话内容

```
User: 我要开始一个新的 Python CLI 工具项目，帮我想想有什么之前积累的经验可以复用？
```

### 验证点

- Runtime Recall 的 Long-term Knowledge Recall 层应命中之前晋升的 pattern
- Agent 回复应提到"之前跨平台路径用 pathlib"、"文件重命名工具中的正则+序号模式"等
- 前端 Memory 标签页的 Long-term Knowledge Recall 卡片应显示跨树知识条目
- 条目的 `sourceTreeId` 应指向旧树，证明跨树召回

---

## Round 7（附加）：LLM Runtime Recall 全链路可视化

> **这是本次新增的核心测试轮次**，验证 Debug 标签页中新增的 Runtime Recall 调试面板。

### 操作步骤

1. 切换到 **Debug 标签页**
2. 点击 **Refresh** 加载数据
3. 回到 **Chat 标签页**，在任一 Session 中发送一条模糊的消息：

```
User: 继续修
```

4. Agent 回复后，立即切换回 **Debug 标签页**，再次点击 **Refresh**

### 验证点（五大核心能力 #2 + #5）

**Runtime Recall 面板应展示 4 张卡片：**

| 卡片 | 预期内容 |
|------|----------|
| **1. Coarse Reasoning** | `NEEDS RETRIEVAL` 徽章 + 决策原因（如 "query is vague, need to find recent errors"） |
| **2. Retrieval Intent** | `GENERATED` 计数 + 6 个字段：Query / Keywords / Node Types / Statuses / Needs Evidence / Limit |
| **3. ContextPacket Overview** | 三层数据：Tree Memory（召回条目 URI + title）、Evidence Snippets（证据片段预览）、Long-term Knowledge（跨树知识） |
| **4. Rendered Context** | 实际注入 Agent 的完整上下文文本（含 `## Runtime Recall` 标记） |

### 关键验证

- "继续修" 这样模糊的原始 query，在 Coarse Reasoning 中应被判断为 `needs_retrieval: true`
- RetrievalIntent 应自动生成更具体的关键词（如 "fix", "error", "continue" 等）
- ContextPacket 应展示各层实际召回的条目数
- Rendered Context 应展示完整的数据流：Active Path → Tree Memory → Evidence → Long-term → 限制在 max_chars 内

---

## 前端可视化差距总览（2026-06-05 审计更新）

### 已实现 ✅

| 组件 | 位置 | 状态 |
|------|------|------|
| Session Tree 树形画布（节点+边缘+平移缩放） | app.js, Tree 标签页 | ✅ |
| Active Path 高亮（`.path` + `.active` CSS） | app.js + styles.css | ✅ |
| SessionNode 操作（+新建/R重命名/X删除） | app.js | ✅ |
| Chat 消息流（SSE 流式 + ToolChip） | Chat 标签页 | ✅ |
| Memory 标签页 2×2 ContextCard 网格 | Memory 标签页 | ✅ |
| **Tree Memory 搜索框** + 检索 API 调用 | Memory 标签页 `memory-toolbar` | ✅ |
| **Fold 按钮** ("Fold Recent") | Memory 标签页顶部 | ✅ |
| **Promote 按钮** | Memory item 展开详情内 | ✅ |
| **Rollback 按钮** | failure/partial 条目展开详情内 | ✅ |
| **Rollback Plan Modal** | risk / related_files / evidence_refs / suggested_steps | ✅ |
| **Memory item 展开详情** | ID / Type / Status / Confidence / Reuse / Evidence links | ✅ |
| **Evidence 列表** | Evidence 标签页 | ✅ |
| **Evidence 内容查看 Modal** | 点击 Evidence → 弹出完整内容 | ✅ |
| **TraceEvent 时间线** | Trace 标签页，可展开查看 Evidence | ✅ |
| **Context Debug 面板** | Debug 标签页，展示 Active Path / Included / Excluded / Compaction / Promotion Log | ✅ |
| **Knowledge Graph 力导向图** | Graph 标签页，SVG 渲染 nodes + edges | ✅ |
| **Long-term Knowledge 可点击追溯** | sourceTreeId 可点击跳转 | ✅ |
| **Tree Memory 类型颜色区分** | 10 种 type 各有独立 CSS 颜色 | ✅ |
| **reuse_count 热度指示** | 🔥 icon + 动态 opacity | ✅ |
| **status 徽章** | active/archived/promoted/discarded/failed/partial 各有 CSS | ✅ |
| Working Context 统计面板 | Memory 标签页 | ✅ |
| CLI 命令提示（/memory /tree） | Chat 输入框 | ✅ |

### 本次新增 🆕

| 组件 | 位置 | 说明 |
|------|------|------|
| **Runtime Recall 调试面板** | Debug 标签页顶部 | 展示四大卡片：Coarse Reasoning → RetrievalIntent → ContextPacket → Rendered Context |
| **`/api/context/runtime-recall` 端点** | server.py | 暴露 TgmRuntimeRecallBuilder.last_packet 完整数据 |

### 仍缺失（低优先级）

| 优先级 | 组件 | 说明 |
|--------|------|------|
| P2 | Evidence → FoldedNode 反向关联 | 从 Evidence 查看哪些 FoldedNode 引用了它 |
| P3 | Runtime Recall 检索链路流程图 | 可视化 SVG 展示 Active Path → Intent → Tree Memory → Evidence → Long-term → ContextPacket 的完整数据流 |
| P2 | TraceEvent 类型过滤器 | 在 Trace 时间线上按事件类型过滤 |

---

## 五大核心能力 × 前端验证映射

| # | 核心能力 | 验证标签页 | 关键 UI 组件 |
|---|----------|------------|-------------|
| 1 | 当前优先上下文路由 | Debug | DebugSummaryCard（Active Leaf / Estimated Tokens / Compaction） |
| 2 | 检索意图生成 | **Debug → Runtime Recall 面板** | RecallCoarseCard + RecallIntentCard |
| 3 | 动态执行记忆树 | Tree + Memory + Trace | SessionNode 树 / FoldedNode 列表 / TraceEvent 时间线 |
| 4 | FoldedNode + Evidence 分离 | Memory + Evidence | MemoryItemCard（展开 Evidence links）/ EvidenceViewModal |
| 5 | Context Debug 可见 | **Debug 标签页（全量）** | Runtime Recall 面板 + Included/Excluded 条目 + 排除原因 |

---

## 测试执行顺序（更新）

```
Round 1: 创建项目 + 首次对话        ── 验证能力1（当前优先上下文路由）
                                        Chat + Tree 基础渲染
Round 2: 创建分支 + Active Path     ── 验证能力3（执行记忆树分支）
                                        Tree 可视化 + 兄弟分支隔离
Round 3: Tree Memory 写入 + 召回    ── 验证能力2（检索意图生成）+ 能力4（Fold+Evidence）
                                        Memory 标签页 + Debug Runtime Recall 面板
Round 4: Evidence + Fold + Rollback ── 验证能力3（Fold 折叠）+ 能力4（Evidence 保留）
                                        Evidence / Trace / Memory 标签页
Round 5: Promote 晋升               ── 验证能力4（Long-term Knowledge 晋升）
                                        Memory Promote 按钮 + Graph 标签页
Round 6: 跨树召回                   ── 验证能力2（跨树检索意图）
                                        Memory Long-term Recall 卡片
Round 7: Runtime Recall 全链路可视化 ── 验证能力2+5（Coarse Reasoning → Intent → ContextPacket）
                                        **Debug Runtime Recall 面板（本次新增）**
```

---

## 执行方式

1. 先启动后端: `python -m prismx.server` (确认在 8000 端口)
2. 用 chrome-devtools MCP 打开前端页面
3. 逐轮执行上述对话，每轮截图 + 检查前后端状态
4. 记录每轮的通过/失败/前端缺失项
