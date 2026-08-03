'use client'

import { FileText, RotateCcw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import type { RunStatus, Stage } from '@/lib/types'
import { getStageStatusLabel } from './stage-status'

interface StageHeaderProps {
  stage: Stage
  runStatus?: RunStatus
  onOpenRightSidebar?: () => void
  onStartRun?: (goal: string) => Promise<void> | void
}

export function StageHeader({ stage, runStatus, onOpenRightSidebar, onStartRun }: StageHeaderProps) {
  const isLocked = stage.status === 'locked'
  const stageStatusLabel = getStageStatusLabel(stage.status, runStatus)

  return (
    <div className="flex items-center justify-between border-b border-border px-6 py-4">
      <div className="flex items-center gap-3">
        <div className="flex size-8 items-center justify-center rounded-lg bg-primary/10">
          <FileText className="size-4 text-primary" />
        </div>
        <div>
          <h2 className="text-sm font-medium text-foreground">{stage.name}</h2>
          <p className="text-xs text-muted-foreground">{stageStatusLabel}</p>
        </div>
      </div>
      <div className="flex items-center gap-2">
        {!isLocked && onStartRun && (
          <Button
            variant="outline"
            size="sm"
            className="h-8 gap-1.5"
            onClick={() => void onStartRun(stage.objective ?? stage.nextStep ?? `${stage.name} 重新运行`)}
          >
            <RotateCcw className="size-3.5" />
            重新运行
          </Button>
        )}
        <Button variant="outline" size="sm" className="h-8 gap-1.5" onClick={onOpenRightSidebar}>
          <FileText className="size-3.5" />
          查看证据
        </Button>
      </div>
    </div>
  )
}
