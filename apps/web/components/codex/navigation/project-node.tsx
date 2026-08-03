'use client'

import type { MouseEvent } from 'react'
import { ChevronDown, ChevronRight, FolderKanban, Trash2 } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { Project } from '@/lib/types'
import { StageNode } from './stage-node'
import { StatusDot } from './status-dot'
import { highlightMatch } from './highlight-match'

interface ProjectNodeProps {
  project: Project
  isExpanded: boolean
  expandedStages: Set<string>
  activeProject?: string
  activeStage?: string
  activeConversation?: string
  searchQuery?: string
  onToggleProject: () => void
  onSelectProject: () => void
  onToggleStage: (stageId: string, event: MouseEvent) => void
  onSelectStage?: (stageId: string) => void
  onSelectConversation?: (conversationId: string, stageId: string) => void
  onCreateConversation?: (stageId: string) => void
  onDeleteConversation?: (conversationId: string, stageId: string) => void
  onDeleteProject?: () => void
}

export function ProjectNode({
  project,
  isExpanded,
  expandedStages,
  activeProject,
  activeStage,
  activeConversation,
  searchQuery,
  onToggleProject,
  onSelectProject,
  onToggleStage,
  onSelectStage,
  onSelectConversation,
  onCreateConversation,
  onDeleteConversation,
  onDeleteProject,
}: ProjectNodeProps) {
  return (
    <div>
      <div
        className={cn(
          'group grid w-full grid-cols-[24px_minmax(0,1fr)_44px] items-center gap-1 rounded-md px-1 py-0.5 text-sm text-sidebar-foreground/80',
          activeProject === project.id && 'text-sidebar-foreground'
        )}
      >
        <button
          type="button"
          onClick={onToggleProject}
          className="flex size-6 shrink-0 items-center justify-center rounded-md text-sidebar-foreground/50 hover:bg-sidebar-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={isExpanded ? '收起项目' : '展开项目'}
        >
          {isExpanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        </button>
        <button
          type="button"
          onClick={onSelectProject}
          className={cn(
            'flex min-w-0 items-center gap-1.5 rounded-md px-1 py-1 text-left transition-colors hover:bg-sidebar-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
            activeProject === project.id && 'bg-sidebar-accent/40'
          )}
        >
          <FolderKanban className="size-3.5 shrink-0 text-sidebar-foreground/60" />
          <span className="flex-1 truncate">{highlightMatch(project.name, searchQuery)}</span>
        </button>
        <div className="flex min-w-[44px] items-center justify-end gap-0.5">
          {project.status && <StatusDot status={project.status} count={project.pendingCount} />}
          {project.hasNotification && project.pendingCount === 0 && <span className="size-2 rounded-full bg-primary" />}
          {onDeleteProject && (
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation()
                onDeleteProject()
              }}
              className="flex size-5 shrink-0 items-center justify-center rounded text-sidebar-foreground/40 opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring group-hover:opacity-100"
              aria-label={`删除项目 ${project.name}`}
              title="删除项目"
            >
              <Trash2 className="size-3" />
            </button>
          )}
        </div>
      </div>

      {isExpanded && project.stages.length > 0 && (
        <div className="ml-3 flex flex-col gap-0.5 border-l border-border/50 pl-2">
          {project.stages.map((stage) => (
            <StageNode
              key={stage.id}
              stage={stage}
              isExpanded={expandedStages.has(stage.id)}
              activeStage={activeStage}
              activeConversation={activeConversation}
              searchQuery={searchQuery}
              onToggle={(event) => onToggleStage(stage.id, event)}
              onSelect={() => onSelectStage?.(stage.id)}
              onSelectConversation={onSelectConversation}
              onCreateConversation={onCreateConversation}
              onDeleteConversation={onDeleteConversation}
            />
          ))}
        </div>
      )}
    </div>
  )
}
