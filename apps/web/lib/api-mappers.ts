import type {
  Conversation,
  ConversationMessage,
  EvidenceItem,
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

const RUN_PROGRESS_EVENTS = new Set([
  'run.tool_started',
  'run.tool_completed',
  'run.tool_failed',
  'run.skill_started',
  'run.skill_completed',
  'run.skill_failed',
  'run.harness_planned',
  'run.harness_decision',
  'run.harness_fallback',
])

function getRunEventName(item: RunEventFrame) {
  const payload = item.data.payload
  if (typeof payload.tool_name === 'string') return payload.tool_name
  if (typeof payload.skill_id === 'string') return payload.skill_id
  if (typeof payload.skill_name === 'string') return payload.skill_name
  if (typeof payload.node === 'string') return payload.node
  if (typeof payload.step === 'string') return payload.step
  if (item.event.startsWith('run.harness')) return 'LangGraph Harness'
  if (item.event.startsWith('run.skill')) return 'Skill Harness'
  return 'tool'
}

function getRunEventStatus(item: RunEventFrame): ToolCall['status'] {
  if (item.event.endsWith('_failed') || item.event === 'run.harness_fallback') return 'failed'
  if (item.event.endsWith('_completed') || item.event === 'run.harness_planned' || item.event === 'run.harness_decision') return 'completed'
  return 'running'
}

function getRunEventOutput(item: RunEventFrame) {
  const payload = item.data.payload
  const parts = [
    typeof payload.summary === 'string' ? payload.summary : undefined,
    typeof payload.reason === 'string' ? `原因：${payload.reason}` : undefined,
    typeof payload.decision === 'string' ? `决策：${payload.decision}` : undefined,
    typeof payload.fallback_reason === 'string' ? `回退：${payload.fallback_reason}` : undefined,
  ].filter(Boolean)
  if (parts.length > 0) return parts.join('；')
  if (item.event === 'run.harness_planned' && Array.isArray(payload.plan)) return `计划 ${payload.plan.length} 个步骤`
  return undefined
}

export function mapRunEventsToToolCalls(events: RunEventFrame[]): ToolCall[] {
  return events
    .filter((item) => RUN_PROGRESS_EVENTS.has(item.event))
    .map((item, index) => ({
      id: `${item.event}-${index}`,
      name: getRunEventName(item),
      status: getRunEventStatus(item),
      output: getRunEventOutput(item),
    }))
}

export function mapRunEventsToSuggestions(events: RunEventFrame[], stageId: string): SuggestionCard[] {
  return events
    .filter((item) => item.event === 'run.suggestion')
    .map((item, index) => ({
      id: `${stageId}-suggestion-${index}`,
      stageId,
      title: String(item.data.payload.title ?? '待确认建议'),
      source: 'LangGraph Harness',
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
    .filter((item) => ['run.step', 'run.suggestion', 'run.completed', 'run.waiting_user', 'run.harness_fallback'].includes(item.event))
    .map((item, index) => ({
      id: `${item.event}-${index}`,
      role: 'assistant',
      content:
        String(item.data.payload.summary ?? item.data.payload.description ?? item.data.payload.fallback_reason ?? item.data.payload.reason ?? item.event),
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

export function canSubmitHomeTask(inputValue: string) {
  return Boolean(inputValue.trim())
}
