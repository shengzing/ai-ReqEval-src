'use client'

import { useEffect, useMemo, useState } from 'react'
import { AlertCircle, Bot, CheckCircle2, ChevronDown, ChevronRight, FileSearch, GitBranch, Loader2, ShieldCheck, Sparkles, Workflow, Wrench } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { isActionableNode } from '@/lib/execution-trace-filter'
import { cn } from '@/lib/utils'
import type { ExecutionTraceKind, ExecutionTraceNode, ToolCall } from '@/lib/types'

interface ExecutionTimelineProps {
  toolCalls: ToolCall[]
  /** Semantically classified Run events. Tool calls are only those with an invocation_id. */
  traceNodes?: ExecutionTraceNode[]
  runStatus?: string | null
  onConfirmOutput?: (toolCall: ToolCall) => Promise<void> | void
  /** Run-level id, required for inline HITL resume buttons on waiting_user nodes. */
  currentRunId?: string
  /** Resume a paused run with human input ({approved: true|false}). */
  onResumeRun?: (runId: string, humanInput?: Record<string, unknown>) => Promise<void> | void
}

interface SkillTraceGroup {
  name: string
  status: ExecutionTraceNode['status']
  nodes: ExecutionTraceNode[]
}

export function ExecutionTimeline({ toolCalls, traceNodes = [], runStatus, onConfirmOutput, currentRunId, onResumeRun }: ExecutionTimelineProps) {
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set())
  const [expandedSkills, setExpandedSkills] = useState<Set<string>>(new Set())
  const [submittingNodeId, setSubmittingNodeId] = useState<string>()
  const [confirmedNodeIds, setConfirmedNodeIds] = useState<Set<string>>(new Set())
  const [errorByNodeId, setErrorByNodeId] = useState<Record<string, string>>({})
  const [showAllAuditNodes, setShowAllAuditNodes] = useState(false)
  const [resumingHitl, setResumingHitl] = useState(false)
  const [hitlError, setHitlError] = useState<string>()
  const isActive = runStatus === 'running' || runStatus === 'queued'

  const { standaloneNodes, skillGroups, auditNodeCount, actualToolCount, completedToolCount, subagentCount, completedSubagentCount } = useMemo(() => {
    const traceInvocationIds = new Set(
      traceNodes.flatMap((node) => node.toolCall ? [node.toolCall.id] : []),
    )
    const fallbackToolNodes: ExecutionTraceNode[] = toolCalls
      .filter((toolCall) => !traceInvocationIds.has(toolCall.id))
      .map((toolCall) => ({
          id: `tool-${toolCall.id}`,
          kind: 'tool' as const,
          name: toolCall.name,
          status: toolCall.status,
          summary: toolCall.output,
          details: toolCall.details,
          evidenceRefs: toolCall.evidenceRefs,
          skillName: undefined,
          toolCall,
        }))
    const sourceNodes: ExecutionTraceNode[] = [...traceNodes, ...fallbackToolNodes]
    // 审计兜底：showAllAuditNodes 开启时绕过过滤还原全量；默认仅展示有具体操作的节点，
    // 隐藏纯状态流转（created/queued/running/resumed/completed、纯 routing 如 run.step）。
    // Run 事件在后端全量持久化，前端不渲染 ≠ 证据丢失。
    const auditNodeCount = sourceNodes.length
    const visibleSource = showAllAuditNodes ? sourceNodes : sourceNodes.filter(isActionableNode)
    const groups = new Map<string, SkillTraceGroup>()
    const standalone: ExecutionTraceNode[] = []
    const seenInvocations = new Set<string>()

    for (const node of visibleSource) {
      const skillName = node.skillName
      if (skillName) {
        const group = groups.get(skillName) ?? { name: skillName, status: 'completed', nodes: [] }
        if (node.status === 'failed') group.status = 'failed'
        else if (node.status === 'running' && group.status !== 'failed') group.status = 'running'
        else if (node.status === 'skipped' && group.status === 'completed') group.status = 'skipped'
        // The skill event becomes the collapsible group header. Its child
        // events remain the auditable planning/tool/decision trail.
        if (node.kind !== 'skill') group.nodes.push(node)
        groups.set(skillName, group)
      } else {
        standalone.push(node)
      }
      if (node.kind === 'tool' && node.toolCall && !seenInvocations.has(node.toolCall.id)) {
        seenInvocations.add(node.toolCall.id)
      }
    }
    const visibleTools = visibleSource.filter((node) => node.kind === 'tool' && node.toolCall)
    return {
      standaloneNodes: standalone,
      skillGroups: [...groups.values()],
      auditNodeCount,
      actualToolCount: seenInvocations.size,
      completedToolCount: visibleTools.filter((node) => node.toolCall?.status === 'completed').length,
      subagentCount: visibleSource.filter((node) => node.kind === 'subagent').length,
      completedSubagentCount: visibleSource.filter((node) => node.kind === 'subagent' && node.status === 'completed').length,
    }
  }, [toolCalls, traceNodes, showAllAuditNodes])

  const displayedNodeCount = standaloneNodes.length + skillGroups.reduce((count, group) => count + group.nodes.length + 1, 0)
  const hiddenCount = Math.max(0, auditNodeCount - displayedNodeCount)
  const emptyText = useMemo(() => {
    if (isActive) return '正在建立执行轨迹…'
    return '尚无过程节点。启动阶段执行或发送对话后，真实执行轨迹会显示在这里。'
  }, [isActive])

  // HITL 节点（run.waiting_user）自动展开，让确认按钮一键直达，免二次点击。
  // 幂等并入：用户手动收起后若 run 仍处暂停态，节点会随依赖变化再次并入。
  useEffect(() => {
    const hitlIds = [
      ...standaloneNodes,
      ...skillGroups.flatMap((group) => group.nodes),
    ]
      .filter((node) => Boolean(node.humanCheckpoint))
      .map((node) => node.id)
    if (hitlIds.length === 0) return
    setExpandedNodes((previous) => {
      let changed = false
      const next = new Set(previous)
      for (const id of hitlIds) {
        if (!next.has(id)) {
          next.add(id)
          changed = true
        }
      }
      return changed ? next : previous
    })
  }, [standaloneNodes, skillGroups])

  const toggleNode = (nodeId: string) => {
    setExpandedNodes((previous) => {
      const next = new Set(previous)
      if (next.has(nodeId)) next.delete(nodeId)
      else next.add(nodeId)
      return next
    })
  }
  const toggleSkill = (skillName: string) => {
    setExpandedSkills((previous) => {
      const next = new Set(previous)
      if (next.has(skillName)) next.delete(skillName)
      else next.add(skillName)
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

  // Inline HITL resume: surface approve/reject on the waiting_user node itself
  // so the confirmation content and action live together, instead of forcing the
  // user down to the conversation footer. Mirrors conversation-thread's
  // handleApprove/handleReject, sharing the same resumeRun backend path.
  const resumeHitl = async (approved: boolean) => {
    if (!currentRunId || !onResumeRun) return
    setResumingHitl(true)
    setHitlError(undefined)
    try {
      await onResumeRun(currentRunId, { approved })
    } catch (error) {
      setHitlError(error instanceof Error ? error.message : '恢复运行失败，请重试。')
    } finally {
      setResumingHitl(false)
    }
  }

  return (
    <section className="overflow-hidden rounded-xl border border-border/80 bg-card shadow-xs">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/70 px-3.5 py-2.5 sm:px-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium text-foreground">
            <Wrench className="size-4 text-primary" />
            执行过程
          </div>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {displayedNodeCount
              ? `展示 ${displayedNodeCount} 个执行节点${hiddenCount > 0 ? ` · 隐藏 ${hiddenCount} 个纯状态节点` : ''}；工具调用仅计入具备 invocation_id 的节点。`
              : emptyText}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2 text-[11px] font-medium tabular-nums">
          {isActive && <span className="flex items-center gap-1 text-primary"><Loader2 className="size-3 animate-spin" />运行中</span>}
          <span className="rounded-full bg-primary/10 px-2.5 py-1 text-primary">工具 {completedToolCount}/{actualToolCount}</span>
          {subagentCount > 0 && <span className="rounded-full bg-secondary px-2.5 py-1 text-secondary-foreground">子代理 {completedSubagentCount}/{subagentCount}</span>}
          {hiddenCount > 0 && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 gap-1 px-2 text-[11px] font-medium"
              onClick={() => setShowAllAuditNodes((previous) => !previous)}
            >
              {showAllAuditNodes ? '仅显示操作节点' : '显示全部审计节点'}
            </Button>
          )}
        </div>
      </div>

      {displayedNodeCount === 0 ? (
        <div className="px-3.5 py-5 text-xs text-muted-foreground sm:px-4">{emptyText}</div>
      ) : (
        <ol className="relative space-y-0 px-3.5 py-3 sm:px-4">
          {/* 时间线主轴 */}
          <div className="absolute left-6 top-0 h-full w-px bg-border/70 sm:left-7" aria-hidden="true" />
          {standaloneNodes.map((node, index) => (
            <TraceNodeRow
              key={node.id}
              node={node}
              index={index}
              expanded={expandedNodes.has(node.id)}
              onToggle={() => toggleNode(node.id)}
              onConfirmOutput={confirmOutput}
              submittingNodeId={submittingNodeId}
              confirmedNodeIds={confirmedNodeIds}
              errorByNodeId={errorByNodeId}
              currentRunId={currentRunId}
              onResumeRun={onResumeRun ? resumeHitl : undefined}
              resumingHitl={resumingHitl}
              hitlError={hitlError}
            />
          ))}
          {skillGroups.map((group) => {
            const expanded = expandedSkills.has(group.name)
            const toolCount = group.nodes.filter((node) => node.kind === 'tool' && node.toolCall).length
            const subagentCount = group.nodes.filter((node) => node.kind === 'subagent').length
            return (
              <li key={group.name} className="relative pl-6 sm:pl-7">
                {/* 节点圆点 */}
                <div className="absolute -left-[5px] top-3 size-2.5 rounded-full border-2 border-background bg-primary" aria-hidden="true" />
                <button
                  type="button"
                  onClick={() => toggleSkill(group.name)}
                  aria-expanded={expanded}
                  className="flex w-full items-center gap-2 rounded-md px-1 py-1 text-left transition-colors hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {expanded ? <ChevronDown className="size-3.5 text-muted-foreground" /> : <ChevronRight className="size-3.5 text-muted-foreground" />}
                  <Sparkles className="size-4 text-primary" />
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">{group.name}</span>
                  <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] font-medium text-secondary-foreground">Skill</span>
                  <span className="text-[10px] text-muted-foreground">
                    {toolCount} 个工具{subagentCount > 0 ? ` · ${subagentCount} 个子代理` : ''}
                  </span>
                  <span className={cn('text-[11px]', statusTextClass(group.status))}>{statusLabel(group.status)}</span>
                </button>
                {expanded && (
                  <ol className="ml-2 mt-1 space-y-0 border-l border-border/70 pl-2">
                    {group.nodes.length === 0 ? (
                      <li className="py-2 text-xs text-muted-foreground">该 Skill 未产生额外执行节点。</li>
                    ) : group.nodes.map((node, index) => (
                      <TraceNodeRow
                        key={node.id}
                        node={node}
                        index={index}
                        nested
                        expanded={expandedNodes.has(node.id)}
                        onToggle={() => toggleNode(node.id)}
                        onConfirmOutput={confirmOutput}
                        submittingNodeId={submittingNodeId}
                        confirmedNodeIds={confirmedNodeIds}
                        errorByNodeId={errorByNodeId}
                        currentRunId={currentRunId}
                        onResumeRun={onResumeRun ? resumeHitl : undefined}
                        resumingHitl={resumingHitl}
                        hitlError={hitlError}
                      />
                    ))}
                  </ol>
                )}
              </li>
            )
          })}
        </ol>
      )}
    </section>
  )
}

function TraceNodeRow({
  node,
  index,
  nested = false,
  expanded,
  onToggle,
  onConfirmOutput,
  submittingNodeId,
  confirmedNodeIds,
  errorByNodeId,
  currentRunId,
  onResumeRun,
  resumingHitl,
  hitlError,
}: {
  node: ExecutionTraceNode
  index: number
  nested?: boolean
  expanded: boolean
  onToggle: () => void
  onConfirmOutput: (toolCall: ToolCall) => Promise<void>
  submittingNodeId?: string
  confirmedNodeIds: Set<string>
  errorByNodeId: Record<string, string>
  currentRunId?: string
  onResumeRun?: (approved: boolean) => Promise<void>
  resumingHitl?: boolean
  hitlError?: string
}) {
  const toolCall = node.toolCall
  const checkpoint = node.humanCheckpoint
  const canResume = Boolean(checkpoint && currentRunId && onResumeRun)
  const hasDetails = Boolean(node.summary || node.details || node.evidenceRefs?.length || toolCall?.canConfirm || canResume)
  const isConfirmed = Boolean(toolCall && confirmedNodeIds.has(toolCall.id))
  const canConfirm = Boolean(
    toolCall?.canConfirm && toolCall.details && Object.keys(toolCall.details).length > 0 && !isConfirmed
  )
  const isSubmitting = toolCall?.id === submittingNodeId
  const error = toolCall ? errorByNodeId[toolCall.id] : undefined
  return (
    <li className={cn('relative', nested ? 'pl-4' : 'pl-6 sm:pl-7')}>
      {/* 节点圆点 - 只在非嵌套时显示 */}
      {!nested && (
        <div
          className={cn(
            'absolute -left-[5px] top-3 size-2.5 rounded-full border-2 border-background',
            node.status === 'failed' ? 'bg-destructive' :
            node.status === 'running' ? 'bg-primary animate-pulse' :
            node.status === 'skipped' ? 'bg-amber-500' : 'bg-emerald-600'
          )}
          aria-hidden="true"
        />
      )}
      <div className="flex items-start gap-2">
        <span className="mt-0.5">{traceIcon(node.kind, node.status)}</span>
        <div className="min-w-0 flex-1">
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={expanded}
            disabled={!hasDetails}
            className={cn(
              'flex w-full items-center gap-2 rounded-md py-0.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              hasDetails && 'transition-colors hover:text-primary',
              !hasDetails && 'cursor-default'
            )}
          >
            <span className="font-mono text-[10px] tabular-nums text-muted-foreground/70">{String(index + 1).padStart(2, '0')}</span>
            <span className="min-w-0 flex-1 truncate text-sm text-foreground">{node.name}</span>
            <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{traceKindLabel(node.kind)}</span>
            {toolCall?.source === 'conversation' && <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] text-secondary-foreground">对话上下文</span>}
            <span className={cn('text-[11px]', statusTextClass(node.status))}>{statusLabel(node.status)}</span>
            {hasDetails && (expanded ? <ChevronDown className="size-3.5 text-muted-foreground" /> : <ChevronRight className="size-3.5 text-muted-foreground" />)}
          </button>
          {expanded && hasDetails && (
            <div className="mt-2 space-y-3 rounded-lg border border-border/70 bg-muted/25 p-3">
              {node.summary && <p className="text-xs leading-5 text-muted-foreground">{node.summary}</p>}
              {node.evidenceRefs && node.evidenceRefs.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5">
                  <FileSearch className="size-3.5 text-primary" />
                  {node.evidenceRefs.map((reference) => <span key={reference} className="rounded-md bg-background px-2 py-1 font-mono text-[10px] text-muted-foreground ring-1 ring-border/70">{reference}</span>)}
                </div>
              )}
              {node.details && <ExecutionDetails details={node.details} />}
              {isConfirmed && <p className="border-t border-border/70 pt-3 text-xs font-medium text-emerald-700">该结果已写入当前阶段数据。</p>}
              {canConfirm && (
                <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/70 pt-3">
                  <p className="text-xs text-muted-foreground">该工具结果可作为阶段产物候选项；确认后会以可追溯记录写入当前阶段数据。</p>
                  <Button size="sm" className="h-7 gap-1.5 text-xs" disabled={isSubmitting} onClick={() => toolCall && void onConfirmOutput(toolCall)}>
                    <ShieldCheck className="size-3.5" />{isSubmitting ? '写入中' : '确认写入阶段'}
                  </Button>
                </div>
              )}
              {canResume && checkpoint && (
                <div className="space-y-2 border-t border-border/70 pt-3">
                  {checkpoint.decision && (
                    <div className="space-y-0.5 text-[11px] text-muted-foreground">
                      {checkpoint.decision.requires_human != null && (
                        <p>需要人工复核：{checkpoint.decision.requires_human ? '是' : '否'}</p>
                      )}
                      {checkpoint.decision.should_continue != null && (
                        <p>建议继续执行：{checkpoint.decision.should_continue ? '是' : '否'}</p>
                      )}
                      {typeof checkpoint.decision.summary === 'string' && checkpoint.decision.summary && (
                        <p className="whitespace-pre-wrap break-words">决策说明：{checkpoint.decision.summary}</p>
                      )}
                      {checkpoint.stageResultId && (
                        <p>关联阶段结果：{checkpoint.stageResultId}</p>
                      )}
                    </div>
                  )}
                  <p className="text-xs text-muted-foreground">确认后将继续执行该阶段任务；拒绝将终止当前运行。</p>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button size="sm" className="h-7 text-xs" disabled={resumingHitl} onClick={() => void onResumeRun?.(true)}>
                      {resumingHitl ? '处理中' : '确认并继续'}
                    </Button>
                    <Button variant="outline" size="sm" className="h-7 text-xs" disabled={resumingHitl} onClick={() => void onResumeRun?.(false)}>
                      拒绝并停止
                    </Button>
                  </div>
                  {hitlError && <p className="text-xs text-destructive">{hitlError}</p>}
                </div>
              )}
              {error && <p className="text-xs text-destructive">{error}</p>}
            </div>
          )}
        </div>
      </div>
    </li>
  )
}

function ExecutionDetails({ details }: { details: Record<string, unknown> }) {
  return <pre className="max-h-64 overflow-auto rounded-md bg-background p-2.5 font-mono text-[11px] leading-5 text-foreground ring-1 ring-border/70">{JSON.stringify(details, null, 2)}</pre>
}

function traceIcon(kind: ExecutionTraceKind, status: ExecutionTraceNode['status']) {
  if (status === 'failed') return <AlertCircle className="size-4 text-destructive" />
  if (status === 'running') return <Loader2 className="size-4 animate-spin text-primary" />
  if (kind === 'routing') return <GitBranch className="size-4 text-muted-foreground" />
  if (kind === 'validation') return <ShieldCheck className="size-4 text-amber-600" />
  if (kind === 'tool') return <Wrench className="size-4 text-primary" />
  if (kind === 'subagent') return <Bot className="size-4 text-secondary-foreground" />
  if (kind === 'decision') return <Workflow className="size-4 text-primary" />
  return <CheckCircle2 className="size-4 text-emerald-600" />
}

function traceKindLabel(kind: ExecutionTraceKind) {
  const labels: Record<ExecutionTraceKind, string> = {
    routing: '路由', skill: 'Skill', tool: '工具', subagent: '子代理', validation: '校验', decision: '决策', state: '状态',
  }
  return labels[kind]
}

function statusLabel(status: ExecutionTraceNode['status']) {
  if (status === 'completed') return '已完成'
  if (status === 'failed') return '失败'
  if (status === 'skipped') return '已跳过'
  return '执行中'
}

function statusTextClass(status: ExecutionTraceNode['status']) {
  if (status === 'completed') return 'text-emerald-700'
  if (status === 'failed') return 'text-destructive'
  if (status === 'skipped') return 'text-amber-700'
  return 'text-primary'
}
