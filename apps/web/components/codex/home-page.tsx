import { defaultSuggestedTasks } from '@/lib/default-tasks'
import { SuggestedTaskList } from './home/suggested-task-list'
import { TaskComposer } from './home/task-composer'
import { WorkspaceEmptyState } from './home/workspace-empty-state'

interface HomePageProps {
  projectName?: string
  projectId?: string
  hasProjects?: boolean
  onSelectProject?: (projectId: string) => void
  onStartTask?: (task: string) => void
}

export function HomePage({ projectName, projectId, hasProjects, onSelectProject, onStartTask }: HomePageProps) {
  const hasProject = Boolean(projectName)

  return (
    <div className="flex h-full flex-col items-center justify-center px-8">
      <div className="w-full max-w-2xl">
        <WorkspaceEmptyState hasProject={hasProject} projectName={projectName} />
        <TaskComposer onStartTask={onStartTask} />
        {/* When no project is active but projects exist, show a prompt to continue in an existing project */}
        {!hasProject && hasProjects && projectId && onSelectProject && (
          <div className="mt-4 rounded-lg border border-dashed border-border bg-muted/30 px-4 py-3 text-center">
            <p className="text-sm text-muted-foreground">
              提交目标将创建新项目。如需在已有项目中工作，请从左侧项目树选择。
            </p>
          </div>
        )}
        {!hasProject && !hasProjects && (
          <div className="mt-4 rounded-lg border border-dashed border-border bg-muted/30 px-4 py-3 text-center">
            <p className="text-sm text-muted-foreground">
              提交目标后将自动创建新项目并启动默认阶段 Run。
            </p>
          </div>
        )}
        <SuggestedTaskList tasks={hasProject ? defaultSuggestedTasks : []} onStartTask={onStartTask} />
      </div>
    </div>
  )
}
