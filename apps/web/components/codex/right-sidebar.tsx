'use client'

import { useEffect, useState } from 'react'
import { ClipboardList, FileText, X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { buildEvidenceStatusCounts } from '@/lib/api-mappers'
import { cn } from '@/lib/utils'
import { type EvidenceItem, type Stage } from '@/lib/types'
import { EvidencePanel } from './evidence/evidence-panel'
import type { EvidenceStatusFilter, EvidenceSuggestionInput } from './evidence/evidence-types'
import { StageStatusPanel } from './evidence/stage-status-panel'

interface RightSidebarProps {
  isOpen: boolean
  onClose: () => void
  currentStage?: string
  currentStageData?: Stage
  evidenceItems: EvidenceItem[]
  highlightedEvidenceName?: string
  onParseFile?: (fileId: string) => Promise<void> | void
  onVisionParseFile?: (fileId: string) => Promise<void> | void
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
  onVisionParseFile,
  onAskEvidenceDetail,
  onCreateEvidenceSuggestion,
  onPreviewResource,
}: RightSidebarProps) {
  const [activeTab, setActiveTab] = useState<'evidence' | 'stage'>('evidence')
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set(['原始材料', '结构化记录']))
  const [showAllEvidence, setShowAllEvidence] = useState(false)
  const [statusFilter, setStatusFilter] = useState<EvidenceStatusFilter>('all')

  useEffect(() => {
    if (!isOpen) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose])

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

  return (
    <aside className="flex h-[50vh] w-full shrink-0 flex-col border-t border-border bg-card lg:h-full lg:w-[360px] lg:border-l lg:border-t-0">
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
          onVisionParseFile={onVisionParseFile}
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
