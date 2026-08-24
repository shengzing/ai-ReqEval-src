'use client'

import type { ReactNode } from 'react'
import { AlertTriangle, CheckCircle2, FileCheck2, GitBranch, MessageSquareWarning, ShieldCheck, XCircle } from 'lucide-react'

import type { EvidenceItem, Stage } from '@/lib/types'
import { asArray, asRecord, getFirst, BoundaryReviewStatusBadge, CardGridPanel, CrossSystemLinksPanel, ErrorAmplificationPathsPanel, ObjectListPanel, PanelTitle, RawPayloadPanel, RiskGovernanceMatrixPanel, TagPanel } from './result-renderers'
import { SAPWorkflowPanel } from './sap-workflow-panel'

/** Render a field badge: "missing" for absent, error badge for invalid enums. */
function FieldBadge({ label, value, valid }: { label: string; value: unknown; valid?: boolean }) {
  if (value === undefined || value === null || value === '' || (Array.isArray(value) && value.length === 0)) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-dashed border-muted-foreground/40 bg-muted/30 px-2 py-1 text-[11px] text-muted-foreground">
        <XCircle className="size-3 opacity-50" />
        {label}: 缺失
      </span>
    )
  }
  if (valid === false) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-destructive/50 bg-destructive/10 px-2 py-1 text-[11px] text-destructive">
        <AlertTriangle className="size-3" />
        {label}: {String(value)}
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-1 text-[11px] text-foreground">
      <CheckCircle2 className="size-3 opacity-50" />
      {label}: {String(value)}
    </span>
  )
}

/** Render evidence_refs as badge chips, showing the source file name when available. */
function EvidenceRefChips({ refs, evidenceMap }: { refs: unknown[]; evidenceMap?: Map<string, EvidenceItem> }) {
  const items = asArray(refs)
  if (!items.length) {
    return <FieldBadge label="证据引用" value={undefined} />
  }
  return (
    <div className="flex flex-wrap gap-1">
      {items.map((ref, i) => {
        const refId = typeof ref === 'string' ? ref : String(ref ?? '')
        const evidence = evidenceMap?.get(refId)
        const label = evidence ? evidence.name : refId
        return (
          <span
            key={`ev-${i}`}
            className="inline-flex items-center gap-1 rounded-md bg-primary/10 px-2 py-1 text-[11px] text-primary"
            title={evidence ? `${refId} → ${evidence.name}` : refId}
          >
            {label}
          </span>
        )
      })}
    </div>
  )
}

function formatScenarioName(value: unknown): string {
  const text = String(value ?? '').trim()
  if (!text) return '阶段一产物未命名'
  if ((text.startsWith('“') && text.endsWith('”')) || (text.startsWith('"') && text.endsWith('"'))) {
    return text
  }
  return `“${text}”`
}

/** Render validation issues with severity-based color. */
function ValidationIssuesPanel({ issues }: { issues: unknown[] }) {
  const items = asArray(issues)
  if (!items.length) return null

  return (
    <div className="rounded-md border border-border p-3">
      <PanelTitle title="合同校验问题" helpText="展示阶段一产物违反风险等级、HITL、证据绑定等合同规则的地方，用于决定是否需要补充材料或修正结果。" />
      <div className="mt-2 space-y-1">
        {items.map((issue, i) => {
          const record = asRecord(issue)
          if (!record) return null
          const severity = String(record.severity ?? 'medium')
          const borderColor = severity === 'high' ? 'border-destructive/50' : 'border-warning/50'
          const bgColor = severity === 'high' ? 'bg-destructive/10' : 'bg-warning/10'
          const textColor = severity === 'high' ? 'text-destructive' : 'text-warning'
          return (
            <div key={`issue-${i}`} className={`rounded-md border ${borderColor} ${bgColor} p-2`}>
              <p className={`text-sm ${textColor}`}>
                [{severity.toUpperCase()}] {String(record.issue_type ?? '')} — {String(record.field ?? '')}
              </p>
              <p className="mt-1 text-[11px] text-muted-foreground">{String(record.message ?? '')}</p>
              {record.suggested_action ? (
                <p className="mt-1 text-[11px] text-foreground">{"建议: " + String(record.suggested_action)}</p>
              ) : null}
            </div>
          )
        })}
      </div>
    </div>
  )
}

/** Render quality scores with threshold indicators. */
const QUALITY_SCORE_LABELS: Record<string, string> = {
  // 核心五维（与 thresholds 对齐，命名与后端 project_service.py 一致）
  completeness_score: '完整性',
  evidence_coverage_score: '证据覆盖度',
  risk_consistency_score: '风险一致性',
  hitl_alignment_score: 'HITL 对齐度',
  audit_readiness_score: '审计可用性',
  // 交付物就绪度的细分维度（compute_stage1_quality 额外产出）
  participant_split_score: '参与者拆分度',
  process_node_completeness_score: '流程节点完整性',
  responsibility_mapping_score: '责任映射度',
  responsibility_chain_score: '责任链完整度',
  audit_node_mapping_score: '审计节点映射度',
  flow_diagram_score: '流程图生成度',
  flow_diagram_generated: '流程图已生成',
  risk_node_binding_score: '风险节点绑定度',
  risk_item_node_binding_score: '风险项节点绑定度',
  hitl_rule_node_binding_score: 'HITL 规则节点绑定度',
  deliverable_readiness_score: '交付物就绪度',
  // F2/F3 新增产物覆盖度
  cross_system_link_score: '跨系统链路覆盖度',
  error_path_coverage_score: '错误放大路径覆盖度',
  extended_deliverable_readiness_score: '扩展交付物就绪度',
}

function QualityScoresPanel({ quality }: { quality: Record<string, unknown> }) {
  const entries = Object.entries(quality)
  if (!entries.length) return null

  const thresholds: Record<string, number> = {
    completeness_score: 0.70,
    evidence_coverage_score: 0.70,
    risk_consistency_score: 0.90,
    hitl_alignment_score: 0.90,
    audit_readiness_score: 0.70,
  }

  return (
    <div className="rounded-md border border-border p-3">
      <PanelTitle title="质量评分" helpText="按完整性、证据覆盖、风险一致性、HITL 对齐和审计可用性评估当前阶段一产物质量。" />
      <div className="mt-2 grid gap-2 md:grid-cols-2">
        {entries.map(([key, value]) => {
          const score = typeof value === 'number' ? value : 0
          const threshold = thresholds[key] ?? 0.70
          const passed = score >= threshold
          const label = QUALITY_SCORE_LABELS[key] ?? key.replace(/_score$/, '').replace(/_/g, ' ')
          return (
            <div key={key} className={`rounded-md p-2 ${passed ? 'bg-emerald-500/10' : 'bg-destructive/10'}`}>
              <p className="text-xs text-muted-foreground">{label}</p>
              <div className="mt-1 flex items-center gap-2">
                <span className={`text-sm font-medium ${passed ? 'text-emerald-600' : 'text-destructive'}`}>
                  {score.toFixed(2)}
                </span>
                <span className="text-[11px] text-muted-foreground">/ {threshold.toFixed(2)}</span>
                {passed ? (
                  <CheckCircle2 className="size-3 text-emerald-600" />
                ) : (
                  <AlertTriangle className="size-3 text-destructive" />
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

const RISK_LEVELS = new Set(['L1', 'L2', 'L3'])
const HITL_LEVELS = new Set(['none', 'standard', 'strict', 'mandatory'])

export function StageOneScenarioPanel({ stage, evidenceItems }: { stage: Stage; evidenceItems?: EvidenceItem[] }) {
  const payload = stage.resultPayload ?? {}
  const scenarioSummary = asRecord(payload.scenario_summary) ?? {}
  const validation = asRecord(payload.stage1_validation) ?? {}
  const quality = asRecord(validation.quality) ?? {}
  const inputBinding = asRecord(payload.input_binding) ?? {}
  const harness = asRecord(payload.harness) ?? asRecord(payload.harness_trace) ?? {}

  // evidence_refs → 文件名映射表：用于把 evidence_refs（如 "ev-1"）渲染为原证据文件名
  const evidenceMap = new Map<string, EvidenceItem>()
  for (const item of (evidenceItems ?? [])) {
    if (item.id) evidenceMap.set(item.id, item)
  }

  // ── 1. Scenario boundary ────────────────────────────────────────────
  const boundary = asRecord(scenarioSummary.boundary) ?? {}
  const inScope = asArray(boundary.in_scope)
  const outOfScope = asArray(boundary.out_of_scope)
  const preconditions = asArray(boundary.preconditions)
  const dataBoundary = asArray(boundary.data_boundary)

  // ── 1a. F2/F3 derived artifacts (单项目级) ──────────────────────
  // 主案例定义 / 补充验证场景 / 材料清单是课题级产物，不在单项目内。
  const crossSystemLinks = asArray(scenarioSummary.cross_system_links)
  const errorAmplificationPaths = asArray(scenarioSummary.error_amplification_paths)
  const boundaryReviewStatus = String(scenarioSummary.boundary_review_status ?? 'business_pending')

  // ── 3. Participants ──────────────────────────────────────────────────
  const participants = asArray(scenarioSummary.participants)

  // ── 4. Process nodes ─────────────────────────────────────────────────
  const processNodes = asArray(scenarioSummary.process_nodes)

  // ── 4a. Flow IR (edges + main_path) ─────────────────────────────────
  const edges = asArray(scenarioSummary.edges)
  const mainPath = asArray(scenarioSummary.main_path).map((id) => String(id))

  // ── 5. Responsibilities ─────────────────────────────────────────────
  const responsibilities = asArray(scenarioSummary.responsibilities)

  // ── 6. Risk governance matrix ──────────────────────────────────────
  const riskGovernanceMatrix = asArray(scenarioSummary.risk_governance_matrix)

  // ── 7. Risk items ───────────────────────────────────────────────────
  const riskItems = asArray(scenarioSummary.risk_items)

  // ── 8. HITL rules ───────────────────────────────────────────────────
  const hitlRules = asArray(scenarioSummary.hitl_rules)

  // ── 9. Prohibited conditions ────────────────────────────────────────
  const prohibitedConditions = asArray(scenarioSummary.prohibited_conditions)

  // ── 10. Fatal errors ─────────────────────────────────────────────────
  const fatalErrors = asArray(scenarioSummary.fatal_errors)

  // ── 11. Audit requirements ───────────────────────────────────────────
  const auditRequirements = asArray(scenarioSummary.audit_requirements)

  // ── 12. Evidence refs ───────────────────────────────────────────────
  const evidenceRefs = asArray(scenarioSummary.evidence_refs)

  // ── 13. To-confirm questions ─────────────────────────────────────────
  const toConfirm = asArray(scenarioSummary.to_confirm)

  // ── 14. Validation issues + quality scores ──────────────────────────
  const validationIssues = asArray(validation.issues)
  const harnessPlan = asArray(harness.plan)
  const harnessTraces = asArray(harness.traces)
  const llmStatus = String(harness.llm_status ?? harness.llmStatus ?? '')
  const fallbackReason = String(harness.fallback_reason ?? harness.fallbackReason ?? '')
  const inputFileCount = asArray(inputBinding.file_ids).length
  const inputEvidenceCount = asArray(inputBinding.evidence_ids).length

  // Enum validity checks
  const riskLevel = String(scenarioSummary.risk_level ?? '')
  const hitlLevel = String(scenarioSummary.hitl_level ?? '')
  const riskLevelValid = RISK_LEVELS.has(riskLevel)
  const hitlLevelValid = HITL_LEVELS.has(hitlLevel)

  return (
    <div>
      <div className="mb-3 rounded-md border border-border bg-muted/20 p-3">
        <div className="space-y-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <GitBranch className="size-3.5" />
              LangGraph Harness 产物
            </div>
            <p className="mt-1 text-sm font-medium text-foreground">
              {formatScenarioName(getFirst(scenarioSummary, ['scenario_name', 'name', 'title']))}
            </p>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              阶段一结果由上传材料驱动，经过风险/HITL 合同校验后形成当前产物。
            </p>
          </div>
          <div className="grid gap-2 text-xs sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-6">
            <StageOneSummaryPill icon={<AlertTriangle className="size-3.5" />} label="风险等级" value={riskLevel || '缺失'} warn={!riskLevelValid} />
            <StageOneSummaryPill icon={<XCircle className="size-3.5" />} label="HITL 等级" value={hitlLevel || '缺失'} warn={!hitlLevelValid} />
            <StageOneSummaryPill icon={<FileCheck2 className="size-3.5" />} label="输入绑定" value={`${inputFileCount} 文件 / ${inputEvidenceCount} 证据`} />
            <StageOneSummaryPill icon={<ShieldCheck className="size-3.5" />} label="校验问题" value={`${validationIssues.length} 个`} warn={validationIssues.length > 0} />
            <StageOneSummaryPill icon={<MessageSquareWarning className="size-3.5" />} label="待确认问题" value={`${toConfirm.length} 个`} warn={toConfirm.length > 0} />
            <StageOneSummaryPill icon={<GitBranch className="size-3.5" />} label="Harness 事件" value={`${harnessPlan.length + harnessTraces.length} 条`} />
          </div>
        </div>
        {(llmStatus || fallbackReason) && (
          <div className="mt-3 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700">
            {llmStatus ? `LLM 状态：${llmStatus}` : 'LLM 状态未返回'}
            {fallbackReason ? `；回退原因：${fallbackReason}` : ''}
          </div>
        )}
      </div>

      {/* 1. Scenario boundary */}
      <div className="grid gap-3">
        <div className="rounded-md border border-border p-3">
          <PanelTitle title="场景边界" helpText="明确本阶段评估覆盖哪些业务范围、不覆盖哪些范围，以及运行前置条件和可使用的数据边界。" />
          <div className="mt-2 grid gap-2 md:grid-cols-2">
            <div>
              <p className="text-[11px] text-muted-foreground">范围内</p>
              <TagPanel title="" items={inScope} />
            </div>
            <div>
              <p className="text-[11px] text-muted-foreground">范围外</p>
              <TagPanel title="" items={outOfScope} />
            </div>
            <div>
              <p className="text-[11px] text-muted-foreground">前置条件</p>
              <TagPanel title="" items={preconditions} />
            </div>
            <div>
              <p className="text-[11px] text-muted-foreground">数据边界</p>
              <TagPanel title="" items={dataBoundary} />
            </div>
          </div>
        </div>

        {/* F1: 本项目边界业务侧认可状态（主案例/补充场景/材料清单是课题级产物，不在单项目内） */}
        <BoundaryReviewStatusBadge reviewStatus={boundaryReviewStatus} />

        {/* 2. SAP workflow */}
        <SAPWorkflowPanel
          sopSummary={scenarioSummary.sop_summary}
          participants={participants}
          processNodes={processNodes}
          responsibilities={responsibilities}
          hitlRules={hitlRules}
          riskLevel={riskLevel}
          hitlLevel={hitlLevel}
          edges={edges}
          mainPath={mainPath}
        />

        {/* 6. Risk governance matrix — 风险项以小卡片形式内嵌矩阵行内，点击展开详情 */}
        <RiskGovernanceMatrixPanel items={riskGovernanceMatrix} riskItems={riskItems} evidenceMap={evidenceMap} />

        {/* F3: 错误放大路径 */}
        <ErrorAmplificationPathsPanel items={errorAmplificationPaths} />

        {/* F2: 跨系统链路 */}
        <CrossSystemLinksPanel items={crossSystemLinks} />

        {/* 7. Risk items (legacy standalone panel — removed, now folded into the matrix above) */}

        {/* 9. Prohibited conditions — 卡片网格，宽屏一行四个 */}
        <CardGridPanel title="禁止条件" items={prohibitedConditions} columns={4} helpText="列出系统或流程不允许自动执行的情形，通常用于高风险或合规底线控制。" />

        {/* 10. Fatal errors */}
        <ObjectListPanel title="致命错误" items={fatalErrors} helpText="列出一旦发生就应立即停止、升级或人工接管的错误类型。" />

        {/* 11. Audit requirements */}
        <TagPanel title="审计要求" items={auditRequirements} helpText="说明需要留痕、可追溯和可审计的证据要求，服务于后续报告和复核。" />

        {/* 12. Evidence refs */}
        <div className="rounded-md border border-border p-3">
          <PanelTitle title="证据引用" helpText="展示本阶段结论引用了哪些材料或证据片段，用于判断输出是否有输入支撑。" />
          <div className="mt-2">
            <EvidenceRefChips refs={evidenceRefs} evidenceMap={evidenceMap} />
          </div>
        </div>

        {/* 13. To-confirm questions */}
        <ObjectListPanel title="待确认问题" items={toConfirm} helpText="列出系统不应自行写回的疑问点，需要用户在对话中确认后再修正阶段产物。" />

        {/* 14. Validation issues + quality scores */}
        <div className="grid gap-3">
          <ValidationIssuesPanel issues={validationIssues} />
          <QualityScoresPanel quality={quality} />
        </div>

        {/* Raw payload */}
        <RawPayloadPanel payload={payload} />
      </div>
    </div>
  )
}

function StageOneSummaryPill({
  icon,
  label,
  value,
  warn,
}: {
  icon: ReactNode
  label: string
  value: string
  warn?: boolean
}) {
  return (
    <div className={`rounded-md border px-3 py-2 ${warn ? 'border-amber-500/40 bg-amber-500/10' : 'border-border/70 bg-background/60'}`}>
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        {icon}
        {label}
      </div>
      <div className={`mt-0.5 font-medium ${warn ? 'text-amber-700' : 'text-foreground'}`}>{value}</div>
    </div>
  )
}
