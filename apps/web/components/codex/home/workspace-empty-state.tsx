'use client'

interface WorkspaceEmptyStateProps {
  hasProject: boolean
  projectName?: string
}

export function WorkspaceEmptyState({ hasProject, projectName }: WorkspaceEmptyStateProps) {
  return (
    <div className="mb-8 text-center">
      <h1 className="text-2xl font-medium text-foreground/90">
        {hasProject && projectName ? `在 ${projectName} 中启动当前阶段` : '输入目标，创建真实项目 Run'}
      </h1>
      <p className="mt-3 text-sm text-muted-foreground">
        {hasProject
          ? '输入一个阶段目标，系统会通过后端创建对话和 Run，并从 SSE 返回执行状态。'
          : '当前没有已选择项目。提交目标后会先创建项目骨架，再启动默认阶段 Run。'}
      </p>
    </div>
  )
}
