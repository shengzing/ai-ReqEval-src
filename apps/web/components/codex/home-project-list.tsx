'use client'

import { useMemo, useState } from 'react'
import { MoreVertical, Pencil, Paperclip, Plus, Search, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { formatDateZh } from '@/lib/utils'
import type { Project, Stage, StageStatus } from '@/lib/types'
import { ProjectRenameDialog } from './project-rename-dialog'

interface HomeProjectListProps {
  projects: Project[]
  activeProject?: string
  onSelectProject: (projectId: string) => void
  onCreateProject: () => void
  onDeleteProject?: (projectId: string) => void
  onRenameProject?: (projectId: string, name: string) => Promise<void> | void
}

/**
 * 计算项目进展：已完成阶段数与当前阶段名。
 *
 * - 已完成（completed/locked）计入 completed 计数
 * - 当前阶段：第一个仍在进行的阶段（in_progress/waiting_user/needs_review）
 *   没有则取第一个未开始；全部完成则「全部阶段已完成」
 */
function computeProjectProgress(project: Project): { completed: number; currentStageName: string } {
  const stages = project.stages ?? []
  const completed = stages.filter(
    (s) => s.status === 'completed' || s.status === 'locked',
  ).length
  const active = stages.find(
    (s) =>
      s.status === 'in_progress' ||
      s.status === 'waiting_user' ||
      s.status === 'needs_review',
  )
  const next = stages.find((s) => s.status === 'not_started')
  const currentStageName = active?.name ?? next?.name ?? '全部阶段已完成'
  return { completed, currentStageName }
}

/** 四阶段点位颜色：已完成/锁定 → emerald；进行中 → blue；未开始/失败 → 空心 muted */
function dotClass(status: StageStatus): string {
  if (status === 'completed' || status === 'locked') {
    return 'bg-emerald-500 border-emerald-500'
  }
  if (status === 'in_progress' || status === 'waiting_user' || status === 'needs_review') {
    return 'bg-blue-500 border-blue-500'
  }
  return 'bg-transparent border-muted-foreground/30'
}

export function HomeProjectList({
  projects,
  activeProject,
  onSelectProject,
  onCreateProject,
  onDeleteProject,
  onRenameProject,
}: HomeProjectListProps) {
  const [query, setQuery] = useState('')
  const [renameTarget, setRenameTarget] = useState<Project | undefined>()
  const trimmedQuery = query.trim().toLowerCase()
  const filteredProjects = useMemo(() => {
    if (!trimmedQuery) return projects
    return projects.filter((project) => project.name.toLowerCase().includes(trimmedQuery))
  }, [projects, trimmedQuery])

  if (projects.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center px-6 py-12">
        <button
          type="button"
          onClick={onCreateProject}
          className="flex w-full max-w-md flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed border-muted-foreground/30 px-6 py-12 text-muted-foreground transition hover:border-primary/50 hover:text-primary"
        >
          <span className="flex size-12 items-center justify-center rounded-full bg-muted">
            <Plus className="size-6" />
          </span>
          <span className="text-sm font-medium">新建第一个项目</span>
        </button>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col overflow-y-auto px-6 py-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-lg font-semibold tracking-tight">我的项目</h1>
        <Button variant="outline" size="sm" onClick={onCreateProject}>
          <Plus className="size-4" />
          新建项目
        </Button>
      </div>
      <div className="relative mb-6">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground/60" />
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="按项目名搜索项目..."
          aria-label="搜索项目"
          className="pl-9"
        />
      </div>
      {filteredProjects.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center py-12 text-sm text-muted-foreground">
          没有匹配“{query.trim()}”的项目
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {filteredProjects.map((project) => {
            const { completed, currentStageName } = computeProjectProgress(project)
            const isActive = activeProject === project.id
            return (
              <Card
                key={project.id}
                onClick={() => onSelectProject(project.id)}
                className={`group cursor-pointer gap-4 px-5 py-4 transition hover:border-primary/40 hover:shadow-md ${
                  isActive ? 'border-primary/40 ring-2 ring-primary/30' : ''
                }`}
              >                <CardHeader className="gap-1 px-0">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-medium" title={project.name}>
                      {project.name}
                    </span>
                    {(onDeleteProject || onRenameProject) && (
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <button
                            type="button"
                            onClick={(event) => event.stopPropagation()}
                            className="flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground/60 transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            aria-label={`项目 ${project.name} 的更多操作`}
                            title="更多操作"
                          >
                            <MoreVertical className="size-4" />
                          </button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent
                          align="end"
                          onClick={(event) => event.stopPropagation()}
                        >
                          {onRenameProject && (
                            <DropdownMenuItem
                              onSelect={() => setRenameTarget(project)}
                            >
                              <Pencil className="size-4" />
                              重命名
                            </DropdownMenuItem>
                          )}
                          {onDeleteProject && (
                            <DropdownMenuItem
                              variant="destructive"
                              onSelect={() => onDeleteProject(project.id)}
                            >
                              <Trash2 className="size-4" />
                              删除项目
                            </DropdownMenuItem>
                          )}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    )}
                  </div>
                </CardHeader>
                <CardContent className="flex flex-col gap-3 px-0">
                  {/* 四阶段点位 */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5" aria-label={`四阶段进度：已完成 ${completed}/4`}>
                      {(project.stages ?? []).map((stage: Stage) => (
                        <span
                          key={stage.id}
                          className={`size-2 rounded-full border ${dotClass(stage.status)}`}
                          title={stage.name}
                        />
                      ))}
                    </div>
                    <span className="text-xs text-muted-foreground">已完成 {completed}/4</span>
                  </div>
                  {/* 进度条 */}
                  <Progress value={(completed / 4) * 100} />
                  {/* 当前阶段名 */}
                  <p className="truncate text-xs text-muted-foreground" title={currentStageName}>
                    当前：{currentStageName}
                  </p>
                  {/* 材料数量 + 创建时间 */}
                  <div className="flex items-center justify-between">
                    <span className="flex items-center gap-1 text-xs text-muted-foreground">
                      <Paperclip className="size-3" />
                      {project.fileCount ?? 0} 份材料
                    </span>
                    <span className="text-xs text-muted-foreground/70">
                      创建于 {formatDateZh(project.createdAt)}
                    </span>
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
      <ProjectRenameDialog
        open={!!renameTarget}
        projectId={renameTarget?.id}
        initialName={renameTarget?.name}
        onOpenChange={(open) => {
          if (!open) setRenameTarget(undefined)
        }}
        onRenameProject={async (projectId, name) => {
          if (!onRenameProject) return
          await onRenameProject(projectId, name)
        }}
      />
    </div>
  )
}
