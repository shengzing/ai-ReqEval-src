'use client'

import type { EvidenceItem } from '@/lib/types'
import { cn } from '@/lib/utils'
import type { EvidenceStatusFilter } from './evidence-types'

interface EvidenceStatusFilterProps {
  statusFilter: EvidenceStatusFilter
  statusCounts: Record<'all' | EvidenceItem['status'], number>
  onStatusFilterChange: (status: EvidenceStatusFilter) => void
}

export function EvidenceStatusFilter({
  statusFilter,
  statusCounts,
  onStatusFilterChange,
}: EvidenceStatusFilterProps) {
  const options: Array<{ key: EvidenceStatusFilter; label: string }> = [
    { key: 'all', label: '全部' },
    { key: 'uploaded', label: '待解析' },
    { key: 'parsed', label: '已解析' },
    { key: 'referenced', label: '已引用' },
  ]

  return (
    <div className="rounded-lg border border-border bg-background/80 p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium text-foreground">处理状态</p>
        <span className="text-xs text-muted-foreground">共 {statusCounts.all} 条</span>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {options.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => onStatusFilterChange(item.key)}
            className={cn(
              'inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              statusFilter === item.key ? 'border-primary bg-primary/8 text-foreground' : 'border-border text-muted-foreground hover:bg-muted'
            )}
          >
            <span>{item.label}</span>
            <span className="text-[10px]">{statusCounts[item.key]}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
