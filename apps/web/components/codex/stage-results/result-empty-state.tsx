'use client'

import { FileText } from 'lucide-react'

import { Button } from '@/components/ui/button'

interface ResultEmptyStateProps {
  stageName: string
  onStartRun?: () => Promise<void> | void
}

export function ResultEmptyState({ stageName, onStartRun }: ResultEmptyStateProps) {
  return (
    <div>
      <div className="flex items-start gap-3">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted">
          <FileText className="size-4 text-muted-foreground" />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-medium text-foreground">暂无阶段结果</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            {stageName} 还没有后端返回的 `resultPayload`。启动当前阶段 Run 后，这里会展示真实阶段结果。
          </p>
          {onStartRun && (
            <Button size="sm" className="mt-3 h-8" onClick={() => void onStartRun()}>
              启动当前阶段 Run
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
