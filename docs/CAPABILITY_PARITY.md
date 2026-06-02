# PrismaX 能力清单

本文记录 `PrismaX` 当前已经具备的核心能力、主要位置和已知差距，方便后续维护。

| 能力 | 状态 | 主要位置 | 说明 |
|---|---:|---|---|
| CLI 入口 | 已完成 | `src/prismax/cli.py`、`src/prismax/loop.py` | 已通过 `pyproject.toml` 打包为 `uv` 项目。 |
| 模型客户端 | 已完成 | `src/prismax/model_client.py` | 支持 `deepseek`、`anthropic` 和 `openai-compatible`。 |
| 工具调用 runner | 已完成 | `src/prismax/runner.py` | 使用 provider-neutral blocks，并支持安全工具并行调用。 |
| 工具注册与参数校验 | 已完成 | `src/prismax/tools/base.py`、`registry.py` | schema helper 较轻量，校验基础 JSON schema 类型。 |
| shell 工具 | 已完成 | `src/prismax/tools/shell.py` | 限定工作区 cwd，支持超时。 |
| 网页抓取工具 | 已完成 | `src/prismax/tools/web.py` | 支持文本提取和原始 HTML。 |
| 文件读写编辑 | 已完成 | `src/prismax/tools/filesystem.py` | 支持工作区逃逸保护。 |
| 搜索工具 | 已完成 | `src/prismax/tools/filesystem.py` | 支持基础 glob/regex 搜索。 |
| Todo 规划 | 已完成 | `src/prismax/tools/state.py` | 保持完整列表覆盖模型，并限制同时只有一个 `in_progress`。 |
| 技能加载器 | 已完成 | `src/prismax/skills.py`、`tools/state.py` | 支持嵌套 `SKILL.md`、技能摘要、`always: true`，并在依赖未安装时使用 fallback frontmatter 解析。 |
| 内置技能 | 部分完成 | `skills/summarize/SKILL.md` | 当前只内置通用 summarization 技能。 |
| system prompt 构造 | 已完成 | `src/prismax/context.py`、`templates/system.md` | 注入 Runtime Recall、user profile 和 skills。 |
| 长期记忆 | 已完成 | `src/prismax/memory.py`、`contextfs.py`、`memory_graph.py` | ContextFS-backed Memory OS with structured memory objects, URI-addressable with L0/L1/L2 layers, MemoryGraph relationship indexing, session archiving from tree compaction, runtime context injection per model call. Legacy MEMORY.md compatibility removed. |
| 用户画像记忆 | 已完成 | `templates/USER.md`、`MemoryStore.read_user/write_user` | 由 compaction 更新。 |
| Tree Memory | 已完成 | `src/prismax/tree_memory.py` | 当前会话树内短期共享经验，URI 使用 `tree://...`。 |
| SessionTrees 事实源 | 已完成 | `sessiontrees/*.jsonl`、`TreeSessionManager` | 保存 TreeSession append-only JSONL，替代旧线性 history。 |
| 会话树压缩 | 已完成 | `src/prismax/tree_session.py` | `/compact` 会在当前 active branch 追加结构化 compaction entry。 |
| token 日志 | 已完成 | `TokenLog` | 记录 provider-neutral 的 input/output token 字段，时间使用 UTC+8。 |
| token 聚合 | 已完成 | `TokenLog.stats_by_date`、`stats_by_model` | 支持基础聚合。 |
| 一次性子代理 | 已完成 | `src/prismax/subagents`、`tools/dispatch.py` | 通用角色：researcher、analyst、coder、reviewer。 |
| 子代理工具白名单 | 已完成 | `src/prismax/subagents/registry.py` | 安全设置写在代码里，不写在 prompt 模板里。 |
| 并行子代理派遣 | 已完成 | `runner.py`、`DispatchSubagentTool.concurrency_safe` | 独立 dispatch 调用可以并行执行。 |
| 持久 Agent Team | 已完成 | `src/prismax/team.py` | 支持命名队友、持久配置、inbox 和线程。 |
| Team 工具 | 已完成 | `src/prismax/tools/team.py` | 注册给 lead 和 teammate agent。 |
| Team CLI 快捷命令 | 已完成 | `src/prismax/cli.py` | 支持 `/team` 和 `/inbox`。 |
| 运行期目录忽略 | 已完成 | `.gitignore` | 避免提交运行生成状态。 |

## 剩余差距

- 文件搜索和编辑工具已经可用，但功能仍偏轻量；后续可增加分页、过滤和更强的编辑匹配。
- 内置技能保持克制。后续应根据项目方向添加通用技能。
- 当前环境没有跑真实 DeepSeek/Anthropic API 集成测试；已有测试主要使用 fake model。
- 超大单轮对话的 prefix/suffix 拆分压缩还未完整接入主流程。

## 当前验证

- `python3 -m compileall src`
- smoke tests 覆盖：
  - 文件工具和 todo 工具
  - provider-neutral 工具调用转换
  - fake model 下的 TreeSession 压缩
  - TGM 三层召回：Active Path、Tree Memory、Long-term Knowledge
  - always-active skills 和 system prompt 注入
  - message bus 和 team 工具
  - 使用 fake model 启动 teammate 线程

