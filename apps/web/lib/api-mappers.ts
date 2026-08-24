import type {
  Conversation,
  ConversationMessage,
  EvidenceItem,
  ExecutionTraceKind,
  ExecutionTraceNode,
  RunStatus,
  Stage,
  StageStatus,
  SuggestionCard,
  ToolCall,
} from './types'

export interface AutoResearchRecordLike {
  id: string
  stage_id: string
  title: string
  source: string
  impact: string
  risk: string
  description: string
  action: string
  context: Record<string, unknown>
  status: string
  edited_description?: string | null
}

export interface RunEventFrame {
  event: string
  data: {
    type: string
    payload: Record<string, unknown>
    created_at: string
  }
}

export interface StageResultLike {
  valid_result?: boolean
  input_file_ids?: string[]
  evidence_item_ids?: string[]
  result_payload: Record<string, unknown>
}

export interface VisionResultLike {
  file_id: string
  to_confirm: Array<Record<string, unknown>>
  uncertainties: string[]
}

export function selectLatestValidStageResult<T extends StageResultLike>(items: T[], requireBinding = false): T | undefined {
  return [...items].reverse().find((item) => (
    item.valid_result !== false &&
    (!requireBinding || (Boolean(item.input_file_ids?.length) && Boolean(item.evidence_item_ids?.length)))
  ))
}

export function mapStageStatus(status: string): StageStatus {
  if (status === 'locked') return 'locked'
  if (status === 'completed') return 'completed'
  if (status === 'waiting_user') return 'waiting_user'
  if (status === 'failed') return 'failed'
  if (status === 'needs_review') return 'needs_review'
  if (status === 'running' || status === 'in_progress') return 'in_progress'
  return 'not_started'
}

export function mapRunStatus(status: string): RunStatus {
  if (status === 'queued') return 'queued'
  if (status === 'running') return 'running'
  if (status === 'waiting_inputs') return 'waiting_inputs'
  if (status === 'waiting_user') return 'waiting_user'
  if (status === 'completed') return 'completed'
  if (status === 'failed') return 'failed'
  if (status === 'cancelled') return 'cancelled'
  return 'created'
}

function mapAutoResearchRisk(risk: string): SuggestionCard['risk'] {
  if (risk === 'high') return 'high'
  if (risk === 'low') return 'low'
  return 'medium'
}

export function mapAutoResearchRecordToSuggestion(record: AutoResearchRecordLike): SuggestionCard {
  const sourceDetails: string[] = []
  const sourceFile = typeof record.context?.source_file === 'string' ? record.context.source_file : undefined
  const sourceLine = typeof record.context?.source_line === 'string' ? record.context.source_line : undefined
  const sourceType = typeof record.context?.source_type === 'string' ? record.context.source_type : undefined
  if (sourceFile) sourceDetails.push(`文件：${sourceFile}`)
  if (sourceLine) sourceDetails.push(`明细：${sourceLine}`)
  if (sourceType) sourceDetails.push(`类型：${sourceType}`)
  return {
    id: record.id,
    recordId: record.id,
    stageId: record.stage_id,
    title: record.title,
    source: record.source,
    impact: record.impact,
    risk: mapAutoResearchRisk(record.risk),
    description: record.edited_description ?? record.description,
    action: record.action,
    sourceFile,
    sourceDetails,
    status: record.status as SuggestionCard['status'],
  }
}

const RUN_TOOL_EVENTS = new Set([
  'run.tool_started',
  'run.tool_completed',
  'run.tool_failed',
])

const RUN_STATE_EVENTS = new Set([
  'run.created',
  'run.queued',
  'run.running',
  'run.resumed',
  'run.waiting_inputs',
  'run.waiting_user',
  'run.completed',
  'run.failed',
  'run.cancelled',
])

// 展示层枚举/原因中文化（后端持久化保留英文枚举用于审计稳定性，前端翻译为中文显示）。
// 未知值原样返回——不吞掉，只翻已知。
const ADOPTION_STATUS_LABELS: Record<string, string> = {
  not_adopted: '未采纳',
  not_applicable: '不适用',
  adopted: '已采纳',
  adopted_with_edits: '采纳（已编辑）',
  rejected: '已拒绝',
  pending: '待定',
  follow_up: '需跟进',
}
const REVIEW_STATUS_LABELS: Record<string, string> = {
  ready_for_probe: '可进入探针',
  need_supplement: '需补充',
  needs_confirmation: '需确认',
  confirmed: '已确认',
}
// 后端 run_service.py 的 failure/waiting reason 是有界英文集合，前端短语表覆盖。
// 工具级 failure.detail 为无界英文，保留原文不翻译。
const RUN_REASON_LABELS: Record<string, string> = {
  'Tool execution failed': '工具执行失败',
  'Skill execution was not accepted': '技能执行未被采纳',
  'Harness requires human review before completion.': '完成前需人工复核',
  'Harness decision did not allow completion': '决策未允许完成',
  'missing_input': '缺少输入',
  'awaiting_skill_execution': '等待技能执行',
}
function labelAdoptionStatus(value: string): string {
  return ADOPTION_STATUS_LABELS[value] ?? value
}
function labelReviewStatus(value: string): string {
  return REVIEW_STATUS_LABELS[value] ?? value
}
function labelRunReason(text: string): string {
  return RUN_REASON_LABELS[text] ?? text
}


function getRunEventName(item: RunEventFrame) {
  const payload = item.data.payload
  if (typeof payload.tool_name === 'string') return payload.tool_name
  if (typeof payload.skill_id === 'string') return payload.skill_id
  if (typeof payload.skill_name === 'string') return payload.skill_name
  if (typeof payload.node === 'string') return payload.node
  if (typeof payload.step === 'string') return payload.step
  if (item.event.startsWith('run.harness')) return '编排框架'
  if (item.event.startsWith('run.skill')) return '技能编排'
  return '工具'
}

function getRunEventStatus(item: RunEventFrame): ToolCall['status'] {
  if (item.data.payload.status === 'failed' || item.event.endsWith('_failed') || item.event === 'run.harness_fallback') return 'failed'
  if (item.event.endsWith('_completed') || item.event === 'run.harness_planned' || item.event === 'run.harness_decision') return 'completed'
  return 'running'
}

function getRunEventOutput(item: RunEventFrame) {
  const payload = item.data.payload
  const parts = [
    typeof payload.summary === 'string' ? payload.summary : undefined,
    typeof payload.reason === 'string' ? `原因：${labelRunReason(payload.reason)}` : undefined,
    typeof payload.decision === 'string' ? `决策：${labelRunReason(payload.decision)}` : undefined,
    typeof payload.fallback_reason === 'string' ? `回退：${labelRunReason(payload.fallback_reason)}` : undefined,
  ].filter(Boolean)
  if (parts.length > 0) return parts.join('；')
  if (item.event === 'run.harness_planned' && Array.isArray(payload.plan)) return `计划 ${payload.plan.length} 个步骤`
  return undefined
}

function getRunEventDetails(item: RunEventFrame): Record<string, unknown> | undefined {
  const payload = item.data.payload
  const rawOutput = payload.raw_output
  if (rawOutput && typeof rawOutput === 'object' && !Array.isArray(rawOutput)) {
    return rawOutput as Record<string, unknown>
  }
  const details = payload.details
  if (details && typeof details === 'object' && !Array.isArray(details)) {
    return details as Record<string, unknown>
  }
  return undefined
}

function getRunEventEvidenceRefs(item: RunEventFrame): string[] | undefined {
  const refs = item.data.payload.evidence_refs
  if (!Array.isArray(refs)) return undefined
  const normalized = refs.filter((item): item is string => typeof item === 'string' && item.length > 0)
  return normalized.length > 0 ? normalized : undefined
}

function hasExecutionOutput(details: Record<string, unknown> | undefined) {
  return Boolean(details && Object.keys(details).length > 0)
}

export function mapRunEventsToToolCalls(events: RunEventFrame[]): ToolCall[] {
  const invocations = new Map<string, ToolCall>()
  for (const item of events) {
    if (!RUN_TOOL_EVENTS.has(item.event)) continue
    const invocationId = item.data.payload.invocation_id
    if (typeof invocationId !== 'string' || !invocationId) continue

    const previous = invocations.get(invocationId)
    const details = getRunEventDetails(item) ?? previous?.details
    const durationMs = item.data.payload.duration_ms
    invocations.set(invocationId, {
      id: invocationId,
      name: getRunEventName(item),
      status: getRunEventStatus(item),
      duration: typeof durationMs === 'number' ? `${durationMs.toFixed(2)} ms` : previous?.duration,
      output: getRunEventOutput(item) ?? previous?.output,
      details,
      evidenceRefs: getRunEventEvidenceRefs(item) ?? previous?.evidenceRefs,
      source: 'stage_run',
      canConfirm: item.event === 'run.tool_completed' && hasExecutionOutput(details),
    })
  }
  return [...invocations.values()]
}

function getTraceKind(item: RunEventFrame): ExecutionTraceKind {
  const payload = item.data.payload
  if (item.event.startsWith('run.tool_')) return item.event === 'run.tool_skipped' ? 'validation' : 'tool'
  if (item.event.startsWith('run.subagent_') || typeof payload.subagent_name === 'string') return 'subagent'
  if (item.event.startsWith('run.skill_')) return 'skill'
  if (item.event === 'run.stage1_phase') return 'decision'
  if (item.event === 'run.harness_planned' || item.event === 'run.step' || item.event === 'run.tool_filtered') return 'routing'
  if (item.event === 'run.harness_decision' || item.event === 'run.suggestion') return 'decision'
  if (
    item.event === 'run.harness_fallback' ||
    item.event === 'run.evidence_filtered' ||
    item.event.endsWith('_validated') ||
    item.event.endsWith('_validation_failed')
  ) return 'validation'
  if (RUN_STATE_EVENTS.has(item.event)) return 'state'
  return 'state'
}

function getTraceName(item: RunEventFrame, kind: ExecutionTraceKind): string {
  const payload = item.data.payload
  if (kind === 'tool' || item.event === 'run.tool_skipped') {
    const toolName = typeof payload.tool_name === 'string' ? payload.tool_name : '未命名工具'
    return item.event === 'run.tool_skipped' ? `${toolName}（已跳过）` : toolName
  }
  if (kind === 'skill') return typeof payload.skill_name === 'string' ? payload.skill_name : 'Skill 配置'
  if (kind === 'subagent') return typeof payload.subagent_name === 'string' ? payload.subagent_name : '子代理'
  const names: Partial<Record<string, string>> = {
    'run.created': '已创建运行',
    'run.queued': '已进入队列',
    'run.running': '开始运行',
    'run.resumed': '已恢复运行',
    'run.waiting_inputs': '等待补充输入',
    'run.waiting_user': '等待人工确认',
    'run.completed': '运行完成',
    'run.failed': '运行失败',
    'run.cancelled': '运行已取消',
    'run.step': '路由阶段',
    'run.harness_planned': 'Harness 执行规划',
    'run.harness_decision': 'Harness 决策',
    'run.harness_fallback': 'Harness 降级校验',
    'run.evidence_filtered': '输入证据校验',
    'run.tool_filtered': '工具启用过滤',
    'run.suggestion': '待确认决策',
  }
  if (item.event in names) return names[item.event] as string
  // 阶段一三段推进事件：按 phase 字段给中文阶段名，标识 F1/F2/F3 推进。
  if (item.event === 'run.stage1_phase') {
    const phase = typeof payload.phase === 'string' ? payload.phase : ''
    const phaseName = typeof payload.phase_name === 'string' ? payload.phase_name : ''
    return phaseName || (phase ? `阶段一 ${phase}` : '阶段一推进')
  }
  // 未显式映射的事件按特征给中文，避免落到英文事件名
  if (item.event.endsWith('_validation_failed')) return '校验失败'
  if (item.event.endsWith('_validated')) return '校验通过'
  if (item.event.endsWith('_skipped')) return '已跳过'
  if (item.event.endsWith('_failed')) return '失败'
  return '执行事件'
}

function getTraceStatus(item: RunEventFrame): ExecutionTraceNode['status'] {
  if (
    item.event === 'run.tool_skipped'
    || item.event === 'run.subagent_skipped'
    || item.data.payload.status === 'skipped_missing_input'
    || item.data.payload.status === 'skipped'
  ) return 'skipped'
  if (item.event.endsWith('_failed') || item.event === 'run.failed' || item.event === 'run.harness_fallback') return 'failed'
  if (item.event.endsWith('_started') || item.event === 'run.running' || item.event === 'run.queued') return 'running'
  return 'completed'
}

function getTraceSummary(item: RunEventFrame): string | undefined {
  const outputSummary = item.data.payload.output_summary
  const adoptionStatus = typeof item.data.payload.adoption_status === 'string'
    ? labelAdoptionStatus(item.data.payload.adoption_status)
    : undefined
  const adoptionReason = typeof item.data.payload.adoption_reason === 'string'
    ? item.data.payload.adoption_reason
    : undefined
  const failure = item.data.payload.failure
  const failureDetail = failure && typeof failure === 'object' && !Array.isArray(failure)
    && typeof (failure as Record<string, unknown>).detail === 'string'
    ? (failure as Record<string, unknown>).detail as string
    : undefined
  const outputText = outputSummary && typeof outputSummary === 'object' && !Array.isArray(outputSummary)
    && typeof (outputSummary as Record<string, unknown>).summary === 'string'
    ? (outputSummary as Record<string, unknown>).summary as string
    : undefined
  const auditText = [outputText, adoptionStatus ? `采纳状态：${adoptionStatus}` : undefined, adoptionReason].filter(Boolean).join('；')
  return failureDetail || auditText || (
    getRunEventOutput(item)
    ?? (typeof item.data.payload.message === 'string' ? item.data.payload.message : undefined)
  )
}

function getTraceDetails(item: RunEventFrame, kind: ExecutionTraceKind): Record<string, unknown> | undefined {
  const details = getRunEventDetails(item)
  if (details || kind !== 'subagent') return details
  // run.stage1_phase 携带本段产物 + 质量分/问题计数，直接作为 details 展示
  if (item.event === 'run.stage1_phase') {
    return item.data.payload as Record<string, unknown>
  }
  const payload = item.data.payload
  // 键名保留为审计契约标识符；枚举值译中文以便 UI 直接展示。
  return {
    input_summary: payload.input_summary ?? {},
    output_summary: payload.output_summary ?? {},
    failure: payload.failure ?? null,
    review_status: labelReviewStatus(typeof payload.review_status === 'string' ? payload.review_status : ''),
    adoption_status: labelAdoptionStatus(typeof payload.adoption_status === 'string' ? payload.adoption_status : 'not_adopted'),
    adoption_reason: payload.adoption_reason ?? '',
    provider: payload.provider ?? '',
    duration_ms: payload.duration_ms ?? 0,
  }
}

/**
 * Maps every Run event to its semantic timeline representation.  Tool events
 * are grouped by invocation_id, while routing/validation/state events remain
 * lightweight trace entries instead of becoming fake tools.
 */
export function mapRunEventsToExecutionTrace(events: RunEventFrame[]): ExecutionTraceNode[] {
  const trace: ExecutionTraceNode[] = []
  const toolsByInvocation = new Map<string, number>()
  const subagentsByInvocation = new Map<string, number>()
  const toolCalls = new Map(mapRunEventsToToolCalls(events).map((call) => [call.id, call]))

  // 按事件时间排序，确保执行顺序正确
  const sortedEvents = [...events].sort((a, b) => {
    const timeA = a.data.created_at ? new Date(a.data.created_at).getTime() : 0
    const timeB = b.data.created_at ? new Date(b.data.created_at).getTime() : 0
    return timeA - timeB
  })

  // 检查是否已有终态事件，如果有则修正 run.running 的状态
  const hasTerminalEvent = sortedEvents.some((item) =>
    ['run.completed', 'run.failed', 'run.cancelled', 'run.waiting_user', 'run.waiting_inputs'].includes(item.event)
  )

  sortedEvents.forEach((item, index) => {
    const kind = getTraceKind(item)
    const payload = item.data.payload
    if (kind === 'subagent') {
      const invocationId = typeof payload.invocation_id === 'string' ? payload.invocation_id : undefined
      if (!invocationId) {
        // 跳过未审计子代理事件，不生成失败节点
        return
      }
      const node: ExecutionTraceNode = {
        id: `subagent-${invocationId}`,
        kind: 'subagent',
        name: getTraceName(item, kind),
        status: getTraceStatus(item),
        createdAt: item.data.created_at,
        summary: getTraceSummary(item),
        details: getTraceDetails(item, kind),
        evidenceRefs: getRunEventEvidenceRefs(item),
        skillName: typeof payload.skill_name === 'string' ? payload.skill_name : undefined,
      }
      const existingIndex = subagentsByInvocation.get(invocationId)
      if (existingIndex === undefined) {
        subagentsByInvocation.set(invocationId, trace.length)
        trace.push(node)
      } else {
        trace[existingIndex] = node
      }
      return
    }
    if (kind === 'tool') {
      const invocationId = typeof payload.invocation_id === 'string' ? payload.invocation_id : undefined
      const toolCall = invocationId ? toolCalls.get(invocationId) : undefined
      // 跳过未审计工具事件，不生成失败节点
      if (!invocationId || !toolCall) {
        return
      }
      const existingIndex = toolsByInvocation.get(invocationId)
      const node: ExecutionTraceNode = {
        id: `tool-${invocationId}`,
        kind: 'tool',
        name: toolCall.name,
        status: toolCall.status,
        createdAt: item.data.created_at,
        summary: toolCall.output,
        details: toolCall.details,
        evidenceRefs: toolCall.evidenceRefs,
        skillName: typeof payload.skill_name === 'string' ? payload.skill_name : undefined,
        toolCall,
      }
      if (existingIndex === undefined) {
        toolsByInvocation.set(invocationId, trace.length)
        trace.push(node)
      } else {
        trace[existingIndex] = node
      }
      return
    }

    // 修正状态节点：如果已有终态事件，"开始运行"/"已进入队列" 应显示为已完成
    let status = getTraceStatus(item)
    if ((item.event === 'run.running' || item.event === 'run.queued') && hasTerminalEvent) {
      status = 'completed'
    }

    trace.push({
      id: `${item.event}-${index}`,
      kind,
      name: getTraceName(item, kind),
      status,
      createdAt: item.data.created_at,
      summary: getTraceSummary(item),
      details: getTraceDetails(item, kind),
      evidenceRefs: getRunEventEvidenceRefs(item),
      skillName: typeof payload.skill_name === 'string' ? payload.skill_name : undefined,
      humanCheckpoint: item.event === 'run.waiting_user' ? {
        reason: typeof payload.reason === 'string' ? payload.reason : undefined,
        decision: payload.decision && typeof payload.decision === 'object' && !Array.isArray(payload.decision)
          ? payload.decision as Record<string, unknown>
          : undefined,
        stageResultId: typeof payload.stage_result_id === 'string' ? payload.stage_result_id : undefined,
      } : undefined,
    })
  })
  return trace
}

export function mapConversationToolCalls(toolCalls: unknown): ToolCall[] {
  if (!Array.isArray(toolCalls)) return []
  return toolCalls.flatMap((item, index) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return []
    const call = item as Record<string, unknown>
    const payload = call.payload && typeof call.payload === 'object' && !Array.isArray(call.payload)
      ? call.payload as Record<string, unknown>
      : {}
    const outputRecord = payload.output && typeof payload.output === 'object' && !Array.isArray(payload.output)
      ? payload.output as Record<string, unknown>
      : undefined
    const output = hasExecutionOutput(outputRecord) ? outputRecord : undefined
    const evidenceRefs = Array.isArray(payload.evidence_refs)
      ? payload.evidence_refs.filter((reference): reference is string => typeof reference === 'string' && reference.length > 0)
      : undefined
    const success = payload.success
    const summary = typeof payload.summary === 'string'
      ? payload.summary
      : typeof call.reason === 'string' ? call.reason : undefined
    const toolName = typeof call.tool_name === 'string' ? call.tool_name : `context_tool_${index + 1}`
    const source = call.source === 'stage_run' ? 'stage_run' : 'conversation'
    const status = call.status === 'running'
      ? 'running'
      : call.status === 'failed' || success === false ? 'failed' : 'completed'
    const invocationId = typeof call.invocation_id === 'string' ? call.invocation_id : undefined
    return [{
      id: invocationId ?? `conversation-tool-${index}-${toolName}`,
      name: toolName,
      status,
      output: summary,
      details: output,
      evidenceRefs,
      source,
      canConfirm: source === 'stage_run' && status === 'completed' && hasExecutionOutput(output),
    }]
  })
}

export function mapRunEventsToSuggestions(events: RunEventFrame[], stageId: string): SuggestionCard[] {
  return events
    .filter((item) => item.event === 'run.suggestion')
    .map((item, index) => ({
      id: `${stageId}-suggestion-${index}`,
      stageId,
      title: String(item.data.payload.title ?? '待确认建议'),
      source: '编排框架',
      impact: '确认后写回当前阶段结果',
      risk: 'medium',
      description: String(item.data.payload.description ?? ''),
    }))
}

export function mapRunEventsToConversation(
  events: RunEventFrame[],
  title: string,
  conversationId?: string
): Conversation {
  const messages: ConversationMessage[] = events
    // Keep internal routing in the execution timeline. The chat should show
    // only user-relevant outcomes and actionable pause explanations.
    .filter((item) => ['run.suggestion', 'run.completed', 'run.waiting_inputs', 'run.waiting_user', 'run.harness_fallback'].includes(item.event))
    .map((item, index) => ({
      id: `${item.event}-${index}`,
      role: 'assistant',
      content:
        String(item.data.payload.message ?? item.data.payload.summary ?? item.data.payload.description ?? item.data.payload.fallback_reason ?? item.data.payload.reason ?? item.event),
    }))
  return {
    // A Run belongs to a real persisted conversation. Keeping that ID means
    // messages sent while the Run is active continue to target the server
    // conversation instead of a temporary UI-only identifier.
    id: conversationId ?? `run-conversation-${title}`,
    title,
    timeAgo: '刚刚',
    status: 'completed',
    messages,
  }
}

export function getLatestConversationRunId(conversation: Conversation): string | undefined {
  return [...(conversation.messages ?? [])].reverse().find((message) => message.runId)?.runId
}

export function buildStageChecklist(stage: Stage | undefined, evidenceCount: number) {
  return [
    { label: '阶段目标已加载', checked: Boolean(stage?.objective) },
    { label: '阶段会话已建立', checked: (stage?.conversations.length ?? 0) > 0 },
    { label: '阶段技能已装载', checked: (stage?.skills?.length ?? 0) > 0 },
    { label: '阶段证据已关联', checked: evidenceCount > 0 },
    { label: '待确认项已清空', checked: (stage?.pendingConfirmations ?? 0) === 0 },
    { label: '阶段结果已锁定', checked: stage?.status === 'locked' },
  ]
}

export function buildLockChecklist(stage: Stage | undefined, evidenceCount: number) {
  return [
    { label: '已有至少一条阶段会话', checked: (stage?.conversations.length ?? 0) > 0 },
    { label: '至少关联一条证据', checked: evidenceCount > 0 },
    { label: '不存在待确认建议', checked: (stage?.pendingConfirmations ?? 0) === 0 },
    { label: '阶段状态允许锁定', checked: stage?.status !== 'not_started' && stage?.status !== 'failed' },
  ]
}

export function buildEvidenceStatusCounts(items: EvidenceItem[]) {
  return {
    all: items.length,
    uploaded: items.filter((item) => item.status === 'uploaded').length,
    parsed: items.filter((item) => item.status === 'parsed').length,
    referenced: items.filter((item) => item.status === 'referenced').length,
    locked: items.filter((item) => item.status === 'locked').length,
    archived: items.filter((item) => item.status === 'archived').length,
  }
}

export function mapEvidenceRelevanceStatus(value?: string | null): EvidenceItem['relevanceStatus'] {
  if (value === 'related' || value === 'needs_review' || value === 'unrelated' || value === 'rejected') {
    return value
  }
  return 'pending_parse'
}

/**
 * HCR-P1-05：把快照里富集的 version_log 映射成右栏 Stage['versionLog']。
 * 复用 loadLatestStageVersion 的 details 提取逻辑（version_id /
 * locked 取 created_at / diff_summary.field_changes），让前端完成 Run
 * 后只读一次快照即可渲染右栏版本块，不再发 /version-logs。
 */
export interface VersionLogLike {
  change_type?: string | null
  resource_id?: string | null
  details?: Record<string, unknown> | null
  created_at?: string | null
}

export function mapVersionLog(log?: VersionLogLike | null): Stage['versionLog'] {
  if (!log) return undefined
  const details = (log.details ?? {}) as Record<string, unknown>
  const versionId = typeof details.version_id === 'string' ? details.version_id : undefined
  const diffSummary = details.diff_summary as Record<string, unknown> | undefined
  const diffFields = Array.isArray(diffSummary?.field_changes)
    ? (diffSummary!.field_changes as unknown[]).map((item) => String(item))
    : undefined
  const lockedAt = log.change_type === 'locked' && log.created_at ? log.created_at : undefined
  if (!versionId && !lockedAt && !diffFields) return undefined
  return { versionId, lockedAt, diffFields }
}

export function mergeVisionEvidenceDetails(
  items: EvidenceItem[],
  visionResults: VisionResultLike[],
): EvidenceItem[] {
  const byFileId = new Map(visionResults.map((item) => [item.file_id, item]))
  return items.map((item) => {
    if (item.type !== 'record' || !item.sourceFileId) return item
    const vision = byFileId.get(item.sourceFileId)
    if (!vision) return item
    const summaryLines = [
      `待确认字段 ${vision.to_confirm.length} 个`,
      `不确定项 ${vision.uncertainties.length} 个`,
    ]
    if (item.reviewNote) summaryLines.push(`处理说明：${item.reviewNote}`)
    return {
      ...item,
      summaryLines,
      detailLines: [
        ...vision.to_confirm.map((entry) => {
          const field = typeof entry.field === 'string' ? entry.field : 'unknown'
          const reason = typeof entry.reason === 'string' ? entry.reason : 'needs_review'
          return `待确认：${field} (${reason})`
        }),
        ...vision.uncertainties.map((entry) => `不确定：${entry}`),
      ],
    }
  })
}

export function canSubmitHomeTask(inputValue: string) {
  return Boolean(inputValue.trim())
}
