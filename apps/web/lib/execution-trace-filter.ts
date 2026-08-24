import type { ExecutionTraceNode } from './types'

/**
 * 承载人工介入点或异常终态的 state 节点名（来自 api-mappers.getTraceName）。
 * ExecutionTraceNode.status 类型无 'cancelled'，run.cancelled 在 getTraceStatus
 * 中被归为 'completed'，故此处靠 name 兜底保留 cancelled 节点。
 */
const HUMAN_INTERVENTION_NAMES = new Set([
  '等待人工确认', // run.waiting_user — HITL 人工介入点
  '等待补充输入', // run.waiting_inputs — 阻塞语义边界
  '运行失败', // run.failed — 异常终态（status 亦为 failed，双保险）
  '运行已取消', // run.cancelled — 人工终止决策
])

/**
 * 判定一个 trace 节点是否承载"具体操作内容"，应默认展示。
 *
 * 纯状态流转节点（run.created/queued/running/resumed/completed、run.step）
 * 无 summary/details/evidenceRefs，返回 false 被隐藏。
 * run.harness_planned 在 api-mappers.getRunEventOutput 中必产 summary
 * （「计划 N 个步骤」），故内容判定天然区分 routing 与纯状态。
 *
 * 注意：前端不渲染 ≠ 证据丢失——Run 事件在后端全量持久化，
 * 此过滤仅为展示层降噪。审计兜底由 execution-timeline 的「显示全部审计节点」
 * 开关提供，开启后绕过此过滤还原全量。
 */
export function isActionableNode(node: ExecutionTraceNode): boolean {
  // 阶段一三段推进节点（run.stage1_phase）始终保留，按 F1/F2/F3 推进展示。
  if (node.kind === 'decision' && node.name && /阶段一|场景边界|流程责任链|风险与HITL|F[123]/.test(node.name)) {
    return true
  }
  // 有具体操作 / 决策校验语义 / 分组头 → 始终保留
  if (
    node.kind === 'tool'
    || node.kind === 'subagent'
    || node.kind === 'skill'
    || node.kind === 'validation'
    || node.kind === 'decision'
  ) {
    return true
  }
  // 异常/跳过终态 → 例外保留
  if (node.status === 'failed' || node.status === 'skipped') {
    return true
  }
  if (HUMAN_INTERVENTION_NAMES.has(node.name)) {
    return true
  }
  // routing/state：以是否承载内容区分
  return Boolean(node.summary || node.details || node.evidenceRefs?.length)
}
