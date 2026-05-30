# PrismaX 接口文档

> 面向前后端对接的完整 API 参考文档
> 版本: feat/context-memory-tree-fusion · 更新: 2026-05-24

---

## 1. 系统概述

PrismaX 是一个本地 Python Agent 框架。核心差异化能力在上下文 (Context) 和记忆 (Memory) 系统。

### 1.1 模块架构

```
CLI / Web UI
    ↓
AgentApp (应用编排)
    ├── AgentRunner (模型+工具循环)
    ├── TreeSessionManager (树形会话)
    ├── SessionMemoryCommitter (记忆提交)
    ├── RuntimeContextBuilder (运行时上下文)
    ├── MemoryStore / Memory OS (记忆门面)
    │   ├── ContextFS (上下文文件系统)
    │   └── MemoryGraph (记忆图谱)
    └── ToolRegistry (工具注册中心)
```

### 1.2 数据流

```
用户消息 → TreeSession (sessions/{id}.jsonl)
    → /compact → CompactionEntry
    → SessionMemoryCommitter → ContextFS + MemoryGraph
    → RuntimeContextBuilder → 下一轮 system prompt
```

### 1.3 目录结构

```
{root}/
├── sessions/           # 会话树 JSONL (原始事实源)
├── memory/
│   ├── context/
│   │   ├── index.jsonl    # ContextObject 索引
│   │   ├── links.jsonl    # MemoryGraph 链接
│   │   ├── diffs.jsonl    # 变更审计日志
│   │   └── mem/           # L2 正文文件
│   ├── MEMORY.md          # 旧版兼容文件
│   ├── history.jsonl      # 旧版历史
│   └── tokens.jsonl       # Token 用量记录
├── templates/
│   └── system.md          # System prompt 模板
└── skills/                # Agent 技能
```

---

## 2. 数据模型

### 2.1 ContextObject（上下文对象）

ContextFS 中的基本存储单元，对应一条持久化记忆或会话归档。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `uri` | string | 是 | 唯一标识，格式见 §3 URI 规范 |
| `context_type` | string | 是 | 类型：`session` / `memory` / `resource` / `skill` |
| `title` | string | 是 | 标题 |
| `abstract` | string | 是 | L0 — 一句话摘要 (≤200 字符) |
| `overview` | string | 是 | L1 — 可注入上下文的概述 (2-4 句) |
| `content_path` | string | 是 | L2 正文文件相对路径（相对于 `memory/context/`） |
| `source` | string | 是 | 来源：`manual`(手动remember) / `compaction`(压缩提取) / `test` |
| `trust_score` | float | 是 | 信任度 0.0-1.0，越高越可信 |
| `sensitivity` | string | 是 | 敏感度：`public` / `internal` / `sensitive` |
| `status` | string | 是 | 状态：`active` / `quarantine` / `archived` |
| `tags` | string[] | 否 | 分类标签 |
| `metadata` | object | 否 | 扩展元数据，键值自由 |
| `digest` | string | 否 | L2 正文 SHA256 前 16 位 hex |
| `created_at` | string | 否 | 创建时间 ISO8601 (UTC) |
| `updated_at` | string | 否 | 更新时间 ISO8601 (UTC) |
| `ttl` | string? | 否 | 过期时间 ISO8601，null 表示永不过期 |

### 2.2 MemoryOperation（记忆操作）

压缩后 LLM 提取出的结构化记忆变更。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `action` | string | 是 | 操作：`upsert` / `append` / `quarantine` |
| `category` | string | 是 | 分类，见 §3 URI 规范中的类别 |
| `key` | string | 是 | 稳定去重标识（英文 slug） |
| `title` | string | 是 | 中文标题 |
| `abstract` | string | 是 | L0 一句话摘要 |
| `overview` | string | 是 | L1 可注入概述 |
| `content` | string | 是 | L2 完整正文 |
| `reason` | string | 是 | 为什么值得长期保留 |
| `trust_score` | float | 否 | 信任度 (default: 0.6) |
| `tags` | string[] | 否 | 标签列表 |
| `links` | MemoryLink[] | 否 | 关联记忆链接 |

### 2.3 MemoryLink（记忆链接）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `target_uri` | string | 是 | 目标 URI |
| `relation` | string | 是 | 关系类型，见下 |
| `confidence` | float | 是 | 置信度 0.0-1.0 |
| `reason` | string | 是 | 关联原因说明 |

**关系类型 (relation):**

| 值 | 方向 | 语义 |
|----|------|------|
| `supports` | A→B | A 支持/佐证 B |
| `contradicts` | A→B | A 与 B 矛盾 |
| `updates` | A→B | A 是 B 的更新版本 |
| `related` | A→B | 一般相关 |
| `derived_from` | A→B | A 派生自 B |
| `uses_tool` | A→B | A 使用了工具 B |

### 2.4 SessionEntry（会话条目）

TreeSession JSONL 中每一行的基类型。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type` | string | 是 | 条目类型，见子类型表 |
| `id` | string | 是 | 唯一 ID (UUID hex) |
| `sessionId` | string | 是 | 所属 session ID |
| `parentId` | string? | 是 | 父条目 ID（树形结构） |
| `timestamp` | string | 是 | ISO8601 时间戳 |
| `metadata` | object | 否 | 扩展元数据 |

**子类型:**

| type 值 | 类 | 额外字段 |
|---------|-----|----------|
| `session_info` | SessionInfoEntry | `version:int`, `rootId:str?`, `activeLeafId:str?`, `title:str?`, `createdAt`, `updatedAt` |
| `session_state` | SessionStateEntry | `activeLeafId:str?`, `reason:jump\|append\|resume\|fork\|clone` |
| `message` | MessageEntry | `message:{"role":"user"\|"assistant","content":str}` |
| `tool_call` | ToolCallEntry | `toolCall:{"id":str,"name":str,"input":object}` |
| `tool_result` | ToolResultEntry | `toolResult:{"id":str,"name":str,"content":str}` |
| `compaction` | CompactionEntry | `summary:str`, `compactedEntryIds:str[]`, `firstKeptEntryId:str`, `tokenEstimateBefore:int`, `tokenEstimateAfter:int` |
| `label` | LabelEntry | `targetId:str`, `label:str?` |
| `branch_summary` | BranchSummaryEntry | `fromLeafId:str`, `targetEntryId:str`, `summary:str` |
| `context_layer` | ContextLayerEntry | `targetId:str`, `layer:int(L1\|L2\|L3)` |

### 2.5 运行时上下文结果

`RuntimeContextBuilder.build()` 返回的 Markdown 格式每条记录的结构：

```
- URI: {uri}
  Trust: {trust_score}
  Updated: {updated_at}
  Matched: {title}
  Summary: {abstract 或 overview}
  Links: {target_uri} ({relation}), ...
```

### 2.6 diff 审计条目

`diffs.jsonl` 中每条记录：

| 字段 | 类型 | 说明 |
|------|------|------|
| `ts` | string | ISO8601 时间戳 |
| `action` | string | remember / upsert / quarantine |
| `uri` | string | 关联 URI |
| `category` | string | 分类（仅 operation diff） |
| `reason` | string | 变更原因 |
| `session_uri` | string | 来源 session（仅 compaction diff） |

---

## 3. URI 规范

### 3.1 格式

```
{scheme}://{path}
```

- `mem://` — 记忆对象
- `ctx://` — 上下文对象（会话归档、资源）

### 3.2 记忆 URI 模板

| 类别 | URI 模式 | 存储路径 |
|------|----------|----------|
| `profile` | `mem://user/profile` | `mem/user/profile.md` |
| `preferences` | `mem://user/preferences/{slug}` | `mem/user/preferences/{slug}.md` |
| `entities` | `mem://user/entities/{slug}` | `mem/user/entities/{slug}.md` |
| `events` | `mem://user/events/{yyyy}/{mm}/{dd}/{slug}` | `mem/user/events/{yyyy}/{mm}/{dd}/{slug}.md` |
| `decisions` | `mem://project/decisions/{slug}` | `mem/project/decisions/{slug}.md` |
| `constraints` | `mem://project/constraints/{slug}` | `mem/project/constraints/{slug}.md` |
| `open_tasks` | `mem://project/open_tasks/{slug}` | `mem/project/open_tasks/{slug}.md` |
| `cases` | `mem://agent/cases/{slug}` | `mem/agent/cases/{slug}.md` |
| `patterns` | `mem://agent/patterns/{slug}` | `mem/agent/patterns/{slug}.md` |
| `tools` | `mem://agent/tools/{slug}` | `mem/agent/tools/{slug}.md` |
| `skills` | `mem://agent/skills/{slug}` | `mem/agent/skills/{slug}.md` |
| `quarantine` | `mem://quarantine/{slug}` | `mem/quarantine/{slug}.md` |

### 3.3 会话归档 URI

```
ctx://sessions/archives/{yyyy}/{mm}/{dd}/{session_id}-{compaction_id}
```

示例: `ctx://sessions/archives/2026/05/24/default-a1b2c3d4`

### 3.4 slug 生成规则

```
1. 取 title 小写
2. 剔除所有非 [\w一-鿿\s-] 字符（保留 ASCII 字母数字、CJK 汉字、空格、连字符）
3. 空格替换为 -
4. 截断至 80 字符
```

---

## 4. API 参考

### 4.1 MemoryStore / Memory OS

#### `search_memory(query, limit=6) → list[dict]`
搜索所有活跃记忆。query 经过 CJK bigram 分词。排除 `sensitivity=sensitive`、`status=quarantine`、过期 TTL。返回 ContextObject 字典列表，按相关度+信任度排序。

#### `read_context(uri, layer="auto") → str`
读取上下文对象。layer: `"auto"` → L1 overview, `"full"` → L2 正文。URI 不存在返回错误字符串。

#### `list_context(prefix="mem://", limit=50) → list[dict]`
按 URI 前缀列出 ContextObject。

#### `graph_neighbors(uri, limit=5) → list[dict]`
查询 URI 的出向 MemoryGraph 链接，按 confidence 降序。

#### `remember_note(note, category="events", title=None) → str`
写入结构化记忆。返回生成的 URI。同 category + 同 title 自动覆盖旧记忆。同时写入旧版 MEMORY.md 做兼容。

#### `commit_session_archive(session_uri, summary, operations, metadata) → str`
提交会话归档。写入 archive ContextObject + 处理 operations（校验 category、写入记忆、添加 derived_from 链接、auto_link）。非法 operation 进 quarantine。

#### `render_memory() → str`
返回 Markdown 格式的 Memory OS 全景视图，按 11 个类别分组显示。

**类别列表:** profile, preferences, entities, events, decisions, constraints, open_tasks, cases, patterns, tools, skills

### 4.2 ContextFS

#### `write_object(obj: ContextObject, content: str) → str`
写入对象（upsert）。更新内存缓存 + 覆写 index.jsonl。

#### `read_object(uri, layer="auto") → dict`
读对象。返回 `{"uri":..., "content":..., **index_fields}`。

#### `list_objects(prefix="", limit=50) → list[dict]`
按前缀列出。

#### `search_objects(query, limit=5, *, include_sensitive=False) → list[dict]`
关键词搜索。评分规则：
- title 命中: +5
- tags 命中: +4
- abstract 命中: +3
- overview 命中: +2
- URI 命中: +1
- L2 全文命中: +1

#### `append_diff(entry: dict) → None`
追加审计日志到 diffs.jsonl。

### 4.3 MemoryGraph

#### `add_link(source, target, relation, confidence, reason) → None`
添加链接。同 source+target+relation 去重，保留高 confidence。

#### `neighbors(uri, limit=5) → list[dict]`
查询出向链接，按 confidence 降序。

#### `expand(uris, fanout=3) → list[dict]`
批量扩展多个 URI 的出向链接，去重。

#### `auto_link(uri, contextfs, client=None, model="", fanout=5, min_confidence=0.3) → list[dict]`
自动链接新记忆到已有记忆。有 LLM client 则调 LLM 判断关系；否则降级为 keyword bigram 匹配。

### 4.4 SessionMemoryCommitter

#### `commit_compaction(session_id, compaction_id) → str`
读取 CompactionEntry → 调用 LlmMemoryExtractor 提取 operations → 写 session archive + 应用 operations。返回 archive URI。提取失败仍写 archive（operations 为空）。

### 4.5 RuntimeContextBuilder

#### `build(query) → str`
搜索 ContextBackend → 过滤 archived/internal → 扩展 MemoryGraph links(最多 2 条) → 按字符预算裁剪 → 返回 `## Runtime Context` Markdown。

### 4.6 ContextBackend (协议)

| 方法 | 签名 | 说明 |
|------|------|------|
| `search` | `(query, limit=6) → list[dict]` | 搜索记忆 |
| `read` | `(uri, layer="auto") → str` | 读取对象 |
| `list` | `(prefix="mem://", limit=50) → list[dict]` | 列出对象 |
| `remember` | `(note, category="events", title=None) → str` | 写入记忆 |
| `neighbors` | `(uri, limit=5) → list[dict]` | 查询链接 |

MVP 实现: `LocalContextBackend`，委托给 MemoryStore。

### 4.7 TreeSessionManager

#### `createSession(session_id, *, cwd="", title=None) → str`
创建新 session JSONL 文件，写入 session_info 首行。

#### `resumeSession(session_id) → TreeSession`
加载已有 session。

#### `append_message(session_id, message: dict) → None`
追加 user/assistant 消息到 active branch。

#### `append_tool_call(session_id, tool_call: dict) → None`
追加工具调用条目。

#### `append_tool_result(session_id, result: dict) → None`
追加工具结果条目，向上查找匹配的 tool_call。

#### `buildModelContext(session_id) → list[SessionEntry]`
从 active leaf 向上遍历构建模型上下文。

#### `compactActiveBranch(session_id, maxContextTokens, keepRecentTokens, summarizer) → str | None`
压缩活跃分支。返回 compaction_id，未触发返回 None。

#### `jumpToEntry(session_id, entry_id) → None`
跳转到历史节点（创建兄弟分支）。

#### `forkFromEntry(session_id, entry_id) → None`
选择分叉点，下一条输入创建新分支。

#### `cloneActiveBranch(session_id) → str`
克隆当前活跃分支到新 session，返回新 session_id。

---

## 5. 工具定义

### 5.1 上下文工具

#### search_context
```
参数:
  query: string (必填, minLength=1) — 搜索关键词
  limit: integer (可选) — 返回条数上限 (default: 5)

返回: 匹配的 ContextObject 列表，每项含 URI、Title、Trust、Type、Overview
```

#### read_context
```
参数:
  uri: string (必填, minLength=1) — 对象 URI
  layer: string (可选, enum=["auto","full"]) — 读取层级 (default: auto)

返回: L1 overview 或 L2 完整正文
```

#### list_context
```
参数:
  prefix: string (可选) — URI 前缀 (default: "mem://")
  limit: integer (可选) — 返回条数上限 (default: 50)

返回: 指定前缀下的 ContextObject URI 列表
```

#### show_context_links
```
参数:
  uri: string (必填, minLength=1) — 对象 URI
  limit: integer (可选) — 返回条数上限 (default: 5)

返回: 指向该 URI 的 MemoryGraph 链接列表 (relation, target_uri, confidence)
```

### 5.2 升级后的 remember

```
参数:
  note: string (必填, minLength=1) — 记忆内容
  category: string (可选) — 分类: preferences|events|decisions|constraints|cases|patterns|tools|skills|entities|open_tasks|profile (default: events)
  title: string (可选) — 标题 (default: note 前 60 字符)

返回: "Remembered: {uri}" 或 "Error: invalid category '{cat}'. Valid: ..."
```

### 5.3 现有内置工具

| 工具 | 类别 | 说明 |
|------|------|------|
| `read_file` | 文件 | 读取文件内容 |
| `write_file` | 文件 | 写入/覆写文件 |
| `edit_file` | 文件 | 精确字符串替换编辑 |
| `glob` | 文件 | 文件名模式匹配 |
| `grep` | 文件 | 文件内容搜索 |
| `run_command` | Shell | 执行终端命令 |
| `web_fetch` | Web | 抓取网页内容 |
| `update_todos` | 任务 | 管理任务列表 |
| `load_skill` | 技能 | 加载 Agent 技能 |
| `dispatch_subagent` | 子代理 | 派发一次性子代理 |
| `spawn_teammate` | 团队 | 创建持久队友 |
| `send_message` | 团队 | 发送队友消息 |
| `read_inbox` | 团队 | 读取收件箱 |
| `broadcast` | 团队 | 广播消息给所有队友 |

---

## 6. 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MY_AGENT_PROVIDER` | `deepseek` | 模型提供商: deepseek / anthropic |
| `MY_AGENT_MODEL` | `deepseek-chat` | 模型名称 |
| `MY_AGENT_MAX_TOKENS` | `4096` | 单次回复最大 token |
| `MY_AGENT_MAX_CONTEXT_TOKENS` | `64000` | 上下文窗口大小 |
| `MY_AGENT_COMPACT_THRESHOLD` | `0.7` | 自动压缩触发阈值（input_tokens / max_context_tokens ≥ 此值时触发） |
| `MY_AGENT_COMPACT_KEEP_MESSAGES` | `8` | 压缩时最少保留消息数 |
| `MY_AGENT_STARTUP_COMPACTION` | `0` | 启动时是否压缩旧历史 (0/1) |
| `MY_AGENT_WORKSPACE` | 当前目录 | 工作区根目录 |
| `MY_AGENT_SESSION_ID` | `default` | 会话 ID（不存在则自动创建） |
| `MY_AGENT_RUNTIME_CONTEXT_LIMIT` | `6` | RuntimeContext 搜索返回条数 |
| `MY_AGENT_RUNTIME_CONTEXT_MAX_CHARS` | `12000` | RuntimeContext 输出字符预算 |
| `MY_AGENT_CONTEXT_BACKEND` | `local` | 上下文后端（MVP 仅 `local`） |
| `MY_AGENT_AUTO_LINK_FANOUT` | `5` | auto_link 候选记忆数 |
| `MY_AGENT_AUTO_LINK_MIN_CONFIDENCE` | `0.3` | auto_link 最低置信度 |

---

## 7. CLI 命令

| 命令 | 说明 |
|------|------|
| `/help` | 查看帮助 |
| `/tools` | 列出已注册工具（含 search_context 等） |
| `/todos` | 查看任务列表 |
| `/memory` | 查看 Memory OS（11 类结构化记忆） |
| `/context` | 列出最近 ContextObject（URI + 类型 + 标题 + trust） |
| `/mcp` | MCP server 状态 |
| `/compact` | 手动触发上下文压缩 + 记忆提取 |
| `/team` | 持久队友状态 |
| `/tree [--filter MODE]` | 查看会话树 |
| `/jump ID` | 跳转到历史节点 |
| `/fork ID` | 从历史节点分叉 |
| `/clone` | 克隆 active branch 到新 session |
| `/label ID LABEL` | 给节点打标签 |
| `/exit` | 退出 |

---

## 8. 文件格式

### 8.1 index.jsonl

每行一个 ContextObject 的 JSON 序列化:

```jsonl
{"uri": "mem://user/preferences/theme", "context_type": "memory", "title": "主题偏好", "abstract": "...", "overview": "...", "content_path": "mem/user/preferences/theme.md", "source": "manual", "trust_score": 0.8, "sensitivity": "public", "status": "active", "tags": ["preference"], "metadata": {}, "digest": "a1b2c3d4e5f6", "created_at": "2026-05-24T10:00:00+00:00", "updated_at": "2026-05-24T10:00:00+00:00", "ttl": null}
```

### 8.2 links.jsonl

每行一条 MemoryGraph 链接:

```jsonl
{"source_uri": "mem://user/preferences/theme", "target_uri": "ctx://sessions/archives/2026/05/24/default-c1", "relation": "derived_from", "confidence": 0.95, "reason": "extracted from compaction"}
```

### 8.3 diffs.jsonl

每行一条审计记录:

```jsonl
{"action": "remember", "uri": "mem://user/preferences/theme", "reason": "manual remember", "ts": "2026-05-24T10:00:00+00:00"}
```

### 8.4 sessions/{session_id}.jsonl

每行一个 SessionEntry 的 JSON 序列化:

```jsonl
{"type": "session_info", "id": "...", "sessionId": "default", "parentId": null, "timestamp": "...", "version": 1, "rootId": "...", "activeLeafId": "...", "title": null, "createdAt": "...", "updatedAt": "..."}
{"type": "session_state", "id": "...", "sessionId": "default", "parentId": null, "timestamp": "...", "activeLeafId": "...", "reason": "resume"}
{"type": "message", "id": "...", "sessionId": "default", "parentId": "...", "timestamp": "...", "message": {"role": "user", "content": "..."}}
{"type": "message", "id": "...", "sessionId": "default", "parentId": "...", "timestamp": "...", "message": {"role": "assistant", "content": "..."}}
{"type": "tool_call", "id": "...", "sessionId": "default", "parentId": "...", "timestamp": "...", "toolCall": {"id": "call_1", "name": "remember", "input": {"note": "...", "category": "preferences", "title": "主题偏好"}}}
{"type": "tool_result", "id": "...", "sessionId": "default", "parentId": "...", "timestamp": "...", "toolResult": {"id": "call_1", "name": "remember", "content": "Remembered: mem://..."}}
{"type": "compaction", "id": "...", "sessionId": "default", "parentId": "...", "timestamp": "...", "summary": "## Goal\n...", "compactedEntryIds": ["e1","e2"], "firstKeptEntryId": "e3", "tokenEstimateBefore": 8000, "tokenEstimateAfter": 1200}
```

### 8.5 L2 正文文件 (.md)

路径: `memory/context/{content_path}`

存储 ContextObject 的完整正文（Markdown 格式）。文件名对应 URI 路径 + `.md` 后缀。

示例 `memory/context/mem/user/preferences/theme.md`:
```
用户偏好使用暗色主题，包括 VS Code 编辑器和终端界面。
```

---

## 9. System Prompt 模板

`templates/system.md` 使用 Jinja2 渲染，可用变量:

| 变量 | 来源 | 说明 |
|------|------|------|
| `{{ workspace }}` | AgentApp.workspace | 工作区绝对路径 |
| `{{ memory }}` | MemoryStore.read_memory() | 旧版 MEMORY.md 内容 |
| `{{ user_profile }}` | MemoryStore.read_user() | 用户画像 (USER.md) |
| `{{ skills_summary }}` | SkillsLoader.summary() | 可用技能摘要 |
| `{{ active_skills }}` | SkillsLoader.active_context() | 始终激活的技能 |
| `{{ runtime_context }}` | RuntimeContextBuilder.build() | 每轮动态记忆召回 |

---

## 10. 搜索行为说明

### 10.1 搜索流程

```
用户输入 "我想换个编辑器配色"
    ↓
_query = "我想换个编辑器配色"
    ↓
tokenize: ["我想换个编辑器配色", "我想", "想换", "换个", "个编", "编辑", "辑器", "器配", "配色"]
    ↓
匹配 index.jsonl 中每条:
  - title 含 "编辑" → +5
  - abstract 含 "编辑器" → +3
  - L2 全文含 "配色" → +1
    ↓
排序: 总分 ↓ → trust_score ↓
    ↓
返回前 N 条
```

### 10.2 过滤规则

搜索自动排除:
- `sensitivity = "sensitive"` 的对象
- `status = "quarantine"` 的对象
- TTL 已过期的对象

RuntimeContextBuilder 额外排除:
- `status = "archived"` 的对象
- `sensitivity = "internal"` 的对象

---

## 11. 关键设计约束

1. **TreeSession 是唯一原始会话事实源** — 不在 ContextFS 中重复存 raw message
2. **禁止** `memory/context/sessions/current/messages.jsonl`
3. **记忆提取只在 compaction 后触发** — 不每次对话都写长期记忆
4. **旧版 MEMORY.md / history.jsonl / compactions.md 保留兼容** — 仅兼容，非核心
5. **MVP 纯本地文件系统** — 不用向量数据库、embedding、外部服务
6. **新增类别需同步 4 处** — `_operation_to_uri`, `_category_prefix`, `valid_categories`, `render_memory.categories`

---

> 文档版本: 1.0 · 生成日期: 2026-05-24
