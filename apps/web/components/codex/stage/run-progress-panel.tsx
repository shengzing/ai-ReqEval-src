'use client'

import { useState } from 'react'
import { AlertCircle, CheckCircle2, ChevronDown, ChevronRight, Loader2, Sparkles } from 'lucide-react'

import type { RunStatus, ToolCall } from '@/lib/types'
import { getRunPanelLabel } from './stage-status'

interface RunProgressPanelProps {
  runStatus?: RunStatus
  toolCalls: ToolCall[]
}

export function RunProgressPanel({ runStatus, toolCalls }: RunProgressPanelProps) {
  const [expandedTools, setExpandedTools] = useState<Set<string>>(new Set(['t1']))
  const runPanelLabel = getRunPanelLabel(runStatus, toolCalls.length)

  const toggleTool = (toolId: string) => {
    const nextExpanded = new Set(expandedTools)
    if (nextExpanded.has(toolId)) nextExpanded.delete(toolId)
    else nextExpanded.add(toolId)
    setExpandedTools(nextExpanded)
  }

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          {runStatus === 'running' ? (
            <Loader2 className="size-4 animate-spin text-primary" />
          ) : runStatus === 'completed' ? (
            <CheckCircle2 className="size-4 text-emerald-500" />
          ) : runStatus === 'failed' ? (
            <AlertCircle className="size-4 text-red-500" />
          ) : (
            <Sparkles className="size-4 text-primary" />
          )}
          <span className="text-sm font-medium">{runPanelLabel}</span>
        </div>
        <span className="text-xs text-muted-foreground">由后端 SSE 实时刷新</span>
      </div>

      <div className="divide-y divide-border rounded-md bg-muted/20">
        {toolCalls.length > 0 ? toolCalls.map((tool) => (
          <div key={tool.id} className="px-4 py-3">
            <button
              type="button"
              onClick={() => toggleTool(tool.id)}
              className="flex w-full items-center gap-2 rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-expanded={expandedTools.has(tool.id)}
            >
              {expandedTools.has(tool.id) ? (
                <ChevronDown className="size-3.5 text-muted-foreground" />
              ) : (
                <ChevronRight className="size-3.5 text-muted-foreground" />
              )}
              {tool.status === 'completed' && <CheckCircle2 className="size-4 text-emerald-500" />}
              {tool.status === 'running' && <Loader2 className="size-4 animate-spin text-primary" />}
              {tool.status === 'failed' && <AlertCircle className="size-4 text-red-500" />}
              <span className="flex-1 text-sm">{tool.name}</span>
              {tool.duration && <span className="text-xs text-muted-foreground">{tool.duration}</span>}
            </button>
            {expandedTools.has(tool.id) && tool.output && (
              <div className="ml-8 mt-2 rounded-md bg-muted/50 p-3 text-xs text-muted-foreground">{tool.output}</div>
            )}
          </div>
        )) : (
          <div className="px-4 py-5 text-sm text-muted-foreground">
            {runStatus === 'completed'
              ? '本次运行已完成，但当前后端还没有返回可展开的工具调用明细。'
              : '当前还没有工具调用。启动 Run 后这里会显示真实执行流。'}
          </div>
        )}
      </div>
    </div>
  )
}
