'use client'

import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'

interface ProjectRenameDialogProps {
  open: boolean
  projectId?: string
  initialName?: string
  onOpenChange: (open: boolean) => void
  onRenameProject: (projectId: string, name: string) => Promise<void> | void
}

export function ProjectRenameDialog({
  open,
  projectId,
  initialName,
  onOpenChange,
  onRenameProject,
}: ProjectRenameDialogProps) {
  const [name, setName] = useState('')
  const [renaming, setRenaming] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string>()

  // Seed the input whenever the dialog is opened with a fresh project.
  useEffect(() => {
    if (open) {
      setName(initialName ?? '')
      setErrorMessage(undefined)
    }
  }, [open, initialName])

  const handleRename = async () => {
    const trimmed = name.trim()
    if (!projectId || !trimmed) return
    setRenaming(true)
    setErrorMessage(undefined)
    try {
      await onRenameProject(projectId, trimmed)
      onOpenChange(false)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '重命名失败，请稍后重试。')
    } finally {
      setRenaming(false)
    }
  }

  const handleCancel = () => {
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>重命名项目</DialogTitle>
          <DialogDescription>修改项目名称。该项目的历史记录与产物不会受到影响。</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <label htmlFor="project-rename-name" className="text-sm font-medium text-foreground">
            项目名称
          </label>
          <Input
            id="project-rename-name"
            className="w-full"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="请输入新的项目名称"
            autoFocus
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault()
                void handleRename()
              }
            }}
          />
        </div>
        {errorMessage && (
          <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {errorMessage}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={handleCancel} disabled={renaming}>
            取消
          </Button>
          <Button onClick={() => void handleRename()} disabled={renaming || !name.trim()}>
            {renaming ? '保存中...' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
