'use client'

import type { MouseEvent } from 'react'
import { ChevronDown, ChevronRight, Plus } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { Stage } from '@/lib/types'
import { ConversationNode } from './conversation-node'
import { StatusDot } from './status-dot'
import { highlightMatch } from './highlight-match'

interface StageNodeProps {
  stage: Stage
  isExpanded: boolean
  activeStage?: string
  activeConversation?: string
  searchQuery?: string
  onToggle: (event: MouseEvent) => void
  onSelect: () => void
  onSelectConversation?: (conversationId: string, stageId: string) => void
  onCreateConversation?: (stageId: string) => void
  onDeleteConversation?: (conversationId: string, stageId: string) => void
}

export function StageNode({
  stage,
  isExpanded,
  activeStage,
  activeConversation,
  searchQuery,
  onToggle,
  onSelect,
  onSelectConversation,
  onCreateConversation,
  onDeleteConversation,
}: StageNodeProps) {
  const visibleConversations = isExpanded ? stage.conversations : stage.conversations.slice(0, 3)
  const hasMore = stage.conversations.length > 3 && !isExpanded

  return (
    <div>
      <div className="grid w-full grid-cols-[20px_minmax(0,1fr)_20px] items-center gap-1">
        {stage.conversations.length > 0 ? (
          <button
            type="button"
            onClick={onToggle}
            className="flex size-5 shrink-0 items-center justify-center rounded-md text-sidebar-foreground/40 hover:bg-sidebar-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={isExpanded ? '收起阶段对话' : '展开阶段对话'}
          >
            {isExpanded ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
          </button>
        ) : (
          <span className="block w-5 shrink-0" />
        )}
        <button
          type="button"
          onClick={onSelect}
          className={cn(
            'flex min-w-0 items-center gap-1.5 overflow-hidden rounded-md px-2 py-1 text-xs text-sidebar-foreground/70 transition-colors hover:bg-sidebar-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
            activeStage === stage.id && 'bg-sidebar-accent/50 text-sidebar-foreground'
          )}
        >
          <span className="flex-1 truncate text-left">{highlightMatch(stage.name, searchQuery)}</span>
          <StatusDot status={stage.status} count={stage.pendingConfirmations} />
        </button>
        <button
          type="button"
          onClick={() => onCreateConversation?.(stage.id)}
          className="flex size-5 shrink-0 items-center justify-center rounded-md text-sidebar-foreground/50 hover:bg-sidebar-accent hover:text-sidebar-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          title="新建会话"
          aria-label="新建会话"
        >
          <Plus className="size-3.5" />
        </button>
      </div>

      {stage.conversations.length > 0 && (
        <div className="ml-3 flex flex-col gap-0.5 border-l border-border/30 pl-2">
          {visibleConversations.map((conversation) => (
            <ConversationNode
              key={conversation.id}
              conversation={conversation}
              isActive={activeConversation === conversation.id}
              searchQuery={searchQuery}
              onSelect={() => onSelectConversation?.(conversation.id, stage.id)}
              onDelete={() => onDeleteConversation?.(conversation.id, stage.id)}
            />
          ))}
          {hasMore && (
            <button
              type="button"
              onClick={onToggle}
              className="px-2 py-0.5 text-left text-[11px] text-sidebar-foreground/40 hover:text-sidebar-foreground/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              查看更多 ({stage.conversations.length - 3})...
            </button>
          )}
        </div>
      )}
    </div>
  )
}
