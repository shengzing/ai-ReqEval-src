'use client'

import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, MessageSquare, MousePointerClick } from 'lucide-react'

import { cn } from '@/lib/utils'
import { MarkdownRenderer } from '@/lib/markdown-renderer'
import { Button } from '@/components/ui/button'
import type { Conversation, ConversationActionProposal, ConversationMessage, ExecutionTraceNode, ToolCall } from '@/lib/types'
import { ConversationComposer } from './conversation-composer'
import { ExecutionTimeline } from './execution-timeline'

interface ConversationThreadProps {
  conversation?: Conversation
  stageConversations?: Conversation[]
  loading?: boolean
  loadError?: string | null
  runStatus?: string | null
  onSelectConversation?: (conversationId: string) => void
  onSendMessage?: (conversationId: string, content: string) => void
  onResumeRun?: (runId: string, humanInput?: Record<string, unknown>) => Promise<void> | void
  currentRunId?: string
  onConfirmActionProposal?: (conversationId: string, proposalId: string) => Promise<void> | void
  onRejectActionProposal?: (conversationId: string, proposalId: string) => Promise<void> | void
  sending?: boolean
  /** 底部 composer 的上传文件回调（传入则显示上传按钮） */
  onUploadFiles?: (files: File[]) => void
  /** 底部 composer 的生成报告回调（传入则显示报告按钮） */
  onGenerateReport?: () => void
  executionToolCalls?: ToolCall[]
  executionTrace?: ExecutionTraceNode[]
  onConfirmExecutionOutput?: (toolCall: ToolCall) => Promise<void> | void
}

export function ConversationThread({
  conversation,
  stageConversations,
  loading,
  loadError,
  runStatus,
  onSelectConversation,
  onSendMessage,
  onResumeRun,
  currentRunId,
  onConfirmActionProposal,
  onRejectActionProposal,
  sending,
  onUploadFiles,
  onGenerateReport,
  executionToolCalls = [],
  executionTrace = [],
  onConfirmExecutionOutput,
}: ConversationThreadProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom when new messages arrive.
  // data-chat-anchor CSS rule supplies scroll-margin-bottom so the bottom
  // message isn't clipped by the sticky composer.
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [conversation?.messages?.length])

  if (!conversation) {
    if (loadError) {
      return (
        <div
          className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm text-warning-foreground"
          role="status"
          aria-live="polite"
        >
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <div className="space-y-0.5">
            <div className="font-medium">当前会话加载失败</div>
            <div className="text-xs opacity-90">{loadError}</div>
            <div className="text-xs opacity-90">
              阶段结果、建议卡和证据栏仍可继续使用；点击左侧其他会话或稍后重试。
            </div>
          </div>
        </div>
      )
    }
    if (loading) {
      return (
        <div
          className="rounded-lg border border-dashed border-border p-5 text-sm text-muted-foreground"
          role="status"
          aria-live="polite"
        >
          正在加载当前会话详情...
        </div>
      )
    }
    // Stage has conversations but none selected — show clickable entries
    if (stageConversations && stageConversations.length > 0 && onSelectConversation) {
      return (
        <div className="rounded-lg border border-dashed border-border p-4">
          <div className="mb-3 flex items-center gap-2 text-sm text-muted-foreground">
            <MousePointerClick className="size-4" aria-hidden="true" />
            <span>当前未选中会话，该阶段已有 {stageConversations.length} 个会话：</span>
          </div>
          <ul className="space-y-1.5">
            {stageConversations.slice(0, 5).map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  className="flex w-full min-w-0 items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm text-foreground/80 transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={() => onSelectConversation(c.id)}
                >
                  <MessageSquare className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                  <span className="min-w-0 flex-1 truncate">{c.title}</span>
                  <span className="ml-auto shrink-0 text-xs text-muted-foreground">{c.timeAgo}</span>
                </button>
              </li>
            ))}
          </ul>
          {stageConversations.length > 5 && (
            <p className="mt-2 text-xs text-muted-foreground">
              还有 {stageConversations.length - 5} 个会话，可在左侧阶段节点下展开查看。
            </p>
          )}
        </div>
      )
    }
    return (
      <div className="flex min-h-[200px] items-center justify-center rounded-lg border border-dashed border-border p-5 text-center text-sm text-muted-foreground">
        当前未选中具体会话。可以从左侧阶段下选择一个会话,或在下方输入目标启动新的阶段内会话。
      </div>
    )
  }

  const messages = conversation.messages ?? []
  const isWaitingUser = runStatus === 'waiting_user' || runStatus === 'waiting_human'
  const isRunActive = runStatus === 'running' || runStatus === 'queued'
  const canResume = isWaitingUser && Boolean(currentRunId && onResumeRun)
  // Historical conversations store tool calls on individual process messages;
  // surface them once as one chronological, expandable run trace.
  const messageToolCalls = messages.flatMap((message) => message.toolCalls ?? [])
  const visibleExecutionToolCalls = deduplicateToolCalls([...messageToolCalls, ...executionToolCalls])
    .map((toolCall, index) => ({ ...toolCall, id: `${toolCall.id}-${index}` }))
  const showLiveExecutionTimeline = visibleExecutionToolCalls.length > 0
    || runStatus === 'running' || runStatus === 'queued'
    || runStatus === 'waiting_user' || runStatus === 'waiting_inputs'
  // 按钮触发的阶段 Run 无用户气泡：执行过程置于对话流最前（上方），完成后
  // 由 assistant 消息承接结果；有历史消息时仍将时间线置顶，避免把历史
  // 对话顶到执行块下方造成错位。

  const handleApprove = () => {
    if (!currentRunId) return
    void onResumeRun?.(currentRunId, { approved: true })
  }
  const handleReject = () => {
    if (!currentRunId) return
    void onResumeRun?.(currentRunId, { approved: false })
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Message list */}
      <div className="min-h-0 flex-1 overflow-y-auto py-4 sm:py-5" aria-busy={Boolean(sending)}>
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-3 sm:px-5 lg:px-8">
          {showLiveExecutionTimeline && (
            <ExecutionTimeline
              runStatus={runStatus}
              toolCalls={visibleExecutionToolCalls}
              traceNodes={executionTrace}
              onConfirmOutput={onConfirmExecutionOutput}
              currentRunId={currentRunId}
              onResumeRun={onResumeRun}
            />
          )}
          {messages.length === 0 && !showLiveExecutionTimeline ? (
            <div className="rounded-xl border border-dashed border-border bg-muted/20 px-4 py-5 text-sm text-muted-foreground">
              会话已创建,在下方输入消息开始对话。
            </div>
          ) : (
            messages.map((message, index) => (
              <div key={message.id} className="contents">
                <MessageBubble
                  message={message}
                  conversationId={conversation.id}
                  onConfirmActionProposal={onConfirmActionProposal}
                  onRejectActionProposal={onRejectActionProposal}
                  onConfirmExecutionOutput={onConfirmExecutionOutput}
                />
              </div>
            ))
          )}
          {sending && (
            <div
              className="flex gap-3 sm:gap-4 text-sm text-muted-foreground"
              role="status"
              aria-live="polite"
              aria-label="对话助手正在思考"
            >
              <Avatar role="assistant" />
              <div className="flex items-center gap-1.5 rounded-2xl rounded-tl-md border border-border/70 bg-muted/35 px-3 py-2 text-xs shadow-xs">
                <span className="motion-safe:animate-pulse size-1.5 rounded-full bg-muted-foreground/60" />
                <span className="motion-safe:animate-pulse size-1.5 rounded-full bg-muted-foreground/60 [animation-delay:150ms]" />
                <span className="motion-safe:animate-pulse size-1.5 rounded-full bg-muted-foreground/60 [animation-delay:300ms]" />
              </div>
            </div>
          )}
          {canResume && (
            <div className="flex flex-wrap items-center justify-end gap-2 rounded-xl border border-warning/40 bg-warning/10 px-3 py-2.5 text-sm text-warning-foreground">
              <span className="mr-auto">阶段任务 Run 已暂停等待人工确认，请选择是否继续。</span>
              {/* Affirmative action on the right (WCAG F-shape reading order) */}
              <Button size="sm" variant="outline" onClick={handleReject} disabled={sending}>
                拒绝并停止
              </Button>
              <Button size="sm" onClick={handleApprove} disabled={sending}>
                确认并继续
              </Button>
            </div>
          )}
          <div ref={messagesEndRef} data-chat-anchor />
        </div>
      </div>

      {/* Composer */}
      <ConversationComposer
        disabled={!onSendMessage || isRunActive}
        sending={sending}
        placeholder={isWaitingUser ? '等待人工确认中…输入回复以继续运行' : isRunActive ? '阶段执行中…' : DEFAULT_PLACEHOLDER}
        onSend={(content) => onSendMessage?.(conversation.id, content)}
        onUploadFiles={onUploadFiles}
        onGenerateReport={onGenerateReport}
      />
    </div>
  )
}

const DEFAULT_PLACEHOLDER = '输入消息与阶段对话助手交流…'

function Avatar({ role }: { role: 'user' | 'assistant' }) {
  return (
    <div
      aria-label={role === 'user' ? '用户头像' : '助手头像'}
      className={cn(
        'flex size-7 shrink-0 items-center justify-center rounded-full border text-[10px] font-semibold tracking-tight shadow-xs',
        role === 'user'
          ? 'border-primary bg-primary text-primary-foreground'
          : 'border-border bg-card text-foreground/70'
      )}
    >
      {role === 'user' ? '我' : 'AI'}
    </div>
  )
}

function deduplicateToolCalls(toolCalls: ToolCall[]) {
  const seen = new Set<string>()
  return toolCalls.filter((toolCall) => {
    const signature = JSON.stringify([
      toolCall.name,
      toolCall.status,
      toolCall.output,
      toolCall.details,
      toolCall.evidenceRefs,
      toolCall.source,
    ])
    if (seen.has(signature)) return false
    seen.add(signature)
    return true
  })
}

function MessageBubble({
  message,
  conversationId,
  onConfirmActionProposal,
  onRejectActionProposal,
  onConfirmExecutionOutput,
}: {
  message: ConversationMessage
  conversationId: string
  onConfirmActionProposal?: (conversationId: string, proposalId: string) => Promise<void> | void
  onRejectActionProposal?: (conversationId: string, proposalId: string) => Promise<void> | void
  onConfirmExecutionOutput?: (toolCall: ToolCall) => Promise<void> | void
}) {
  const isUser = message.role === 'user'
  if (message.processOnly && message.toolCalls?.length) {
    return null
  }
  return (
    <div className={cn('flex w-full gap-3 sm:gap-4', isUser && 'flex-row-reverse')}>
      <Avatar role={message.role} />
      <div className={cn('flex min-w-0 flex-1', isUser ? 'justify-end' : 'justify-start')}>
        <div className={cn('w-full min-w-0 max-w-3xl space-y-2', isUser && 'flex flex-col items-end')}>
          <div
            className={cn(
              'min-w-0 max-w-full text-sm break-words',
              isUser
                ? 'w-fit rounded-2xl rounded-br-md bg-primary px-3.5 py-2.5 text-primary-foreground shadow-xs'
                : 'w-fit rounded-2xl rounded-tl-md border border-border/70 bg-muted/35 px-3.5 py-3 shadow-xs'
            )}
          >
            {isUser ? (
              <p className="whitespace-pre-wrap break-words">{message.content}</p>
            ) : (
              // MarkdownRenderer is responsible for its own overflow handling
              <div className="overflow-wrap-anywhere">
                <MarkdownRenderer content={message.content} />
              </div>
            )}
          </div>
          {message.harnessWarnings?.map((warning, index) => (
            <div
              key={`${message.id}-warning-${index}`}
              className="w-full max-w-full rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning-foreground"
            >
              {typeof warning.message === 'string' ? warning.message : '对话助手已使用降级模式。'}
            </div>
          ))}
          {message.citations && message.citations.length > 0 && (
            <p className="w-full max-w-full text-xs text-muted-foreground">
              已引用 {message.citations.length} 条当前阶段上下文。
            </p>
          )}
          {message.actionProposals && message.actionProposals.length > 0 && (
            <div className="w-full space-y-2">
              {message.actionProposals.map((proposal) => (
                <ActionProposalCard
                  key={proposal.id}
                  proposal={proposal}
                  onConfirm={proposal.status === 'pending' ? () => onConfirmActionProposal?.(conversationId, proposal.id) : undefined}
                  onReject={proposal.status === 'pending' ? () => onRejectActionProposal?.(conversationId, proposal.id) : undefined}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function ActionProposalCard({
  proposal,
  onConfirm,
  onReject,
}: {
  proposal: ConversationActionProposal
  onConfirm?: () => Promise<void> | void
  onReject?: () => Promise<void> | void
}) {
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string>()

  const submit = async (action?: () => Promise<void> | void) => {
    if (!action) return
    setSubmitting(true)
    setError(undefined)
    try {
      await action()
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : '操作失败，请重试。')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm">
      <div className="flex items-center gap-1.5 text-xs font-medium text-warning-foreground">
        <span className="rounded bg-warning/20 px-1.5 py-0.5 text-[10px] uppercase tracking-wide">
          待确认
        </span>
        <span>{proposal.title}</span>
      </div>
      <p className="mt-1.5 text-xs text-muted-foreground">
        类型: {proposal.actionType}
        {proposal.requiresConfirmation ? ' · 需确认后执行' : ' · 可自动执行'}
      </p>
      {proposal.status && proposal.status !== 'pending' && (
        <p className="mt-1.5 text-xs text-muted-foreground">
          状态：{proposal.status === 'accepted'
            ? (proposal.confirmationId ? '已创建待人工确认项' : '已启动')
            : proposal.status === 'rejected' ? '已拒绝' : '处理中'}
        </p>
      )}
      {(onConfirm || onReject) && (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" className="h-7 text-xs" disabled={submitting} onClick={() => void submit(onConfirm)}>
            {submitting ? '处理中' : '确认并启动'}
          </Button>
          <Button variant="ghost" size="sm" className="h-7 text-xs" disabled={submitting} onClick={() => void submit(onReject)}>
            拒绝
          </Button>
        </div>
      )}
      {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
    </div>
  )
}
