import type { Conversation, RunStatus, Stage, StageSkill, SuggestionCard } from '@/lib/types'

export function buildEnrichedStage(input: {
  currentStage?: Stage
  resultPayload?: Record<string, unknown>
  reportInfo?: Stage['reportInfo']
  versionLog?: Stage['versionLog']
  lockCheck?: Stage['lockCheck']
  skills: StageSkill[]
  suggestions: SuggestionCard[]
  currentRunStatus?: RunStatus
}): Stage | undefined {
  if (!input.currentStage) return undefined

  return {
    ...input.currentStage,
    resultPayload: input.resultPayload,
    reportInfo: input.reportInfo,
    versionLog: input.versionLog,
    lockCheck: input.lockCheck,
    skills: input.skills,
    pendingConfirmations: input.suggestions.length,
    recommendedActions:
      input.currentStage.recommendedActions && input.currentStage.recommendedActions.length > 0
        ? input.currentStage.recommendedActions
        : ['创建 Run', '查看证据'],
    nextStep: input.currentStage.nextStep ?? '创建运行任务并等待阶段建议。',
    exitAction: input.currentStage.exitAction ?? '锁定阶段结果',
    status: getStageStatusFromRun(input.currentStage.status, input.currentRunStatus, input.suggestions.length),
  }
}

export function getStageStatusFromRun(
  stageStatus: Stage['status'],
  runStatus: RunStatus | undefined,
  suggestionCount: number
): Stage['status'] {
  if (runStatus === 'running') return 'in_progress'
  if (runStatus === 'waiting_user') return 'waiting_user'
  if (runStatus === 'completed' && suggestionCount > 0) return 'waiting_user'
  return stageStatus
}

export function resolveActiveConversation(input: {
  currentConversation?: Conversation
  stageConversations?: Conversation[]
  activeConversationId?: string
}): Conversation | undefined {
  if (input.currentConversation) return input.currentConversation
  if (!input.activeConversationId) return undefined
  return input.stageConversations?.find((item) => item.id === input.activeConversationId)
}
