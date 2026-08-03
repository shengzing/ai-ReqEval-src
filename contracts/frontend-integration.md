# Frontend Integration

本文档定义 `src/apps/web` 当前接入后端 API / SSE 的口径。前端产品代码不读取 `mock-data.ts`，项目、阶段、Run、证据、建议、锁定和报告都来自 REST / SSE。

## 1. 环境变量

- `NEXT_PUBLIC_API_BASE_URL`
  - 默认值：`http://127.0.0.1:8000/api/v1`
  - `src/apps/web/lib/api-client.ts` 的 REST 请求和 SSE 订阅都基于该前缀。
- `WEB_E2E_BASE_URL`
  - 仅用于 `npm run test:e2e`。
  - 未设置时浏览器 smoke test 跳过，避免用 mock 数据伪造通过。

## 2. 前端组件与数据边界

| 区域 | 组件入口 | 数据来源 | 说明 |
|---|---|---|---|
| 工作台外壳 | `components/codex/codex-layout.tsx`、`workspace-shell.tsx`、`workspace-content.tsx` | `use-codex-data.ts`、`use-workspace-selection.ts` | 负责项目/阶段/对话选择、右侧栏开关和动作编排 |
| 左侧导航 | `components/codex/navigation/*` | `GET /workspace/tree` | 展示项目、阶段、对话和待确认数 |
| 首页 | `components/codex/home/*` | 当前项目状态、`default-tasks.ts` | 只作为目标输入和空态引导，不展示未接后端的模型/分支/权限控件 |
| 阶段工作区 | `components/codex/stage-workspace.tsx`、`components/codex/stage/*` | 阶段详情、Run SSE、Skills、autoResearch、lock-check、version logs | 展示阶段目标、结果、执行流、建议卡、锁定门禁和报告门禁 |
| 阶段结果 | `components/codex/stage-results/*` | `GET /stages/{stage_id}/results` | 根据 `result_payload` 和阶段类型展示结构化结果，无结果时展示明确空态 |
| 右侧资料栏 | `components/codex/evidence/*`、`right-sidebar.tsx` | 文件、证据、视觉解析、阶段状态 | 展示上传文件、证据状态、视觉详情和状态清单 |

## 3. 当前主要读取路径

### 3.1 左侧项目树

前端当前使用聚合接口：

1. `GET /workspace/tree`

输出目标：

- 项目树。
- 阶段状态。
- 阶段待确认项数量。
- 阶段对话摘要。

### 3.2 中央阶段工作区

选中阶段后，前端加载：

1. `GET /stages/{stage_id}`
2. `GET /skills?stage_id={stage_id}`
3. `GET /autoresearch?stage_id={stage_id}`
4. `GET /stages/{stage_id}/lock-check`
5. `GET /stages/{stage_id}/results`
6. `GET /version-logs?project_id={project_id}`
7. `GET /evidence?project_id={project_id}`
8. `GET /files?project_id={project_id}`
9. `GET /vision-results?project_id={project_id}`

输出目标：

- 当前阶段信息。
- 最新阶段结果 `result_payload`。
- 可用 Skill。
- 待确认建议卡。
- 锁定前检查项。
- 锁定版本、锁定时间和差异摘要。
- 当前项目资料与证据。

### 3.3 右侧资料 / 证据栏

右侧栏复用阶段上下文中的资料加载结果：

1. `GET /files?project_id={project_id}`
2. `GET /evidence?project_id={project_id}`
3. `GET /vision-results?project_id={project_id}`

输出目标：

- 原始文件列表。
- 证据状态。
- 视觉解析摘要、待确认字段和不确定项。

### 3.4 报告预览

前端当前读取：

1. `GET /reports/{report_id}/content`

输出目标：

- 报告标题。
- 报告状态。
- 报告正文预览。

说明：报告元数据来自 `POST /reports/generate` 的返回值；如需要刷新历史报告详情，可使用 `GET /reports/{report_id}`。

## 4. 当前写操作

- `POST /projects`
- `POST /stages/{stage_id}/conversations`
- `POST /files/upload`
- `POST /files/{file_id}/parse`
- `POST /files/{file_id}/vision-parse`
- `POST /runs`
- `POST /autoresearch/run`
- `POST /autoresearch/manual`
- `POST /autoresearch/{record_id}/confirm`
- `POST /stages/{stage_id}/lock`
- `POST /reports/generate`

说明：前端当前不直接调用 `POST /skills/{skill_id}/invoke`；Skill 执行由 Run/后端编排触发。

## 5. SSE 订阅

事件流入口：

- `GET /runs/{run_id}/events`

前端当前消费事件：

- 工具流：`run.tool_started`、`run.tool_completed`
- 建议卡：`run.suggestion`
- 对话摘要：`run.step`、`run.suggestion`、`run.waiting_user`、`run.completed`
- 运行状态：`run.running`、`run.waiting_user`、`run.completed`、`run.failed`
- 终止重连：`run.completed`、`run.failed`、`run.cancelled`

详细事件契约见：

- [events/README.md](./events/README.md)

## 6. 状态映射

### 6.1 阶段状态

后端 -> 前端

- `locked` -> `locked`
- `completed` -> `completed`
- `waiting_user` -> `waiting_user`
- `failed` -> `failed`
- `needs_review` -> `needs_review`
- `running` / `in_progress` -> `in_progress`
- 其他 -> `not_started`

### 6.2 Run 状态

后端 -> 前端

- `queued` -> `queued`
- `running` -> `running`
- `waiting_user` -> `waiting_user`
- `completed` -> `completed`
- `failed` -> `failed`
- `cancelled` -> `cancelled`
- 其他 -> `created`

### 6.3 前端覆盖状态

`workspace-state.ts` 会根据实时 Run 和待确认建议覆盖当前阶段展示状态：

- Run `running` 时阶段展示为 `in_progress`。
- Run `waiting_user` 时阶段展示为 `waiting_user`。
- Run `completed` 且仍有建议卡时阶段展示为 `waiting_user`。

## 7. 错误处理约定

1. REST 错误统一抛出 `ApiError`，保留 `status`、`detail` 和 `path`。
2. `404` 表示资源不存在，不做静默回退。
3. `409` 表示资源状态不允许当前操作，前端必须把后端原因展示给用户。
4. `422` 表示请求参数校验失败。

当前前端明确展示的 `409` 场景：

- 阶段锁定失败：阶段结果不存在、阶段已锁定、仍有待处理 autoResearch。
- 报告生成失败：四阶段结果未齐备、四阶段未全部锁定、仍有待处理 autoResearch。

## 8. 当前前端依赖的关键字段

### Stage

- `id`
- `project_id`
- `name`
- `status`
- `objective`

### StageResult

- `id`
- `version_id`
- `base_version_id`
- `status`
- `evidence_item_ids`
- `confirmation_ids`
- `result_payload`
- `locked_at`

### StageLockCheck

- `stage_id`
- `ready`
- `checks[].key`
- `checks[].label`
- `checks[].passed`

### VersionLog

- `resource_id`
- `change_type`
- `created_at`
- `details.stage_id`
- `details.version_id`
- `details.diff_summary.field_changes`

### AutoResearchRecord

- `id`
- `stage_id`
- `title`
- `source`
- `impact`
- `risk`
- `description`
- `action`
- `context.source_file`
- `context.source_line`
- `context.source_type`
- `status`
- `edited_description`

### Report

- `id`
- `title`
- `status`
- `approval_check_passed`
- `export_path`
- `decision_card_path`
- `evidence_directory_path`
- `bundle_export_path`
- `stage_result_ids`
- `evidence_item_ids`

### ReportContent

- `id`
- `title`
- `status`
- `content`

## 9. 测试入口

- 单元测试：`cd src/apps/web && npm test`
- 类型检查：`cd src/apps/web && npx tsc --noEmit`
- 真实后端 smoke：`cd src/apps/web && WEB_E2E_BASE_URL=<真实前端地址> npm run test:e2e`

## 10. 设置页（Settings workspace）

设置页是项目级配置入口，**不保存任何 API Key / 密钥 / 真实凭据**。所有密钥仍由后端 `.env` 加载（参见 `src/apps/api/.env` 与 `src/apps/api/app/core/config.py`）。

### 10.1 入口

- 左侧底部 `设置` 按钮（`components/codex/left-sidebar.tsx`）会切换到 `components/codex/settings-workspace.tsx`。
- 没有选中项目时显示空态，不会请求设置接口。

### 10.2 主要读取路径

1. `GET /api/v1/projects/{project_id}/settings` — 返回 `{ published, draft, has_draft }`。
   - `published` 始终存在（系统默认或在创建项目时初始化）。
   - `draft` 仅在用户显式保存草稿后存在；新项目默认 `draft = null`、`has_draft = false`。
2. `GET /api/v1/projects/{project_id}/settings/versions` — 返回按时间排序的版本列表。
3. `GET /api/v1/projects/{project_id}/settings/impact` — 返回未发布草稿的影响范围摘要。
4. `GET /api/v1/model-options` — 返回后端允许的模型供应商、模型名和能力标签。

### 10.3 主要写入路径

| 动作 | 接口 | 副作用 |
|---|---|---|
| 保存草稿 | `POST /api/v1/projects/{project_id}/settings/draft` | 写入 `execution_logs`；不创建新版本号；`has_draft = true` |
| 恢复默认 | `POST /api/v1/projects/{project_id}/settings/reset` | 生成新 draft，内容等于系统默认 |
| 发布配置 | `POST /api/v1/projects/{project_id}/settings/publish` | 校验 `change_reason`；写入 `version_logs`（`resource_type=project_settings`、`change_type=published`）；新 Run 引用 `version_id` |
| 草稿影响 | 客户端直接读 `GET .../settings/impact` | 不写入数据 |

### 10.4 Run / 阶段结果引用

- 新 `Run` 自动读取最新 `published` 设置的 `version_id` 并写入 `Run.config_version_id`。
- 已有 `Run` 不会被新的设置发布影响：仍保留旧的 `config_version_id`。
- `RunPolicy.allow_locked_stage_rerun = false` 时，新 Run 在锁定阶段上返回 409。
- `Skill` 调用会根据 `stage_skill_profiles[stage_id].enabled_tools` 过滤；前端展示的 `SkillInvokeResponse.enabled_tools` 是后端真正执行的子集。
- `stage_results.model_config.config_version_id` 与 `prompt_refs` 记录每次 Skill 调用时实际生效的配置版本与提示词引用。

### 10.5 状态映射

- 状态枚举与后端 `ProjectSettingsResponse.status` 一致：`draft | published`。
- `has_draft` 为 `True` 时，工作区展示 `draft`；为 `False` 时展示 `published` 作为编辑来源。
- 保存草稿成功后，前端立即调用 `bundle` 重新加载。
- 发布成功后重新加载 `bundle` 与 `versions`，并清空本地 `change_reason` 草稿态。

### 10.6 校验

- 模型数值 `temperature ∈ [0, 2]`、`max_tokens > 0`、`timeout_seconds > 0`、`retry_limit >= 0`（前端 + 后端双重校验）。
- `enabled_tools` 必须是 `Skill.allowed_tools` 子集；`enabled_subagents` 必须是 `Skill.allowed_subagents` 子集。
- `run_policy.min_audit_requirements` 必须包含 `config_version_id / model_alias / prompt_hash / skill_version`。
- 阶段提示词（`category = stage`）必须包含必需变量 `project_goal / stage_objective / evidence_summary / previous_stage_result`。
- 后端拒绝非法配置时返回 422 + 明确 `detail`；前端用 toast / 错误条展示。

## 11. 实现参考

- `src/apps/web/lib/api-client.ts`
- `src/apps/web/lib/api-types.ts`
- `src/apps/web/lib/api-mappers.ts`
- `src/apps/web/lib/settings-state.ts`
- `src/apps/web/components/codex/settings-workspace.tsx`
- `src/apps/api/app/services/settings_service.py`
- `src/contracts/openapi.yaml`
- `src/contracts/jsonschema/project-settings.schema.json`
