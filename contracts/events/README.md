# Event Contracts

当前 SSE 事件通道为 `GET /api/v1/runs/{run_id}/events`，返回 `text/event-stream`。

## 通用帧格式

```text
event: <event_name>
data: {"type":"<event_name>","payload":{...},"created_at":"<iso_datetime>"}
```

## 当前事件集合

- `run.created`
  - `payload.run_id`
  - `payload.project_id`
- `run.queued`
  - `payload.stage_id`
  - `payload.skill_name`
- `run.running`
  - `payload.goal`
  - `payload.stage_id`
- `run.step`
  - `payload.summary`
  - `payload.reasoning`
  - `payload.stage_name`
- `run.skill_started`
  - `payload.skill_name`
  - `payload.tool_names`
  - `payload.subagent_names`
  - `payload.source`（可选）
- `run.skill_completed`
  - `payload.skill_name`
  - `payload.summary`
  - `payload.source`（可选）
  - `payload.stage_result_id`（部分路径存在）
- `run.tool_started`
  - `payload.skill_name`
  - `payload.tool_name`
- `run.tool_completed`
  - `payload.skill_name`
  - `payload.tool_name`
  - `payload.summary`
- `run.suggestion`
  - `payload.title`
  - `payload.description`
  - `payload.stage_result_id`
- `run.waiting_user`
  - `payload.reason`
  - `payload.stage_result_id`
- `run.completed`
  - `payload.summary`
  - `payload.stage_result_id`
- `run.failed`
  - `payload.reason`
  - `payload.stage_result_id`（可选）
- `run.cancelled`
  - `payload.reason`（可选）

## 前端当前消费口径

- 工作区工具流使用：`run.tool_started`、`run.tool_completed`
- 建议卡使用：`run.suggestion`
- 对话记录摘要使用：`run.step`、`run.suggestion`、`run.waiting_user`、`run.completed`
- 运行状态使用：`run.running`、`run.waiting_user`、`run.completed`、`run.failed`
- SSE 重连终止事件：`run.completed`、`run.failed`、`run.cancelled`
