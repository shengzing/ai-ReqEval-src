# `src/` 源码目录

ai-ReqEval 平台的源码根目录。采用 **monorepo 拆分**布局：后端 API、前端 Web、可复用评估包、契约定义分目录组织，每个一级子目录都有自己的 README 说明。

## 目录结构

```text
src/
├── apps/                      # 可运行应用（部署单元）
│   ├── api/                   # Python FastAPI 后端（评估执行与 Harness 核心）
│   ├── web/                   # Next.js / React 前端
│   └── README.md
├── packages/                  # 可复用 Python 包
│   ├── reqeval/               # 评估、检索、Agent 编排函数库
│   ├── bank_gai_eval_workbench/  # CLI 工作台
│   └── README.md
├── contracts/                 # 跨端契约（OpenAPI / JSON Schema / 事件）
│   ├── openapi.yaml
│   ├── jsonschema/
│   ├── events/
│   ├── acceptance.md
│   ├── frontend-integration.md
│   └── README.md
├── .env                       # 根级共享环境变量（模型/检索密钥）
└── __init__.py                # 使 src 成为可导入包根（src.apps.api...）
```

> 子目录职责细节见各自 README：[`apps/README.md`](apps/README.md)、[`apps/api/README.md`](apps/api/README.md)、[`packages/README.md`](packages/README.md)、[`contracts/README.md`](contracts/README.md)。

---

## 一、`apps/api` —— Python 后端

FastAPI 应用，承载四阶段评估流水线、阶段任务 Harness、对话 Harness、AutoResearch 能力优化与持久化。详细运行说明见 [`apps/api/README.md`](apps/api/README.md)，这里给出结构与启动要点。

### 代码结构

```text
apps/api/
├── app/
│   ├── main.py                # FastAPI 入口（CORS、路由挂载、静态托管、全局异常）
│   ├── api/v1/                # HTTP 层
│   │   ├── router.py          # 聚合所有 v1 路由
│   │   ├── routers/            # projects / runs / skills / settings / autoresearch / health
│   │   └── schemas/           # 请求/响应 Pydantic 模型
│   ├── agents/                # Agent 与 Harness 层（核心）
│   │   ├── harness/            # 阶段任务 Harness
│   │   │   ├── graph.py        # LangGraph DAG（load→plan→execute→synthesize→validate→refine→autoresearch）
│   │   │   ├── runner.py       # run_skill_harness / resume_skill_harness（HITL）
│   │   │   ├── registry.py     # 版本化 Provider 注册表
│   │   │   ├── versions/       # langgraph-v1（默认）/ honeycomb-v1 / deepagents-v1（官方 SDK ReAct）
│   │   │   └── adapters/       # tool / permission / hook / llm 适配器
│   │   ├── conversation_harness/  # 对话 Harness（阶段下问答，不写 StageResult）
│   │   │   ├── registry.py
│   │   │   ├── context_builder.py
│   │   │   └── versions/        # conversation-deepagents-v1（默认）/ simple-v1 / openharness-v1(skeleton)
│   │   ├── tools/registry.py   # 项目工具（document_parse / risk_identify / value_model ...）
│   │   ├── skills/registry.py  # SkillDefinition 配置（5 个 Skill，纯数据 dataclass）
│   │   ├── risk_semantic/      # 语义风险分级 + 证据链校验 + 词汇表
│   │   └── deepagent/          # 自有 subagent 编排（非官方 SDK）
│   ├── services/               # 领域服务
│   │   ├── skill_service.py    # invoke_skill：Harness 入口（含 _build_stage_*_summary 综合）
│   │   ├── settings_service.py # ProjectSettings 快照、Harness 版本解析
│   │   ├── run_service.py / project_service.py / stage_result_service.py
│   │   ├── autoresearch_service.py  # 能力优化旁路：候选/门禁/发布
│   │   ├── alignment_service.py    # 三维对齐（风险/SLA/价值）
│   │   ├── conversation_harness_service.py / conversation_action_service.py
│   │   ├── tool_service.py / vision_service.py / log_service.py
│   │   └── stage1~4_contract.py    # 各阶段契约校验与质量分
│   ├── domain/models.py        # 领域实体（Run / StageResult / AutoResearchCandidate ...）
│   ├── repositories/            # store.py（JSON/JSONL MVP + MongoDB 目标）、mongodb.py
│   ├── integrations/            # file_storage.py、vision_llm.py
│   ├── core/                    # config.py、harness_constants.py（默认 Harness 版本）
│   └── static/                  # 前端构建产物托管
├── tests/                       # pytest 测试套件（含 Harness/契约/E2E 回归）
├── data/                        # 评估数据与 fixtures
├── outputs/                     # 运行产物输出
├── pyproject.toml               # 依赖与项目元数据（uv 管理）
└── uv.lock                      # 锁定依赖
```

### 两种 Harness 体系（关键边界）

| 体系 | 入口 | 版本（默认加粗） | 是否写 StageResult |
|---|---|---|---|
| **阶段任务 Harness** | `skill_service.invoke_skill` → `get_harness_provider(version).run()` | **`langgraph-v1`**、`honeycomb-v1`、`deepagents-v1` | ✅ 综合后写 |
| **对话 Harness** | `conversation_harness_service` → `get_conversation_harness_provider(version).run()` | **`conversation-deepagents-v1`**、`simple-v1`、`openharness-v1`(skeleton) | ❌ 仅 `propose_create_run` 待确认 |

`deepagents-v1` / `conversation-deepagents-v1` 均真实调用官方 `deepagents.create_deep_agent`，隐藏内置文件/Shell 工具只暴露受限上下文。详见 `DOCS/项目统一口径.md` §3 与 `DOCS/ARCHITECTURE.md` §5。

### 启动命令

> **Python 要求 ≥3.11**（官方 `deepagents==0.6.12` 强制）。统一用 `src/apps/api/.venv/bin/python`，禁止回退 shell 默认 `python`。命令均在各自代码目录下执行。

```bash
# 1) 安装/同步锁定依赖（唯一引导命令，在仓库根执行）
uv sync --locked --project src/apps/api --group dev --no-install-project --python 3.11

# 2) 就绪检查（验证 Python 版本 + deepagents/fastapi/langgraph 等导入 + Mongo ping）
cd src/apps/api && .venv/bin/python ../../scripts/check_dev_ready.py

# 3) 启动 API 开发服务器（默认端口 8899，脚本会校验环境，拒绝用错 Python）
cd src/apps/api && ../../scripts/start_api_dev.sh
# 等价于：.venv/bin/
python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8899 --reload

# 4) 跑测试
cd src/apps/api && .venv/bin/python -m pytest tests/ -q
#   单跑 harness 相关：
cd src/apps/api && .venv/bin/python -m pytest tests/test_deepagents_harness_provider.py tests/test_langgraph_harness.py -q
```

**切换 Harness 版本**（环境变量覆盖全局默认，或经 `StageSkillProfile` 按 stage 配置）：

```bash
export AGENT_HARNESS_VERSION=deepagents-v1          # 阶段任务 Harness
export CONVERSATION_HARNESS_VERSION=conversation-deepagents-v1  # 对话 Harness（已是默认）
```

**配置与 `.env`**：API 进程启动时由 `apps/api/app/core/config.py` 调 `load_dotenv(src/apps/api/.env, override=False)`，即 **shell 环境变量优先、`.env` 兜底**。`get_settings()` 用 `@lru_cache` 缓存，测试改 env 后需 `get_settings.cache_clear()`。

| 用途 | 变量（`AGENT_LLM_*` / `VISION_LLM_*` / `MONGODB_*` 等缺失时走代码默认） |
|---|---|
| Agent LLM（Harness 规划/综合/Deep Agents） | `AGENT_LLM_BASE_URL` / `AGENT_LLM_API_KEY` / `AGENT_LLM_MODEL` / `AGENT_LLM_TIMEOUT_SECONDS` / `AGENT_LLM_REQUIRED` |
| Vision LLM（OCR/解析） | `VISION_LLM_BASE_URL` / `VISION_LLM_API_KEY` / `VISION_LLM_MODEL` |
| MongoDB | `MONGODB_URI`（优先）或 `MONGODB_USER`+`MONGODB_PASSWORD`(+`MONGODB_HOST`/`MONGODB_PORT`/`MONGODB_AUTH_SOURCE`/`DATABASE_NAME`) |
| Harness 版本 | `AGENT_HARNESS_VERSION` / `CONVERSATION_HARNESS_VERSION`（或经 `StageSkillProfile` 按 stage 覆盖） |
| 文件根 / CORS | `AI_REQEVAL_DATA_ROOT` / `AI_REQEVAL_OUTPUT_ROOT` / `AI_REQEVAL_STATIC_ROOT` / `CORS_ALLOW_ORIGINS` |
| 检索/嵌入（`packages/reqeval`，独立加载器） | `SILICONFLOW_API_KEY` / `EMBEDDING_*` / `PAGEINDEX_*`（默认读 `packages/reqeval/.env`） |

> Agent/Vision LLM 缺失时走规则 fallback 并显式告警；`AGENT_LLM_REQUIRED=true` 时配置缺失返回受控 409，不静默 fallback。**注意**：根目录的 `src/.env` 不会被 API 进程加载——后端只读 `src/apps/api/.env`，检索包只读 `packages/reqeval/.env`。

---

## 二、`apps/web` —— Next.js 前端

```text
apps/web/
├── app/            # Next.js App Router（layout.tsx / page.tsx / globals.css）
├── components/      # UI 组件（ui/ shadcn、codex/、theme-provider）
├── hooks/           # use-codex-data / use-workspace-selection / use-toast
├── lib/             # api-client / api-types / api-mappers / workspace-state / settings-state
├── package.json / next.config.mjs / tsconfig.json / playwright.config.ts
└── out/             # 构建产物（被 apps/api/app/static 托管，可整体单服务部署）
```

### 启动命令

```bash
cd src/apps/web
npm install
npm run dev          # 开发服务器（默认 :3000），后端默认 http://127.0.0.1:8899
npm run build        # 产出静态站点到 out/，供后端托管
```

或用根级脚本（在 `src/apps/web` 下执行）：

```bash
../../scripts/start_web_dev.sh     # 开发
../../scripts/build_web_static.sh  # 构建静态产物供 API 托管
```

前端通过 `lib/api-client.ts` 调用后端 REST/SSE 接口，默认 `http://127.0.0.1:8899/api/v1`，可用 `NEXT_PUBLIC_API_BASE_URL` 覆盖；契约见 `src/contracts/`。

---

## 三、`packages` —— 可复用 Python 包

```text
packages/
├── reqeval/                    # 评估函数库（被 apps/api 复用）
│   ├── agents/                  # langgraph_orchestrator / deepagent_orchestrator / supervisor / router / state
│   ├── evaluators/              # 六大评估方法论实现：mckinsey / bcg / mit / servicenow / dx / yiou
│   ├── retrieval/               # bm25 + 向量检索 + embedding/pageindex 客户端 + chunking
│   ├── data/                    # document_processor / metrics_loader / database / models
│   └── utils/
└── bank_gai_eval_workbench/     # CLI 工作台（__main__.py / cli.py / collector.py / models.py）
```

`packages/reqeval` 的 Agent 编排（`deepagent_orchestrator` 等）是项目自有小写 `deepagent` 风格，**非官方 `deepagents` SDK**；官方 SDK 接入集中在 `apps/api/app/agents/harness/versions/deepagents_v1` 与 `conversation_harness/versions/deepagents_v1`。

### 使用命令

```bash
# 作为库被 apps/api 导入（已通过 pyproject 配置 src 为包根；在仓库根执行）
src/apps/api/.venv/bin/python -c "from src.packages.reqeval.evaluators import mckinsey; print('ok')"

# CLI 工作台
src/apps/api/.venv/bin/python -m src.packages.bank_gai_eval_workbench --help
```

---

## 四、`contracts` —— 跨端契约

```text
contracts/
├── openapi.yaml             # API OpenAPI 规约（前后端接口契约来源）
├── jsonschema/              # 请求/响应 JSON Schema
├── events/                  # 事件契约（SSE / Run 事件）
├── acceptance.md            # 验收规约
└── frontend-integration.md  # 前端集成约定
```

契约是前后端的唯一真相来源；`apps/web/lib/api-types.ts` 与 `apps/api/app/api/v1/schemas/` 应与 `contracts/` 保持一致。

---

## 常用根级脚本（位于仓库根 `scripts/`，在 `src/apps/api` 下执行）

| 脚本 | 作用 |
|---|---|
| `../../scripts/start_api_dev.sh` | 启动 API 开发服务器（:8899，校验 Python 3.11 环境） |
| `../../scripts/start_web_dev.sh` | 启动 Web 开发服务器（在 `src/apps/web` 下执行，:3000） |
| `../../scripts/build_web_static.sh` | 构建前端静态产物供 API 托管 |
| `../../scripts/check_dev_ready.py` | 就绪检查（依赖导入 + Mongo ping + 端口 8899/3000） |
| `../../scripts/check_api_layering.py` | 校验 API 分层（路由不绕过服务层） |
| `../../scripts/init_demo_storage.py` / `../../scripts/init_mongodb.py` | 初始化演示数据 / Mongo |
| `../../scripts/mock_llm_server.py` | 本地 mock LLM（用于离线测试） |
| `../../scripts/run_harness_*.py` / `../../scripts/run_stage*_*.py` | Harness 跨版本对比与各阶段 AutoResearch 实验 |

---

## 相关文档

- 平台总览与目录分区：`DOCS/README.md`、`DOCS/PROJECT_OVERVIEW.md`
- 运行时与 Harness 边界：`DOCS/ARCHITECTURE.md` §5
- 当前实现 vs 目标架构口径：`DOCS/项目统一口径.md` §3
- 子目录 README：[`apps/`](apps/README.md)、[`apps/api/`](apps/api/README.md)、[`packages/`](packages/README.md)、[`contracts/`](contracts/README.md)
