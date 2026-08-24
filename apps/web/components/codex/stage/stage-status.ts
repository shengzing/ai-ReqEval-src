import type { RunStatus, Stage } from '@/lib/types'

export function getStageStatusLabel(status: Stage['status'], runStatus?: RunStatus) {
  if (runStatus === 'running') return '正在运行当前阶段'
  if (runStatus === 'waiting_inputs') return '等待补充相关材料'
  if (runStatus === 'waiting_user') return '等待确认当前运行结果'
  if (runStatus === 'completed') return '当前运行已完成'
  if (runStatus === 'failed') return '当前运行失败'
  if (runStatus === 'cancelled') return '当前运行已取消'

  const labels: Record<Stage['status'], string> = {
    in_progress: '正在进行中',
    completed: '已完成',
    waiting_user: '等待确认',
    not_started: '未开始',
    locked: '已锁定',
    needs_review: '需要复核',
    failed: '执行失败',
  }
  return labels[status]
}

export function getRunPanelLabel(runStatus: RunStatus | undefined, toolCallCount: number) {
  if (runStatus === 'running') return '正在执行'
  if (runStatus === 'waiting_inputs') return '等待材料'
  if (runStatus === 'waiting_user') return '等待确认'
  if (runStatus === 'completed') return toolCallCount > 0 ? '执行结果' : '运行摘要'
  if (runStatus === 'failed') return '执行失败'
  if (runStatus === 'cancelled') return '已取消'
  return '执行流'
}

export function getStageRerunAvailability(
  stageId: string,
  runStatus: RunStatus | undefined,
  relatedEvidenceCount: number,
) {
  if (runStatus === 'queued' || runStatus === 'running') {
    return { disabled: true, reason: '当前运行尚未结束，请稍候。' }
  }
  if (stageId.endsWith('stage-1') && relatedEvidenceCount === 0) {
    return { disabled: true, reason: '请先解析材料并确认与项目相关，再重新运行。' }
  }
  return { disabled: false, reason: undefined }
}
