'use client'

import { AlertCircle, FileText, GripVertical, ImageIcon, Loader2, Maximize2, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { EvidenceItem, FilePreview } from '@/lib/types'
import { cn } from '@/lib/utils'

interface RawResourcePreviewSidebarProps {
  item?: EvidenceItem
  preview?: FilePreview
  loading?: boolean
  error?: string | null
  onClose: () => void
}

const MIN_PREVIEW_WIDTH = 320
const MAX_PREVIEW_WIDTH = 800
const DEFAULT_PREVIEW_WIDTH = 420

export function RawResourcePreviewSidebar({
  item,
  preview,
  loading = false,
  error,
  onClose,
}: RawResourcePreviewSidebarProps) {
  const [width, setWidth] = useState(DEFAULT_PREVIEW_WIDTH)
  const [isResizing, setIsResizing] = useState(false)
  const asideRef = useRef<HTMLElement>(null)
  const widthRef = useRef(width)
  widthRef.current = width

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem('ai-reqeval:preview-sidebar-width')
      if (stored) {
        const parsed = Number(stored)
        if (Number.isFinite(parsed)) {
          setWidth(Math.min(MAX_PREVIEW_WIDTH, Math.max(MIN_PREVIEW_WIDTH, parsed)))
        }
      }
    } catch {
      // 忽略存储不可用的情况
    }
  }, [])

  // 组件卸载时恢复全局 cursor / userSelect，避免拖拽中卸载残留样式
  useEffect(() => {
    return () => {
      if (isResizing) {
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
      }
    }
  }, [isResizing])

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || !asideRef.current) return
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    setIsResizing(true)
  }

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!isResizing || !asideRef.current) return
    const asideRect = asideRef.current.getBoundingClientRect()
    const newWidth = asideRect.right - event.clientX
    const clamped = Math.min(MAX_PREVIEW_WIDTH, Math.max(MIN_PREVIEW_WIDTH, newWidth))
    setWidth(clamped)
  }

  const handlePointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!isResizing) return
    event.currentTarget.releasePointerCapture(event.pointerId)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
    setIsResizing(false)
    try {
      window.localStorage.setItem('ai-reqeval:preview-sidebar-width', String(widthRef.current))
    } catch {
      // 忽略存储不可用的情况
    }
  }

  const resetWidth = () => {
    setWidth(DEFAULT_PREVIEW_WIDTH)
    try {
      window.localStorage.setItem('ai-reqeval:preview-sidebar-width', String(DEFAULT_PREVIEW_WIDTH))
    } catch {
      // 忽略存储不可用的情况
    }
  }

  if (!item && !loading && !error) return null

  return (
    <aside
      ref={asideRef}
      style={{ width: `${width}px` }}
      className="relative flex h-[42vh] w-full shrink-0 flex-col border-t border-border bg-background lg:h-full lg:border-l lg:border-t-0"
    >
      {/* 拖拽手柄 */}
      <div
        role="separator"
        aria-label="调整预览面板宽度"
        aria-orientation="vertical"
        aria-valuemin={MIN_PREVIEW_WIDTH}
        aria-valuemax={MAX_PREVIEW_WIDTH}
        aria-valuenow={width}
        tabIndex={0}
        title="拖动调整宽度，双击恢复默认"
        onDoubleClick={resetWidth}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        className={cn(
          'group absolute inset-y-0 -left-1 z-20 hidden w-2 touch-none cursor-col-resize items-center justify-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary lg:flex',
          isResizing && 'bg-primary/10',
        )}
      >
        <span className={cn(
          'flex h-10 w-3 items-center justify-center rounded-full border border-border bg-card text-muted-foreground opacity-60 shadow-sm transition group-hover:opacity-100 group-focus-visible:opacity-100',
          isResizing && 'border-primary bg-primary text-primary-foreground opacity-100',
        )}>
          <GripVertical className="size-3" />
        </span>
      </div>

      <div className="flex min-h-14 items-center gap-3 border-b border-border px-4">
        <PreviewIcon preview={preview} loading={loading} error={error} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground">{preview?.filename ?? item?.name ?? '原始资源预览'}</p>
          <p className="truncate text-xs text-muted-foreground">{preview ? formatPreviewMeta(preview) : '正在准备预览内容'}</p>
        </div>
        <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="关闭预览">
          <X className="size-4" />
        </Button>
      </div>

      <div className="min-h-0 flex-1">
        {loading ? <PreviewLoading /> : error ? <PreviewError message={error} /> : preview ? <PreviewContent preview={preview} /> : null}
      </div>
    </aside>
  )
}

function PreviewIcon({ preview, loading, error }: { preview?: FilePreview; loading: boolean; error?: string | null }) {
  const className = 'size-4'
  if (loading) return <Loader2 className={cn(className, 'animate-spin text-primary')} />
  if (error) return <AlertCircle className={cn(className, 'text-destructive')} />
  if (preview?.previewType === 'image') return <ImageIcon className={cn(className, 'text-primary')} />
  return <FileText className={cn(className, 'text-primary')} />
}

function PreviewLoading() {
  return (
    <div className="space-y-3 p-4">
      <div className="h-4 w-2/3 rounded-md bg-muted" />
      <div className="h-4 w-5/6 rounded-md bg-muted" />
      <div className="h-4 w-3/4 rounded-md bg-muted" />
      <div className="h-40 rounded-md bg-muted/70" />
    </div>
  )
}

function PreviewError({ message }: { message: string }) {
  return (
    <div className="p-4">
      <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm leading-6 text-destructive">
        {message}
      </div>
    </div>
  )
}

function PreviewContent({ preview }: { preview: FilePreview }) {
  if (preview.previewType === 'image') {
    return (
      <ScrollArea className="h-full">
        <div className="flex min-h-full items-start justify-center bg-muted/20 p-4">
          <img
            src={toDataUrl(preview)}
            alt={preview.filename}
            className="max-h-full max-w-full rounded-md border border-border bg-background object-contain"
          />
        </div>
      </ScrollArea>
    )
  }

  if (preview.previewType === 'pdf') {
    return (
      <div className="flex h-full flex-col">
        <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
          <span className="text-xs text-muted-foreground">PDF 原文预览</span>
          <Button variant="outline" size="sm" className="h-7 gap-1 px-2 text-xs" asChild>
            <a href={toDataUrl(preview)} target="_blank" rel="noreferrer">
              <Maximize2 className="size-3" />
              新窗口
            </a>
          </Button>
        </div>
        <iframe
          title={preview.filename}
          src={toDataUrl(preview)}
          className="h-full w-full border-0 bg-muted/20"
        />
      </div>
    )
  }

  return (
    <ScrollArea className="h-full">
      <div className="space-y-3 p-4">
        {preview.truncated ? (
          <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
            文件内容较长，当前只显示前 {formatBytes(preview.content.length)} 文本。
          </div>
        ) : null}
        <pre className="whitespace-pre-wrap break-words rounded-md border border-border bg-muted/20 p-3 font-mono text-xs leading-6 text-foreground">
          {preview.content || '该文件没有可显示的文本内容。'}
        </pre>
      </div>
    </ScrollArea>
  )
}

function toDataUrl(preview: FilePreview) {
  return `data:${preview.contentType};base64,${preview.content}`
}

function formatPreviewMeta(preview: FilePreview) {
  const typeLabel = preview.previewType === 'text' ? '文本' : preview.previewType === 'pdf' ? 'PDF' : '图片'
  return `${typeLabel} · ${preview.contentType} · ${formatBytes(preview.sizeBytes)}`
}

function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let unitIndex = 0
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024
    unitIndex += 1
  }
  return `${value >= 10 || unitIndex === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unitIndex]}`
}
