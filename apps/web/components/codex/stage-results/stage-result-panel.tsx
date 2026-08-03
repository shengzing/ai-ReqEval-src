'use client'

import type { EvidenceItem, Stage } from '@/lib/types'
import { ResultEmptyState } from './result-empty-state'
import { RawPayloadPanel } from './result-renderers'
import { getStageSuffix, hasRenderablePayload } from './result-utils'
import { StageFourDecisionPanel } from './stage-four-decision-panel'
import { StageOneScenarioPanel } from './stage-one-scenario-panel'
import { StageThreeProbePanel } from './stage-three-probe-panel'
import { StageTwoValuePanel } from './stage-two-value-panel'

interface StageResultPanelProps {
  stage: Stage
  evidenceItems?: EvidenceItem[]
  onStartRun?: () => Promise<void> | void
}

export function StageResultPanel({ stage, evidenceItems, onStartRun }: StageResultPanelProps) {
  if (!hasRenderablePayload(stage.resultPayload)) {
    return <ResultEmptyState stageName={stage.name} onStartRun={onStartRun} />
  }

  const stageSuffix = getStageSuffix(stage.id)

  if (stageSuffix === 'stage-1') return <StageOneScenarioPanel stage={stage} evidenceItems={evidenceItems} />
  if (stageSuffix === 'stage-2') return <StageTwoValuePanel stage={stage} />
  if (stageSuffix === 'stage-3') return <StageThreeProbePanel stage={stage} />
  if (stageSuffix === 'stage-4') return <StageFourDecisionPanel stage={stage} />

  return (
    <div>
      <p className="mb-3 text-sm text-muted-foreground">当前阶段类型暂未匹配到专用面板，以下保留后端返回的原始结果字段。</p>
      <RawPayloadPanel payload={stage.resultPayload ?? {}} />
    </div>
  )
}
