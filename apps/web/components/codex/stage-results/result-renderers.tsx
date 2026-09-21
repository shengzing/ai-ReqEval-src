'use client'

import type { ReactNode } from 'react'
import { CircleHelp } from 'lucide-react'

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import type { StageLockCheck } from '@/lib/types'
import {
  asArray,
  asRecord,
  formatValue,
  getFirst,
  getStageSuffix,
  hasRenderablePayload,
  type ResultPayload,
} from './result-utils'

export { asArray, asRecord, formatValue, getFirst, getStageSuffix, hasRenderablePayload, type ResultPayload } from './result-utils'

export function PanelTitle({ title, helpText }: { title: string; helpText?: ReactNode }) {
  if (!title) return null

  return (
    <div className="flex items-center gap-1.5">
      <p className="text-xs font-semibold text-foreground/85">{title}</p>
      {helpText ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              aria-label={`${title}说明`}
              className="inline-flex size-4 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <CircleHelp className="size-3.5" aria-hidden="true" />
            </button>
          </TooltipTrigger>
          <TooltipContent side="top" sideOffset={6} className="max-w-72 text-left leading-5">
            {helpText}
          </TooltipContent>
        </Tooltip>
      ) : null}
    </div>
  )
}

export function Metric({ label, value, className, helpText }: { label: string; value: unknown; className?: string; helpText?: ReactNode }) {
  return (
    <div className={cn('rounded-md bg-muted/40 p-3', className)}>
      <PanelTitle title={label} helpText={helpText} />
      <p className="mt-1 text-sm text-foreground">{formatValue(value)}</p>
    </div>
  )
}


// ── Stage 1 审计留痕 8 字段 schema（§3.2.4 / NFRA 第二十一条+第二十二条+金规〔2024〕24号第五十条） ──
export const AUDIT_FIELD_SCHEMA = [
  { id: 'input_material_version', label: '输入材料版本', base: true,  group: 'base',     help: '材料版本号 + 解析时间戳' },
  { id: 'raw_analysis_output',    label: '原始分析结果', base: true,  group: 'base',     help: 'AI 原始 JSON / 文本输出快照' },
  { id: 'reviewer_opinion',       label: '复核人意见',   base: true,  group: 'base',     help: '复核人签字 + 复核结论' },
  { id: 'timestamp',              label: '时间戳',       base: true,  group: 'base',     help: 'UTC+本地时区，覆盖各阶段节点' },
  { id: 'inference_path',         label: '推理路径',     base: false, group: 'extended', help: '输入→中间推理→输出的完整链路与引用来源（NFRA 第二十二条）' },
  { id: 'threshold_trigger_log',  label: '阈值触发记录', base: false, group: 'extended', help: '风险等级/客户处置/监管敏感阈值的命中记录（NFRA 第二十二条）' },
  { id: 'ai_disclosure',          label: 'AI 生成内容显著标识', base: false, group: 'extended', help: '显式水印 / 隐式元数据 / 不标识（NFRA 第二十一条 + 深度合成规定第十七条）' },
  { id: 'log_retention',          label: '日志保存期限', base: false, group: 'extended', help: '业务生命周期 / 5 年 / 10 年（NFRA 第二十一条 ≥业务存续期）' },
] as const
export type AuditFieldId = typeof AUDIT_FIELD_SCHEMA[number]['id']
export const AML_EXTRA_AUDIT_FIELDS = [
  { id: 'regulatory_reporting_log', label: '监管报送流水', help: 'AML 场景特有，监管报送批次号+回执' },
] as const

// 关键词归一：把 audit_requirements 中的自由文本项映射到 8 字段
const AUDIT_KEYWORD_RULES: Array<{ id: AuditFieldId; patterns: RegExp[] }> = [
  { id: 'input_material_version',  patterns: [/输入材料版本/, /原始纪要/, /材料版本/, /版本号/, /input.{0,3}version/i] },
  { id: 'raw_analysis_output',     patterns: [/原始分析结果/, /原始输出/, /AI.{0,3}输出/, /生成快照/, /raw.{0,3}output/i] },
  { id: 'reviewer_opinion',        patterns: [/复核人意见/, /复核意见/, /复核结论/, /签字/, /reviewer/i] },
  { id: 'timestamp',               patterns: [/时间戳/, /timestamp/i, /UTC/, /本地时区/] },
  { id: 'inference_path',          patterns: [/推理路径/, /推理链路/, /inference.{0,3}path/i, /引用来源/] },
  { id: 'threshold_trigger_log',   patterns: [/阈值触发/, /阈值命中/, /trigger.{0,3}log/i] },
  { id: 'ai_disclosure',           patterns: [/显著标识/, /AIGC\s*标识/, /水印/, /显式标识/, /隐式元数据/, /ai.{0,3}disclosure/i, /deepfake/i] },
  { id: 'log_retention',           patterns: [/日志保存/, /保存期限/, /存续期/, /\d+\s*年/, /log.{0,3}retention/i, /business.{0,3}lifetime/i] },
]

function matchAuditField(fieldId: AuditFieldId, items: string[]): string[] {
  const rule = AUDIT_KEYWORD_RULES.find((r) => r.id === fieldId)
  if (!rule) return []
  return items.filter((raw) => rule.patterns.some((re) => re.test(raw)))
}

/** 判断 AML 场景是否触发（监管报送相关关键词或 boundary_flag=true） */
function isAmlScenario(items: string[], boundaryFlag?: boolean): boolean {
  if (boundaryFlag === true) return true
  const joined = items.join(' ')
  return /反洗钱|AML|监管报送|报送流水|可疑交易|大额/.test(joined)
}

/** 8 字段 schema 网格：覆盖度 + 已命中条目预览；可叠加 AML 第 9 字段。 */
export function AuditRequirementsGrid({
  items,
  boundaryFlag,
  title = '审计留痕字段（§3.2.4 八字段 schema）',
  helpText,
}: {
  items: unknown[]
  boundaryFlag?: boolean
  title?: string
  helpText?: ReactNode
}) {
  // P2: structured items ({field_id, label, configured, value}) map directly;
  // legacy string items fall back to keyword matching.
  const structured = asArray(items).map((v) => asRecord(v)).filter((rec): rec is Record<string, unknown> => Boolean(rec && rec.field_id))
  const structuredIds = new Set(structured.map((rec) => String(rec.field_id)))
  const raw = asArray(items).filter((v) => typeof v === 'string').map((v) => String(v))
  const baseFields = AUDIT_FIELD_SCHEMA.filter((f) => f.group === 'base')
  const extFields  = AUDIT_FIELD_SCHEMA.filter((f) => f.group === 'extended')
  const showAml = isAmlScenario([...raw, ...structured.map((r) => String(r.label ?? ''))], boundaryFlag) || structuredIds.has('regulatory_reporting_log')
  const coveredCount =
    AUDIT_FIELD_SCHEMA.filter((f) => structuredIds.has(f.id) || matchAuditField(f.id, raw).length > 0).length
    + (showAml && (structuredIds.has('regulatory_reporting_log') || /监管报送|报送流水|反洗钱|AML/.test(raw.join(' '))) ? 1 : 0)
  const totalCount = AUDIT_FIELD_SCHEMA.length + (showAml ? 1 : 0)

  return (
    <div className="rounded-md border border-border p-3">
      <PanelTitle
        title={title}
        helpText={helpText ?? '依据 §3.2.4：基础 4 字段（输入版本/原始输出/复核意见/时间戳）+ 扩展 4 字段（推理路径/阈值触发记录/AIGC 标识/日志保存期），AML 场景再加 1 字段（监管报送流水）。'}
      />
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
        <span className={`rounded-md px-2 py-1 font-medium ${coveredCount === totalCount ? 'bg-emerald-500/15 text-emerald-700' : 'bg-amber-500/15 text-amber-700'}`}>
          {coveredCount} / {totalCount} 字段已留痕
        </span>
        {raw.length === 0 && (
          <span className="text-muted-foreground">当前 audit_requirements 为空，关键词归一匹配不到任何字段。</span>
        )}
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {[...baseFields, ...extFields].map((field) => {
          const structHit = structured.find((rec) => String(rec.field_id) === field.id && rec.configured === true)
          const structValue = structHit ? String(structHit.value ?? '') : ''
          const hits: string[] = structHit
            ? [structValue || String(structHit.label ?? '') || field.label]
            : matchAuditField(field.id, raw)
          const covered = hits.length > 0
          return (
            <div
              key={field.id}
              className={`rounded-md border p-2 ${covered ? 'border-emerald-500/40 bg-emerald-500/10' : 'border-dashed border-muted-foreground/40 bg-muted/20'}`}
            >
              <div className="flex items-center justify-between gap-2">
                <p className="text-[11px] font-medium text-foreground">{field.label}</p>
                {covered
                  ? <span className="rounded bg-emerald-500/20 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700">已覆盖</span>
                  : <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">缺失</span>}
              </div>
              <p className="mt-0.5 text-[10px] leading-4 text-muted-foreground">{field.help}</p>
              {covered && (
                <ul className="mt-1 space-y-0.5">
                  {hits.slice(0, 2).map((h, i) => (
                    <li key={`hit-${i}`} className="truncate text-[10px] text-emerald-700">✓ {h}</li>
                  ))}
                </ul>
              )}
            </div>
          )
        })}
        {showAml && AML_EXTRA_AUDIT_FIELDS.map((field) => {
          const covered = structuredIds.has(field.id) || /监管报送|报送流水|反洗钱|AML/.test(raw.join(' '))
          return (
            <div
              key={field.id}
              className={`rounded-md border p-2 ${covered ? 'border-emerald-500/40 bg-emerald-500/10' : 'border-dashed border-muted-foreground/40 bg-muted/20'}`}
            >
              <div className="flex items-center justify-between gap-2">
                <p className="text-[11px] font-medium text-foreground">{field.label}</p>
                {covered
                  ? <span className="rounded bg-emerald-500/20 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700">已覆盖</span>
                  : <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">缺失</span>}
              </div>
              <p className="mt-0.5 text-[10px] leading-4 text-muted-foreground">{field.help}</p>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── §3.2 步骤1 STS 六变量社会子系统诊断（§1.3.1 STS 理论） ──────────────
export const STS_6_VARIABLES = [
  { id: 'autonomy',           label: '自律性 (Autonomy)' },
  { id: 'responsibility',     label: '责任 (Responsibility)' },
  { id: 'task_integrity',     label: '任务整体性 (Task Integrity)' },
  { id: 'diversity',          label: '多样性 (Diversity)' },
  { id: 'social_support',     label: '社会支持 (Social Support)' },
  { id: 'boundary_spanning',  label: '边界跨越 (Boundary Spanning)' },
] as const
const STS_STATUS_META: Record<string, { label: string; cls: string }> = {
  aligned:    { label: '已对齐', cls: 'bg-emerald-500/15 text-emerald-700' },
  tension:    { label: '需协调', cls: 'bg-amber-500/15 text-amber-700' },
  misaligned: { label: '失配',   cls: 'bg-destructive/15 text-destructive' },
  unmapped:   { label: '未识别', cls: 'bg-muted text-muted-foreground' },
}
/** 渲染 §3.2 步骤1 STS 六变量社会子系统诊断面板。 */
export function StsDiagnosisPanel({ diagnosis }: { diagnosis: unknown }) {
  const obj = asRecord(diagnosis)
  const hasAny = obj && Object.keys(obj).length > 0
  return (
    <div className="rounded-md border border-border p-3">
      <PanelTitle
        title="STS 六变量诊断（§3.2 步骤1 / §1.3.1 社会子系统诊断）"
        helpText="按 STS 理论六变量给出社会侧诊断（aligned / tension / misaligned / unmapped），与 ISO 可能性×后果矩阵（技术侧分级）共同构成「分级依据 + 映射依据」双层。"
      />
      {!hasAny ? (
        <p className="mt-2 text-[11px] text-muted-foreground">未提供 STS 诊断（论文 §3.2 步骤1 推荐补全）。</p>
      ) : (
        <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {STS_6_VARIABLES.map((v) => {
            const status = String(obj[v.id] ?? 'unmapped')
            const meta = STS_STATUS_META[status] ?? STS_STATUS_META.unmapped
            return (
              <div key={v.id} className="flex items-center justify-between rounded-md border border-border bg-background/60 px-3 py-2">
                <span className="text-[11px] text-foreground">{v.label}</span>
                <span className={`rounded-md px-2 py-0.5 text-[10px] font-medium ${meta.cls}`}>{meta.label}</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

const ORG_LOOP_KIND_LABEL: Record<string, string> = {
  'UA-Tasks': 'AI 使用循环',
  'CA-Tasks': 'AI 定制循环',
  'O-Tasks':  '原任务循环',
  'C-Tasks':  '上下文变化循环',
}
/** 渲染 §3.2 步骤2 KOITL 组织循环归属面板。 */
export function OrgLoopsPanel({ loops }: { loops: unknown[] }) {
  const items = asArray(loops)
    .map((it) => asRecord(it))
    .filter((rec): rec is Record<string, unknown> => Boolean(rec))
  if (!items.length) {
    return (
      <div className="rounded-md border border-dashed border-muted-foreground/40 bg-muted/30 p-3 text-xs text-muted-foreground">
        <PanelTitle title="KOITL 组织循环归属（§3.2 步骤2 四字段之一）" helpText="阶段一联合设计映射要求同时设计 KOITL 组织循环归属（org_loops）。L2/L3 建议至少 1 条。" />
        <p className="mt-2">当前未配置 org_loops。</p>
      </div>
    )
  }
  return (
    <div className="rounded-md border border-border p-3">
      <PanelTitle title="KOITL 组织循环归属（§3.2 步骤2）" helpText="组织在环（KOITL）的载体——记录哪些角色在哪些决策点形成闭环，配合 HITL 强度形成责任不可悬空的治理底线。" />
      <ul className="mt-2 space-y-2">
        {items.map((loop, i) => {
          const loopType = String(loop.loop_type ?? loop.kind ?? '')
          const kindLabel = (ORG_LOOP_KIND_LABEL[loopType] ?? loopType) || '循环'
          const responsibleRole = String(loop.responsible_role ?? loop.role ?? '未指定角色')
          const frequency = String(loop.frequency ?? '')
          const mandatoryFlag = loop.mandatory_flag === true
          return (
            <li key={`loop-${i}`} className="rounded-md border border-border bg-muted/40 p-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">{kindLabel}</span>
                <span className="text-sm font-medium text-foreground">{responsibleRole}</span>
                <span className="font-mono text-[10px] text-muted-foreground">{String(loop.loop_id ?? '')}</span>
                {frequency && (
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{frequency}</span>
                )}
                {mandatoryFlag && (
                  <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">mandatory</span>
                )}
              </div>
              {typeof loop.responsibility === 'string' && loop.responsibility && (
                <p className="mt-1 text-[11px] text-muted-foreground">{loop.responsibility}</p>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export function HarnessStepsTimeline({ plan, traces, scenarioSummary, validation, lockCheck }: {
  plan: unknown[]
  traces: unknown[]
  scenarioSummary: Record<string, unknown>
  validation?: Record<string, unknown>
  lockCheck?: StageLockCheck
}) {
  // 从已有 scenario_summary + validation 合成 §3.2 步骤 1→2→3 四元组
  const rl = String(scenarioSummary.risk_level ?? '')
  const hl = String(scenarioSummary.hitl_level ?? '')
  const sts = scenarioSummary.sts_diagnosis
  const orgLoops = Array.isArray(scenarioSummary.org_loops) ? scenarioSummary.org_loops : []
  const auditReq = Array.isArray(scenarioSummary.audit_requirements) ? scenarioSummary.audit_requirements : []
  const procNodes = Array.isArray(scenarioSummary.process_nodes) ? scenarioSummary.process_nodes : []
  const prohibited = Array.isArray(scenarioSummary.prohibited_conditions) ? scenarioSummary.prohibited_conditions : []
  const fatalErrors = Array.isArray(scenarioSummary.fatal_errors) ? scenarioSummary.fatal_errors : []
  const alternativeChannel = String(scenarioSummary.alternative_channel ?? '')
  const approvalSubject = String(scenarioSummary.approval_subject ?? '')
  const evRefs = Array.isArray(scenarioSummary.evidence_refs) ? scenarioSummary.evidence_refs : []
  const highIssues = asArray(validation?.issues).filter((it: any) => (it as any)?.severity === 'high').length
  const totalIssues = asArray(validation?.issues).length
  // P2: consume backend /lock-check when available (authoritative gate);
  // fall back to the local heuristic only when the caller has not wired
  // the backend result yet (e.g. legacy payloads without lockCheck).
  const backendLockable = lockCheck ? lockCheck.ready : undefined
  const lockable = backendLockable ?? (rl === 'L3'
    ? (hl === 'mandatory' || hl === 'strict') && approvalSubject && alternativeChannel && prohibited.length > 0 && fatalErrors.length > 0
    : rl === 'L2'
      ? prohibited.length >= 0
      : true)

  const step1Ok = rl && (sts ? Object.keys(sts as object).length >= 3 : true)
  const step2Ok = hl && orgLoops.length > 0 && auditReq.length > 0
  const step3Ok = totalIssues === 0 && lockable

  const steps = [
    {
      id: 'step-1',
      label: '步骤1 社会技术分级',
      thesis: '§3.2 步骤1 — 联合优化：按 ISO 31000/23894 做风险等级判定 + 按 STS 六变量做社会子系统诊断',
      input: { desc: '场景业务底稿 + 责任链 + 输入材料', refs: evRefs },
      operation: `STS 六变量诊断（${sts ? Object.keys(sts as object).length : 0} / 6）+ 风险关键词扫描 → 判定 ${rl || '?'}`,
      output: `risk_level = ${rl || '未判定'}`,
      criterion: 'ISO 可能性×后果矩阵（论文 §3.2.1） + STS 六变量（§1.3.1）',
      pass: !!step1Ok,
    },
    {
      id: 'step-2',
      label: '步骤2 联合设计映射',
      thesis: '§3.2 步骤2 — HITL 强度 + 准入禁入 + 审计留痕 + KOITL 组织循环归属同时设计',
      input: { desc: '步骤1 产出的 risk_level', refs: rl ? [`risk_level=${rl}`] : [] },
      operation: `HITL=${hl || '?'} · 禁入 ${prohibited.length} 条 · 致命 ${fatalErrors.length} 条 · 审计 ${auditReq.length} 条 · 替代渠道 ${alternativeChannel || '—'} · 批准主体 ${approvalSubject || '—'} · KOITL ${orgLoops.length} 环`,
      output: `hitl_level=${hl || '?'} · org_loops=${orgLoops.length} · alternative_channel=${alternativeChannel || '—'} · approval_subject=${approvalSubject || '—'}`,
      criterion: 'L3→strict/mandatory 强制对齐 + L3 须风管委批准 + mandatory 须 PIPL §24 替代渠道',
      pass: !!step2Ok,
    },
    {
      id: 'step-3',
      label: '步骤3 门控校验',
      thesis: '§3.2 步骤3 — 强制对齐检查，论文规定 L3 + strict/mandatory + 致命错误已定义 + 审计字段完整 + 人工最终复核才可锁定',
      input: { desc: '步骤2 四字段', refs: [hl, approvalSubject, alternativeChannel].filter(Boolean) as string[] },
      operation: lockCheck
        ? `后端 /lock-check — ${lockCheck.checks.filter((c) => c.passed).length} / ${lockCheck.checks.length} 门禁通过`
        : `阶段一契约校验 — high ${highIssues} / total ${totalIssues}`,
      output: lockable ? '可锁定（stage1_locked=True）' : '不可锁定（校验不通过）',
      criterion: lockCheck
        ? `后端权威门禁（${lockCheck.checks.length} 项）+ 5 维质量评分`
        : '5 硬门控（risk_level / hitl_level / evidence_refs / L3 prohibited / L3 fatal）+ 5 维质量评分',
      pass: step3Ok,
    },
  ]

  const passedCount = steps.filter(s => s.pass).length
  const overall = passedCount === steps.length

  return (
    <div className="rounded-md border border-border p-3">
      <PanelTitle
        title="阶段一执行轨迹（§3.2 步骤 1→2→3 输入/操作/产出/判据）"
        helpText="从 scenario_summary + stage1_validation 合成的四元组时间线；真实执行时 harness.plan/traces 会以 LLM 输出为准。"
      />
      <div className="mt-2 flex items-center gap-2 text-xs">
        <span className={`rounded-md px-2 py-1 font-medium ${overall ? 'bg-emerald-500/15 text-emerald-700' : 'bg-amber-500/15 text-amber-700'}`}>
          {passedCount} / {steps.length} 步通过 · 阶段一 {overall ? '可锁定' : '待补正'}
        </span>
      </div>
      <ol className="mt-3 space-y-3">
        {steps.map((s, i) => (
          <li key={s.id} className={`rounded-md border p-3 ${s.pass ? 'border-emerald-500/40 bg-emerald-500/5' : 'border-amber-500/40 bg-amber-500/5'}`}>
            <div className="flex flex-wrap items-center gap-2">
              <span className={`inline-flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold ${s.pass ? 'bg-emerald-500/30 text-emerald-700' : 'bg-amber-500/30 text-amber-700'}`}>{i + 1}</span>
              <span className="text-sm font-semibold text-foreground">{s.label}</span>
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{s.thesis}</span>
            </div>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              <div>
                <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">输入 (Input)</p>
                <p className="mt-0.5 text-[11px] text-foreground">{s.input.desc}</p>
                {s.input.refs.length > 0 && (
                  <p className="mt-0.5 text-[10px] text-muted-foreground">{s.input.refs.join(', ')}</p>
                )}
              </div>
              <div>
                <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">操作 (Operation)</p>
                <p className="mt-0.5 text-[11px] text-foreground">{s.operation}</p>
              </div>
              <div>
                <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">产出 (Output)</p>
                <p className="mt-0.5 text-[11px] text-foreground">{s.output}</p>
              </div>
              <div>
                <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">判据 (Criterion)</p>
                <p className="mt-0.5 text-[11px] text-foreground">{s.criterion}</p>
              </div>
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}

/**
 * §3.6 / F1：主案例 / 补充验证场景 / 材料清单 — 课题级产物（不在单项目内）。
 * 这里仅提供入口与说明，不在单项目 evaluation scope 内编辑或锁定。
 */
export function ProjectLevelArtifactsPanel({ payload }: { payload?: Record<string, unknown> }) {
  const artifacts = asRecord(payload)
  const mainCase = asRecord(artifacts?.main_case)
  const supplementary = asArray(artifacts?.supplementary_scenarios)
  const materials = asArray(artifacts?.material_inventory)
  return (
    <div className="rounded-md border border-border p-3">
      <PanelTitle
        title="课题级产物（§3.6 / F1 主案例 · 补充场景 · 材料清单）"
        helpText="以下三项为课题研究级产物，不在单项目 evaluation scope 内编辑或锁定——它们是单项目 scenario_summary 的上游输入，在研究侧维护。"
      />
      <div className="mt-2 grid gap-2 md:grid-cols-3">
        <div className="rounded-md border border-border bg-muted/30 p-3">
          <p className="text-sm font-semibold text-foreground">主案例</p>
          {mainCase ? (
            <>
              <p className="mt-1 text-[11px] text-foreground">{String(mainCase.name ?? '')}</p>
              <p className="mt-1 text-[11px] text-muted-foreground">{String(mainCase.description ?? '')}</p>
              <div className="mt-1 flex flex-wrap gap-1">
                {mainCase.risk_level ? <span className="rounded bg-destructive/10 px-1.5 py-0.5 text-[10px] font-medium text-destructive">{String(mainCase.risk_level)}</span> : null}
                {mainCase.hitl_level ? <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">{String(mainCase.hitl_level)}</span> : null}
              </div>
              {Array.isArray(mainCase.core_roles) && mainCase.core_roles.length > 0 && (
                <p className="mt-1 text-[10px] text-muted-foreground">角色：{mainCase.core_roles.join(' / ')}</p>
              )}
            </>
          ) : (
            <p className="mt-1 text-[11px] text-muted-foreground">课题核心代表性案例（贷后风险监测），研究侧草稿。</p>
          )}
        </div>
        <div className="rounded-md border border-border bg-muted/30 p-3">
          <p className="text-sm font-semibold text-foreground">补充验证场景</p>
          {supplementary.length > 0 ? (
            <ul className="mt-1 space-y-1">
              {supplementary.map((it, i) => {
                const rec = asRecord(it)
                if (!rec) return null
                return (
                  <li key={`sup-${i}`} className="text-[11px]">
                    <span className="font-medium text-foreground">{String(rec.name ?? '')}</span>
                    <span className="ml-1 text-muted-foreground">({String(rec.similarity ?? '')})</span>
                    <p className="text-[10px] text-muted-foreground">{String(rec.purpose ?? '')}</p>
                  </li>
                )
              })}
            </ul>
          ) : (
            <p className="mt-1 text-[11px] text-muted-foreground">2-3 个相近场景用于迁移验证（授信准入 / 反欺诈 / 客户画像）。</p>
          )}
        </div>
        <div className="rounded-md border border-border bg-muted/30 p-3">
          <p className="text-sm font-semibold text-foreground">材料清单</p>
          {materials.length > 0 ? (
            <ul className="mt-1 space-y-1">
              {materials.map((it, i) => {
                const rec = asRecord(it)
                if (!rec) return null
                return (
                  <li key={`mat-${i}`} className="text-[11px] text-muted-foreground">
                    <span className="font-medium text-foreground">{String(rec.name ?? '')}</span>
                    <span className="ml-1 rounded bg-muted px-1 py-0.5 text-[10px]">{String(rec.type ?? '')}</span>
                  </li>
                )
              })}
            </ul>
          ) : (
            <p className="mt-1 text-[11px] text-muted-foreground">全课题共享输入材料目录（法规 / 标准 / SOP 模板）。</p>
          )}
        </div>
      </div>
    </div>
  )
}


export function TagPanel({ title, items, helpText }: { title: string; items: unknown[]; helpText?: ReactNode }) {
  if (!items.length) return null

  return (
    <div className="rounded-md border border-border p-3">
      <PanelTitle title={title} helpText={helpText} />
      <div className="mt-2 flex flex-wrap gap-2">
        {items.map((item, index) => (
          <span key={`${formatValue(item)}-${index}`} className="rounded-md bg-muted px-2 py-1 text-[11px] text-muted-foreground">
            {formatValue(item)}
          </span>
        ))}
      </div>
    </div>
  )
}

/**
 * 卡片网格面板：把 items 渲染为卡片网格，宽屏一行四个，逐级降列数。
 * 每张卡片展示记录的标题字段 + 其余字段平铺。用于禁止条件这类需要"横向填充、
 * 一目了然"的场景。无记录或纯文本项则按文本卡片兜底。
 */
export function CardGridPanel({ title, items, helpText, columns = 4 }: { title: string; items: unknown[]; helpText?: ReactNode; columns?: number }) {
  if (!items.length) return null

  // 响应式列数：宽屏 columns 列，逐级降到 2 列、1 列
  const colsCls = {
    4: 'grid gap-3 sm:grid-cols-2 lg:grid-cols-4',
    3: 'grid gap-3 sm:grid-cols-2 lg:grid-cols-3',
    2: 'grid gap-3 sm:grid-cols-2',
    1: 'grid gap-3',
  }[columns] ?? 'grid gap-3 sm:grid-cols-2 lg:grid-cols-4'

  return (
    <div className="rounded-md border border-border p-3">
      <PanelTitle title={title} helpText={helpText} />
      <div className={colsCls}>
        {items.map((item, index) => {
          const record = asRecord(item)
          if (!record) {
            return (
              <div key={`${formatValue(item)}-${index}`} className="rounded-md bg-muted/40 p-2 text-sm text-foreground">
                {formatValue(item)}
              </div>
            )
          }
          const entries = Object.entries(record)
          const titleValue = getFirst(record, ['condition', 'name', 'title', 'item']) ?? `条目 ${index + 1}`
          return (
            <div key={`${formatValue(titleValue)}-${index}`} className="rounded-md border border-border bg-muted/40 p-2">
              <p className="text-sm font-medium text-foreground">{formatValue(titleValue)}</p>
              {entries
                .filter(([key]) => !['condition', 'name', 'title', 'item'].includes(key))
                .map(([key, value]) => (
                  <p key={key} className="mt-1 text-[11px] text-muted-foreground">
                    {key}：{formatValue(value)}
                  </p>
                ))}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function ObjectListPanel({ title, items, helpText }: { title: string; items: unknown[]; helpText?: ReactNode }) {
  if (!items.length) return null

  return (
    <div className="rounded-md border border-border p-3">
      <PanelTitle title={title} helpText={helpText} />
      <div className="mt-2 space-y-2">
        {items.map((item, index) => {
          const record = asRecord(item)
          if (!record) {
            return (
              <div key={`${formatValue(item)}-${index}`} className="rounded-md bg-muted/40 p-2 text-sm text-foreground">
                {formatValue(item)}
              </div>
            )
          }

          const entries = Object.entries(record)
          const titleValue = getFirst(record, ['name', 'title', 'item', 'node', 'task_id', 'sample_id', 'metric', 'dimension']) ?? `记录 ${index + 1}`
          return (
            <div key={`${formatValue(titleValue)}-${index}`} className="rounded-md bg-muted/40 p-2">
              <p className="text-sm text-foreground">{formatValue(titleValue)}</p>
              {entries
                .filter(([key]) => !['name', 'title', 'item', 'node', 'task_id', 'sample_id', 'metric', 'dimension'].includes(key))
                .map(([key, value]) => (
                  <p key={key} className="mt-1 text-[11px] text-muted-foreground">
                    {key}：{formatValue(value)}
                  </p>
                ))}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function RawPayloadPanel({ payload }: { payload: ResultPayload }) {
  return (
    <details className="rounded-md border border-border bg-muted/20 p-3">
      <summary className="cursor-pointer text-xs text-muted-foreground">查看原始结果字段</summary>
      <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap text-xs leading-6 text-foreground">
        {JSON.stringify(payload, null, 2)}
      </pre>
    </details>
  )
}

/**
 * 错误放大路径面板（F3 产物）：把 risk-bound 节点向下游推导的放大链
 * 渲染为「起点 → 下游链 → 放大机制」卡片列表，缺失时显示缺失提示。
 */
export function ErrorAmplificationPathsPanel({ items }: { items: unknown[] }) {
  const paths = items
    .map((item) => asRecord(item))
    .filter((rec): rec is Record<string, unknown> => Boolean(rec)) as Record<string, unknown>[]

  if (!paths.length) {
    return (
      <div className="rounded-md border border-dashed border-muted-foreground/40 bg-muted/30 p-3 text-xs text-muted-foreground">
        <PanelTitle title="错误放大路径" helpText="M1 硬性收口：L2/L3 风险至少 3 条可定位的错误放大路径。当前未生成，请在证据中补充风险绑定节点或人工复核点。" />
        <p className="mt-2">当前未生成错误放大路径（L2/L3 风险至少需 3 条）。</p>
      </div>
    )
  }

  return (
    <div className="rounded-md border border-border p-3">
      <PanelTitle title="错误放大路径" helpText="从风险绑定节点向下游推导的放大链：起点风险 → 下游节点链 → 放大机制，用于判断一旦出错会放大到什么程度。" />
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        {paths.map((path, index) => {
          const downstream = Array.isArray(path.downstream_node_ids) ? path.downstream_node_ids : []
          const mechanisms = Array.isArray(path.amplification_mechanisms) ? path.amplification_mechanisms : []
          const reached = path.terminal_reached === true
          return (
            <div key={`eap-${index}`} className="rounded-md border border-border bg-muted/40 p-2">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-medium text-foreground">
                  {String(path.path_id ?? `路径 ${index + 1}`)}
                  <span className="ml-2 text-[11px] text-muted-foreground">{String(path.start_node_name ?? '')}</span>
                </p>
                <span className={`rounded px-1.5 py-0.5 text-[10px] ${reached ? 'bg-emerald-500/10 text-emerald-700' : 'bg-amber-500/10 text-amber-700'}`}>
                  {reached ? '已到达终点' : '未到达终点'}
                </span>
              </div>
              {typeof path.trigger_risk === 'string' && path.trigger_risk && (
                <p className="mt-1 text-[11px] text-muted-foreground">触发风险：{path.trigger_risk}</p>
              )}
              {downstream.length > 0 && (
                <div className="mt-1 flex flex-wrap items-center gap-1">
                  <span className="text-[11px] text-muted-foreground">下游链：</span>
                  {downstream.map((id, i) => (
                    <span key={`${id}-${i}`} className="rounded bg-background px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground ring-1 ring-border/70">
                      {String(id)}
                    </span>
                  ))}
                </div>
              )}
              {mechanisms.length > 0 && (
                <ul className="mt-1 space-y-0.5">
                  {mechanisms.map((m, i) => (
                    <li key={`m-${i}`} className="text-[11px] text-amber-700">• {String(m)}</li>
                  ))}
                </ul>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

/**
 * 跨系统链路面板（F2 产物）：每个流程节点绑定的系统与链路类型。
 */
export function CrossSystemLinksPanel({ items }: { items: unknown[] }) {
  const links = items
    .map((item) => asRecord(item))
    .filter((rec): rec is Record<string, unknown> => Boolean(rec)) as Record<string, unknown>[]

  if (!links.length) {
    return (
      <div className="rounded-md border border-dashed border-muted-foreground/40 bg-muted/30 p-3 text-xs text-muted-foreground">
        <PanelTitle title="跨系统链路" helpText="流程节点绑定的跨系统链路（预警平台/贷后系统/核心系统等），用于判断系统交互复杂度。当前未生成。" />
        <p className="mt-2">当前未生成跨系统链路绑定。</p>
      </div>
    )
  }

  return (
    <div className="rounded-md border border-border p-3">
      <PanelTitle title="跨系统链路" helpText="每个流程节点绑定的系统与链路类型，体现系统交互复杂度。" />
      <div className="mt-2 space-y-2">
        {links.map((link, index) => {
          const systems = Array.isArray(link.systems) ? link.systems : []
          return (
            <div key={`csl-${index}`} className="rounded-md border border-border bg-muted/40 p-2">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="font-mono text-[10px] text-muted-foreground">{String(link.node_id ?? '')}</span>
                <span className="text-sm font-medium text-foreground">{String(link.node_name ?? '')}</span>
                <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] text-secondary-foreground">
                  {String(link.link_type ?? 'reference')}
                </span>
                {systems.map((sys, i) => (
                  <span key={`${sys}-${i}`} className="rounded-md bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">
                    {String(sys)}
                  </span>
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

/**
 * 本项目边界认可状态小徽标（F1）：单项目级，描述本项目场景边界是否已获
 * 业务侧认可。主案例定义 / 补充验证场景 / 材料清单是课题级产物（每个
 * Project 是一个独立案例，主案例与补充场景的区分是课题级研究对象决策），
 * 不在单项目 scenario_summary 内。
 */
export function BoundaryReviewStatusBadge({ reviewStatus }: { reviewStatus?: string }) {
  const reviewLabel = reviewStatus === 'business_confirmed'
    ? '业务侧已认可'
    : reviewStatus === 'business_rejected'
      ? '业务侧已退回'
      : '业务侧待认可'
  const tone = reviewStatus === 'business_confirmed'
    ? 'bg-emerald-500/10 text-emerald-700'
    : reviewStatus === 'business_rejected'
      ? 'bg-destructive/10 text-destructive'
      : 'bg-amber-500/10 text-amber-700'
  return (
    <div className="rounded-md border border-border p-3">
      <PanelTitle title="边界业务侧认可状态" helpText="本项目场景边界是否已获业务侧初步认可。M1 关卡要求主案例边界获业务侧认可；认可证据需线下取得，平台只标记状态。" />
      <div className="mt-2">
        <span className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium ${tone}`}>
          {reviewLabel}
        </span>
      </div>
    </div>
  )
}

/**
 * 风险分级矩阵（B 类分级治理映射）：风险等级 → HITL 强度 / 准入规则 / 最小审计留痕要求
 *
 * 渲染为真正的二维表格，让"分级→治理配置"的映射关系一目了然。矩阵始终完整显示
 * L1/L2/L3 三行（与开题报告三级风险等级对齐），即使某等级暂无风险项也保留行结构。
 * 每行的"涉及风险项"列填入真实风险项的小卡片，点击卡片弹出该风险项的完整详情。
 *
 * 数据来源：
 * - 若 risk_governance_matrix 字段已落地（items 非空），直接用后端数据
 * - 否则用 L1/L2/L3 固定模板生成三行，治理配置文本从 RISK_LEVEL_TO_* 映射表取
 * - risk_ids 从真实 risk_items 按 risk_level 分组填入对应行
 */
export function RiskGovernanceMatrixPanel({
  items,
  riskItems,
  evidenceMap,
}: {
  items: unknown[]
  riskItems?: unknown[]
  evidenceMap?: Map<string, { name: string }>
}) {
  // Build a lookup map: risk_id -> risk_item record, for card + detail lookup.
  const riskItemMap = new Map<string, Record<string, unknown>>()
  // Group real risk_items by risk_level: level -> [risk_id, ...]
  const riskIdsByLevel = new Map<string, string[]>()
  for (const raw of (riskItems ?? [])) {
    const rec = asRecord(raw)
    if (!rec) continue
    const rid = rec.risk_id ? String(rec.risk_id) : ''
    if (rid) riskItemMap.set(rid, rec)
    const lvl = String(rec.risk_level ?? '').toUpperCase().trim()
    if (!['L1', 'L2', 'L3'].includes(lvl) || !rid) continue
    if (!riskIdsByLevel.has(lvl)) riskIdsByLevel.set(lvl, [])
    riskIdsByLevel.get(lvl)!.push(rid)
  }

  // 矩阵行：若后端字段已落地则直接用；否则用 L1/L2/L3 固定模板（保证三行齐全）
  const rows = items.length
    ? (items.map(item => asRecord(item)).filter(Boolean) as Record<string, unknown>[])
    : DEFAULT_MATRIX_ROWS.map(row => ({
        ...row,
        risk_ids: riskIdsByLevel.get(row.risk_level) ?? [],
      }))

  if (!rows.length) return null

  return (
    <div className="rounded-md border border-border p-3">
      <PanelTitle title="风险分级矩阵" helpText="将风险等级映射为 HITL 强度、准入规则与最小审计留痕要求。每行的风险项以卡片形式展示，点击查看详情。" />
      <div className="mt-2 overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-border text-left text-[11px] text-muted-foreground">
              <th className="p-2 font-medium">风险等级</th>
              <th className="p-2 font-medium">HITL 强度</th>
              <th className="p-2 font-medium">准入规则</th>
              <th className="p-2 font-medium">最小审计留痕要求</th>
              <th className="p-2 font-medium">涉及风险项</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => {
              const level = formatValue(row.risk_level)
              const riskIds: string[] = Array.isArray(row.risk_ids)
                ? row.risk_ids.map(String)
                : []
              return (
                <tr key={`${level}-${idx}`} className="border-b border-border/50 align-top">
                  <td className="p-2 font-medium text-foreground">
                    <RiskLevelBadge level={level} />
                  </td>
                  <td className="p-2">
                    <HitlLevelBadge level={formatValue(row.hitl_level)} />
                  </td>
                  <td className="p-2 text-foreground">{formatValue(row.admission_rule)}</td>
                  <td className="p-2 text-muted-foreground">{formatValue(row.audit_requirement)}</td>
                  <td className="p-2">
                    <div className="flex flex-wrap gap-1.5">
                      {riskIds.length ? (
                        riskIds.map(rid => (
                          <RiskItemChip key={rid} riskId={rid} item={riskItemMap.get(rid)} evidenceMap={evidenceMap} />
                        ))
                      ) : (
                        <span className="text-[11px] text-muted-foreground">—</span>
                      )}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/**
 * 风险项小卡片：显示 risk_id + 描述前缀，点击弹出该风险项的完整详情。
 * 卡片左边框颜色根据风险等级（risk_level）区分：L1 绿、L2 琥珀、L3 玫红，
 * 让风险程度一目了然。当无法从 riskItems 里查到对应记录时（数据不一致），
 * 显示虚线占位卡片作为告警。
 */
function RiskItemChip({ riskId, item, evidenceMap }: { riskId: string; item?: Record<string, unknown>; evidenceMap?: Map<string, { name: string }> }) {
  if (!item) {
    return (
      <span
        className="inline-flex items-center rounded-md border border-dashed border-destructive/40 bg-destructive/5 px-2 py-0.5 text-[11px] text-muted-foreground"
        title={`未找到 ${riskId} 对应的风险项记录（数据不一致）`}
      >
        {riskId} ⚠
      </span>
    )
  }

  const description = formatValue(item.description)
  const shortLabel = description && description !== '—'
    ? (description.length > 10 ? `${description.slice(0, 10)}…` : description)
    : riskId
  const level = String(item.risk_level ?? '').toUpperCase().trim()
  const levelStyle = RISK_LEVEL_TO_CHIP_STYLE[level] ?? RISK_LEVEL_TO_CHIP_STYLE.default

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] transition-colors hover:brightness-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${levelStyle}`}
        >
          <span className="font-mono text-[10px] opacity-70">{riskId}</span>
          <span>{shortLabel}</span>
        </button>
      </PopoverTrigger>
      <PopoverContent side="bottom" align="start" className="w-80 max-w-[90vw] p-3">
        <RiskItemDetail item={item} evidenceMap={evidenceMap} />
      </PopoverContent>
    </Popover>
  )
}

/** 风险项详情：在 Popover 里展开全部字段。evidence_refs 字段优先显示原证据文件名。 */
function RiskItemDetail({ item, evidenceMap }: { item: Record<string, unknown>; evidenceMap?: Map<string, { name: string }> }) {
  const entries = Object.entries(item)
  const titleValue = getFirst(item, ['description', 'risk_id']) ?? '风险项'

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2 border-b border-border pb-2">
        <p className="text-sm font-semibold text-foreground">{formatValue(titleValue)}</p>
        {item.risk_level ? <RiskLevelBadge level={formatValue(item.risk_level)} /> : null}
      </div>
      <dl className="space-y-1.5">
        {entries
          .filter(([key]) => !['description', 'risk_id', 'risk_level'].includes(key))
          .map(([key, value]) => (
            <div key={key} className="flex gap-2 text-[12px] leading-5">
              <dt className="shrink-0 text-muted-foreground">{RISK_ITEM_LABELS[key] ?? key}：</dt>
              <dd className="break-words text-foreground">
                {Array.isArray(value) ? (
                  value.length ? (
                    key === 'evidence_refs' && evidenceMap ? (
                      <div className="flex flex-wrap gap-1">
                        {value.map((v, i) => {
                          const refId = formatValue(v)
                          const ev = evidenceMap.get(refId)
                          return (
                            <span key={i} className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground" title={ev ? `${refId} → ${ev.name}` : refId}>
                              {ev ? ev.name : refId}
                            </span>
                          )
                        })}
                      </div>
                    ) : (
                      <div className="flex flex-wrap gap-1">
                        {value.map((v, i) => (
                          <span key={i} className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                            {formatValue(v)}
                          </span>
                        ))}
                      </div>
                    )
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )
                ) : (
                  formatValue(value) || <span className="text-muted-foreground">—</span>
                )}
              </dd>
            </div>
          ))}
      </dl>
    </div>
  )
}

const RISK_ITEM_LABELS: Record<string, string> = {
  node_id: '所属节点',
  severity: '严重度',
  likelihood: '发生概率',
  impact: '影响',
  owner_role: '责任角色',
  mitigation: '缓解措施',
  audit_need: '审计需求',
  evidence_refs: '证据引用',
  evidence_verified: '证据校验',
}

function RiskLevelBadge({ level }: { level: string }) {
  const styles: Record<string, string> = {
    L1: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
    L2: 'bg-amber-500/10 text-amber-600 dark:text-amber-400',
    L3: 'bg-rose-500/10 text-rose-600 dark:text-rose-400',
  }
  const cls = styles[level] || 'bg-muted text-muted-foreground'
  return <span className={`inline-block rounded-md px-2 py-0.5 text-xs font-semibold ${cls}`}>{level || '—'}</span>
}

function HitlLevelBadge({ level }: { level: string }) {
  const styles: Record<string, string> = {
    none: 'bg-muted text-muted-foreground',
    standard: 'bg-sky-500/10 text-sky-600 dark:text-sky-400',
    strict: 'bg-orange-500/10 text-orange-600 dark:text-orange-400',
    mandatory: 'bg-rose-500/15 text-rose-700 dark:text-rose-300',
  }
  const cls = styles[level] || 'bg-muted text-muted-foreground'
  return <span className={`inline-block rounded-md px-2 py-0.5 text-xs font-medium ${cls}`}>{level || '—'}</span>
}

// ── 矩阵固定模板 + 治理配置映射表 ──

// 与后端 registry.py 的 _hitl_map / _admission_rule / _audit_requirement 保持一致
const RISK_LEVEL_TO_HITL: Record<string, string> = {
  L1: 'none',
  L2: 'standard',
  L3: 'mandatory',
}

const RISK_LEVEL_TO_ADMISSION: Record<string, string> = {
  L1: '常规评审通过即可立项',
  L2: '需业务负责人 + 风险负责人双签确认',
  L3: '需风险委员会评审 + 强制人工复核节点',
}

const RISK_LEVEL_TO_AUDIT: Record<string, string> = {
  L1: '基础日志留痕，保留关键决策记录',
  L2: '完整审计留痕，关键节点双录',
  L3: '强审计留痕，全链路可追溯 + 定期回溯校准',
}

// 风险项卡片整体配色：按风险等级（risk_level）区分风险程度
// L1 绿色（低）/ L2 琥珀（中）/ L3 玫红（高）/ 灰色（未知/未分级）
// 整个标签的边框+背景+文字色都随等级变化
const RISK_LEVEL_TO_CHIP_STYLE: Record<string, string> = {
  L1: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  L2: 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300',
  L3: 'border-rose-500/40 bg-rose-500/10 text-rose-700 dark:text-rose-300',
  default: 'border-border bg-muted/50 text-foreground',
}

/**
 * 默认矩阵行模板：始终完整显示 L1/L2/L3 三行，与开题报告三级风险等级对齐。
 * 即使某等级暂无风险项（risk_ids 为空），也保留行结构，显示"—"占位。
 * 当后端 risk_governance_matrix 字段落地后，直接用后端数据替换此模板。
 */
const DEFAULT_MATRIX_ROWS = [
  {
    risk_level: 'L1',
    hitl_level: RISK_LEVEL_TO_HITL.L1,
    admission_rule: RISK_LEVEL_TO_ADMISSION.L1,
    audit_requirement: RISK_LEVEL_TO_AUDIT.L1,
  },
  {
    risk_level: 'L2',
    hitl_level: RISK_LEVEL_TO_HITL.L2,
    admission_rule: RISK_LEVEL_TO_ADMISSION.L2,
    audit_requirement: RISK_LEVEL_TO_AUDIT.L2,
  },
  {
    risk_level: 'L3',
    hitl_level: RISK_LEVEL_TO_HITL.L3,
    admission_rule: RISK_LEVEL_TO_ADMISSION.L3,
    audit_requirement: RISK_LEVEL_TO_AUDIT.L3,
  },
]
