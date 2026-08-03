'use client'

import { Zap } from 'lucide-react'

import type { SuggestedTask } from '@/lib/types'

interface SuggestedTaskListProps {
  tasks: SuggestedTask[]
  onStartTask?: (task: string) => void
}

export function SuggestedTaskList({ tasks, onStartTask }: SuggestedTaskListProps) {
  if (!tasks.length) return null

  return (
    <div className="mt-6 space-y-2">
      {tasks.map((task) => (
        <button
          key={task.id}
          type="button"
          onClick={() => onStartTask?.(task.title)}
          className="flex w-full items-center gap-3 rounded-lg px-4 py-2.5 text-left text-sm text-muted-foreground transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Zap className="size-4 shrink-0 text-amber-500" />
          <span className="flex-1">{task.title}</span>
        </button>
      ))}
    </div>
  )
}
