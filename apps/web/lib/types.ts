export type StageStatus =
  | 'not_started'
  | 'in_progress'
  | 'waiting_user'
  | 'locked'
  | 'completed'
  | 'needs_review'
  | 'failed'

export type RunStatus =
  | 'created'
  | 'queued'
  | 'running'
  | 'waiting_user'
  | 'completed'
  | 'failed'
  | 'cancelled'

export interface Conversation {
  id: string
  title: string
  timeAgo: string
  status?: RunStatus | 'archived'
  messages?: ConversationMessage[]
}

export interface ConversationMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at?: string
  bullets?: string[]
  /** assistant 消息可能附带工具调用过程（仅运行模式） */
  toolCalls?: ToolCall[]
  processOnly?: boolean
  /** assistant 消息可能附带 action proposals（对话 harness 返回） */
  actionProposals?: ConversationActionProposal[]
  /** 对话 harness 的 intent 摘要（仅 assistant） */
  intent?: Record<string, unknown>
  /** 对话 Harness 的运行告警，例如模型未配置或调用失败。 */
  harnessWarnings?: Array<Record<string, unknown>>
}

/** 对话 Harness 产出的受控动作建议 */
export interface ConversationActionProposal {
  id: string
  actionType: string
  title: string
  requiresConfirmation: boolean
  status?: 'pending' | 'accepting' | 'accepted' | 'rejected'
}

/** 对话 Harness 调用摘要 */
export interface ConversationHarness {
  conversationHarnessVersion: string
  intent: Record<string, unknown>
  warnings: Array<Record<string, unknown>>
  actionProposals: ConversationActionProposal[]
}

export interface StageSkill {
  id: string
  name: string
  status: 'ready' | 'running' | 'waiting_user' | 'completed'
  description: string
}

export interface Stage {
  id: string
  name: string
  status: StageStatus
  objective?: string
  nextStep?: string
  recommendedActions?: string[]
  exitAction?: string
  pendingConfirmations?: number
  skills?: StageSkill[]
  resultPayload?: Record<string, unknown>
  versionLog?: {
    versionId?: string
    lockedAt?: string
    diffFields?: string[]
  }
  reportInfo?: {
    id?: string
    title?: string
    status?: string
    content?: string
    approvalCheckPassed?: boolean
    exportPath?: string
    decisionCardPath?: string
    evidenceDirectoryPath?: string
    bundleExportPath?: string
    gateMessage?: string
  }
  lockCheck?: StageLockCheck
  conversations: Conversation[]
}

export interface StageLockCheck {
  stageId: string
  ready: boolean
  checks: StageLockCheckItem[]
}

export interface StageLockCheckItem {
  key: string
  label: string
  passed: boolean
}

export interface Project {
  id: string
  name: string
  status?: StageStatus
  pendingCount?: number
  fileCount?: number
  hasNotification?: boolean
  createdAt?: string
  stages: Stage[]
}

export interface SuggestionCard {
  id: string
  stageId: string
  recordId?: string
  title: string
  source: string
  impact: string
  risk: 'low' | 'medium' | 'high'
  description: string
  action?: string
  sourceFile?: string
  sourceDetails?: string[]
  status?: 'pending' | 'accepted' | 'accepted_with_edits' | 'rejected' | 'follow_up'
}

export interface SuggestionConfirmationResult {
  suggestion: SuggestionCard
  stageResultPayload?: Record<string, unknown>
}

export interface EvidenceItem {
  id: string
  name: string
  type: 'file' | 'record' | 'result' | 'attachment' | 'report'
  sourceFileId?: string
  stage?: string
  status: 'uploaded' | 'parsed' | 'referenced' | 'locked' | 'archived'
  updatedAt: string
  isReferenced?: boolean
  summaryLines?: string[]
  detailLines?: string[]
  attachmentPath?: string
  reviewNote?: string
}

export interface FilePreview {
  id: string
  projectId: string
  filename: string
  contentType: string
  previewType: 'text' | 'pdf' | 'image'
  content: string
  encoding: 'utf-8' | 'base64'
  sizeBytes: number
  truncated: boolean
}

export interface SuggestedTask {
  id: string
  icon: string
  title: string
}

export interface ToolCall {
  id: string
  name: string
  status: 'running' | 'completed' | 'failed'
  duration?: string
  output?: string
  details?: Record<string, unknown>
  evidenceRefs?: string[]
  source?: 'stage_run' | 'conversation'
  canConfirm?: boolean
}
