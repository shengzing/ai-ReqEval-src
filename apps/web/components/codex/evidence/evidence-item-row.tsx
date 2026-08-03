'use client'

import { useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, Eye, Link2, ScanSearch, Wand2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import type { EvidenceItem } from '@/lib/types'
import { canVisionParseEvidence, type EvidenceSuggestionInput, statusConfig, typeIcons } from './evidence-types'
import { VisionEvidenceDetail } from './vision-evidence-detail'

interface EvidenceItemRowProps {
  item: EvidenceItem
  highlighted?: boolean
  onParseFile?: (fileId: string) => Promise<void> | void
  onVisionParseFile?: (fileId: string) => Promise<void> | void
  onAskEvidenceDetail?: (prompt: string) => Promise<void> | void
  onCreateEvidenceSuggestion?: (input: EvidenceSuggestionInput) => Promise<void> | void
  onPreviewResource?: (item: EvidenceItem) => void
}

export function EvidenceItemRow({
  item,
  highlighted,
  onParseFile,
  onVisionParseFile,
  onAskEvidenceDetail,
  onCreateEvidenceSuggestion,
  onPreviewResource,
}: EvidenceItemRowProps) {
  const status = statusConfig[item.status]
  const TypeIcon = typeIcons[item.type]
  const StatusIcon = status.icon
  const [parsing, setParsing] = useState(false)
  const [visionParsing, setVisionParsing] = useState(false)
  const [expandedDetail, setExpandedDetail] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string>()
  const showVisionParse = item.status === 'uploaded' && canVisionParseEvidence(item)
  const canPreview = item.type === 'file' && Boolean(item.sourceFileId) && Boolean(onPreviewResource)

  useEffect(() => {
    if (highlighted && item.detailLines && item.detailLines.length > 0) {
      setExpandedDetail(true)
    }
  }, [highlighted, item.detailLines])

  return (
    <div className={cn('flex flex-col gap-2 px-3 py-2 transition-colors hover:bg-muted/30 sm:flex-row sm:items-center sm:gap-3', highlighted && 'bg-primary/5 ring-1 ring-inset ring-primary/40')}>
      <TypeIcon className="size-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          {canPreview ? (
            <button
              type="button"
              onClick={() => onPreviewResource?.(item)}
              className="min-w-0 truncate rounded-sm text-left text-sm text-foreground underline-offset-2 hover:text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {item.name}
            </button>
          ) : (
            <span className="truncate text-sm text-foreground">{item.name}</span>
          )}
          {item.isReferenced && <Link2 className="size-3 shrink-0 text-emerald-500" />}
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {item.stage && <span>{item.stage}</span>}
          <span>{item.updatedAt}</span>
        </div>
        {item.summaryLines && item.summaryLines.length > 0 && (
          <div className="mt-1 space-y-1">
            {item.summaryLines.map((line) => (
              <p key={line} className="text-xs text-muted-foreground">{line}</p>
            ))}
          </div>
        )}
        {item.detailLines && item.detailLines.length > 0 && (
          <div className="mt-2">
            <button
              type="button"
              onClick={() => setExpandedDetail((previous) => !previous)}
              className="flex items-center gap-1 rounded-md text-xs text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-expanded={expandedDetail}
            >
              {expandedDetail ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
              <span>{expandedDetail ? '收起详情' : '查看详情'}</span>
            </button>
            {expandedDetail && (
              <VisionEvidenceDetail
                item={item}
                onAskEvidenceDetail={onAskEvidenceDetail}
                onCreateEvidenceSuggestion={onCreateEvidenceSuggestion}
              />
            )}
          </div>
        )}
        {errorMessage && (
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-2 py-1.5 text-xs text-destructive">
            <span>{errorMessage}</span>
            <button
              type="button"
              className="rounded px-1.5 py-0.5 underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => setErrorMessage(undefined)}
            >
              关闭
            </button>
          </div>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2 sm:justify-end">
        {canPreview && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                className="size-7"
                onClick={() => onPreviewResource?.(item)}
                aria-label={`预览 ${item.name}`}
              >
                <Eye className="size-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="top" sideOffset={6}>预览原始资源</TooltipContent>
          </Tooltip>
        )}
        {item.status === 'uploaded' && onParseFile && (
          <Button
            variant="outline"
            size="sm"
            className="h-7 gap-1 px-2 text-xs"
            disabled={parsing}
            onClick={async () => {
              setParsing(true)
              setErrorMessage(undefined)
              try {
                await onParseFile(item.id)
              } catch (error) {
                setErrorMessage(error instanceof Error ? error.message : '文件解析失败，请重试。')
              } finally {
                setParsing(false)
              }
            }}
          >
            <Wand2 className="size-3" />
            {parsing ? '解析中' : '解析'}
          </Button>
        )}
        {showVisionParse && onVisionParseFile && (
          <Button
            variant="outline"
            size="sm"
            className="h-7 gap-1 px-2 text-xs"
            disabled={visionParsing}
            onClick={async () => {
              setVisionParsing(true)
              setErrorMessage(undefined)
              try {
                await onVisionParseFile(item.id)
              } catch (error) {
                setErrorMessage(error instanceof Error ? error.message : '视觉解析失败，请重试。')
              } finally {
                setVisionParsing(false)
              }
            }}
          >
            <ScanSearch className="size-3" />
            {visionParsing ? '视觉解析中' : '视觉解析'}
          </Button>
        )}
        <div className={cn('flex items-center gap-1 text-xs', status.className)}>
          <StatusIcon className="size-3" />
          <span>{status.label}</span>
        </div>
      </div>
    </div>
  )
}
