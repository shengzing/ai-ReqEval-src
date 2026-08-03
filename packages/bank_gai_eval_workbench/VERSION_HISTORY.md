# Version History

## v0.1.0-mvp

- 状态：开发中
- 范围：
  - 数据收集
  - 数据处理
  - 问答支持
- 说明：
  - 无界面
  - 使用本地 JSON 存储
  - 使用证据问答，不依赖外部 LLM
  - 服务于开题报告中的四阶段前置评估链路
  - 版本记录与执行日志属于 P0

## v0.1.1-mvp

- 状态：可运行
- 新增：
  - `status` 和 `list-projects` 命令
  - `export-report` 命令
  - `stage_1_result` 到 `stage_4_result` 四阶段结果文件
  - 报告导出与证据文件索引
- 修正：
  - README 运行命令改为真实模块路径
  - 问答服务在未处理时给出明确提示
