'use client'

import { useState } from 'react'
import { Check, ChevronDown, ChevronRight, Edit3, FileText, MessageSquare, X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import type { SuggestionCard as SuggestionCardModel } from '@/lib/types'

export interface SuggestionActionInput {
  recordId: string
  decision: 'accepted' | 'accepted_with_edits' | 'rejected' | 'follow_up'
  note?: string
  editedDescription?: string
}

interface SuggestionCardProps {
  card: SuggestionCardModel
  mode?: 'default' | 'stage1'
  onConfirmSuggestion?: (input: SuggestionActionInput) => Promise<void> | void
  onFollowUpSuggestion?: (input: { title: string; note: string; description: string }) => Promise<void> | void
  onOpenSuggestionSource?: (card: SuggestionCardModel) => void
}

type DialogMode = 'accepted' | 'accepted_with_edits' | 'rejected' | 'follow_up'

export function SuggestionCard({
  card,
  mode = 'default',
  onConfirmSuggestion,
  onFollowUpSuggestion,
  onOpenSuggestionSource,
}: SuggestionCardProps) {
  const [isExpanded, setIsExpanded] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [dialogMode, setDialogMode] = useState<DialogMode | null>(null)
  const [dialogValue, setDialogValue] = useState('')
  const [errorMessage, setErrorMessage] = useState<string | undefined>()

  const riskColors = {
    low: 'bg-emerald-500/10 text-emerald-600',
    medium: 'bg-amber-500/10 text-amber-600',
    high: 'bg-red-500/10 text-red-600',
  }
  const isStageOne = mode === 'stage1'

  const submitAction = async (input: Omit<SuggestionActionInput, 'recordId'>) => {
    if (!card.recordId || !onConfirmSuggestion) return
    setIsSubmitting(true)
    setErrorMessage(undefined)
    try {
      await onConfirmSuggestion({ recordId: card.recordId, ...input })
      if (input.decision === 'follow_up' && input.note?.trim()) {
        await onFollowUpSuggestion?.({
          title: card.title,
          note: input.note.trim(),
          description: card.description,
        })
      }
      setDialogMode(null)
      setDialogValue('')
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '建议操作失败，请稍后重试。')
    } finally {
      setIsSubmitting(false)
    }
  }

  const openDialog = (mode: DialogMode) => {
    setDialogMode(mode)
    setDialogValue(mode === 'accepted_with_edits' ? card.description : '')
  }

  const dialogTitle = {
    accepted: '确认写回',
    accepted_with_edits: '编辑后采纳',
    rejected: '拒绝建议',
    follow_up: '追问建议',
  }[dialogMode ?? 'accepted_with_edits']

  return (
    <div className="rounded-md bg-muted/20 p-3">
      <div>
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <h4 className="text-sm font-medium">{card.title}</h4>
              <span className={cn('rounded-full px-2 py-0.5 text-[10px] font-medium', riskColors[card.risk])}>
                {card.risk === 'low' && '低风险'}
                {card.risk === 'medium' && '中风险'}
                {card.risk === 'high' && '高风险'}
              </span>
            </div>
            <div className="mt-1 flex items-center gap-3 text-xs text-muted-foreground">
              <span>来源：{card.source}</span>
              {card.sourceFile && <span>来源文件：{card.sourceFile}</span>}
              <span>影响：{card.impact}</span>
              {card.action && <span>动作：{card.action}</span>}
            </div>
            {card.sourceDetails && card.sourceDetails.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2">
                {card.sourceDetails.map((detail) => (
                  <span key={detail} className="rounded-md bg-muted px-2 py-1 text-[11px] text-muted-foreground">
                    {detail}
                  </span>
                ))}
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={() => setIsExpanded(!isExpanded)}
            className="rounded-md p-1 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={isExpanded ? '收起建议详情' : '展开建议详情'}
            aria-expanded={isExpanded}
          >
            {isExpanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
          </button>
        </div>

        {isExpanded && <div className="mt-3 rounded-md bg-muted/50 p-3 text-xs text-muted-foreground">{card.description}</div>}
        {errorMessage && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            <span>{errorMessage}</span>
            <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => setErrorMessage(undefined)}>
              知道了
            </Button>
          </div>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            className="h-7 gap-1 text-xs"
            disabled={isSubmitting || !card.recordId}
            onClick={() => isStageOne ? openDialog('accepted') : void submitAction({ decision: 'accepted' })}
          >
            <Check className="size-3" />
            {isStageOne ? '确认写回' : '采纳'}
          </Button>
          <Button variant="outline" size="sm" className="h-7 gap-1 text-xs" disabled={isSubmitting || !card.recordId} onClick={() => openDialog('accepted_with_edits')}>
            <Edit3 className="size-3" />
            {isStageOne ? '编辑后写回' : '编辑后采纳'}
          </Button>
          <Button variant="ghost" size="sm" className="h-7 gap-1 text-xs text-muted-foreground" disabled={isSubmitting || !card.recordId} onClick={() => openDialog('rejected')}>
            <X className="size-3" />
            {isStageOne ? '不写回' : '拒绝'}
          </Button>
          <Button variant="ghost" size="sm" className="h-7 gap-1 text-xs text-muted-foreground" disabled={isSubmitting || !card.recordId} onClick={() => openDialog('follow_up')}>
            <MessageSquare className="size-3" />
            追问
          </Button>
          {card.sourceFile && (
            <Button variant="ghost" size="sm" className="h-7 gap-1 text-xs text-muted-foreground" onClick={() => onOpenSuggestionSource?.(card)}>
              <FileText className="size-3" />
              查看来源
            </Button>
          )}
        </div>
      </div>

      <Dialog open={dialogMode !== null} onOpenChange={(open) => !open && setDialogMode(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{isStageOne && dialogMode === 'accepted_with_edits' ? '编辑后写回' : dialogTitle}</DialogTitle>
            <DialogDescription>
              {isStageOne
                ? '请确认是否将该修正写回阶段一产物。确认后会调用后端写回接口并刷新阶段结果。'
                : '该操作会调用后端确认接口并刷新当前阶段上下文。'}
            </DialogDescription>
          </DialogHeader>
          {dialogMode === 'accepted' ? (
            <div className="rounded-md border border-border bg-muted/30 p-3 text-sm text-muted-foreground">
              {card.description}
            </div>
          ) : (
            <Textarea
              value={dialogValue}
              onChange={(event) => setDialogValue(event.target.value)}
              placeholder={dialogMode === 'rejected' ? '填写拒绝原因' : '填写补充说明'}
              className="min-h-28"
            />
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogMode(null)} disabled={isSubmitting}>
              取消
            </Button>
            <Button
              disabled={isSubmitting || (dialogMode !== 'accepted' && !dialogValue.trim())}
              onClick={() => {
                if (!dialogMode) return
                void submitAction({
                  decision: dialogMode,
                  note: dialogMode === 'accepted_with_edits' || dialogMode === 'accepted' ? undefined : dialogValue.trim(),
                  editedDescription: dialogMode === 'accepted_with_edits' ? dialogValue.trim() : undefined,
                })
              }}
            >
              {isSubmitting ? '提交中...' : '确认'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
