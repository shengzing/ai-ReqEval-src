# JSON Schema Contracts

本目录保存当前 MVP 已稳定下来的结构化契约，用于：

- 持久化对象约束
- 前后端共享结构口径
- 自动化测试中的结构校验
- 阶段验收时的字段完整性检查

## 当前文件

- `stage-result.schema.json`
  - 阶段结果对象契约。
  - 对齐 `StageResultResponse` 和持久化 `stage_results` 文档。

- `autoresearch-record.schema.json`
  - autoResearch 记录对象契约。
  - 对齐 `AutoResearchRecordResponse` 和持久化 `autoresearch_records` 文档。

- `report.schema.json`
  - 报告对象契约。
  - 对齐 `ReportResponse` 和持久化 `reports` 文档。

- `project-settings.schema.json`
  - 项目级设置契约：模型、提示词、阶段 Skill、运行与留痕策略。
  - 对齐 `ProjectSettingsResponse` 和持久化 `project_settings` 文档。
  - `stage_skill_profiles[].enabled_tools` 必须是 `Skill.allowed_tools` 的子集；
    `enabled_subagents` 必须是 `Skill.allowed_subagents` 的子集（由后端校验）。

- `run-event-frame.schema.json`
  - SSE `data:` 帧中的 JSON 结构契约。
  - 事件名枚举不在 schema 中硬编码，详细集合以 `events/README.md` 为准。

## 使用约束

1. 阶段结果增加关键字段时，先更新 `stage-result.schema.json`。
2. autoResearch 状态机变化时，先更新 `autoresearch-record.schema.json`。
3. 报告输出路径或核心元数据变化时，先更新 `report.schema.json`。
4. 项目级设置增加或调整模型、提示词、阶段 Skill 或运行策略字段时，先更新 `project-settings.schema.json` 与 `openapi.yaml`。
5. 事件通用帧结构变化时，先更新 `run-event-frame.schema.json` 与 `events/README.md`。
