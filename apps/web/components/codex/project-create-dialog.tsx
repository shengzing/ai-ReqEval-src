'use client'

import { useState } from 'react'
import { CircleHelp, Paperclip, X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { encodeProjectFile } from '@/lib/file-encoding'

interface ProjectCreateDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreateProject: (input: {
    name: string
    goal?: string
    files?: Array<{ filename: string; contentType?: string; content?: string; contentBase64?: string }>
  }) => Promise<void> | void
}

function FieldHelp({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={`${label}说明`}
          className="inline-flex size-4 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <CircleHelp className="size-3.5" aria-hidden="true" />
        </button>
      </TooltipTrigger>
      <TooltipContent side="top" sideOffset={6} className="max-w-72 text-left leading-5">
        {children}
      </TooltipContent>
    </Tooltip>
  )
}

export function ProjectCreateDialog({ open, onOpenChange, onCreateProject }: ProjectCreateDialogProps) {
  const [projectName, setProjectName] = useState('')
  const [projectGoal, setProjectGoal] = useState('')
  const [projectFiles, setProjectFiles] = useState<File[]>([])
  const [creatingProject, setCreatingProject] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string>()

  const reset = () => {
    setProjectName('')
    setProjectGoal('')
    setProjectFiles([])
    setErrorMessage(undefined)
  }

  const handleCreateProject = async () => {
    if (!projectName.trim()) return
    setCreatingProject(true)
    setErrorMessage(undefined)
    try {
      const encodedFiles = await Promise.all(projectFiles.map(encodeProjectFile))
      await onCreateProject({
        name: projectName.trim(),
        goal: projectGoal.trim() || projectName.trim(),
        files: encodedFiles,
      })
      reset()
      onOpenChange(false)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '项目创建失败，请稍后重试。')
    } finally {
      setCreatingProject(false)
    }
  }

  const handleCancel = () => {
    reset()
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[calc(100vh-2rem)] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>新建项目</DialogTitle>
          <DialogDescription>创建项目骨架和默认四阶段，不自动启动分析。</DialogDescription>
        </DialogHeader>
        <div className="min-w-0 space-y-4">
          <div className="space-y-2">
            <div className="flex items-center gap-1.5">
              <label htmlFor="project-name" className="text-sm font-medium text-foreground">项目名称</label>
              <FieldHelp label="项目名称">
                用于左侧项目树、项目目录和后续报告标题。建议写成可识别的业务场景名称，例如“宏观产经研究”或“贷前质检评估”。
              </FieldHelp>
            </div>
            <Input
              id="project-name"
              className="w-full"
              value={projectName}
              onChange={(event) => setProjectName(event.target.value)}
              placeholder="例如：贷前质检评估"
              autoFocus
            />
          </div>
          <div className="space-y-2">
            <div className="flex items-center gap-1.5">
              <label htmlFor="project-goal" className="text-sm font-medium text-foreground">项目目标</label>
              <FieldHelp label="项目目标">
                用于描述本项目要完成的评估或研究任务，后续阶段目标、Run 提示词和报告产出会参考该字段；不填时默认使用项目名称。
              </FieldHelp>
            </div>
            <Input
              id="project-goal"
              className="w-full"
              value={projectGoal}
              onChange={(event) => setProjectGoal(event.target.value)}
              placeholder="可选，默认使用项目名称"
            />
          </div>
          <div className="space-y-2">
            <div className="flex items-center gap-1.5">
              <label className="text-sm font-medium text-foreground">首批材料</label>
              <FieldHelp label="首批材料">
                上传项目初始化资料，例如需求文档、开题报告、调研材料、评估标准、截图或表格。支持常见文本、PDF、Word、Excel、图片等格式；当前只保存到项目目录，不自动解析。
              </FieldHelp>
            </div>
            <div className="min-w-0 rounded-md border border-dashed border-border p-3">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <p className="text-sm text-foreground">可在创建项目时一起上传首批文件</p>
                  <p className="mt-1 text-xs text-muted-foreground">当前只上传到项目目录，不自动解析，不自动启动分析。</p>
                  <p className="mt-1 text-xs text-muted-foreground">建议格式：.docx、.pdf、.xlsx、.csv、.md、.txt、.png、.jpg。</p>
                </div>
                <label htmlFor="project-files" className="inline-flex shrink-0 cursor-pointer items-center rounded-md focus-within:ring-2 focus-within:ring-ring">
                  <input
                    id="project-files"
                    aria-label="选择项目材料文件"
                    type="file"
                    multiple
                    className="sr-only"
                    onChange={(event) => {
                      const files = Array.from(event.target.files ?? [])
                      if (!files.length) return
                      setProjectFiles((previous) => [...previous, ...files])
                      event.currentTarget.value = ''
                    }}
                  />
                  <span className="inline-flex h-8 items-center gap-1.5 rounded-md border bg-background px-3 text-sm hover:bg-accent">
                    <Paperclip className="size-3.5" />
                    选择文件
                  </span>
                </label>
              </div>
              {projectFiles.length > 0 && (
                <div className="mt-3 min-w-0 space-y-2">
                  {projectFiles.map((file, index) => (
                    <div key={`${file.name}-${index}`} className="flex min-w-0 items-center justify-between gap-3 rounded-md bg-muted/40 px-3 py-2">
                      <div className="min-w-0 flex-1">
                        <p className="max-w-full truncate text-sm text-foreground" title={file.name}>{file.name}</p>
                        <p className="text-xs text-muted-foreground">{Math.max(1, Math.round(file.size / 1024))} KB</p>
                      </div>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        className="shrink-0"
                        aria-label={`移除文件 ${file.name}`}
                        onClick={() => {
                          setProjectFiles((previous) => previous.filter((_, currentIndex) => currentIndex !== index))
                        }}
                      >
                        <X className="size-3.5" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
        {errorMessage && (
          <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {errorMessage}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={handleCancel} disabled={creatingProject}>
            取消
          </Button>
          <Button onClick={() => void handleCreateProject()} disabled={creatingProject || !projectName.trim()}>
            {creatingProject ? '创建中...' : '创建项目'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
