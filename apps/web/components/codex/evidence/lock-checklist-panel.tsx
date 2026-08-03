'use client'

import { Check } from 'lucide-react'

import { cn } from '@/lib/utils'

interface LockChecklistPanelProps {
  items: Array<{ label: string; checked: boolean }>
}

export function LockChecklistPanel({ items }: LockChecklistPanelProps) {
  return (
    <div className="rounded-lg border border-border bg-muted/30 p-4">
      <h3 className="mb-3 text-sm font-medium text-foreground">锁定前检查</h3>
      <div className="space-y-2">
        {items.map((item) => (
          <div key={item.label} className="flex items-center gap-2 text-sm">
            {item.checked ? <Check className="size-3.5 text-emerald-500" /> : <div className="size-3.5 rounded border border-muted-foreground/30" />}
            <span className={cn(item.checked ? 'text-muted-foreground' : 'text-foreground')}>{item.label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
