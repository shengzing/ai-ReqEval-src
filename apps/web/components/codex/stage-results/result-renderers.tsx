'use client'

import type { ReactNode } from 'react'
import { CircleHelp } from 'lucide-react'

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import {
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
