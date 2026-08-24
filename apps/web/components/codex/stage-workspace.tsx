'use client'

import { useId, useRef, useState, type ReactNode } from 'react'
import {
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CircleDashed,
  ClipboardList,
  Database,
  FileText,
  Files,
  Loader2,
  MessageSquare,
  Paperclip,
  Plus,
  RefreshCw,
  RotateCcw,
  ScanSearch,
  ShieldX,
  Sparkles,
  Target,
} from 'lucide-react'

import { ScrollArea } from '@/components/ui/scroll-area'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import type { FileParseStateMap } from '@/lib/file-parse-lifecycle'
import { type Conversation, type EvidenceItem, type ExecutionTraceNode, type Project, type RunStatus, type Stage, type SuggestionCard, type ToolCall } from '@/lib/types'
import { getHiddenStageInputCount, getVisibleStageInputItems } from '@/lib/stage-input-list'
import { isImageEvidence } from './evidence/evidence-types'
import { hasRenderablePayload } from './stage-results/result-utils'
import { ConversationThread } from './stage/conversation-thread'
import { ExecutionTimeline } from './stage/execution-timeline'
import { SkillStrip } from './stage/skill-strip'
import { StageHeader } from './stage/stage-header'
import { StageExitCard } from './stage/stage-exit-card'
import { StageReportPanel } from './stage/stage-report-panel'
import { StageVersionPanel } from './stage/stage-version-panel'
import { getStageRerunAvailability, getStageStatusLabel } from './stage/stage-status'
import { WorkspaceCollapsible } from './stage/workspace-collapsible'
import { StageResultPanel } from './stage-results/stage-result-panel'

interface StageWorkspaceProps {
  project?: Project
  stage: Stage
  conversation?: Conversation
  activeConversationId?: string
  stageConversations?: Conversation[]
  conversationLoading?: boolean
  conversationLoadError?: string | null
  toolCalls: ToolCall[]
  executionTrace: ExecutionTraceNode[]
  suggestionCards: SuggestionCard[]
  evidenceItems?: EvidenceItem[]
  runStatus?: RunStatus
  /** HCR-P1-03：当前 Run 冻结的纳入/排除快照（无 Run / 旧 Run 为 undefined，回退当前派生）。 */
  runEvidenceFilter?: {
    includedEvidenceIds: string[]
    excludedEvidence: Array<{
      id: string
      name: string
      relevanceStatus: EvidenceItem['relevanceStatus']
      relevanceReasons: string[]
    }>
    reason?: string
  }
  onSelectConversation?: (conversationId: string) => void
  onCreateConversation?: () => Promise<void> | void
  onOpenRightSidebar?: () => void
  onStartRun?: (goal: string) => Promise<void> | void
  onSendMessage?: (conversationId: string, content: string) => void
  onConfirmConversationAction?: (conversationId: string, proposalId: string) => Promise<void> | void
  onRejectConversationAction?: (conversationId: string, proposalId: string) => Promise<void> | void
  onUploadFiles?: (files: File[]) => Promise<void> | void
  onParseFile?: (fileId: string) => Promise<void> | void
  onVisionParseFile?: (fileId: string) => Promise<void> | void
  fileParseStates?: FileParseStateMap
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
  project,
  stage,
  conversation,
  activeConversationId,
  conversationLoading,
  conversationLoadError,
  toolCalls,
  executionTrace,
  suggestionCards,
  evidenceItems = [],
  runStatus,
  runEvidenceFilter,
  onCreateConversation,
  onOpenRightSidebar,
  onStartRun,
  onSendMessage,
  onConfirmConversationAction,
  onRejectConversationAction,
  onUploadFiles,
  onParseFile,
  onVisionParseFile,
  fileParseStates = {},
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
  const stageInputCount = evidenceItems.filter((item) => item.relevanceStatus === 'related').length
  const completedToolCount = toolCalls.filter((tool) => tool.status === 'completed').length

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <StageHeader project={project} stage={stage} runStatus={runStatus} />

      {isConversationMode ? (
        <div className="flex min-h-0 flex-1 flex-col">
          {/* 固定阶段信息卡片 */}
          <div className="border-b border-border bg-card/60 px-6 py-2">
            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5">
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
              <div className="flex flex-wrap items-center justify-end gap-2">
                {stageSuggestions.length > 0 && (
                  <span className="rounded-full bg-amber-100 px-2.5 py-1 text-xs text-amber-700">
                    待确认 {stageSuggestions.length} 条
                  </span>
                )}
                <StageActionButtons
                  stage={stage}
                  runStatus={runStatus}
                  relatedEvidenceCount={stageInputCount}
                  onStartRun={onStartRun}
                  onOpenRightSidebar={onOpenRightSidebar}
                  onCreateConversation={onCreateConversation}
                />
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
            executionTrace={executionTrace}
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
                runStatus={runStatus}
                onStartRun={onStartRun}
                onCreateConversation={onCreateConversation}
                onOpenRightSidebar={onOpenRightSidebar}
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
                <StageInputList
                  evidenceItems={evidenceItems}
                  runEvidenceFilter={runEvidenceFilter}
                  onParseFile={onParseFile}
                  onVisionParseFile={onVisionParseFile}
                  fileParseStates={fileParseStates}
                />
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
                    traceNodes={executionTrace}
                    onConfirmOutput={onConfirmExecutionOutput}
                    currentRunId={currentRunId}
                    onResumeRun={onResumeRun}
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
                  onStartRun={
                    getStageRerunAvailability(stage.id, runStatus, stageInputCount).disabled
                      ? undefined
                      : () => onStartRun?.(stage.objective ?? stage.nextStep ?? `${stage.name} 运行分析`)
                  }
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
  runStatus,
  onStartRun,
  onCreateConversation,
  onOpenRightSidebar,
}: {
  stage: Stage
  statusLabel: string
  inputCount: number
  completedToolCount: number
  toolCount: number
  suggestionCount: number
  hasResult: boolean
  runStatus?: RunStatus
  onStartRun?: (goal: string) => Promise<void> | void
  onCreateConversation?: () => Promise<void> | void
  onOpenRightSidebar?: () => void
}) {
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
      {(onStartRun || onOpenRightSidebar || onCreateConversation) && (
        <div className="mt-3 flex flex-wrap justify-end gap-2">
          <StageActionButtons
            stage={stage}
            runStatus={runStatus}
            relatedEvidenceCount={inputCount}
            onStartRun={onStartRun}
            onOpenRightSidebar={onOpenRightSidebar}
            onCreateConversation={onCreateConversation}
          />
        </div>
      )}
    </div>
  )
}

function StageActionButtons({
  stage,
  runStatus,
  relatedEvidenceCount,
  onStartRun,
  onOpenRightSidebar,
  onCreateConversation,
}: {
  stage: Stage
  runStatus?: RunStatus
  relatedEvidenceCount: number
  onStartRun?: (goal: string) => Promise<void> | void
  onOpenRightSidebar?: () => void
  onCreateConversation?: () => Promise<void> | void
}) {
  const [startingRun, setStartingRun] = useState(false)
  const startingRunRef = useRef(false)
  const rerunAvailability = getStageRerunAvailability(stage.id, runStatus, relatedEvidenceCount)

  const startRun = async () => {
    if (!onStartRun || startingRunRef.current || rerunAvailability.disabled) return
    startingRunRef.current = true
    setStartingRun(true)
    try {
      await onStartRun(stage.objective ?? stage.nextStep ?? `${stage.name} 重新运行`)
    } finally {
      startingRunRef.current = false
      setStartingRun(false)
    }
  }

  return (
    <>
      {stage.status !== 'locked' && onStartRun && (
        <Button
          size="sm"
          className="h-8 gap-1.5"
          disabled={startingRun || rerunAvailability.disabled}
          title={rerunAvailability.reason}
          onClick={() => void startRun()}
        >
          <RotateCcw className="size-3.5" />
          {startingRun ? '启动中' : '重新运行'}
        </Button>
      )}
      {onOpenRightSidebar && (
        <Button size="sm" variant="outline" className="h-8 gap-1.5" onClick={onOpenRightSidebar}>
          <Database className="size-3.5" />
          查看证据
        </Button>
      )}
      {onCreateConversation && (
        <Button size="sm" variant="outline" className="h-8 gap-1.5" onClick={() => void onCreateConversation()}>
          <Plus className="size-3.5" />
          新建会话
        </Button>
      )}
    </>
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

function StageInputList({
  evidenceItems,
  runEvidenceFilter,
  onParseFile,
  onVisionParseFile,
  fileParseStates,
}: {
  evidenceItems: EvidenceItem[]
  runEvidenceFilter?: {
    includedEvidenceIds: string[]
    excludedEvidence: Array<{
      id: string
      name: string
      relevanceStatus: EvidenceItem['relevanceStatus']
      relevanceReasons: string[]
    }>
    reason?: string
  }
  onParseFile?: (fileId: string) => Promise<void> | void
  onVisionParseFile?: (fileId: string) => Promise<void> | void
  fileParseStates: FileParseStateMap
}) {
  const [showAllItems, setShowAllItems] = useState(false)
  // HCR-P1-03：有 run-scoped 快照时渲染该 Run 冻结的纳入/排除列表，
  // 否则回退到从当前 evidenceItems 派生（兼容无 Run / 旧 Run）。
  const hasRunFilter = Boolean(runEvidenceFilter)

  if (hasRunFilter && runEvidenceFilter) {
    const includedCount = runEvidenceFilter.includedEvidenceIds.length
    const excludedCount = runEvidenceFilter.excludedEvidence.length
    if (includedCount === 0 && excludedCount === 0) {
      return (
        <div className="space-y-2">
          <p className="text-xs font-medium text-foreground">本次运行纳入/排除材料</p>
          <div className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
            本次运行未记录证据过滤快照。
          </div>
        </div>
      )
    }
    return (
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span className="font-medium text-foreground">本次运行纳入/排除材料</span>
          <span>纳入 {includedCount}</span>
          <span>排除 {excludedCount}</span>
        </div>
        {runEvidenceFilter.reason && (
          <p className="text-[11px] leading-5 text-muted-foreground">{runEvidenceFilter.reason}</p>
        )}
        {includedCount === 0 && (
          <div className="rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs leading-5 text-amber-700">
            本次运行没有已确认相关的证据，阶段执行进入等待材料状态。
          </div>
        )}
        {runEvidenceFilter.excludedEvidence.slice(0, 6).map((item) => (
          <div key={item.id} className="rounded-md border border-border/70 bg-muted/20 px-3 py-2">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-foreground">{item.name || item.id}</div>
                {item.relevanceReasons.length > 0 && (
                  <div className="mt-1 space-y-0.5">
                    {item.relevanceReasons.slice(0, 2).map((reason) => (
                      <p key={reason} className="text-[11px] leading-5 text-muted-foreground">{reason}</p>
                    ))}
                  </div>
                )}
              </div>
              <RunScopedDisposition status={item.relevanceStatus} />
            </div>
          </div>
        ))}
        {excludedCount > 6 && (
          <div className="text-xs text-muted-foreground">还有 {excludedCount - 6} 项被排除，可在右侧资料栏查看。</div>
        )}
      </div>
    )
  }

  if (evidenceItems.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
        当前阶段还没有绑定输入材料。使用底部“上传材料”，或在右侧资料栏查看全部项目资料。
      </div>
    )
  }

  const includedCount = evidenceItems.filter((item) => item.relevanceStatus === 'related').length
  const pendingParseCount = evidenceItems.filter((item) => item.relevanceStatus === 'pending_parse').length
  const reviewCount = evidenceItems.filter((item) => item.relevanceStatus === 'needs_review').length
  const excludedCount = evidenceItems.filter((item) => item.relevanceStatus === 'unrelated' || item.relevanceStatus === 'rejected').length
  const hiddenItemCount = getHiddenStageInputCount(evidenceItems.length)
  const visibleItems = getVisibleStageInputItems(evidenceItems, showAllItems)
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">当前阶段绑定材料</span>
        <span>纳入 {includedCount}</span>
        <span>待解析 {pendingParseCount}</span>
        <span>待复核 {reviewCount}</span>
        <span>排除 {excludedCount}</span>
      </div>
      {includedCount === 0 && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/5 px-2.5 py-1.5 text-xs leading-5 text-amber-700">
          当前没有已解析且确认相关的证据，阶段执行会进入等待材料状态。
        </div>
      )}
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {visibleItems.map((item) => (
          <StageInputCard
            key={item.id}
            item={item}
            onParseFile={onParseFile}
            onVisionParseFile={onVisionParseFile}
            parseState={item.sourceFileId ? fileParseStates[item.sourceFileId] : undefined}
          />
        ))}
      </div>
      {hiddenItemCount > 0 && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-7 w-full gap-1.5 text-xs text-muted-foreground"
          onClick={() => setShowAllItems((previous) => !previous)}
          aria-expanded={showAllItems}
        >
          {showAllItems ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
          {showAllItems ? '收起其他材料' : `展开其余 ${hiddenItemCount} 项材料`}
        </Button>
      )}
    </div>
  )
}

function StageInputCard({
  item,
  onParseFile,
  onVisionParseFile,
  parseState,
}: {
  item: EvidenceItem
  onParseFile?: (fileId: string) => Promise<void> | void
  onVisionParseFile?: (fileId: string) => Promise<void> | void
  parseState?: FileParseStateMap[string]
}) {
  const [visionParsing, setVisionParsing] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string>()
  const imageEvidence = isImageEvidence(item)
  const canParse = Boolean(
    item.type === 'file'
    && item.sourceFileId
    && (imageEvidence ? onVisionParseFile : onParseFile),
  )
  const parseLabel = imageEvidence ? '重新视觉解析' : '重新解析'
  const parsing = imageEvidence ? visionParsing : parseState?.status === 'parsing'

  const handleParse = async () => {
    if (!item.sourceFileId || parsing || !canParse) return
    setErrorMessage(undefined)
    if (!imageEvidence) {
      await onParseFile?.(item.sourceFileId)
      return
    }
    setVisionParsing(true)
    try {
      await onVisionParseFile?.(item.sourceFileId)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : `${parseLabel}失败，请重试。`)
    } finally {
      setVisionParsing(false)
    }
  }

  return (
    <div className="flex min-h-[64px] flex-col justify-between rounded-md border border-border/70 bg-muted/20 px-2 py-1.5">
      <div className="min-w-0">
        <div className="flex items-start justify-between gap-1.5">
          <div className="min-w-0 flex-1">
            <div className="truncate text-xs font-medium text-foreground" title={item.name}>
              {item.name}
            </div>
            <div className="mt-0.5 flex flex-wrap items-center gap-1 text-[10px] text-muted-foreground">
              <span>{getEvidenceTypeLabel(item.type)}</span>
              <span>{getEvidenceStatusLabel(item.status)}</span>
              <span>{item.updatedAt}</span>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-0.5">
            {canParse && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    className="size-5"
                    disabled={parsing}
                    onClick={() => void handleParse()}
                    aria-label={`${parseLabel} ${item.name}`}
                  >
                    {parsing
                      ? <Loader2 className="size-2.5 animate-spin" />
                      : imageEvidence
                        ? <ScanSearch className="size-2.5" />
                        : <RefreshCw className="size-2.5" />}
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="top" sideOffset={6}>{parsing ? '解析中' : parseLabel}</TooltipContent>
              </Tooltip>
            )}
            <EvidenceRelevanceDisposition item={item} compact />
          </div>
        </div>
        {item.summaryLines && item.summaryLines.length > 0 ? (
          <div className="mt-0.5 line-clamp-1 text-[11px] leading-4 text-muted-foreground">
            {item.summaryLines[0]}
          </div>
        ) : null}
        {!imageEvidence && parseState && (
          <div
            className={parseState.status === 'error' ? 'mt-0.5 text-[11px] text-destructive' : parseState.status === 'success' ? 'mt-0.5 text-[11px] text-emerald-600' : 'mt-0.5 text-[11px] text-primary'}
            aria-live="polite"
          >
            {parseState.message}
          </div>
        )}
        {errorMessage && (
          <div className="mt-0.5 flex items-center justify-between gap-1 rounded border border-destructive/30 bg-destructive/10 px-1 py-0.5 text-[11px] text-destructive">
            <span className="truncate">{errorMessage}</span>
            <button
              type="button"
              className="shrink-0 rounded px-1 underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              onClick={() => setErrorMessage(undefined)}
            >
              关闭
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

function RunScopedDisposition({ status }: { status: EvidenceItem['relevanceStatus'] }) {
  if (status === 'related') {
    return (
      <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-600">
        <CheckCircle2 className="size-3" />
        纳入执行
      </span>
    )
  }
  return (
    <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-destructive/10 px-2 py-0.5 text-[10px] text-destructive">
      <ShieldX className="size-3" />
      排除
    </span>
  )
}

function EvidenceRelevanceDisposition({ item, compact }: { item: EvidenceItem; compact?: boolean }) {
  const sizeClass = compact ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-0.5 text-[10px]'
  if (item.relevanceStatus === 'related') {
    return (
      <span className={cn('inline-flex shrink-0 items-center gap-1 rounded-md bg-emerald-500/10 font-medium text-emerald-600', sizeClass)}>
        <CheckCircle2 className="size-3" />
        纳入执行
      </span>
    )
  }
  if (item.relevanceStatus === 'unrelated' || item.relevanceStatus === 'rejected') {
    return (
      <span className={cn('inline-flex shrink-0 items-center gap-1 rounded-md bg-destructive/10 text-destructive', sizeClass)}>
        <ShieldX className="size-3" />
        排除
      </span>
    )
  }
  return (
    <span className={cn('inline-flex shrink-0 items-center gap-1 rounded-md bg-amber-500/10 text-amber-700', sizeClass)}>
      <CircleDashed className="size-3" />
      {item.relevanceStatus === 'needs_review' ? '待复核' : '待解析'}
    </span>
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
