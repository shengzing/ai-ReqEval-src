'use client'

import { ArrowRight, Sparkles, Target } from 'lucide-react'

import { Button } from '@/components/ui/button'
import type { Stage } from '@/lib/types'

interface StageGuidanceProps {
  stage: Stage
  onOpenRightSidebar?: () => void
  onStartRun?: (goal: string) => Promise<void> | void
}

export function StageGuidance({ stage, onOpenRightSidebar, onStartRun }: StageGuidanceProps) {
  const isLocked = stage.status === 'locked'

  const handleRecommendedAction = (action: string) => {
    if (action.includes('证据')) {
      onOpenRightSidebar?.()
      return
    }
    if (isLocked) return
    if (action.includes('Run') || action.includes('运行') || action.includes('生成') || action.includes('分析')) {
      void onStartRun?.(`${stage.name}：${stage.objective ?? stage.nextStep ?? action}`)
    }
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-start gap-3">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-emerald-500/10">
          <Target className="size-4 text-emerald-600" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">当前阶段目标</p>
          <p className="mt-1 text-sm text-foreground">{stage.objective ?? '围绕当前阶段继续补齐材料、执行分析并确认关键结论。'}</p>
          <div className="mt-3 rounded-md bg-muted/45 p-3">
            <div className="flex items-center gap-2 text-sm font-medium text-foreground">
              <Sparkles className="size-4 text-primary" />
              <span>推荐下一步</span>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">{stage.nextStep ?? '继续对话，或查看当前阶段的证据与待确认项。'}</p>
            {stage.recommendedActions && stage.recommendedActions.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {stage.recommendedActions.map((action, index) => (
                  <Button
                    key={action}
                    variant={index === 0 ? 'default' : 'outline'}
                    size="sm"
                    className="h-7 gap-1.5 text-xs"
                    disabled={isLocked && !action.includes('证据')}
                    onClick={() => handleRecommendedAction(action)}
                  >
                    {action}
                    {index === 0 && <ArrowRight className="size-3" />}
                  </Button>
                ))}
              </div>
            )}
            {isLocked && <p className="mt-2 text-xs text-muted-foreground">阶段已锁定，仅允许查看证据和结果。</p>}
          </div>
        </div>
      </div>
    </div>
  )
}
