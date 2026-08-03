# API Workspace

Python 后端工作区，FastAPI 应用入口。完整代码结构、启动命令与 `.env` 配置见 [`../README.md`](../README.md) §一（后端）与 [`../../README.md`](../../README.md)。

## 内部布局

- `app/` — 应用入口与分层：`api/v1`（路由+schema）、`agents`（Harness 核心）、`services`、`domain`、`repositories`、`integrations`、`core`、`static`
- `tests/` — pytest 测试套件（Harness/契约/E2E 回归）
- `data/` — 评估数据与 fixtures
- `outputs/` — 运行产物
- `pyproject.toml` / `uv.lock` — 依赖（uv 管理，Python ≥3.11）

## 两种 Harness 体系（关键边界）

| 体系 | 入口 | 版本（默认加粗） | 写 StageResult |
|---|---|---|---|
| **阶段任务 Harness** | `skill_service.invoke_skill` → `get_harness_provider(version).run()` | **`langgraph-v1`**、`honeycomb-v1`、`deepagents-v1` | ✅ 综合后写 |
| **对话 Harness** | `conversation_harness_service` → `get_conversation_harness_provider(version).run()` | **`conversation-deepagents-v1`**、`simple-v1`、`openharness-v1`(skeleton) | ❌ 仅 `propose_create_run` 待确认 |

`deepagents-v1` / `conversation-deepagents-v1` 真实调用官方 `deepagents.create_deep_agent`，隐藏内置文件/Shell 工具只暴露受限上下文。详见 `DOCS/项目统一口径.md` §3 与 `DOCS/ARCHITECTURE.md` §5。

## 关键约定

- **Python ≥3.11**（官方 `deepagents==0.6.12` 强制）；统一用 `src/apps/api/.venv/bin/python`，启动脚本拒绝回退 shell 默认 `python`。
- **默认端口 8899**；前端经 `http://127.0.0.1:8899/api/v1` 调用，可用 `NEXT_PUBLIC_API_BASE_URL` 覆盖。
- **配置**：`app/core/config.py` 调 `load_dotenv(src/apps/api/.env, override=False)`（shell env 优先、.env 兜底）；变量清单与加载优先级见 [`../README.md`](../README.md) 的配置表。
- **Agent LLM** 缺失时走规则 fallback 并在 response / `run.harness_fallback` / `StageResult.harness.llm_status` 显式告警；`AGENT_LLM_REQUIRED=true` 时缺失返回受控 409，不静默 fallback。
