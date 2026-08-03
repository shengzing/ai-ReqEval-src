'use client'

import type { Stage } from '@/lib/types'
import { asArray, asRecord, getFirst, Metric, ObjectListPanel, RawPayloadPanel } from './result-renderers'

export function StageThreeProbePanel({ stage }: { stage: Stage }) {
  const payload = stage.resultPayload ?? {}
  const stageResult = asRecord(payload.stage_3_result) ?? asRecord(payload.probe_result) ?? payload

  return (
    <div>
      <div className="grid gap-3 md:grid-cols-3">
        <Metric label="Actual SLA" value={getFirst(stageResult, ['actual_sla', 'actual_sla_score', 'sla_actual'])} />
        <Metric label="质量 SLA" value={getFirst(stageResult, ['quality_sla', 'quality_score'])} />
        <Metric label="治理 SLA" value={getFirst(stageResult, ['governance_sla', 'governance_score'])} />
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <ObjectListPanel title="原子任务" items={asArray(getFirst(stageResult, ['atomic_tasks', 'tasks']))} />
        <ObjectListPanel title="样本台账" items={asArray(getFirst(stageResult, ['sample_ledger', 'samples', 'sample_records']))} />
        <ObjectListPanel title="低分归因" items={asArray(getFirst(stageResult, ['low_score_reasons', 'failure_reasons', 'error_distribution']))} />
        <ObjectListPanel title="人工复核负担" items={normalizeObjectOrArray(getFirst(stageResult, ['human_review_load', 'review_burden']))} />
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
  return record ? Object.entries(record).map(([metric, value]) => ({ metric, value })) : []
}
