'use client'

import { AlertCircle, Loader2, RefreshCcw } from 'lucide-react'

import { Button } from '@/components/ui/button'

interface WorkspaceStateViewProps {
  type: 'loading' | 'error'
  message: string
  onRetry?: () => void
}

export function WorkspaceStateView({ type, message, onRetry }: WorkspaceStateViewProps) {
  const Icon = type === 'loading' ? Loader2 : AlertCircle

  return (
    <div className="flex h-full min-h-[320px] items-center justify-center p-6">
      <div className="w-full max-w-sm rounded-xl border border-border bg-card p-5 text-center shadow-xs">
        <div className="mx-auto flex size-10 items-center justify-center rounded-full bg-muted">
          <Icon className={type === 'loading' ? 'size-5 animate-spin text-primary' : 'size-5 text-destructive'} />
        </div>
        <p className="mt-3 text-sm font-medium text-foreground">{message}</p>
        {type === 'error' && (
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            请确认后端 API 可用，或稍后重试加载工作台。
          </p>
        )}
        {type === 'error' && onRetry && (
          <Button variant="outline" size="sm" className="mt-4 h-8 gap-1.5" onClick={onRetry}>
            <RefreshCcw className="size-3.5" />
            重试加载
          </Button>
        )}
      </div>
    </div>
  )
}
