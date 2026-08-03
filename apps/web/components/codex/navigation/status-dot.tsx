'use client'

import { AlertCircle, CheckCircle2, Circle, Clock, Lock, XCircle } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { StageStatus } from '@/lib/types'

const statusConfig: Record<StageStatus, { label: string; icon: React.ReactNode; className: string }> = {
  not_started: {
    label: '未开始',
    icon: <Circle className="size-2.5" />,
    className: 'text-muted-foreground/50',
  },
  in_progress: {
    label: '进行中',
    icon: <Circle className="size-2.5 fill-current" />,
    className: 'text-blue-500',
  },
  waiting_user: {
    label: '等待人工确认',
    icon: <Clock className="size-3" />,
    className: 'text-amber-500',
  },
  locked: {
    label: '已锁定',
    icon: <Lock className="size-3" />,
    className: 'text-muted-foreground',
  },
  completed: {
    label: '已完成',
    icon: <CheckCircle2 className="size-3" />,
    className: 'text-emerald-500',
  },
  needs_review: {
    label: '需复核',
    icon: <AlertCircle className="size-3" />,
    className: 'text-amber-500',
  },
  failed: {
    label: '失败',
    icon: <XCircle className="size-3" />,
    className: 'text-red-500',
  },
}

interface StatusDotProps {
  status: StageStatus
  count?: number
}

export function StatusDot({ status, count }: StatusDotProps) {
  const config = statusConfig[status]
  const label = count !== undefined && count > 0 ? `${config.label}，${count} 项待处理` : config.label

  return (
    <span className={cn('shrink-0', config.className)} title={label} aria-label={label}>
      {status === 'waiting_user' && count !== undefined && count > 0 ? (
        <span className="flex size-4 items-center justify-center rounded-full bg-amber-500 text-[10px] font-medium text-white">
          {count}
        </span>
      ) : (
        config.icon
      )}
    </span>
  )
}
