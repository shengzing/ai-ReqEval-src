'use client'

import { useState } from 'react'
import { Send } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { canSubmitHomeTask } from '@/lib/api-mappers'

interface TaskComposerProps {
  placeholder?: string
  onStartTask?: (task: string) => void
}

export function TaskComposer({ placeholder = '描述你的目标...', onStartTask }: TaskComposerProps) {
  const [inputValue, setInputValue] = useState('')

  const handleSubmit = () => {
    if (!canSubmitHomeTask(inputValue)) return
    onStartTask?.(inputValue)
    setInputValue('')
  }

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div className="rounded-xl border border-border bg-card shadow-sm">
      <div className="p-4">
        <textarea
          value={inputValue}
          onChange={(event) => setInputValue(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          className="min-h-[88px] w-full resize-none bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
          rows={3}
        />
      </div>
      <div className="flex items-center justify-between border-t border-border px-3 py-2">
        <p className="text-xs text-muted-foreground">Enter 发送，Shift + Enter 换行</p>
        <Button
          size="sm"
          onClick={handleSubmit}
          disabled={!canSubmitHomeTask(inputValue)}
          className="h-8 gap-1.5 rounded-full px-3"
        >
          <Send className="size-3.5" />
          启动 Run
        </Button>
      </div>
    </div>
  )
}
