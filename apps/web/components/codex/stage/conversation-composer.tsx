'use client'

import { useState, useRef, type KeyboardEvent, type ChangeEvent } from 'react'
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

export function DEFAULT_COMPOSER_PLACEHOLDER() {
  return '输入消息与阶段对话助手交流…'
}

export function ConversationComposer({
  disabled,
  sending,
  placeholder = DEFAULT_COMPOSER_PLACEHOLDER(),
  onSend,
  onUploadFiles,
  onGenerateReport,
}: ConversationComposerProps) {
  const [value, setValue] = useState('')
  const [uploading, setUploading] = useState(false)
  const [generatingReport, setGeneratingReport] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  // Track IME composition so Enter during Chinese/Japanese input
  // commits text instead of triggering submit (keyCode 229).
  const isComposingRef = useRef(false)

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
    if (event.key !== 'Enter' || event.shiftKey) return
    if (event.nativeEvent.isComposing || event.keyCode === 229 || isComposingRef.current) {
      // IME is in progress — let the IME handle Enter.
      return
    }
    event.preventDefault()
    submit()
  }

  const handleCompositionStart = () => {
    isComposingRef.current = true
  }
  const handleCompositionEnd = () => {
    isComposingRef.current = false
  }

  const handleInput = (event: ChangeEvent<HTMLTextAreaElement>) => {
    setValue(event.target.value)
    // field-sizing: content lets the textarea auto-grow without
    // manual height math. Browsers without support fall back to the
    // legacy min/max-h styling below.
    const target = event.target
    target.style.height = 'auto'
    target.style.height = `${Math.min(target.scrollHeight, 160)}px`
  }

  const handleUpload = async (event: ChangeEvent<HTMLInputElement>) => {
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
  const canSubmit = value.trim().length > 0 && !isLocked

  return (
    <div className="border-t border-border bg-background/95 px-3 py-3 backdrop-blur-sm sm:px-5 lg:px-8">
      <div className="mx-auto max-w-3xl">
        <div className="rounded-2xl border border-border bg-card shadow-sm transition-shadow focus-within:border-ring/60 focus-within:ring-2 focus-within:ring-ring/30">
          <textarea
            ref={textareaRef}
            value={value}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            onCompositionStart={handleCompositionStart}
            onCompositionEnd={handleCompositionEnd}
            placeholder={placeholder}
            disabled={disabled}
            rows={1}
            aria-label="消息输入框"
            className="block max-h-40 min-h-[44px] w-full resize-none bg-transparent px-3.5 py-3 text-sm text-foreground outline-none placeholder:text-muted-foreground field-sizing-content"
          />
          <div className="flex items-center justify-between gap-2 border-t border-border/60 px-2.5 py-2">
            <div className="flex flex-wrap items-center gap-1.5">
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
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-7 gap-1 px-2 text-xs"
                    disabled={disabled || uploading}
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <Paperclip className="size-3.5" aria-hidden="true" />
                    {uploading ? '上传中' : '上传'}
                  </Button>
                </>
              )}
              {onGenerateReport && (
                <Button
                  type="button"
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
                  <FileText className="size-3.5" aria-hidden="true" />
                  {generatingReport ? '生成中' : '报告'}
                </Button>
              )}
            </div>
            <Button
              type="button"
              size="sm"
              onClick={submit}
              disabled={!canSubmit}
              aria-label={sending ? '正在发送' : '发送消息'}
              className={cn('h-7 gap-1.5 rounded-lg px-3 text-xs')}
            >
              {sending ? (
                <>
                  <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                  <span>思考中…</span>
                </>
              ) : (
                <>
                  <Send className="size-3.5" aria-hidden="true" />
                  <span>发送</span>
                </>
              )}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
