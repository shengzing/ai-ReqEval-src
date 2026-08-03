# Contracts

本目录是 MVP v1.0 的共享契约层，服务对象包括：

- FastAPI 后端实现
- Next.js / React 前端接入
- 自动化测试
- 阶段验收与回归检查

## 目录说明

- `openapi.yaml`
  - REST API 主契约。
  - 覆盖当前已实现的项目、阶段、对话、文件、视觉解析、Run、Skill、autoResearch、报告、日志接口。

- `events/README.md`
  - `GET /api/v1/runs/{run_id}/events` 的 SSE 事件契约。
  - 说明事件名、通用帧格式、前端消费口径。

- `jsonschema/`
  - 结构化产物契约。
  - 当前包含阶段结果、autoResearch 记录、报告对象、RunEvent 帧的 JSON Schema。

- `frontend-integration.md`
  - 前端接入说明。
  - 说明 API base URL、关键资源读取顺序、SSE 消费、状态枚举映射、错误处理约定。

- `acceptance.md`
  - 阶段验收说明。
  - 对齐 MVP 设计文档中的四阶段验收点、锁定条件和端到端通过标准。

## 当前约束

1. 新增 REST 接口时，必须同步更新 `openapi.yaml`。
2. 新增 Run 事件时，必须同步更新 `events/README.md`。
3. 新增阶段结果或报告关键字段时，必须同步更新 `jsonschema/`。
4. 前端如果新增状态映射或新消费路径，必须同步更新 `frontend-integration.md`。
5. 验收口径发生变化时，必须同步更新 `acceptance.md`。
