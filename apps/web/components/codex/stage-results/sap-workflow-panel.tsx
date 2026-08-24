'use client'

import { useState, type ReactNode } from 'react'
import {
  AlertTriangle,
  ArrowDown,
  CheckCircle2,
  CircleDot,
  FileText,
  Flag,
  GitBranch,
  Play,
  RotateCcw,
  ShieldCheck,
  UserRound,
  UsersRound,
} from 'lucide-react'

import { asRecord, formatValue, PanelTitle } from './result-renderers'

type SAPWorkflowPanelProps = {
  sopSummary: unknown
  participants: unknown[]
  processNodes: unknown[]
  responsibilities: unknown[]
  hitlRules: unknown[]
  riskLevel: string
  hitlLevel: string
  edges?: unknown[]
  mainPath?: unknown[]
}

type SAPEdge = {
  from: string
  to: string
  label: string
  variant: 'main' | 'branch' | 'return'
}

type SAPParticipant = {
  role: string
  responsibility: string
}

type SAPResponsibility = {
  nodeId: string
  role: string
  responsibility: string
  handoffTo: string[]
}

type SAPHitlRule = {
  nodeId: string
  riskLevel: string
  reviewLevel: string
  trigger: string
  owner: string
  evidence: string[]
}

type SAPNode = {
  id: string
  title: string
  ownerRole: string
  inputItems: string[]
  outputItems: string[]
  systemRefs: string[]
  auditFields: string[]
  evidenceRefs: string[]
  humanReviewRequired: boolean | undefined
  responsibilities: SAPResponsibility[]
  hitlRules: SAPHitlRule[]
}

type SAPFlowStep =
  | { id: 'sap-start'; kind: 'start'; title: string; subtitle: string }
  | { id: string; kind: 'process'; title: string; subtitle: string; node: SAPNode; index: number }
  | { id: 'sap-decision'; kind: 'decision'; title: string; subtitle: string }
  | { id: 'sap-end'; kind: 'end'; title: string; subtitle: string }

function cleanText(value: unknown): string {
  const text = formatValue(value).trim()
  return text === '-' ? '' : text
}

function firstText(record: Record<string, unknown> | undefined, keys: string[]): string {
  if (!record) return ''
  for (const key of keys) {
    const text = cleanText(record[key])
    if (text) return text
  }
  return ''
}

function toTextList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => cleanText(item)).filter(Boolean)
  }
  const text = cleanText(value)
  return text ? [text] : []
}

function uniqueTexts(values: string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))]
}

function normalizeParticipants(participants: unknown[]): SAPParticipant[] {
  return participants
    .map((participant, index) => {
      const record = asRecord(participant)
      if (!record) {
        return { role: cleanText(participant) || `角色 ${index + 1}`, responsibility: '' }
      }
      return {
        role: firstText(record, ['role', 'name', 'title']) || `角色 ${index + 1}`,
        responsibility: firstText(record, ['responsibility', 'description', 'duty']),
      }
    })
    .filter((participant) => participant.role)
}

function normalizeResponsibilities(responsibilities: unknown[]): SAPResponsibility[] {
  return responsibilities
    .map((item) => {
      const record = asRecord(item)
      if (!record) return undefined
      return {
        nodeId: firstText(record, ['node_id', 'nodeId', 'process_node_id']),
        role: firstText(record, ['role', 'owner_role', 'owner']),
        responsibility: firstText(record, ['responsibility', 'description', 'duty']),
        handoffTo: uniqueTexts(toTextList(record.handoff_to ?? record.handoffTo)),
      }
    })
    .filter((item): item is SAPResponsibility => Boolean(item))
}

function normalizeHitlRules(hitlRules: unknown[]): SAPHitlRule[] {
  return hitlRules
    .map((rule) => {
      const record = asRecord(rule)
      if (!record) return undefined
      return {
        nodeId: firstText(record, ['node_id', 'nodeId', 'process_node_id']),
        riskLevel: firstText(record, ['risk_level', 'riskLevel']),
        reviewLevel: firstText(record, ['review_level', 'reviewLevel', 'hitl_level']),
        trigger: firstText(record, ['review_trigger', 'reviewTrigger', 'trigger', 'condition']),
        owner: firstText(record, ['review_owner', 'reviewOwner', 'owner_role', 'owner']),
        evidence: uniqueTexts(toTextList(record.review_evidence ?? record.evidence_refs ?? record.evidenceRefs)),
      }
    })
    .filter((rule): rule is SAPHitlRule => Boolean(rule))
}

function normalizeNodes({
  processNodes,
  responsibilities,
  hitlRules,
}: {
  processNodes: unknown[]
  responsibilities: SAPResponsibility[]
  hitlRules: SAPHitlRule[]
}): SAPNode[] {
  const sourceNodes = processNodes.length ? processNodes : [{ name: '流程节点未拆分', node_id: 'sap-unmapped' }]

  return sourceNodes.map((node, index) => {
    const record = asRecord(node)
    const id = firstText(record, ['node_id', 'nodeId', 'id']) || `sap-node-${index + 1}`
    const title = record ? firstText(record, ['name', 'title', 'node', 'label']) : cleanText(node)
    const ownerRole = firstText(record, ['owner_role', 'ownerRole', 'owner', 'role'])
    const nodeResponsibilities = responsibilities.filter((item) => item.nodeId === id)
    const roleFallbackResponsibilities = nodeResponsibilities.length
      ? []
      : responsibilities.filter((item) => ownerRole && item.role === ownerRole && !item.nodeId)
    const nodeHitlRules = hitlRules.filter((rule) => rule.nodeId === id)

    return {
      id,
      title: title || `流程节点 ${index + 1}`,
      ownerRole,
      inputItems: uniqueTexts(toTextList(record?.input ?? record?.inputs)),
      outputItems: uniqueTexts(toTextList(record?.output ?? record?.outputs)),
      systemRefs: uniqueTexts(toTextList(record?.system_refs ?? record?.systemRefs)),
      auditFields: uniqueTexts(toTextList(record?.audit_fields ?? record?.auditFields)),
      evidenceRefs: uniqueTexts(toTextList(record?.evidence_refs ?? record?.evidenceRefs)),
      humanReviewRequired: typeof record?.human_review_required === 'boolean' ? record.human_review_required : undefined,
      responsibilities: [...nodeResponsibilities, ...roleFallbackResponsibilities],
      hitlRules: nodeHitlRules,
    }
  })
}

function hasMeaningfulSAPData(processNodes: unknown[], participants: unknown[], responsibilities: unknown[], hitlRules: unknown[], sopSummary: unknown) {
  return Boolean(processNodes.length || participants.length || responsibilities.length || hitlRules.length || cleanText(sopSummary))
}

function needsHumanGate(hitlLevel: string, rules: SAPHitlRule[]) {
  return Boolean(rules.length || (hitlLevel && hitlLevel !== 'none'))
}

function nodeStatus(node: SAPNode, hitlLevel: string) {
  if (node.hitlRules.length || node.humanReviewRequired) return 'HITL'
  if (hitlLevel && hitlLevel !== 'none') return '待判定'
  return '自动'
}

function edgeLabelBetween(index: number, total: number) {
  if (index === 0) return '启动流程'
  if (index === total - 2) return '提交门禁'
  return '完成当前节点'
}

function normalizeEdges(edges: unknown[], knownIds: Set<string>): SAPEdge[] {
  if (!Array.isArray(edges) || !edges.length) return []
  const result: SAPEdge[] = []
  for (const edge of edges) {
    const record = asRecord(edge)
    if (!record) continue
    const from = cleanText(record.from)
    const to = cleanText(record.to)
    if (!from || !to) continue
    if (!knownIds.has(from) || !knownIds.has(to)) continue
    const rawVariant = cleanText(record.variant) || 'main'
    const variant: SAPEdge['variant'] =
      rawVariant === 'return' ? 'return' : rawVariant === 'branch' ? 'branch' : 'main'
    result.push({ from, to, label: cleanText(record.label), variant })
  }
  return result
}

function buildSteps(
  nodes: SAPNode[],
  hitlLevel: string,
  hitlRules: SAPHitlRule[],
  edges: SAPEdge[],
  mainPath: string[],
): { steps: SAPFlowStep[]; returnEdges: SAPEdge[] } {
  const gateEnabled = needsHumanGate(hitlLevel, hitlRules)
  const start: SAPFlowStep = { id: 'sap-start', kind: 'start', title: '起点', subtitle: '接收 SOP 输入' }
  const decision: SAPFlowStep = {
    id: 'sap-decision',
    kind: 'decision',
    title: gateEnabled ? 'HITL 门禁判断' : '完成条件判断',
    subtitle: gateEnabled ? '人工确认 / 风险放行' : '输出是否达标',
  }
  const end: SAPFlowStep = { id: 'sap-end', kind: 'end', title: '终点', subtitle: '锁定阶段产物' }

  const nodeById = new Map(nodes.map((node, index) => [node.id, { node, index }]))

  // Edge-driven path: derive the main path node sequence from mainPath (or
  // all node order when mainPath is missing), collecting return edges
  // separately so they render as configurable loop bars instead of steps.
  if (edges.length) {
    const orderedIds = (
      Array.isArray(mainPath) && mainPath.length >= 2
        ? mainPath.map((id) => cleanText(id)).filter(Boolean)
        : nodes.map((node) => node.id)
    )
    const seen = new Set<string>()
    const processSteps: SAPFlowStep[] = []
    for (const id of orderedIds) {
      if (!id || seen.has(id) || !nodeById.has(id)) continue
      seen.add(id)
      const { node, index } = nodeById.get(id)!
      processSteps.push({
        id: node.id,
        kind: 'process',
        title: node.title,
        subtitle: node.ownerRole || '未绑定角色',
        node,
        index,
      })
    }
    const returnEdges = edges.filter((edge) => edge.variant === 'return')
    return { steps: [start, ...processSteps, decision, end], returnEdges }
  }

  // Fallback: linear buildSteps over all nodes (backward compatible with
  // summaries that only carried process_nodes).
  const linearSteps: SAPFlowStep[] = [
    start,
    ...nodes.map((node, index) => ({
      id: node.id,
      kind: 'process' as const,
      title: node.title,
      subtitle: node.ownerRole || '未绑定角色',
      node,
      index,
    })),
    decision,
    end,
  ]
  return { steps: linearSteps, returnEdges: [] }
}

function listPreview(items: string[], fallback: string) {
  if (!items.length) return <span className="text-muted-foreground">{fallback}</span>
  return items.slice(0, 3).join(' / ') + (items.length > 3 ? ` / +${items.length - 3}` : '')
}

function DetailRow({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <div className="rounded-md border border-border/70 bg-background p-3">
      <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold text-muted-foreground">
        {icon}
        {label}
      </div>
      <div className="text-xs leading-5 text-foreground">{children}</div>
    </div>
  )
}

function SAPMetric({ label, value, tone = 'default' }: { label: string; value: string; tone?: 'default' | 'warn' | 'ok' }) {
  const toneClass =
    tone === 'warn'
      ? 'border-amber-400/40 bg-amber-500/10 text-amber-700 dark:text-amber-200'
      : tone === 'ok'
        ? 'border-emerald-400/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200'
        : 'border-border bg-background/70 text-foreground'
  return (
    <div className={`rounded-md border px-3 py-2 ${toneClass}`}>
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-sm font-semibold">{value}</p>
    </div>
  )
}

function FlowConnector({ label, dashed }: { label: string; dashed?: boolean }) {
  return (
    <div className="flex h-10 w-40 shrink-0 flex-col items-center justify-center">
      <span className="mb-1 max-w-40 truncate rounded-sm bg-background px-1.5 py-0.5 text-[10px] text-muted-foreground ring-1 ring-border/70">
        {label}
      </span>
      <div className="flex h-full flex-col items-center text-muted-foreground">
        <span className={`w-px flex-1 ${dashed ? 'border-l border-dashed border-slate-300 dark:border-slate-600' : 'bg-slate-300 dark:bg-slate-600'}`} />
        <ArrowDown className="size-4 shrink-0" />
      </div>
    </div>
  )
}

function SAPFlowNode({
  step,
  selected,
  onSelect,
  hitlLevel,
}: {
  step: SAPFlowStep
  selected: boolean
  onSelect: () => void
  hitlLevel: string
}) {
  const isDecision = step.kind === 'decision'
  const isTerminal = step.kind === 'start' || step.kind === 'end'
  const tone =
    step.kind === 'decision'
      ? 'border-amber-400/70 bg-amber-50/90 text-amber-950 dark:bg-amber-950/20 dark:text-amber-100'
      : step.kind === 'start'
        ? 'border-emerald-400/70 bg-emerald-50/90 text-emerald-950 dark:bg-emerald-950/20 dark:text-emerald-100'
        : step.kind === 'end'
          ? 'border-sky-400/70 bg-sky-50/90 text-sky-950 dark:bg-sky-950/20 dark:text-sky-100'
          : step.node.hitlRules.length || step.node.humanReviewRequired
            ? 'border-rose-400/70 bg-rose-50/90 text-rose-950 dark:bg-rose-950/20 dark:text-rose-100'
            : 'border-cyan-500/60 bg-cyan-50/80 text-cyan-950 dark:bg-cyan-950/20 dark:text-cyan-100'
  const shape = isDecision ? 'h-24 w-24 rotate-45' : isTerminal ? 'h-20 w-28 rounded-full' : 'h-20 w-36 rounded-md'
  const contentShape = isDecision ? '-rotate-45' : ''
  const icon =
    step.kind === 'start' ? <Play className="size-3.5" />
      : step.kind === 'end' ? <Flag className="size-3.5" />
        : step.kind === 'decision' ? <GitBranch className="size-3.5" />
          : <CircleDot className="size-3.5" />

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      aria-label={`${step.title}详情`}
      className={`relative flex shrink-0 items-center justify-center border p-3 text-center shadow-sm transition hover:-translate-y-0.5 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${shape} ${tone} ${selected ? 'ring-2 ring-primary/60' : ''}`}
    >
      <div className={`min-w-0 ${contentShape}`}>
        <div className="mx-auto mb-1 flex items-center justify-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          {icon}
          {step.kind === 'process' ? `N${String(step.index + 1).padStart(2, '0')}` : step.kind}
        </div>
        <p className="max-h-10 overflow-hidden break-words text-xs font-semibold leading-5 text-foreground">{step.title}</p>
        <p className="mt-1 max-h-8 overflow-hidden break-words text-[10px] leading-4 text-muted-foreground">{step.subtitle}</p>
        {step.kind === 'process' ? (
          <span className="mt-1 inline-flex rounded-sm bg-background/80 px-1.5 py-0.5 text-[10px] text-muted-foreground ring-1 ring-border/70">
            {nodeStatus(step.node, hitlLevel)}
          </span>
        ) : null}
      </div>
    </button>
  )
}

function FlowDetailPanel({
  step,
  participants,
  unboundHitlRules,
  riskLevel,
  hitlLevel,
  passLabel,
  rejectLabel,
  loopTarget,
  returnEdges,
  nodesById,
}: {
  step: SAPFlowStep
  participants: SAPParticipant[]
  unboundHitlRules: SAPHitlRule[]
  riskLevel: string
  hitlLevel: string
  passLabel: string
  rejectLabel: string
  loopTarget: SAPNode
  returnEdges: SAPEdge[]
  nodesById: Map<string, SAPNode>
}) {
  if (step.kind === 'start') {
    return (
      <SAPDetailShell title="起点详情" subtitle="SAP 输入和角色池">
        <DetailRow icon={<FileText className="size-3.5" />} label="输入">
          SOP 摘要、参与角色、流程节点、责任分配、HITL 规则。
        </DetailRow>
        <DetailRow icon={<UsersRound className="size-3.5" />} label="参与角色">
          {participants.length ? participants.map((item) => item.role).join(' / ') : '未识别参与角色'}
        </DetailRow>
      </SAPDetailShell>
    )
  }

  if (step.kind === 'decision') {
    const loopLines = returnEdges.length
      ? returnEdges.map((edge) => {
          const fromNode = nodesById.get(edge.from)
          const toNode = nodesById.get(edge.to)
          const fromTitle = fromNode?.title ?? edge.from
          const toTitle = toNode?.title ?? edge.to
          return {
            key: `${edge.from}->${edge.to}`,
            label: edge.label || rejectLabel,
            fromTitle,
            toTitle,
          }
        })
      : [{
          key: 'fallback-loop',
          label: rejectLabel,
          fromTitle: loopTarget.title,
          toTitle: loopTarget.title,
        }]
    return (
      <SAPDetailShell title="判断节点详情" subtitle={`${riskLevel || '风险缺失'} / ${hitlLevel || 'none'}`}>
        <DetailRow icon={<CheckCircle2 className="size-3.5" />} label="通过线路">
          {passLabel}，进入终点并锁定阶段产物。
        </DetailRow>
        <DetailRow icon={<RotateCcw className="size-3.5" />} label="循环线路">
          <div className="flex flex-col gap-1">
            {loopLines.map((line) => (
              <span key={line.key}>
                {line.label}，返回 {line.toTitle} 补充责任、证据或人工确认。
              </span>
            ))}
          </div>
        </DetailRow>
        <DetailRow icon={<ShieldCheck className="size-3.5" />} label="未绑定 HITL">
          {unboundHitlRules.length ? `${unboundHitlRules.length} 条 HITL 规则未绑定具体节点` : 'HITL 规则均已绑定或当前无强制 HITL'}
        </DetailRow>
      </SAPDetailShell>
    )
  }

  if (step.kind === 'end') {
    return (
      <SAPDetailShell title="终点详情" subtitle="阶段产物输出">
        <DetailRow icon={<Flag className="size-3.5" />} label="输出">
          锁定后的阶段一产物继续进入风险治理矩阵、价值建模和后续评估。
        </DetailRow>
      </SAPDetailShell>
    )
  }

  const node = step.node
  const responsibilityTexts = node.responsibilities.map((item) => item.responsibility).filter(Boolean)
  const handoffTo = uniqueTexts(node.responsibilities.flatMap((item) => item.handoffTo))

  return (
    <SAPDetailShell title={`N${String(step.index + 1).padStart(2, '0')} ${node.title}`} subtitle={node.ownerRole || '未绑定责任角色'}>
      <div className="grid gap-2 lg:grid-cols-2">
        <DetailRow icon={<UserRound className="size-3.5" />} label="参与角色">
          {node.ownerRole || '未绑定责任角色'}
        </DetailRow>
        <DetailRow icon={<FileText className="size-3.5" />} label="节点内容">
          <div>输入：{listPreview(node.inputItems, '未提供输入')}</div>
          <div>输出：{listPreview(node.outputItems, '未提供输出')}</div>
          {node.systemRefs.length ? <div>系统：{listPreview(node.systemRefs, '无')}</div> : null}
        </DetailRow>
        <DetailRow icon={<GitBranch className="size-3.5" />} label="责任分工">
          {responsibilityTexts.length ? responsibilityTexts.join('；') : '责任未绑定到节点'}
          {handoffTo.length ? `；移交：${handoffTo.join(' / ')}` : ''}
        </DetailRow>
        <DetailRow icon={<ShieldCheck className="size-3.5" />} label="HITL 规则">
          {node.hitlRules.length
            ? node.hitlRules.map((rule) => `${rule.reviewLevel || hitlLevel || '人工复核'} · ${rule.trigger || '触发条件未写明'}${rule.owner ? ` · ${rule.owner}` : ''}`).join('；')
            : node.humanReviewRequired
              ? '节点标记需要人工复核，但未绑定规则详情'
              : hitlLevel && hitlLevel !== 'none'
                ? '全局存在 HITL 要求，但当前节点未绑定规则'
                : '无强制人工介入'}
        </DetailRow>
        <DetailRow icon={<AlertTriangle className="size-3.5" />} label="审计留痕">
          {listPreview([...node.auditFields, ...node.evidenceRefs], '未绑定留痕字段')}
        </DetailRow>
      </div>
    </SAPDetailShell>
  )
}

function SAPDetailShell({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <div className="rounded-md border border-border bg-muted/20 p-3">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-foreground">{title}</p>
          <p className="text-xs text-muted-foreground">{subtitle}</p>
        </div>
      </div>
      <div className="mt-3 grid gap-2">{children}</div>
    </div>
  )
}

export function SAPWorkflowPanel({
  sopSummary,
  participants,
  processNodes,
  responsibilities,
  hitlRules,
  riskLevel,
  hitlLevel,
  edges: edgesProp,
  mainPath: mainPathProp,
}: SAPWorkflowPanelProps) {
  const [selectedStepId, setSelectedStepId] = useState<string>('sap-start')
  const normalizedParticipants = normalizeParticipants(participants)
  const normalizedResponsibilities = normalizeResponsibilities(responsibilities)
  const normalizedHitlRules = normalizeHitlRules(hitlRules)
  const nodes = normalizeNodes({
    processNodes,
    responsibilities: normalizedResponsibilities,
    hitlRules: normalizedHitlRules,
  })
  const knownIds = new Set(nodes.map((node) => node.id))
  const edges = normalizeEdges(edgesProp ?? [], knownIds)
  const mainPath = Array.isArray(mainPathProp)
    ? mainPathProp.map((id) => cleanText(id)).filter(Boolean)
    : []
  const nodesById = new Map(nodes.map((node) => [node.id, node]))
  const unboundHitlRules = normalizedHitlRules.filter((rule) => !rule.nodeId)
  const hasData = hasMeaningfulSAPData(processNodes, participants, responsibilities, hitlRules, sopSummary)
  const sopText = cleanText(sopSummary)
  const reviewNodeCount = nodes.filter((node) => node.humanReviewRequired || node.hitlRules.length).length
  const { steps, returnEdges } = buildSteps(nodes, hitlLevel, normalizedHitlRules, edges, mainPath)
  const selectedStep = steps.find((step) => step.id === selectedStepId) ?? steps[0]
  const gateEnabled = needsHumanGate(hitlLevel, normalizedHitlRules)
  const passLabel = gateEnabled ? '通过：人工确认通过' : '通过：输出达标'
  const rejectLabel = gateEnabled ? '退回：复核未通过' : '退回：条件不满足'
  const loopTarget = nodes.find((node) => node.humanReviewRequired || node.hitlRules.length) ?? nodes[0]
  const loopBars = returnEdges.length
    ? returnEdges.map((edge) => ({
      key: `${edge.from}->${edge.to}`,
      label: edge.label || rejectLabel,
      fromTitle: nodesById.get(edge.from)?.title ?? edge.from,
      toTitle: nodesById.get(edge.to)?.title ?? edge.to,
    }))
    : loopTarget
      ? [{ key: 'fallback-loop', label: rejectLabel, fromTitle: loopTarget.title, toTitle: loopTarget.title }]
      : []

  return (
    <section className="rounded-md border border-border bg-background p-3">
      <div className="flex flex-col gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="inline-flex size-7 items-center justify-center rounded-md border border-cyan-500/40 bg-cyan-500/10 text-cyan-700 dark:text-cyan-200">
              <GitBranch className="size-4" />
            </span>
            <PanelTitle title="SAP 工作流" helpText="把 SOP 摘要、参与角色、流程节点、责任分配和 HITL 规则整合到同一个工作流框中，并通过判断节点表达通过与回退路径。" />
          </div>
          <p className="mt-2 text-xs leading-5 text-muted-foreground">
            {sopText || '尚未生成 SOP 摘要。'}
          </p>
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
          <SAPMetric label="参与角色" value={`${normalizedParticipants.length} 个`} tone={normalizedParticipants.length ? 'ok' : 'warn'} />
          <SAPMetric label="流程节点" value={`${processNodes.length} 个`} tone={processNodes.length ? 'ok' : 'warn'} />
          <SAPMetric label="责任绑定" value={`${normalizedResponsibilities.length} 条`} tone={normalizedResponsibilities.length ? 'ok' : 'warn'} />
          <SAPMetric label="HITL 节点" value={`${reviewNodeCount} 个`} tone={hitlLevel && hitlLevel !== 'none' && !reviewNodeCount ? 'warn' : 'default'} />
        </div>
      </div>

      {!hasData ? (
        <div className="mt-3 rounded-md border border-dashed border-muted-foreground/40 bg-muted/20 p-4 text-sm text-muted-foreground">
          SAP 工作流暂无可展示内容。需要先生成 SOP 摘要、参与角色、流程节点、责任分配或 HITL 规则。
        </div>
      ) : (
        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          <div className="max-h-[70vh] overflow-auto rounded-md border border-border/80 bg-[linear-gradient(to_right,rgba(148,163,184,0.14)_1px,transparent_1px),linear-gradient(to_bottom,rgba(148,163,184,0.14)_1px,transparent_1px)] bg-[size:28px_28px] p-4">
            <div className="min-w-max rounded-md border border-dashed border-cyan-600/50 bg-background/80 p-4 shadow-sm">
              <div className="flex items-center justify-between gap-4 border-b border-border/70 pb-3">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-cyan-700 dark:text-cyan-200">SAP / Workflow Container</p>
                  <p className="mt-1 text-sm font-medium text-foreground">起点、节点、判断、终点和回退闭环</p>
                </div>
                <div className="flex flex-wrap justify-end gap-2 text-[10px] text-muted-foreground">
                  <span className="inline-flex items-center gap-1 rounded-sm border border-cyan-500/40 bg-cyan-500/10 px-2 py-1">
                    <CircleDot className="size-3 text-cyan-600" />
                    业务节点
                  </span>
                  <span className="inline-flex items-center gap-1 rounded-sm border border-amber-500/40 bg-amber-500/10 px-2 py-1">
                    <GitBranch className="size-3 text-amber-600" />
                    判断节点
                  </span>
                  <span className="inline-flex items-center gap-1 rounded-sm border border-rose-500/40 bg-rose-500/10 px-2 py-1">
                    <RotateCcw className="size-3 text-rose-600" />
                    循环回退
                  </span>
                </div>
              </div>

              <div className="mt-4 flex flex-col items-center">
                {steps.map((step, index) => (
                  <div key={step.id} className="flex w-full flex-col items-center">
                    <SAPFlowNode
                      step={step}
                      selected={selectedStep.id === step.id}
                      onSelect={() => setSelectedStepId(step.id)}
                      hitlLevel={hitlLevel}
                    />
                    {index < steps.length - 1 ? (
                      <FlowConnector
                        label={step.kind === 'decision' ? passLabel : edgeLabelBetween(index, steps.length)}
                        dashed={step.kind === 'decision'}
                      />
                    ) : null}
                  </div>
                ))}
              </div>

              {loopBars.length ? (
                <div className="mt-4 flex min-w-0 flex-col items-center gap-2">
                  {loopBars.map((bar) => (
                    <div
                      key={bar.key}
                      className="flex min-w-0 items-center justify-center gap-2 rounded-md border border-dashed border-rose-400/60 bg-rose-500/5 px-3 py-2 text-xs text-rose-700 dark:text-rose-200"
                    >
                      <RotateCcw className="size-4 shrink-0" />
                      <span className="rounded-sm bg-background px-2 py-1 ring-1 ring-rose-300/50">{bar.label}</span>
                      <span className="h-px w-10 border-t border-dashed border-rose-300" />
                      <span>返回：{bar.toTitle}</span>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </div>

          {/* 节点详情：右栏，随左侧流程节点选中切换 */}
          <div className="min-w-0">
            <FlowDetailPanel
              step={selectedStep}
              participants={normalizedParticipants}
              unboundHitlRules={unboundHitlRules}
              riskLevel={riskLevel}
              hitlLevel={hitlLevel}
              passLabel={passLabel}
              rejectLabel={rejectLabel}
              loopTarget={loopTarget}
              returnEdges={returnEdges}
              nodesById={nodesById}
            />
          </div>
        </div>
      )}
    </section>
  )
}
