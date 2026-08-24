'use client'

import { useEffect, useState } from 'react'
import { Ban, CheckCircle2, ChevronDown, ChevronRight, CircleDashed, Eye, Link2, Loader2, MoreHorizontal, RefreshCw, ScanSearch, ShieldX, UserRoundCheck } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'
import type { EvidenceItem } from '@/lib/types'
import type { FileParseState } from '@/lib/file-parse-lifecycle'
import { canVisionParseEvidence, isImageEvidence, type EvidenceSuggestionInput, statusConfig, typeIcons } from './evidence-types'
import { VisionEvidenceDetail } from './vision-evidence-detail'

const RELEVANCE_LABELS: Record<EvidenceItem['relevanceStatus'], string> = {
  pending_parse: '待解析',
  needs_review: '待人工复核',
  related: '与项目相关',
  unrelated: '与项目无关',
  rejected: '已拒绝纳入',
}

function relevanceLabel(status: string): string {
  return (RELEVANCE_LABELS as Record<string, string>)[status] ?? status
}

/** 打开复核面板/切换结论时的默认复核依据，减少重复手输；用户改过的内容不被覆盖。 */
const DEFAULT_REVIEW_REASONS: Record<'related' | 'unrelated' | 'rejected', string> = {
  related: '人工确认与当前项目场景相关，纳入阶段分析。',
  unrelated: '人工确认与当前项目场景无关，不纳入阶段分析。',
  rejected: '人工确认不符合纳入要求，拒绝纳入。',
}

function isDefaultReviewReason(value: string, previousSaved?: string): boolean {
  const trimmed = value.trim()
  if (!trimmed) return true
  if (previousSaved && trimmed === previousSaved) return true
  return Object.values(DEFAULT_REVIEW_REASONS).includes(trimmed)
}

interface EvidenceItemRowProps {
  item: EvidenceItem
  highlighted?: boolean
  onParseFile?: (fileId: string) => Promise<void> | void
  parseState?: FileParseState
  onVisionParseFile?: (fileId: string) => Promise<void> | void
  onReviewRelevance?: (
    fileId: string,
    decision: 'related' | 'unrelated' | 'rejected',
    reason: string,
  ) => Promise<void> | void
  onAskEvidenceDetail?: (prompt: string) => Promise<void> | void
  onCreateEvidenceSuggestion?: (input: EvidenceSuggestionInput) => Promise<void> | void
  onPreviewResource?: (item: EvidenceItem) => void
}

export function EvidenceItemRow({
  item,
  highlighted,
  onParseFile,
  parseState,
  onVisionParseFile,
  onReviewRelevance,
  onAskEvidenceDetail,
  onCreateEvidenceSuggestion,
  onPreviewResource,
}: EvidenceItemRowProps) {
  const status = statusConfig[item.status]
  const TypeIcon = typeIcons[item.type]
  const StatusIcon = status.icon
  const [visionParsing, setVisionParsing] = useState(false)
  const [reviewing, setReviewing] = useState(false)
  const [reviewOpen, setReviewOpen] = useState(false)
  const [reviewDecision, setReviewDecision] = useState<'related' | 'unrelated' | 'rejected'>('related')
  const [reviewReason, setReviewReason] = useState('')
  const [expandedDetail, setExpandedDetail] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string>()
  const showVisionParse = item.status === 'uploaded' && canVisionParseEvidence(item)
  const canPreview = item.type === 'file' && Boolean(item.sourceFileId) && Boolean(onPreviewResource)
  const canReparse = Boolean(
    item.type === 'file'
    && item.sourceFileId
    && onParseFile
    && !isImageEvidence(item),
  )
  const parsing = parseState?.status === 'parsing'
  const canReviewRelevance = Boolean(
    item.type === 'file'
    && item.sourceFileId
    && onReviewRelevance
    && item.relevanceStatus !== 'pending_parse',
  )
  const relevanceConfig = {
    pending_parse: { label: '待解析', className: 'text-muted-foreground' },
    needs_review: { label: '待人工复核', className: 'text-amber-600' },
    related: { label: '与项目相关', className: 'text-emerald-600' },
    unrelated: { label: '与项目无关', className: 'text-muted-foreground' },
    rejected: { label: '已拒绝纳入', className: 'text-destructive' },
  }[item.relevanceStatus]

  useEffect(() => {
    if (highlighted && item.detailLines && item.detailLines.length > 0) {
      setExpandedDetail(true)
    }
  }, [highlighted, item.detailLines])

  const handleVisionParse = async () => {
    setVisionParsing(true)
    setErrorMessage(undefined)
    try {
      await onVisionParseFile?.(item.id)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '视觉解析失败，请重试。')
    } finally {
      setVisionParsing(false)
    }
  }

  const handleReview = async () => {
    setReviewing(true)
    setErrorMessage(undefined)
    try {
      await onReviewRelevance?.(item.sourceFileId!, reviewDecision, reviewReason.trim())
      setReviewOpen(false)
      setReviewReason('')
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '相关性复核失败，请重试。')
    } finally {
      setReviewing(false)
    }
  }

  const handleReviewDecisionChange = (decision: 'related' | 'unrelated' | 'rejected') => {
    // 切换结论时：若当前理由还是默认值（或与已保存结论一致），同步换成对应默认文案；
    // 用户已手动输入的内容保持不变。
    setReviewReason((previous) =>
      isDefaultReviewReason(previous, item.relevanceReviewReason ?? undefined)
        ? DEFAULT_REVIEW_REASONS[decision]
        : previous,
    )
    setReviewDecision(decision)
  }

  return (
    <div className={cn('flex flex-col gap-1.5 px-3 py-2 transition-colors hover:bg-muted/30', highlighted && 'bg-primary/5 ring-1 ring-inset ring-primary/40')}>
      {/* 第一行：图标 + 名称 + 状态 + 操作 */}
      <div className="flex items-center gap-2">
        <TypeIcon className="size-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
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
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {/* 文件处理状态 + 相关性状态 */}
          <span className={cn('text-xs', status.className)}>
            {status.label}
          </span>
          <span className={cn('text-xs', relevanceConfig.className)}>
            {relevanceConfig.label}
          </span>
          {item.relevanceStatus !== 'pending_parse' && (
            <span className="text-xs text-muted-foreground">
              {Math.round(item.relevanceScore * 100)}%
            </span>
          )}
          {/* 操作按钮 */}
          <div className="flex items-center gap-0.5">
            {canPreview && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="size-6"
                    onClick={() => onPreviewResource?.(item)}
                    aria-label={`预览 ${item.name}`}
                  >
                    <Eye className="size-3.5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="top" sideOffset={6}>预览</TooltipContent>
              </Tooltip>
            )}
            {canReparse && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="size-6"
                    disabled={parsing}
                    onClick={() => void onParseFile?.(item.sourceFileId!)}
                    aria-label={`重新解析 ${item.name}`}
                  >
                    {parsing ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="top" sideOffset={6}>{parsing ? '解析中' : '重新解析'}</TooltipContent>
              </Tooltip>
            )}
            {/* 更多操作下拉菜单 */}
            {(showVisionParse || canReviewRelevance || (item.detailLines?.length ?? 0) > 0) && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="size-6"
                    aria-label={`更多操作 ${item.name}`}
                  >
                    <MoreHorizontal className="size-3.5" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-40">
                  {showVisionParse && onVisionParseFile && (
                    <DropdownMenuItem
                      disabled={visionParsing}
                      onClick={() => void handleVisionParse()}
                    >
                      <ScanSearch className="size-3.5" />
                      {visionParsing ? '视觉解析中' : '视觉解析'}
                    </DropdownMenuItem>
                  )}
                  {canReviewRelevance && (
                    <DropdownMenuItem
                      onClick={() => {
                        const initialDecision =
                          item.relevanceStatus === 'related' || item.relevanceStatus === 'unrelated' || item.relevanceStatus === 'rejected'
                            ? item.relevanceStatus
                            : 'related'
                        setReviewDecision(initialDecision)
                        // 打开复核面板即预填默认依据；已有历史复核理由时回填原理由。
                        setReviewReason(item.relevanceReviewReason ?? DEFAULT_REVIEW_REASONS[initialDecision])
                        setReviewOpen(true)
                      }}
                    >
                      <UserRoundCheck className="size-3.5" />
                      复核相关性
                    </DropdownMenuItem>
                  )}
                  {item.detailLines && item.detailLines.length > 0 && (
                    <>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem onClick={() => setExpandedDetail((previous) => !previous)}>
                        {expandedDetail ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                        {expandedDetail ? '收起详情' : '查看详情'}
                      </DropdownMenuItem>
                    </>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
        </div>
      </div>

      {/* 第二行：元信息 */}
      <div className="flex items-center gap-2 pl-6 text-xs text-muted-foreground">
        {item.stage && <span>{item.stage}</span>}
        <span>{item.updatedAt}</span>
        {item.relevanceSource === 'human' && <span className="text-foreground">人工结论</span>}
        {item.isReferenced && <Link2 className="size-3 text-emerald-500" />}
      </div>

      {/* 第三行：关键原因/摘要（最多2条） */}
      {item.relevanceReasons.length > 0 && (
        <div className="pl-6 space-y-0.5">
          {item.relevanceReasons.slice(0, 2).map((reason) => (
            <p key={reason} className="text-xs leading-4 text-muted-foreground">{reason}</p>
          ))}
        </div>
      )}

      {/* 待复核提示 */}
      {item.relevanceStatus === 'needs_review' && (
        <p className="pl-6 text-xs leading-4 text-amber-600">待复核：须人工确认后才能纳入阶段执行。</p>
      )}

      {/* 已脱敏提示（非阻断：脱敏后仍进入阶段分析） */}
      {item.securityRejected && (
        <p className="pl-6 text-xs leading-4 text-amber-600">已脱敏：检测到敏感配置，已自动脱敏后纳入分析。</p>
      )}

      {/* 解析状态 */}
      {parseState && (
        <div
          className={cn('pl-6 text-xs', parseState.status === 'error' ? 'text-destructive' : parseState.status === 'success' ? 'text-emerald-600' : 'text-primary')}
          aria-live="polite"
        >
          {parseState.message}
        </div>
      )}

      {/* 错误消息 */}
      {errorMessage && (
        <div className="ml-6 flex items-center justify-between gap-2 rounded border border-destructive/30 bg-destructive/10 px-2 py-1 text-xs text-destructive">
          <span className="truncate">{errorMessage}</span>
          <button
            type="button"
            className="shrink-0 rounded px-1 underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            onClick={() => setErrorMessage(undefined)}
          >
            关闭
          </button>
        </div>
      )}

      {/* 详情展开 */}
      {expandedDetail && item.detailLines && item.detailLines.length > 0 && (
        <div className="pl-6">
          <VisionEvidenceDetail
            item={item}
            onAskEvidenceDetail={onAskEvidenceDetail}
            onCreateEvidenceSuggestion={onCreateEvidenceSuggestion}
          />
        </div>
      )}

      {/* 复核面板 */}
      {reviewOpen && canReviewRelevance && (
        <div className="ml-6 mt-1 space-y-2 rounded border border-border bg-muted/30 p-2">
          <div className="flex flex-wrap gap-1" role="group" aria-label="相关性复核结论">
            <Button
              type="button"
              variant={reviewDecision === 'related' ? 'default' : 'outline'}
              size="sm"
              className="h-6 gap-1 px-1.5 text-xs"
              onClick={() => handleReviewDecisionChange('related')}
            >
              <CheckCircle2 className="size-3" />
              确认相关
            </Button>
            <Button
              type="button"
              variant={reviewDecision === 'unrelated' ? 'default' : 'outline'}
              size="sm"
              className="h-6 gap-1 px-1.5 text-xs"
              onClick={() => handleReviewDecisionChange('unrelated')}
            >
              <Ban className="size-3" />
              标记无关
            </Button>
            <Button
              type="button"
              variant={reviewDecision === 'rejected' ? 'destructive' : 'outline'}
              size="sm"
              className="h-6 gap-1 px-1.5 text-xs"
              onClick={() => handleReviewDecisionChange('rejected')}
            >
              <ShieldX className="size-3" />
              拒绝纳入
            </Button>
          </div>
          <Textarea
            value={reviewReason}
            onChange={(event) => setReviewReason(event.target.value)}
            rows={2}
            maxLength={500}
            placeholder="填写复核依据（至少 3 个字符）"
            aria-label="相关性复核依据"
            className="min-h-12 resize-y text-xs"
          />
          <div className="flex justify-end gap-1.5">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-6 text-xs"
              disabled={reviewing}
              onClick={() => {
                setReviewOpen(false)
                setReviewReason('')
              }}
            >
              取消
            </Button>
            <Button
              type="button"
              size="sm"
              className="h-6 text-xs"
              disabled={reviewing || reviewReason.trim().length < 3}
              onClick={() => void handleReview()}
            >
              {reviewing ? '保存中' : '保存结论'}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
