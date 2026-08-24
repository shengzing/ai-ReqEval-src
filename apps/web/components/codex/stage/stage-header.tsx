'use client'

import { FolderKanban } from 'lucide-react'

import type { Project, RunStatus, Stage } from '@/lib/types'
import { cn, formatDateZh } from '@/lib/utils'
import { getProjectStageExecutionStatus, getProjectStageShortName } from '@/lib/project-overview'

interface StageHeaderProps {
  project?: Project
  stage: Stage
  runStatus?: RunStatus
}

const stageToneClasses = {
  neutral: 'bg-muted-foreground/50',
  active: 'bg-primary',
  warning: 'bg-warning',
  success: 'bg-success',
  danger: 'bg-destructive',
}

export function StageHeader({ project, stage, runStatus }: StageHeaderProps) {
  const projectStages = project?.stages ?? [stage]

  return (
    <header className="border-b border-border bg-card px-6 py-3">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10">
            <FolderKanban className="size-4 text-primary" />
          </div>
          <div className="min-w-0">
            <h1 className="truncate text-sm font-semibold text-foreground">{project?.name ?? '当前项目'}</h1>
            <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
              <span className="font-mono tabular-nums">项目 ID：{project?.id ?? stage.id.split('-stage-')[0]}</span>
              <span>创建于 {formatDateZh(project?.createdAt)}</span>
            </div>
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
          {projectStages.map((projectStage) => {
            const isCurrent = projectStage.id === stage.id
            const execution = getProjectStageExecutionStatus(
              isCurrent ? stage.status : projectStage.status,
              isCurrent ? runStatus : undefined,
            )
            return (
              <div
                key={projectStage.id}
                className={cn(
                  'flex items-center gap-1.5 rounded-full border px-2.5 py-1',
                  isCurrent
                    ? 'border-primary/40 bg-primary/5'
                    : 'border-border/60 bg-muted/25',
                )}
                title={projectStage.name}
              >
                <span className="shrink-0 text-xs font-medium text-foreground">
                  {getProjectStageShortName(projectStage)}
                </span>
                <span
                  className={cn('size-1.5 shrink-0 rounded-full', stageToneClasses[execution.tone])}
                  aria-hidden="true"
                />
                <span className={cn('shrink-0 text-xs', isCurrent ? 'font-medium text-foreground' : 'text-muted-foreground')}>
                  {execution.label}
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </header>
  )
}
