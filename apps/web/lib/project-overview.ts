import type { RunStatus, Stage, StageStatus } from './types'

export type ProjectStageExecutionStatus = {
  label: string
  tone: 'neutral' | 'active' | 'warning' | 'success' | 'danger'
}

/**
 * Produces the compact, project-level execution status shown for each stage.
 * A currently selected stage may have a newer live Run state than its persisted
 * Stage record, so that Run state takes precedence when it is available.
 */
export function getProjectStageExecutionStatus(
  stageStatus: StageStatus,
  runStatus?: RunStatus,
): ProjectStageExecutionStatus {
  const runStatusLabels: Partial<Record<RunStatus, ProjectStageExecutionStatus>> = {
    created: { label: '待执行', tone: 'neutral' },
    queued: { label: '待执行', tone: 'neutral' },
    running: { label: '执行中', tone: 'active' },
    waiting_inputs: { label: '等待材料', tone: 'warning' },
    waiting_user: { label: '待确认', tone: 'warning' },
    completed: { label: '已完成', tone: 'success' },
    failed: { label: '执行失败', tone: 'danger' },
    cancelled: { label: '已取消', tone: 'neutral' },
  }

  if (runStatus && runStatusLabels[runStatus]) return runStatusLabels[runStatus]

  const stageStatusLabels: Record<StageStatus, ProjectStageExecutionStatus> = {
    not_started: { label: '未执行', tone: 'neutral' },
    in_progress: { label: '执行中', tone: 'active' },
    waiting_user: { label: '待确认', tone: 'warning' },
    locked: { label: '已完成', tone: 'success' },
    completed: { label: '已完成', tone: 'success' },
    needs_review: { label: '待复核', tone: 'warning' },
    failed: { label: '执行失败', tone: 'danger' },
  }

  return stageStatusLabels[stageStatus]
}

export function getProjectStageShortName(stage: Pick<Stage, 'name'>) {
  return stage.name.split('：', 1)[0] || stage.name
}
