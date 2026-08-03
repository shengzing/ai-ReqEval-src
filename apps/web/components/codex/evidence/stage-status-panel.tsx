'use client'

import { AlertCircle, Check, Lock } from 'lucide-react'

import { ScrollArea } from '@/components/ui/scroll-area'
import { buildLockChecklist, buildStageChecklist } from '@/lib/api-mappers'
import { cn } from '@/lib/utils'
import type { Stage } from '@/lib/types'
import { LockChecklistPanel } from './lock-checklist-panel'

interface StageStatusPanelProps {
  currentStage?: string
  stage?: Stage
  evidenceCount: number
}

export function StageStatusPanel({ currentStage, stage, evidenceCount }: StageStatusPanelProps) {
  const checklist = buildStageChecklist(stage, evidenceCount)
  const lockChecklist = buildLockChecklist(stage, evidenceCount)
  const statusLabel = {
    not_started: '未开始',
    in_progress: '进行中',
    waiting_user: '待确认',
    locked: '已锁定',
    completed: '已完成',
    needs_review: '待复核',
    failed: '失败',
  } satisfies Record<Stage['status'], string>

  return (
    <ScrollArea className="flex-1">
      <div className="space-y-4 p-4">
        <div className={cn('rounded-lg border border-border p-4', currentStage && stage?.id === currentStage && 'border-primary/50 bg-primary/5')}>
          <div className="mb-3 flex items-center gap-2">
            {stage?.status === 'completed' && <Check className="size-4 text-emerald-500" />}
            {stage?.status === 'locked' && <Lock className="size-4 text-amber-500" />}
            {stage?.status === 'in_progress' && <div className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />}
            {stage?.status === 'not_started' && <div className="size-4 rounded-full border-2 border-muted-foreground/30" />}
            {stage?.status === 'waiting_user' && <AlertCircle className="size-4 text-amber-500" />}
            {stage?.status === 'failed' && <AlertCircle className="size-4 text-red-500" />}
            <span className="text-sm font-medium text-foreground">{stage?.name ?? '未选择阶段'}</span>
          </div>

          <div className="mb-3 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
            <div className="rounded-md bg-muted/40 px-3 py-2">状态：{stage ? statusLabel[stage.status] : '-'}</div>
            <div className="rounded-md bg-muted/40 px-3 py-2">证据：{evidenceCount}</div>
            <div className="rounded-md bg-muted/40 px-3 py-2">对话：{stage?.conversations.length ?? 0}</div>
            <div className="rounded-md bg-muted/40 px-3 py-2">待确认：{stage?.pendingConfirmations ?? 0}</div>
          </div>

          <div className="space-y-2">
            {checklist.map((item) => (
              <div key={item.label} className="flex items-center gap-2 text-sm">
                {item.checked ? <Check className="size-3.5 text-emerald-500" /> : <div className="size-3.5 rounded border border-muted-foreground/30" />}
                <span className={cn(item.checked ? 'text-muted-foreground' : 'text-foreground')}>{item.label}</span>
              </div>
            ))}
          </div>
        </div>

        <LockChecklistPanel items={lockChecklist} />
      </div>
    </ScrollArea>
  )
}
