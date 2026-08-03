'use client'

import type { Stage } from '@/lib/types'
import { asArray, asRecord, getFirst, Metric, ObjectListPanel, RawPayloadPanel, TagPanel } from './result-renderers'

export function StageFourDecisionPanel({ stage }: { stage: Stage }) {
  const payload = stage.resultPayload ?? {}
  const stageResult = asRecord(payload.stage_4_result) ?? asRecord(payload.decision_result) ?? payload

  return (
    <div>
      <div className="grid gap-3 md:grid-cols-3">
        <Metric label="风险对齐" value={getFirst(stageResult, ['risk_alignment'])} />
        <Metric label="价值对齐" value={getFirst(stageResult, ['value_alignment'])} />
        <Metric label="技术对齐" value={getFirst(stageResult, ['technical_alignment'])} />
        <Metric label="最终建议" value={getFirst(stageResult, ['recommendation', 'final_recommendation', 'decision'])} className="md:col-span-3" />
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <ObjectListPanel title="硬约束检查" items={asArray(getFirst(stageResult, ['hard_constraints', 'constraints']))} />
        <ObjectListPanel title="目标-实际差距" items={normalizeObjectOrArray(getFirst(stageResult, ['target_actual_gap', 'sla_gap']))} />
        <ObjectListPanel title="证据融合" items={asArray(getFirst(stageResult, ['evidence_fusion', 'evidence_refs', 'evidences']))} />
        <ObjectListPanel title="决策卡 / 报告 / 证据目录" items={normalizeDecisionArtifacts(stageResult)} />
      </div>
      <div className="mt-3">
        <TagPanel title="需补齐动作" items={asArray(getFirst(stageResult, ['required_actions', 'actions']))} />
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

function normalizeDecisionArtifacts(stageResult: Record<string, unknown>) {
  const keys = ['decision_card_path', 'report_path', 'evidence_catalog_path', 'archive_path']
  const artifacts = keys
    .map((key) => ({ title: key, value: stageResult[key] }))
    .filter((item) => item.value)
  const nested = asArray(getFirst(stageResult, ['artifacts', 'outputs']))
  return [...artifacts, ...nested]
}
