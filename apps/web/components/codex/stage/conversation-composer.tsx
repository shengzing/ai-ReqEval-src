'use client'

import { useState, useRef, type KeyboardEvent } from 'react'
import { FileText, Loader2, Paperclip, Send } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface ConversationComposerProps {
  /** 当前会话是否可写（已归档/删除/锁定时禁用） */
  disabled?: boolean
  /** 是否正在等待回复（发送后、收到 assistant 前的 loading 态） */
  sending?: boolean
  placeholder?: string
  onSend: (content: string) => void
  /** 上传证据文件（可选） */
  onUploadFiles?: (files: File[]) => void
  /** 生成报告（可选） */
  onGenerateReport?: () => void
}

const DEFAULT_PLACEHOLDER = '输入消息与阶段对话助手交流…'

export function ConversationComposer({
  disabled,
  sending,
  placeholder = DEFAULT_PLACEHOLDER,
  onSend,
  onUploadFiles,
  onGenerateReport,
}: ConversationComposerProps) {
  const [value, setValue] = useState('')
  const [uploading, setUploading] = useState(false)
  const [generatingReport, setGeneratingReport] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const submit = () => {
    const trimmed = value.trim()
    if (!trimmed || disabled || sending) return
    onSend(trimmed)
    setValue('')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  const handleInput = (event: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(event.target.value)
    const target = event.target
    target.style.height = 'auto'
    target.style.height = `${Math.min(target.scrollHeight, 160)}px`
  }

  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? [])
    if (!files.length) return
    setUploading(true)
    try {
      onUploadFiles?.(files)
    } finally {
      setUploading(false)
      event.currentTarget.value = ''
    }
  }

  const isLocked = disabled || sending

  return (
    <div className="border-t border-border bg-background p-3">
      <div className="rounded-xl border border-border bg-card focus-within:ring-2 focus-within:ring-ring">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          rows={1}
          className="block max-h-40 min-h-[40px] w-full resize-none bg-transparent px-3 py-2.5 text-sm text-foreground outline-none placeholder:text-muted-foreground"
        />
        <div className="flex items-center justify-between border-t border-border/60 px-2 py-1.5">
          <div className="flex items-center gap-1.5">
            {onUploadFiles && (
              <>
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  className="sr-only"
                  disabled={disabled || uploading}
                  onChange={handleUpload}
                />
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 gap-1 px-2 text-xs"
                  asChild={false}
                  disabled={disabled || uploading}
                  onClick={() => fileInputRef.current?.click()}
                >
                  <span className="inline-flex items-center gap-1">
                    <Paperclip className="size-3.5" />
                    {uploading ? '上传中' : '上传'}
                  </span>
                </Button>
              </>
            )}
            {onGenerateReport && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 gap-1 px-2 text-xs"
                disabled={disabled || generatingReport}
                onClick={async () => {
                  setGeneratingReport(true)
                  try {
                    onGenerateReport()
                  } finally {
                    setGeneratingReport(false)
                  }
                }}
              >
                <FileText className="size-3.5" />
                {generatingReport ? '生成中' : '报告'}
              </Button>
            )}
          </div>
          <button
            type="button"
            onClick={submit}
            disabled={!value.trim() || isLocked}
            className={cn(
              'inline-flex h-7 items-center gap-1.5 rounded-md px-3 text-xs font-medium transition-colors',
              !value.trim() || isLocked
                ? 'cursor-not-allowed bg-muted text-muted-foreground'
                : 'bg-primary text-primary-foreground hover:bg-primary/90'
            )}
          >
            {sending ? <Loader2 className="size-3.5 animate-spin" /> : <Send className="size-3.5" />}
            <span>{sending ? '思考中…' : '发送'}</span>
          </button>
        </div>
      </div>
    </div>
  )
}
