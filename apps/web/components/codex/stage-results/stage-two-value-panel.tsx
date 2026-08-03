'use client'

import type { Stage } from '@/lib/types'
import { asArray, asRecord, getFirst, Metric, ObjectListPanel, RawPayloadPanel, TagPanel } from './result-renderers'

export function StageTwoValuePanel({ stage }: { stage: Stage }) {
  const payload = stage.resultPayload ?? {}
  const stageResult = asRecord(payload.stage_2_result) ?? asRecord(payload.value_result) ?? payload

  return (
    <div>
      <div className="grid gap-3 md:grid-cols-3">
        <Metric label="实施税合计" value={getFirst(stageResult, ['implementation_tax_total', 'implementation_tax', 'tax_total'])} />
        <Metric label="净价值" value={getFirst(stageResult, ['net_value', 'net_benefit', 'value'])} />
        <Metric label="目标 SLA" value={getFirst(stageResult, ['target_sla', 'target_sla_score', 'sla_target'])} />
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <ObjectListPanel title="目标 SLA 组件" items={normalizeObjectOrArray(getFirst(stageResult, ['target_sla_components', 'sla_components']))} />
        <ObjectListPanel title="敏感性分析" items={asArray(getFirst(stageResult, ['sensitivity_results', 'sensitivity_analysis', 'sensitivity']))} />
        <ObjectListPanel title="参数来源 / 证据引用" items={asArray(getFirst(stageResult, ['evidence_refs', 'parameter_sources', 'sources']))} />
        <TagPanel title="需补充参数" items={asArray(getFirst(stageResult, ['required_supplements', 'missing_parameters']))} />
      </div>
      <div className="mt-3">
        <ObjectListPanel title="盈亏平衡条件" items={normalizeObjectOrArray(getFirst(stageResult, ['break_even_conditions', 'break_even']))} />
      </div>
      <div className="mt-3">
        <RawPayloadPanel payload={payload} />
      </div>
    </div>
  )
}

function normalizeObjectOrArray(value: unknown) {
  if (Array.isArray(value)) return value
  const record = asRecord(value)
  return record ? Object.entries(record).map(([metric, target]) => ({ metric, target })) : []
}
