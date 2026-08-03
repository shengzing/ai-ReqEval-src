'use client'

import { useMemo, useState } from 'react'
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FileSearch,
  Loader2,
  ShieldCheck,
  Wrench,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { ToolCall } from '@/lib/types'

interface ExecutionTimelineProps {
  toolCalls: ToolCall[]
  runStatus?: string | null
  onConfirmOutput?: (toolCall: ToolCall) => Promise<void> | void
}

export function ExecutionTimeline({ toolCalls, runStatus, onConfirmOutput }: ExecutionTimelineProps) {
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set())
  const [submittingNodeId, setSubmittingNodeId] = useState<string>()
  const [confirmedNodeIds, setConfirmedNodeIds] = useState<Set<string>>(new Set())
  const [errorByNodeId, setErrorByNodeId] = useState<Record<string, string>>({})
  const completedCount = toolCalls.filter((item) => item.status === 'completed').length
  const isActive = runStatus === 'running' || runStatus === 'queued'

  const emptyText = useMemo(() => {
    if (isActive) return '正在建立执行轨迹，调用 Skill、工具和文件读取后会依次显示在这里。'
    return '尚无过程节点。启动阶段执行或发送对话后，这里会保留实际调用的 Skill、工具与文件读取记录。'
  }, [isActive])

  const toggleNode = (nodeId: string) => {
    setExpandedNodes((previous) => {
      const next = new Set(previous)
      if (next.has(nodeId)) next.delete(nodeId)
      else next.add(nodeId)
      return next
    })
  }

  const confirmOutput = async (toolCall: ToolCall) => {
    if (!onConfirmOutput) return
    setSubmittingNodeId(toolCall.id)
    setErrorByNodeId((previous) => {
      const next = { ...previous }
      delete next[toolCall.id]
      return next
    })
    try {
      await onConfirmOutput(toolCall)
      setConfirmedNodeIds((previous) => new Set(previous).add(toolCall.id))
    } catch (error) {
      setErrorByNodeId((previous) => ({
        ...previous,
        [toolCall.id]: error instanceof Error ? error.message : '写入阶段数据失败，请重试。',
      }))
    } finally {
      setSubmittingNodeId(undefined)
    }
  }

  return (
    <section className="rounded-xl border border-border bg-card shadow-xs">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-4 py-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <Wrench className="size-4 text-primary" />
            执行轨迹
          </div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            默认收起；展开节点可查看工具调用、文件读取和返回内容。可写入的结果需经人工确认。
          </p>
        </div>
        <span className="rounded-full bg-primary/10 px-2.5 py-1 text-[11px] font-medium text-primary">
          {completedCount}/{toolCalls.length} 已完成
        </span>
      </div>

      {toolCalls.length === 0 ? (
        <div className="px-4 py-6 text-sm text-muted-foreground">{emptyText}</div>
      ) : (
        <ol className="divide-y divide-border/80 px-4">
          {toolCalls.map((toolCall, index) => {
            const expanded = expandedNodes.has(toolCall.id)
            const isConfirmed = confirmedNodeIds.has(toolCall.id)
            const canConfirm = Boolean(
              toolCall.canConfirm &&
              toolCall.details &&
              Object.keys(toolCall.details).length > 0 &&
              onConfirmOutput &&
              !isConfirmed
            )
            const isSubmitting = submittingNodeId === toolCall.id
            const error = errorByNodeId[toolCall.id]
            return (
              <li key={toolCall.id} className="relative py-3 pl-8">
                {index < toolCalls.length - 1 && <span aria-hidden className="absolute bottom-0 left-[11px] top-8 w-px bg-border" />}
                <span className="absolute left-0 top-4">{statusIcon(toolCall.status)}</span>
                <button
                  type="button"
                  onClick={() => toggleNode(toolCall.id)}
                  aria-expanded={expanded}
                  className="flex w-full items-center gap-2 rounded-md py-0.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {expanded ? <ChevronDown className="size-3.5 text-muted-foreground" /> : <ChevronRight className="size-3.5 text-muted-foreground" />}
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">{toolCall.name}</span>
                  {toolCall.source === 'conversation' && (
                    <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] font-medium text-secondary-foreground">对话上下文</span>
                  )}
                  <span className={cn('text-[11px]', statusTextClass(toolCall.status))}>{statusLabel(toolCall.status)}</span>
                </button>

                {expanded && (
                  <div className="mt-2 space-y-3 rounded-lg border border-border/80 bg-muted/30 p-3">
                    {toolCall.output && (
                      <p className="text-xs leading-5 text-muted-foreground">{toolCall.output}</p>
                    )}
                    {toolCall.evidenceRefs && toolCall.evidenceRefs.length > 0 && (
                      <div className="flex flex-wrap items-center gap-1.5">
                        <FileSearch className="size-3.5 text-primary" />
                        {toolCall.evidenceRefs.map((reference) => (
                          <span key={reference} className="rounded-md bg-background px-2 py-1 font-mono text-[10px] text-muted-foreground ring-1 ring-border/70">
                            {reference}
                          </span>
                        ))}
                      </div>
                    )}
                    {toolCall.details && <ExecutionDetails details={toolCall.details} />}
                    {isConfirmed && (
                      <p className="border-t border-border/70 pt-3 text-xs font-medium text-emerald-700">该结果已写入当前阶段数据。</p>
                    )}
                    {canConfirm && (
                      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/70 pt-3">
                        <p className="text-xs text-muted-foreground">该结果可作为阶段产物候选项；确认后会以可追溯记录写入当前阶段数据。</p>
                        <Button size="sm" className="h-7 gap-1.5 text-xs" disabled={isSubmitting} onClick={() => void confirmOutput(toolCall)}>
                          <ShieldCheck className="size-3.5" />
                          {isSubmitting ? '写入中' : '确认写入阶段'}
                        </Button>
                      </div>
                    )}
                    {error && <p className="text-xs text-destructive">{error}</p>}
                  </div>
                )}
              </li>
            )
          })}
        </ol>
      )}
    </section>
  )
}

function ExecutionDetails({ details }: { details: Record<string, unknown> }) {
  const content = JSON.stringify(details, null, 2)
  return (
    <pre className="max-h-64 overflow-auto rounded-md bg-background p-2.5 font-mono text-[11px] leading-5 text-foreground ring-1 ring-border/70">
      {content}
    </pre>
  )
}

function statusIcon(status: ToolCall['status']) {
  if (status === 'completed') return <CheckCircle2 className="size-5 text-emerald-600" />
  if (status === 'failed') return <AlertCircle className="size-5 text-destructive" />
  return <Loader2 className="size-5 animate-spin text-primary" />
}

function statusLabel(status: ToolCall['status']) {
  if (status === 'completed') return '已完成'
  if (status === 'failed') return '失败'
  return '执行中'
}

function statusTextClass(status: ToolCall['status']) {
  if (status === 'completed') return 'text-emerald-700'
  if (status === 'failed') return 'text-destructive'
  return 'text-primary'
}
