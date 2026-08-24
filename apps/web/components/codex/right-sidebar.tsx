'use client'

import { type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent, useEffect, useRef, useState } from 'react'
import { ClipboardList, FileText, GripVertical, X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { buildEvidenceStatusCounts } from '@/lib/api-mappers'
import {
  DEFAULT_RIGHT_SIDEBAR_WIDTH,
  MAX_RIGHT_SIDEBAR_WIDTH,
  MIN_RIGHT_SIDEBAR_WIDTH,
  adjustRightSidebarWidthFromKey,
  clampRightSidebarWidth,
  getAvailableRightSidebarMaxWidth,
  resizeRightSidebarFromPointer,
} from '@/lib/right-sidebar-width'
import { cn } from '@/lib/utils'
import { type EvidenceItem, type Stage } from '@/lib/types'
import type { FileParseStateMap } from '@/lib/file-parse-lifecycle'
import { EvidencePanel } from './evidence/evidence-panel'
import type { EvidenceStatusFilter, EvidenceSuggestionInput } from './evidence/evidence-types'
import { StageStatusPanel } from './evidence/stage-status-panel'

const RIGHT_SIDEBAR_WIDTH_STORAGE_KEY = 'ai-reqeval:right-sidebar-width'

interface ResizeSession {
  pointerId: number
  sidebarRight: number
  maxWidth: number
  previousCursor: string
  previousUserSelect: string
}

interface RightSidebarProps {
  isOpen: boolean
  onClose: () => void
  currentStage?: string
  currentStageData?: Stage
  evidenceItems: EvidenceItem[]
  highlightedEvidenceName?: string
  onParseFile?: (fileId: string) => Promise<void> | void
  fileParseStates?: FileParseStateMap
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

export function RightSidebar({
  isOpen,
  onClose,
  currentStage,
  currentStageData,
  evidenceItems,
  highlightedEvidenceName,
  onParseFile,
  fileParseStates = {},
  onVisionParseFile,
  onReviewRelevance,
  onAskEvidenceDetail,
  onCreateEvidenceSuggestion,
  onPreviewResource,
}: RightSidebarProps) {
  const [activeTab, setActiveTab] = useState<'evidence' | 'stage'>('evidence')
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set(['原始材料', '结构化记录']))
  const [showAllEvidence, setShowAllEvidence] = useState(false)
  const [statusFilter, setStatusFilter] = useState<EvidenceStatusFilter>('all')
  const [sidebarWidth, setSidebarWidth] = useState(DEFAULT_RIGHT_SIDEBAR_WIDTH)
  const [isResizing, setIsResizing] = useState(false)
  const asideRef = useRef<HTMLElement>(null)
  const sidebarWidthRef = useRef(sidebarWidth)
  const resizeSessionRef = useRef<ResizeSession | null>(null)

  const updateSidebarWidth = (width: number) => {
    sidebarWidthRef.current = width
    setSidebarWidth(width)
  }

  const persistSidebarWidth = (width: number) => {
    try {
      window.localStorage.setItem(RIGHT_SIDEBAR_WIDTH_STORAGE_KEY, String(width))
    } catch {
      // Resizing remains available when browser storage is unavailable.
    }
  }

  const getCurrentMaxWidth = () => {
    const aside = asideRef.current
    const mainWorkspace = aside?.parentElement?.firstElementChild
    if (!(aside instanceof HTMLElement) || !(mainWorkspace instanceof HTMLElement)) {
      return MAX_RIGHT_SIDEBAR_WIDTH
    }
    return getAvailableRightSidebarMaxWidth({
      currentWidth: sidebarWidthRef.current,
      mainWorkspaceWidth: mainWorkspace.getBoundingClientRect().width,
    })
  }

  useEffect(() => {
    try {
      const storedWidth = Number(window.localStorage.getItem(RIGHT_SIDEBAR_WIDTH_STORAGE_KEY))
      if (Number.isFinite(storedWidth) && storedWidth > 0) {
        updateSidebarWidth(clampRightSidebarWidth(storedWidth, getCurrentMaxWidth()))
      }
    } catch {
      // Keep the default width when browser storage is unavailable.
    }
  }, [])

  useEffect(() => {
    const handleWindowResize = () => {
      if (!window.matchMedia('(min-width: 1024px)').matches) return
      const width = clampRightSidebarWidth(sidebarWidthRef.current, getCurrentMaxWidth())
      if (width !== sidebarWidthRef.current) updateSidebarWidth(width)
    }
    window.addEventListener('resize', handleWindowResize)
    return () => window.removeEventListener('resize', handleWindowResize)
  }, [])

  useEffect(() => {
    return () => {
      const session = resizeSessionRef.current
      if (!session) return
      document.body.style.cursor = session.previousCursor
      document.body.style.userSelect = session.previousUserSelect
    }
  }, [])

  useEffect(() => {
    if (!isOpen) return
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose])

  useEffect(() => {
    if (!isOpen || !window.matchMedia('(min-width: 1024px)').matches) return
    const width = clampRightSidebarWidth(sidebarWidthRef.current, getCurrentMaxWidth())
    if (width !== sidebarWidthRef.current) updateSidebarWidth(width)
  }, [isOpen])

  if (!isOpen) return null

  const currentStageEvidence = evidenceItems.filter((item) => item.stage && currentStageData?.name.startsWith(item.stage))
  const scopedEvidence = showAllEvidence || currentStageEvidence.length === 0 ? evidenceItems : currentStageEvidence
  const visibleEvidence = statusFilter === 'all' ? scopedEvidence : scopedEvidence.filter((item) => item.status === statusFilter)
  const statusCounts = buildEvidenceStatusCounts(scopedEvidence)
  const groupedEvidence = {
    '原始材料': visibleEvidence.filter((item) => item.type === 'file'),
    '结构化记录': visibleEvidence.filter((item) => item.type === 'record'),
    '阶段结果': visibleEvidence.filter((item) => item.type === 'result'),
    '证据附件': visibleEvidence.filter((item) => item.type === 'attachment'),
    '报告文件': visibleEvidence.filter((item) => item.type === 'report'),
  }

  const toggleGroup = (group: string) => {
    const nextExpanded = new Set(expandedGroups)
    if (nextExpanded.has(group)) nextExpanded.delete(group)
    else nextExpanded.add(group)
    setExpandedGroups(nextExpanded)
  }

  const handleResizePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || !window.matchMedia('(min-width: 1024px)').matches) return
    const aside = asideRef.current
    if (!aside) return

    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    resizeSessionRef.current = {
      pointerId: event.pointerId,
      sidebarRight: aside.getBoundingClientRect().right,
      maxWidth: getCurrentMaxWidth(),
      previousCursor: document.body.style.cursor,
      previousUserSelect: document.body.style.userSelect,
    }
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    setIsResizing(true)
  }

  const handleResizePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const session = resizeSessionRef.current
    if (!session || session.pointerId !== event.pointerId) return
    updateSidebarWidth(resizeRightSidebarFromPointer({
      pointerClientX: event.clientX,
      sidebarRight: session.sidebarRight,
      maxWidth: session.maxWidth,
    }))
  }

  const finishResize = (event: PointerEvent<HTMLDivElement>) => {
    const session = resizeSessionRef.current
    if (!session || session.pointerId !== event.pointerId) return
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    document.body.style.cursor = session.previousCursor
    document.body.style.userSelect = session.previousUserSelect
    resizeSessionRef.current = null
    setIsResizing(false)
    persistSidebarWidth(sidebarWidthRef.current)
  }

  const handleResizeKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const width = adjustRightSidebarWidthFromKey({
      key: event.key,
      currentWidth: sidebarWidthRef.current,
      maxWidth: getCurrentMaxWidth(),
      step: event.shiftKey ? 50 : undefined,
    })
    if (width === undefined) return
    event.preventDefault()
    updateSidebarWidth(width)
    persistSidebarWidth(width)
  }

  const resetSidebarWidth = () => {
    const width = clampRightSidebarWidth(DEFAULT_RIGHT_SIDEBAR_WIDTH, getCurrentMaxWidth())
    updateSidebarWidth(width)
    persistSidebarWidth(width)
  }

  return (
    <aside
      ref={asideRef}
      style={{ '--right-sidebar-width': `${sidebarWidth}px` } as CSSProperties}
      className="relative flex h-[50vh] w-full shrink-0 flex-col border-t border-border bg-card lg:h-full lg:w-[var(--right-sidebar-width)] lg:border-l lg:border-t-0"
    >
      <div
        role="separator"
        aria-label="调整右侧面板宽度"
        aria-orientation="vertical"
        aria-valuemin={MIN_RIGHT_SIDEBAR_WIDTH}
        aria-valuemax={MAX_RIGHT_SIDEBAR_WIDTH}
        aria-valuenow={sidebarWidth}
        aria-valuetext={`${sidebarWidth} 像素`}
        tabIndex={0}
        title="拖动调整宽度，双击恢复默认宽度"
        onDoubleClick={resetSidebarWidth}
        onKeyDown={handleResizeKeyDown}
        onPointerDown={handleResizePointerDown}
        onPointerMove={handleResizePointerMove}
        onPointerUp={finishResize}
        onPointerCancel={finishResize}
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
      <div className="flex items-center border-b border-border">
        <button
          type="button"
          onClick={() => setActiveTab('evidence')}
          aria-selected={activeTab === 'evidence'}
          className={cn(
            'flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
            activeTab === 'evidence' ? 'border-primary text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground'
          )}
        >
          <FileText className="size-4" />
          资料与证据
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('stage')}
          aria-selected={activeTab === 'stage'}
          className={cn(
            'flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
            activeTab === 'stage' ? 'border-primary text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground'
          )}
        >
          <ClipboardList className="size-4" />
          阶段状态
        </button>
        <div className="flex-1" />
        <Button variant="ghost" size="icon-sm" onClick={onClose} className="mr-2" aria-label="关闭右侧栏">
          <X className="size-4" />
        </Button>
      </div>

      {activeTab === 'evidence' ? (
        <EvidencePanel
          groupedEvidence={groupedEvidence}
          expandedGroups={expandedGroups}
          currentStageName={currentStageData?.name}
          showAllEvidence={showAllEvidence}
          isFallbackToAll={currentStageEvidence.length === 0}
          statusFilter={statusFilter}
          statusCounts={statusCounts}
          highlightedEvidenceName={highlightedEvidenceName}
          onToggleShowAll={() => setShowAllEvidence(!showAllEvidence)}
          onStatusFilterChange={setStatusFilter}
          onToggleGroup={toggleGroup}
          onParseFile={onParseFile}
          fileParseStates={fileParseStates}
          onVisionParseFile={onVisionParseFile}
          onReviewRelevance={onReviewRelevance}
          onAskEvidenceDetail={onAskEvidenceDetail}
          onCreateEvidenceSuggestion={onCreateEvidenceSuggestion}
          onPreviewResource={onPreviewResource}
        />
      ) : (
        <StageStatusPanel currentStage={currentStage} stage={currentStageData} evidenceCount={visibleEvidence.length} />
      )}
    </aside>
  )
}
