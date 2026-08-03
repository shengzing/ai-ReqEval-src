# Bank GAI Eval Workbench

该目录对应开题报告中的“轻量化辅助原型”，用于承接商业银行生成式AI项目的前置评估方法。

## 目标

- 把四阶段九步骤固化为可执行工具
- 围绕阶段产出物组织数据与流程
- 支持证据留痕、回放与报告生成

## 四阶段结构

- `stage_1_scenario_risk/`
  - 场景解构与风险定级
- `stage_2_value_sla/`
  - 价值建模与目标SLA反推
- `stage_3_task_probe/`
  - 任务拆解与微型探针测试
- `stage_4_alignment_validation/`
  - 三维对齐与案例验证

## 当前状态

当前已形成最小可运行 MVP，范围限定为：

- 数据收集
- 数据处理
- 问答支持（仅证据问答）

当前不包含前端界面，仅保留 CLI 与核心服务。

## 边界说明

- 问答仅基于项目目录中已落盘的结构化产出物
- 回答尽量标注来源文件
- 不接外部 LLM 作为事实来源
- 不替代正式审批结论

## 设计文档

- [产品设计文档](/Users/jiachengbin/workspace/ai-ReqEval/DOCS/design/06_整体设计.md)
- [MVP 功能列表](/Users/jiachengbin/workspace/ai-ReqEval/src/packages/bank_gai_eval_workbench/MVP_FEATURES.md)
- [版本记录](/Users/jiachengbin/workspace/ai-ReqEval/src/packages/bank_gai_eval_workbench/VERSION_HISTORY.md)
- [执行日志](/Users/jiachengbin/workspace/ai-ReqEval/src/packages/bank_gai_eval_workbench/EXECUTION_LOG.md)

## MVP 运行方式

初始化示例项目：

```bash
python -m src.packages.bank_gai_eval_workbench init-demo
```

执行处理：

```bash
python -m src.packages.bank_gai_eval_workbench process demo-loan-post-risk
```

执行问答：

```bash
python -m src.packages.bank_gai_eval_workbench ask demo-loan-post-risk "目标SLA是多少？"
```

导出报告：

```bash
python -m src.packages.bank_gai_eval_workbench export-report demo-loan-post-risk
```

查看项目状态：

```bash
python -m src.packages.bank_gai_eval_workbench status demo-loan-post-risk
python -m src.packages.bank_gai_eval_workbench list-projects
```

## 目录说明

- `collector.py`
  - 数据收集与项目文件初始化
- `processor.py`
  - 数据处理与四阶段结果汇总
- `qa.py`
  - 规则式问答支持
- `reporter.py`
  - Markdown 底稿导出
- `storage.py`
  - 本地 JSON 存储
- `versioning.py`
  - 全局与项目级版本/执行记录写入

## 数据产出

默认数据目录为 `outputs/bank_gai_eval_workbench/`，每个项目一个目录，典型文件包括：

- `project_meta.json`
- `scenario_record.json`
- `value_record.json`
- `probe_record.json`
- `stage_1_result.json`
- `stage_2_result.json`
- `stage_3_result.json`
- `stage_4_result.json`
- `processing_result.json`
- `report.md`
- `version_log.jsonl`
- `execution_log.jsonl`
