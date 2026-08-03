'use client'

import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, MessageSquare, MousePointerClick } from 'lucide-react'

import { cn } from '@/lib/utils'
import { MarkdownRenderer } from '@/lib/markdown-renderer'
import { Button } from '@/components/ui/button'
import type { Conversation, ConversationActionProposal, ConversationMessage } from '@/lib/types'
import { ConversationComposer } from './conversation-composer'

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
}: ConversationThreadProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [conversation?.messages?.length])

  if (!conversation) {
    if (loadError) {
      return (
        <div
          className="flex items-start gap-2 rounded-lg border border-amber-300/60 bg-amber-50 p-3 text-sm text-amber-700"
          role="status"
        >
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <div className="space-y-0.5">
            <div className="font-medium">当前会话加载失败</div>
            <div className="text-xs text-amber-700/80">{loadError}</div>
            <div className="text-xs text-amber-700/80">
              阶段结果、建议卡和证据栏仍可继续使用；点击左侧其他会话或稍后重试。
            </div>
          </div>
        </div>
      )
    }
    if (loading) {
      return (
        <div className="rounded-lg border border-dashed border-border p-5 text-sm text-muted-foreground">
          正在加载当前会话详情...
        </div>
      )
    }
    // Stage has conversations but none selected — show clickable entries
    if (stageConversations && stageConversations.length > 0 && onSelectConversation) {
      return (
        <div className="rounded-lg border border-dashed border-border p-4">
          <div className="mb-3 flex items-center gap-2 text-sm text-muted-foreground">
            <MousePointerClick className="size-4" />
            <span>当前未选中会话，该阶段已有 {stageConversations.length} 个会话：</span>
          </div>
          <ul className="space-y-1.5">
            {stageConversations.slice(0, 5).map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm text-foreground/80 transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={() => onSelectConversation(c.id)}
                >
                  <MessageSquare className="size-3.5 shrink-0 text-muted-foreground" />
                  <span className="truncate">{c.title}</span>
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
      <div className="rounded-lg border border-dashed border-border p-5 text-sm text-muted-foreground">
        当前未选中具体会话。可以从左侧阶段下选择一个会话,或在下方输入目标启动新的阶段内会话。
      </div>
    )
  }

  const messages = conversation.messages ?? []
  const isWaitingUser = runStatus === 'waiting_user' || runStatus === 'waiting_human'
  const canResume = isWaitingUser && Boolean(currentRunId && onResumeRun)

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
      <div className="flex-1 space-y-4 overflow-y-auto px-1 py-2">
        {messages.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-5 text-sm text-muted-foreground">
            会话已创建,在下方输入消息开始对话。
          </div>
        ) : (
          messages.map((message) => (
            <MessageBubble
              key={message.id}
              message={message}
              conversationId={conversation.id}
              onConfirmActionProposal={onConfirmActionProposal}
              onRejectActionProposal={onRejectActionProposal}
            />
          ))
        )}
        {sending && (
          <div className="flex gap-3 text-sm text-muted-foreground">
            <Avatar role="assistant" />
            <div className="flex items-center gap-1.5 rounded-lg bg-muted/40 px-3 py-2 text-xs">
              <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground/60" />
              <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground/60 [animation-delay:150ms]" />
              <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground/60 [animation-delay:300ms]" />
            </div>
          </div>
        )}
        {canResume && (
          <div className="flex items-center justify-end gap-2 rounded-lg border border-amber-300/60 bg-amber-50 px-3 py-2 text-sm text-amber-700">
            <span className="mr-auto">阶段任务 Run 已暂停等待人工确认，请选择是否继续。</span>
            <Button size="sm" variant="outline" onClick={handleReject} disabled={sending}>
              拒绝并停止
            </Button>
            <Button size="sm" onClick={handleApprove} disabled={sending}>
              确认并继续
            </Button>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Composer */}
      <ConversationComposer
        disabled={!onSendMessage}
        sending={sending}
        placeholder={isWaitingUser ? '等待人工确认中…输入回复以继续运行' : DEFAULT_PLACEHOLDER}
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
      className={cn(
        'flex size-7 shrink-0 items-center justify-center rounded-full text-xs font-medium',
        role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-emerald-500/10 text-emerald-600'
      )}
    >
      {role === 'user' ? 'U' : 'A'}
    </div>
  )
}

function MessageBubble({
  message,
  conversationId,
  onConfirmActionProposal,
  onRejectActionProposal,
}: {
  message: ConversationMessage
  conversationId: string
  onConfirmActionProposal?: (conversationId: string, proposalId: string) => Promise<void> | void
  onRejectActionProposal?: (conversationId: string, proposalId: string) => Promise<void> | void
}) {
  const isUser = message.role === 'user'
  return (
    <div className={cn('flex gap-3', isUser && 'flex-row-reverse')}>
      <Avatar role={message.role} />
      <div className={cn('flex-1 space-y-2', isUser && 'flex flex-col items-end')}>
        <div
          className={cn(
            'max-w-[85%] rounded-lg text-sm',
            isUser ? 'bg-primary text-primary-foreground p-3' : 'bg-muted/40 p-3'
          )}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap break-words">{message.content}</p>
          ) : (
            <MarkdownRenderer content={message.content} />
          )}
        </div>
        {message.harnessWarnings?.map((warning, index) => (
          <div key={`${message.id}-warning-${index}`} className="max-w-[85%] rounded-md border border-amber-300/60 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            {typeof warning.message === 'string' ? warning.message : '对话助手已使用降级模式。'}
          </div>
        ))}
        {message.actionProposals && message.actionProposals.length > 0 && (
          <div className="space-y-2">
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
    <div className="rounded-lg border border-amber-300/60 bg-amber-50/60 p-3 text-sm">
      <div className="flex items-center gap-1.5 text-xs font-medium text-amber-700">
        <span className="rounded bg-amber-200/60 px-1.5 py-0.5 text-[10px] uppercase tracking-wide">
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
          状态：{proposal.status === 'accepted' ? '已启动' : proposal.status === 'rejected' ? '已拒绝' : '处理中'}
        </p>
      )}
      {(onConfirm || onReject) && (
        <div className="mt-3 flex gap-2">
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
