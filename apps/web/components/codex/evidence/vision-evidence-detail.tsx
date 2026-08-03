'use client'

import { useState } from 'react'
import { AlertCircle, Wand2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { EvidenceItem } from '@/lib/types'
import type { EvidenceSuggestionInput } from './evidence-types'

interface VisionEvidenceDetailProps {
  item: EvidenceItem
  onAskEvidenceDetail?: (prompt: string) => Promise<void> | void
  onCreateEvidenceSuggestion?: (input: EvidenceSuggestionInput) => Promise<void> | void
}

export function VisionEvidenceDetail({ item, onAskEvidenceDetail, onCreateEvidenceSuggestion }: VisionEvidenceDetailProps) {
  const [asking, setAsking] = useState(false)
  const [creatingSuggestion, setCreatingSuggestion] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string>()
  const toConfirmLines = (item.detailLines ?? []).filter((line) => line.startsWith('待确认：'))
  const uncertainLines = (item.detailLines ?? []).filter((line) => line.startsWith('不确定：'))
  const otherLines = (item.detailLines ?? []).filter((line) => !line.startsWith('待确认：') && !line.startsWith('不确定：'))

  const handleAsk = async (line: string, type: 'to_confirm' | 'uncertainty') => {
    if (!onAskEvidenceDetail) return
    setAsking(true)
    setErrorMessage(undefined)
    try {
      await onAskEvidenceDetail(
        type === 'to_confirm'
          ? `请基于资料「${item.name}」的视觉解析结果，只分析这一条待确认字段，并给出需要人工确认的结论、补充材料建议和下一步动作：\n${line}`
          : `请基于资料「${item.name}」的视觉解析结果，只分析这一条不确定项，说明不确定原因、补证方式和是否需要人工确认：\n${line}`
      )
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '追问失败，请重试。')
    } finally {
      setAsking(false)
    }
  }

  const handleCreateSuggestion = async (line: string, type: 'to_confirm' | 'uncertainty') => {
    if (!onCreateEvidenceSuggestion) return
    setCreatingSuggestion(true)
    setErrorMessage(undefined)
    try {
      await onCreateEvidenceSuggestion({
        title: type === 'to_confirm' ? `视觉待确认：${item.name}` : `视觉不确定项：${item.name}`,
        description:
          type === 'to_confirm'
            ? `来源资料「${item.name}」存在待确认字段，需要进入当前阶段建议流处理：${line}`
            : `来源资料「${item.name}」存在视觉解析不确定项，需要进入当前阶段建议流处理：${line}`,
        action: type === 'to_confirm' ? '请补充该字段依据，确认是否采纳为正式结论。' : '请补证或人工核对该不确定项，再决定是否写入阶段结论。',
        impact: type === 'to_confirm' ? '影响当前阶段结果' : '影响当前阶段证据完整性',
        risk: 'medium',
        source: 'vision_manual',
        context: {
          source_file: item.name,
          source_line: line,
          source_type: type,
        },
      })
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '加入建议失败，请重试。')
    } finally {
      setCreatingSuggestion(false)
    }
  }

  return (
    <div className="mt-2 rounded-md bg-muted/40 p-2">
      <LineGroup
        title="待确认字段"
        lines={toConfirmLines}
        className="space-y-2"
        actionLabel="追问此字段"
        suggestionLabel="加入建议"
        asking={asking}
        creatingSuggestion={creatingSuggestion}
        onAsk={(line) => handleAsk(line, 'to_confirm')}
        onCreateSuggestion={(line) => handleCreateSuggestion(line, 'to_confirm')}
        canAsk={Boolean(onAskEvidenceDetail)}
        canCreateSuggestion={Boolean(onCreateEvidenceSuggestion)}
      />
      <LineGroup
        title="不确定项"
        lines={uncertainLines}
        className={cn('space-y-2', toConfirmLines.length > 0 && 'mt-3')}
        actionLabel="分析此项"
        suggestionLabel="加入建议"
        asking={asking}
        creatingSuggestion={creatingSuggestion}
        onAsk={(line) => handleAsk(line, 'uncertainty')}
        onCreateSuggestion={(line) => handleCreateSuggestion(line, 'uncertainty')}
        canAsk={Boolean(onAskEvidenceDetail)}
        canCreateSuggestion={Boolean(onCreateEvidenceSuggestion)}
      />
      {toConfirmLines.length === 0 && uncertainLines.length === 0 && otherLines.map((line) => (
        <p key={line} className="text-xs leading-5 text-muted-foreground">{line}</p>
      ))}
      {errorMessage && (
        <div className="mt-2 rounded-md border border-destructive/30 bg-destructive/10 px-2 py-1.5 text-xs text-destructive">
          {errorMessage}
        </div>
      )}
    </div>
  )
}

function LineGroup({
  title,
  lines,
  className,
  actionLabel,
  suggestionLabel,
  asking,
  creatingSuggestion,
  canAsk,
  canCreateSuggestion,
  onAsk,
  onCreateSuggestion,
}: {
  title: string
  lines: string[]
  className?: string
  actionLabel: string
  suggestionLabel: string
  asking: boolean
  creatingSuggestion: boolean
  canAsk: boolean
  canCreateSuggestion: boolean
  onAsk: (line: string) => void
  onCreateSuggestion: (line: string) => void
}) {
  if (!lines.length) return null

  return (
    <div className={className}>
      <p className="text-[11px] font-medium tracking-normal text-foreground">{title}</p>
      {lines.map((line) => (
        <div key={line} className="rounded border border-border bg-background/70 p-2">
          <p className="text-xs leading-5 text-muted-foreground">{line}</p>
          {(canAsk || canCreateSuggestion) && (
            <div className="mt-2 flex flex-wrap gap-2">
              {canAsk && (
                <Button variant="outline" size="sm" className="h-7 gap-1 px-2 text-xs" disabled={asking} onClick={() => onAsk(line)}>
                  <Wand2 className="size-3" />
                  {asking ? '发起中' : actionLabel}
                </Button>
              )}
              {canCreateSuggestion && (
                <Button variant="outline" size="sm" className="h-7 gap-1 px-2 text-xs" disabled={creatingSuggestion} onClick={() => onCreateSuggestion(line)}>
                  <AlertCircle className="size-3" />
                  {creatingSuggestion ? '加入中' : suggestionLabel}
                </Button>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
