'use client'

import { Trash2 } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { Conversation } from '@/lib/types'
import { highlightMatch } from './highlight-match'

interface ConversationNodeProps {
  conversation: Conversation
  isActive: boolean
  searchQuery?: string
  onSelect: () => void
  onDelete?: () => void
}

const STATUS_DOT_COLORS: Record<string, string> = {
  completed: 'bg-emerald-500',
  running: 'bg-blue-500',
  waiting_user: 'bg-amber-500',
  failed: 'bg-red-500',
  created: 'bg-muted-foreground/40',
  queued: 'bg-muted-foreground/40',
  cancelled: 'bg-muted-foreground/30',
  archived: 'bg-muted-foreground/30',
}

export function ConversationNode({ conversation, isActive, searchQuery, onSelect, onDelete }: ConversationNodeProps) {
  const statusDotColor = conversation.status
    ? STATUS_DOT_COLORS[conversation.status] ?? 'bg-muted-foreground/30'
    : 'bg-muted-foreground/20'

  return (
    <div
      className={cn(
        'group grid grid-cols-[minmax(0,1fr)_48px_20px] items-center rounded-md text-[11px] text-sidebar-foreground/50 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground/70',
        isActive && 'bg-sidebar-accent text-sidebar-foreground'
      )}
    >
      <button
        type="button"
        onClick={onSelect}
        className="flex min-w-0 items-center gap-1.5 rounded-md px-1.5 py-0.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className={cn('size-1.5 shrink-0 rounded-full', statusDotColor)} />
        <span className="flex-1 truncate">{highlightMatch(conversation.title, searchQuery)}</span>
      </button>
      <div className="truncate pr-1 text-right text-sidebar-foreground/30">
        {conversation.timeAgo ?? ''}
      </div>
      {onDelete && (
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation()
            onDelete()
          }}
          className="mr-0.5 flex size-5 shrink-0 items-center justify-center rounded text-sidebar-foreground/40 opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring group-hover:opacity-100"
          aria-label={`删除会话 ${conversation.title}`}
          title="删除会话"
        >
          <Trash2 className="size-3" />
        </button>
      )}
    </div>
  )
}
