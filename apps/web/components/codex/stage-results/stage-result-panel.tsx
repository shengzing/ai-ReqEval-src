'use client'

import type { ReactNode } from 'react'
import { CheckCircle2, Wrench } from 'lucide-react'
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

  if (stageSuffix === 'stage-1') {
    return <ResultWithConfirmedNodes stage={stage}><StageOneScenarioPanel stage={stage} evidenceItems={evidenceItems} /></ResultWithConfirmedNodes>
  }
  if (stageSuffix === 'stage-2') {
    return <ResultWithConfirmedNodes stage={stage}><StageTwoValuePanel stage={stage} /></ResultWithConfirmedNodes>
  }
  if (stageSuffix === 'stage-3') {
    return <ResultWithConfirmedNodes stage={stage}><StageThreeProbePanel stage={stage} /></ResultWithConfirmedNodes>
  }
  if (stageSuffix === 'stage-4') {
    return <ResultWithConfirmedNodes stage={stage}><StageFourDecisionPanel stage={stage} /></ResultWithConfirmedNodes>
  }

  return (
    <ResultWithConfirmedNodes stage={stage}>
      <p className="mb-3 text-sm text-muted-foreground">当前阶段类型暂未匹配到专用面板，以下保留后端返回的原始结果字段。</p>
      <RawPayloadPanel payload={stage.resultPayload ?? {}} />
    </ResultWithConfirmedNodes>
  )
}

function ResultWithConfirmedNodes({ stage, children }: { stage: Stage; children: ReactNode }) {
  const confirmedNodes = Array.isArray(stage.resultPayload?.confirmed_execution_nodes)
    ? stage.resultPayload.confirmed_execution_nodes
    : []

  return (
    <div className="space-y-3">
      {children}
      {confirmedNodes.length > 0 && (
        <section className="rounded-lg border border-primary/25 bg-primary/[0.04] p-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <CheckCircle2 className="size-4 text-primary" />
            已确认的执行输出
          </div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">这些工具结果已由人工确认并写入本阶段版本，可展开查看审计信息。</p>
          <div className="mt-2 space-y-2">
            {confirmedNodes.map((item, index) => {
              const node = item && typeof item === 'object' && !Array.isArray(item)
                ? item as Record<string, unknown>
                : {}
              const name = typeof node.tool_name === 'string' ? node.tool_name : `执行节点 ${index + 1}`
              return (
                <details key={`${name}-${index}`} className="rounded-md border border-border bg-card px-3 py-2">
                  <summary className="flex cursor-pointer list-none items-center gap-2 text-xs font-medium text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                    <Wrench className="size-3.5 text-primary" />
                    {name}
                  </summary>
                  <pre className="mt-2 max-h-48 overflow-auto rounded bg-muted/40 p-2 text-[11px] leading-5 text-foreground">
                    {JSON.stringify(node, null, 2)}
                  </pre>
                </details>
              )
            })}
          </div>
        </section>
      )}
    </div>
  )
}
