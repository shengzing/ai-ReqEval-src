'use client'

import { useEffect, useState } from 'react'
import { Home, Plus, Search, Settings } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { type Project } from '@/lib/types'
import { cn } from '@/lib/utils'
import { ProjectTree } from './navigation/project-tree'

interface LeftSidebarProps {
  projects: Project[]
  activeProject?: string
  activeStage?: string
  activeConversation?: string
  onProjectChange?: (projectId: string) => void
  onStageChange?: (stageId: string) => void
  onConversationChange?: (conversationId: string, stageId: string) => void
  onCreateConversation?: (stageId: string) => void
  onDeleteConversation?: (conversationId: string, stageId: string) => void
  onDeleteProject?: (projectId: string) => void
  onCreateProject?: () => void
  onOpenSettings?: () => void
  onGoHome?: () => void
  settingsActive?: boolean
}

export function LeftSidebar({
  projects,
  activeProject,
  activeStage,
  activeConversation,
  onProjectChange,
  onStageChange,
  onConversationChange,
  onCreateConversation,
  onDeleteConversation,
  onDeleteProject,
  onCreateProject,
  onOpenSettings,
  onGoHome,
  settingsActive,
}: LeftSidebarProps) {
  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(
    new Set()
  )
  const [expandedStages, setExpandedStages] = useState<Set<string>>(
    new Set()
  )
  const [searchQuery, setSearchQuery] = useState('')

  useEffect(() => {
    if (activeProject) {
      setExpandedProjects((prev) => new Set(prev).add(activeProject))
    }
  }, [activeProject])

  useEffect(() => {
    if (activeStage) {
      setExpandedStages((prev) => new Set(prev).add(activeStage))
    }
  }, [activeStage])

  const toggleProject = (projectId: string) => {
    setExpandedProjects((prev) => {
      const newExpanded = new Set(prev)
      if (newExpanded.has(projectId)) {
        newExpanded.delete(projectId)
      } else {
        newExpanded.add(projectId)
      }
      return newExpanded
    })
  }

  const toggleStage = (stageId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    setExpandedStages((prev) => {
      const newExpanded = new Set(prev)
      if (newExpanded.has(stageId)) {
        newExpanded.delete(stageId)
      } else {
        newExpanded.add(stageId)
      }
      return newExpanded
    })
  }

  // 过滤项目
  const filteredProjects = searchQuery
    ? projects.filter(p =>
        p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        p.stages.some(s =>
          s.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          s.conversations.some(c => c.title.toLowerCase().includes(searchQuery.toLowerCase()))
        )
      )
    : projects

  return (
    <div className="flex h-auto max-h-[42vh] w-full shrink-0 flex-col border-b border-border bg-sidebar lg:h-full lg:max-h-none lg:min-w-[320px] lg:w-[320px] lg:border-b-0 lg:border-r">
      {/* App branding / Home */}
      <button
        type="button"
        onClick={onGoHome}
        className="flex items-center gap-2 border-b border-border px-4 py-3 text-sm font-semibold text-sidebar-foreground transition-colors hover:bg-sidebar-accent/50"
      >
        <Home className="size-4" />
        <span>AI-ReqEval</span>
      </button>

      {/* Search */}
      <div className="p-3">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="搜索项目、阶段或对话..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="h-8 bg-sidebar-accent/50 pl-8 text-sm"
          />
        </div>
      </div>

      {/* Projects Section Header */}
      <div className="flex items-center justify-between px-3 py-1.5">
        <span className="text-xs font-medium text-sidebar-foreground/50">项目</span>
        <Button
          variant="ghost"
          size="icon-sm"
          className="size-6 text-sidebar-foreground/60 hover:text-sidebar-foreground"
          onClick={onCreateProject}
          aria-label="创建项目"
        >
          <Plus className="size-3.5" />
        </Button>
      </div>

      {/* Project Tree */}
      <ScrollArea className="flex-1">
        <ProjectTree
          projects={filteredProjects}
          expandedProjects={expandedProjects}
          expandedStages={expandedStages}
          activeProject={activeProject}
          activeStage={activeStage}
          activeConversation={activeConversation}
          searchQuery={searchQuery}
          onToggleProject={toggleProject}
          onToggleStage={toggleStage}
          onSelectProject={onProjectChange}
          onSelectStage={onStageChange}
          onSelectConversation={onConversationChange}
          onCreateConversation={onCreateConversation}
          onDeleteConversation={onDeleteConversation}
          onDeleteProject={onDeleteProject}
        />
      </ScrollArea>

      {/* Settings at Bottom */}
      <div className="border-t border-border p-2">
        <button
          type="button"
          onClick={onOpenSettings}
          disabled={!activeProject}
          aria-pressed={settingsActive === true}
          aria-disabled={!activeProject}
          title={activeProject ? undefined : '请先选择一个项目再进入设置'}
          className={cn(
            'flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-colors',
            settingsActive
              ? 'bg-sidebar-accent text-sidebar-foreground'
              : 'text-sidebar-foreground/80 hover:bg-sidebar-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
            !activeProject && 'cursor-not-allowed opacity-40 hover:bg-transparent'
          )}
        >
          <Settings className="size-4" />
          <span>设置</span>
        </button>
      </div>
    </div>
  )
}
