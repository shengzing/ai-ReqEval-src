'use client'

import type { MouseEvent } from 'react'

import type { Project } from '@/lib/types'
import { ProjectNode } from './project-node'

interface ProjectTreeProps {
  projects: Project[]
  expandedProjects: Set<string>
  expandedStages: Set<string>
  activeProject?: string
  activeStage?: string
  activeConversation?: string
  searchQuery?: string
  onToggleProject: (projectId: string) => void
  onToggleStage: (stageId: string, event: MouseEvent) => void
  onSelectProject?: (projectId: string) => void
  onSelectStage?: (stageId: string) => void
  onSelectConversation?: (conversationId: string, stageId: string) => void
  onCreateConversation?: (stageId: string) => void
  onDeleteConversation?: (conversationId: string, stageId: string) => void
  onDeleteProject?: (projectId: string) => void
}

export function ProjectTree({
  projects,
  expandedProjects,
  expandedStages,
  activeProject,
  activeStage,
  activeConversation,
  searchQuery,
  onToggleProject,
  onToggleStage,
  onSelectProject,
  onSelectStage,
  onSelectConversation,
  onCreateConversation,
  onDeleteConversation,
  onDeleteProject,
}: ProjectTreeProps) {
  return (
    <div className="flex flex-col gap-0.5 px-2 pb-4">
      {projects.map((project) => (
        <ProjectNode
          key={project.id}
          project={project}
          isExpanded={expandedProjects.has(project.id)}
          expandedStages={expandedStages}
          activeProject={activeProject}
          activeStage={activeStage}
          activeConversation={activeConversation}
          searchQuery={searchQuery}
          onToggleProject={() => onToggleProject(project.id)}
          onSelectProject={() => onSelectProject?.(project.id)}
          onToggleStage={onToggleStage}
          onSelectStage={onSelectStage}
          onSelectConversation={onSelectConversation}
          onCreateConversation={onCreateConversation}
          onDeleteConversation={onDeleteConversation}
          onDeleteProject={() => onDeleteProject?.(project.id)}
        />
      ))}
    </div>
  )
}
