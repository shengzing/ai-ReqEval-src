'use client'

import { useId, useState, type ReactNode } from 'react'
import {
  ArrowRight,
  CheckCircle2,
  CircleDashed,
  ClipboardList,
  Database,
  FileText,
  Files,
  MessageSquare,
  Paperclip,
  Plus,
  Sparkles,
  Target,
} from 'lucide-react'

import { ScrollArea } from '@/components/ui/scroll-area'
import { Button } from '@/components/ui/button'
import { type Conversation, type EvidenceItem, type RunStatus, type Stage, type SuggestionCard, type ToolCall } from '@/lib/types'
import { hasRenderablePayload } from './stage-results/result-utils'
import { ConversationThread } from './stage/conversation-thread'
import { ExecutionTimeline } from './stage/execution-timeline'
import { SkillStrip } from './stage/skill-strip'
import { StageHeader } from './stage/stage-header'
import { StageExitCard } from './stage/stage-exit-card'
import { StageReportPanel } from './stage/stage-report-panel'
import { StageVersionPanel } from './stage/stage-version-panel'
import { getStageStatusLabel } from './stage/stage-status'
import { WorkspaceCollapsible } from './stage/workspace-collapsible'
import { StageResultPanel } from './stage-results/stage-result-panel'
import { getStageSuffix } from './stage-results/result-utils'

interface StageWorkspaceProps {
  projectId?: string
  stage: Stage
  conversation?: Conversation
  activeConversationId?: string
  stageConversations?: Conversation[]
  conversationLoading?: boolean
  conversationLoadError?: string | null
  toolCalls: ToolCall[]
  suggestionCards: SuggestionCard[]
  evidenceItems?: EvidenceItem[]
  runStatus?: RunStatus
  onSelectConversation?: (conversationId: string) => void
  onCreateConversation?: () => Promise<void> | void
  onOpenRightSidebar?: () => void
  onStartRun?: (goal: string) => Promise<void> | void
  onSendMessage?: (conversationId: string, content: string) => void
  onConfirmConversationAction?: (conversationId: string, proposalId: string) => Promise<void> | void
  onRejectConversationAction?: (conversationId: string, proposalId: string) => Promise<void> | void
  onUploadFiles?: (files: File[]) => Promise<void> | void
  onGenerateReport?: () => Promise<void> | void
  onPreviewReport?: () => Promise<void> | void
  onLockStage?: () => Promise<void> | void
  onResumeRun?: (runId: string, humanInput?: Record<string, unknown>) => Promise<void> | void
  onConfirmExecutionOutput?: (toolCall: ToolCall) => Promise<void> | void
  currentRunId?: string
  stageCommandHint?: string
  conversationSending?: boolean
}

export function StageWorkspace({
  stage,
  conversation,
  activeConversationId,
  conversationLoading,
  conversationLoadError,
  toolCalls,
  suggestionCards,
  evidenceItems = [],
  runStatus,
  onCreateConversation,
  onOpenRightSidebar,
  onStartRun,
  onSendMessage,
  onConfirmConversationAction,
  onRejectConversationAction,
  onUploadFiles,
  onGenerateReport,
  onPreviewReport,
  onLockStage,
  onResumeRun,
  onConfirmExecutionOutput,
  currentRunId,
  stageCommandHint,
  conversationSending,
}: StageWorkspaceProps) {
  const stageSuggestions = suggestionCards.filter((card) => card.stageId === stage.id)
  const isLocked = stage.status === 'locked'
  const isStageOne = getStageSuffix(stage.id) === 'stage-1'
  const stageInputUploadId = useId()
  const [uploadingInputFiles, setUploadingInputFiles] = useState(false)

  // Progressive disclosure: sections with meaningful content default open,
  // empty/no-data sections default collapsed
  const hasResult = hasRenderablePayload(stage.resultPayload)
  const hasVersion = Boolean(stage.versionLog?.versionId)
  const hasReport = Boolean(stage.reportInfo?.title)
  const hasSkills = (stage.skills?.length ?? 0) > 0
  const hasToolCalls = toolCalls.length > 0
  const isRunActive = runStatus === 'running' || runStatus === 'waiting_user'
  const isConversationMode = Boolean(activeConversationId)
  const stageStatusLabel = getStageStatusLabel(stage.status, runStatus)
  const stageInputCount = evidenceItems.length
  const completedToolCount = toolCalls.filter((tool) => tool.status === 'completed').length

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <StageHeader stage={stage} runStatus={runStatus} onOpenRightSidebar={onOpenRightSidebar} onStartRun={onStartRun} />

      {isConversationMode ? (
        <div className="flex min-h-0 flex-1 flex-col">
          {/* 固定阶段信息卡片 */}
          <div className="border-b border-border bg-card/60 px-6 py-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  <MessageSquare className="size-3.5" />
                  阶段对话
                </div>
                <h3 className="mt-0.5 truncate text-sm font-semibold text-foreground">
                  {conversation?.title ?? '当前会话'}
                </h3>
                {stage.objective && (
                  <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">
                    {stage.objective}
                  </p>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="rounded-full bg-muted px-2.5 py-1 text-muted-foreground">
                  阶段状态：{stageStatusLabel}
                </span>
                {stageSuggestions.length > 0 && (
                  <span className="rounded-full bg-amber-100 px-2.5 py-1 text-amber-700">
                    待确认 {stageSuggestions.length} 条
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* 对话消息流(中间滚动区,含底部 composer;composer 同时承担上传/报告操作) */}
          <ConversationThread
            conversation={conversation}
            loading={conversationLoading}
            loadError={conversationLoadError}
            runStatus={runStatus}
            onSendMessage={onSendMessage}
            onConfirmActionProposal={onConfirmConversationAction}
            onRejectActionProposal={onRejectConversationAction}
            onResumeRun={onResumeRun}
            currentRunId={currentRunId}
            sending={conversationSending}
            onUploadFiles={onUploadFiles}
            onGenerateReport={onGenerateReport}
            executionToolCalls={toolCalls}
            onConfirmExecutionOutput={onConfirmExecutionOutput}
          />
        </div>
      ) : (
        <>
        <ScrollArea className="min-h-0 flex-1">
        <div className="space-y-3 p-6">
              <StageWorkbenchSummary
                stage={stage}
                statusLabel={stageStatusLabel}
                inputCount={stageInputCount}
                completedToolCount={completedToolCount}
                toolCount={toolCalls.length}
                suggestionCount={stageSuggestions.length}
                hasResult={hasResult}
                isStageOne={isStageOne}
                runStatus={runStatus}
                onStartRun={onStartRun}
                onCreateConversation={onCreateConversation}
              />

          <div className="space-y-3">
              <StageWorkbenchPanel
                title="阶段输入"
                icon={<Files className="size-4" />}
                helpText="查看本阶段已经接入的文件、材料和引用摘要。这里应该让用户直接看清输入了什么。"
                action={(
                  <div className="flex flex-wrap items-center justify-end gap-2">
                    <label htmlFor={stageInputUploadId} className="inline-flex cursor-pointer rounded-md focus-within:ring-2 focus-within:ring-ring">
                      <input
                        id={stageInputUploadId}
                        type="file"
                        multiple
                        className="sr-only"
                        disabled={isLocked || uploadingInputFiles}
                        onChange={async (event) => {
                          const files = Array.from(event.target.files ?? [])
                          if (!files.length) return
                          setUploadingInputFiles(true)
                          try {
                            await onUploadFiles?.(files)
                          } finally {
                            setUploadingInputFiles(false)
                            event.currentTarget.value = ''
                          }
                        }}
                      />
                      <span className="inline-flex">
                        <Button variant="outline" size="sm" className="h-7 gap-1.5 text-xs" disabled={isLocked || uploadingInputFiles} asChild={false}>
                          <span className="inline-flex items-center gap-1.5">
                            <Paperclip className="size-3.5" />
                            {uploadingInputFiles ? '上传中' : '上传文件'}
                          </span>
                        </Button>
                      </span>
                    </label>
                    <Button variant="outline" size="sm" className="h-7 gap-1.5 text-xs" onClick={onOpenRightSidebar}>
                      <Database className="size-3.5" />
                      查看全部
                    </Button>
                  </div>
                )}
              >
                <StageInputList evidenceItems={evidenceItems} />
              </StageWorkbenchPanel>

              <StageWorkbenchPanel
                title="执行过程"
                icon={<Sparkles className="size-4" />}
                helpText="展示当前阶段调用了哪些能力、运行到了哪一步，以及每个工具调用的状态。"
              >
                <div className="space-y-3">
                  {hasSkills ? <SkillStrip skills={stage.skills ?? []} /> : (
                    <div className="rounded-md border border-dashed border-border p-3 text-sm text-muted-foreground">
                      当前阶段还没有返回能力配置。
                    </div>
                  )}
                  <ExecutionTimeline
                    runStatus={runStatus}
                    toolCalls={toolCalls}
                    onConfirmOutput={onConfirmExecutionOutput}
                  />
                </div>
              </StageWorkbenchPanel>

              <StageWorkbenchPanel
                title="阶段输出"
                icon={<FileText className="size-4" />}
                helpText="这里显示本阶段直接产出的结构化结果，应该让用户一眼看懂结论、问题和待确认项。"
              >
                <StageResultPanel
                  stage={stage}
                  evidenceItems={evidenceItems}
                  onStartRun={() => onStartRun?.(stage.objective ?? stage.nextStep ?? `${stage.name} 运行分析`)}
                />
              </StageWorkbenchPanel>

              {!isLocked && (
                <StageWorkbenchPanel
                  title="阶段闭环"
                  icon={<ArrowRight className="size-4" />}
                  helpText="确认门禁通过后锁定阶段结果，锁定后下游阶段才能消费本阶段结论。"
                >
                  <StageExitCard stage={stage} onLockStage={onLockStage} />
                </StageWorkbenchPanel>
              )}

              {hasVersion && (
                <StageWorkbenchPanel
                  title="阶段版本"
                  icon={<ClipboardList className="size-4" />}
                  helpText="记录当前阶段产物的版本快照，便于回看每次修正后的差异。"
                >
                  <StageVersionPanel stage={stage} />
                </StageWorkbenchPanel>
              )}

              {hasReport && (
                <StageWorkbenchPanel
                  title="报告产物"
                  icon={<FileText className="size-4" />}
                  helpText="这里放最终导出的报告文件或预览入口，属于可交付产物。"
                >
                  <StageReportPanel stage={stage} onPreviewReport={onPreviewReport} />
                </StageWorkbenchPanel>
              )}
            </div>
        </div>
      </ScrollArea>
        </>
      )}

    </div>
  )
}

function StageSnapshotItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border/70 bg-muted/35 px-3 py-2">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="mt-0.5 truncate font-medium text-foreground">{value}</div>
    </div>
  )
}

function StageWorkbenchSummary({
  stage,
  statusLabel,
  inputCount,
  completedToolCount,
  toolCount,
  suggestionCount,
  hasResult,
  isStageOne,
  runStatus,
  onStartRun,
  onCreateConversation,
}: {
  stage: Stage
  statusLabel: string
  inputCount: number
  completedToolCount: number
  toolCount: number
  suggestionCount: number
  hasResult: boolean
  isStageOne: boolean
  runStatus?: RunStatus
  onStartRun?: (goal: string) => Promise<void> | void
  onCreateConversation?: () => Promise<void> | void
}) {
  const isRunning = runStatus === 'running' || runStatus === 'queued'
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex flex-col gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <Target className="size-3.5" />
            阶段工作台
          </div>
          <h3 className="mt-1 text-base font-semibold text-foreground">{stage.name}</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            {stage.objective ?? '查看阶段输入、执行过程和阶段输出；需要修正时通过会话生成待确认建议。'}
          </p>
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-3 md:grid-cols-5">
          <StageSnapshotItem label="状态" value={statusLabel} />
          <StageSnapshotItem label="输入" value={`${inputCount} 项`} />
          <StageSnapshotItem label="执行" value={`${completedToolCount}/${toolCount}`} />
          <StageSnapshotItem label="待确认" value={`${suggestionCount} 条`} />
          <StageSnapshotItem label="输出" value={hasResult ? '已生成' : '未生成'} />
        </div>
      </div>
      {(isStageOne || onCreateConversation) && (
        <div className="mt-3 flex flex-wrap justify-end gap-2">
          {isStageOne && (
            <Button
              size="sm"
              className="h-8 gap-1.5"
              disabled={stage.status === 'locked' || isRunning}
              onClick={() => void onStartRun?.('基于已上传材料运行 scenario_risk_skill，生成阶段一场景解构与风险定级产物。')}
            >
              <Sparkles className="size-3.5" />
              运行第一阶段
            </Button>
          )}
          {onCreateConversation && (
          <Button size="sm" variant="outline" className="h-8 gap-1.5" onClick={() => void onCreateConversation()}>
            <Plus className="size-3.5" />
            新建会话
          </Button>
          )}
        </div>
      )}
    </div>
  )
}

function StageWorkbenchPanel({
  title,
  icon,
  action,
  badge,
  helpText,
  children,
}: {
  title: string
  icon: ReactNode
  action?: ReactNode
  badge?: string
  helpText?: string
  children: ReactNode
}) {
  return (
    <section className="rounded-lg border border-border bg-card">
      <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
            {icon}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <h3 className="text-sm font-semibold text-foreground">{title}</h3>
            </div>
            {helpText ? (
              <p className="mt-1 max-w-2xl text-xs leading-5 text-muted-foreground">{helpText}</p>
            ) : null}
          </div>
          {badge ? (
            <span className="mt-1 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">{badge}</span>
          ) : null}
        </div>
        {action}
      </div>
      <div className="p-4">{children}</div>
    </section>
  )
}

function StageInputList({ evidenceItems }: { evidenceItems: EvidenceItem[] }) {
  if (evidenceItems.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
        当前阶段还没有绑定输入材料。使用底部“上传材料”，或在右侧资料栏查看全部项目资料。
      </div>
    )
  }

  const visibleItems = evidenceItems.slice(0, 6)
  return (
    <div className="space-y-2">
      {visibleItems.map((item) => (
        <div key={item.id} className="rounded-md border border-border/70 bg-muted/20 px-3 py-2">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="truncate text-sm font-medium text-foreground">{item.name}</div>
              <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                <span>{getEvidenceTypeLabel(item.type)}</span>
                <span>{getEvidenceStatusLabel(item.status)}</span>
                <span>{item.updatedAt}</span>
              </div>
            </div>
            {item.isReferenced ? (
              <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-600">
                <CheckCircle2 className="size-3" />
                已引用
              </span>
            ) : (
              <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">
                <CircleDashed className="size-3" />
                待引用
              </span>
            )}
          </div>
          {item.summaryLines && item.summaryLines.length > 0 ? (
            <div className="mt-2 line-clamp-2 text-xs leading-5 text-muted-foreground">
              {item.summaryLines.slice(0, 2).join(' / ')}
            </div>
          ) : null}
        </div>
      ))}
      {evidenceItems.length > visibleItems.length && (
        <div className="text-xs text-muted-foreground">还有 {evidenceItems.length - visibleItems.length} 项输入，可在右侧资料栏查看。</div>
      )}
    </div>
  )
}

function getEvidenceTypeLabel(type: EvidenceItem['type']) {
  const labels: Record<EvidenceItem['type'], string> = {
    file: '文件',
    record: '记录',
    result: '结果',
    attachment: '附件',
    report: '报告',
  }
  return labels[type]
}

function getEvidenceStatusLabel(status: EvidenceItem['status']) {
  const labels: Record<EvidenceItem['status'], string> = {
    uploaded: '已上传',
    parsed: '已解析',
    referenced: '已引用',
    locked: '已锁定',
    archived: '已归档',
  }
  return labels[status]
}
