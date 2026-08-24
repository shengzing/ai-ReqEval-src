'use client'

import { ListFilter } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { EvidenceItem } from '@/lib/types'
import type { FileParseStateMap } from '@/lib/file-parse-lifecycle'
import type { EvidenceStatusFilter, EvidenceSuggestionInput } from './evidence-types'
import { EvidenceGroup } from './evidence-group'
import { EvidenceStatusFilter as EvidenceStatusFilterControl } from './evidence-status-filter'

interface EvidencePanelProps {
  groupedEvidence: Record<string, EvidenceItem[]>
  expandedGroups: Set<string>
  currentStageName?: string
  showAllEvidence: boolean
  isFallbackToAll: boolean
  statusFilter: EvidenceStatusFilter
  statusCounts: Record<'all' | EvidenceItem['status'], number>
  highlightedEvidenceName?: string
  onToggleShowAll: () => void
  onStatusFilterChange: (status: EvidenceStatusFilter) => void
  onToggleGroup: (group: string) => void
  onParseFile?: (fileId: string) => Promise<void> | void
  fileParseStates: FileParseStateMap
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

export function EvidencePanel({
  groupedEvidence,
  expandedGroups,
  currentStageName,
  showAllEvidence,
  isFallbackToAll,
  statusFilter,
  statusCounts,
  highlightedEvidenceName,
  onToggleShowAll,
  onStatusFilterChange,
  onToggleGroup,
  onParseFile,
  fileParseStates,
  onVisionParseFile,
  onReviewRelevance,
  onAskEvidenceDetail,
  onCreateEvidenceSuggestion,
  onPreviewResource,
}: EvidencePanelProps) {
  return (
    <ScrollArea className="flex-1">
      <div className="space-y-3 p-4">
        <div className="rounded-lg border border-border bg-muted/30 p-3">
          <div className="flex items-start gap-2">
            <ListFilter className="mt-0.5 size-4 shrink-0 text-primary" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-foreground">
                {showAllEvidence || isFallbackToAll ? '全部项目资料' : '当前阶段资料'}
              </p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                {isFallbackToAll && !showAllEvidence ? '当前阶段暂未绑定资料，已临时显示全部资料。' : currentStageName ?? '未选择阶段'}
              </p>
            </div>
            <Button variant="outline" size="sm" className="h-7 shrink-0 text-xs" onClick={onToggleShowAll}>
              {showAllEvidence ? '仅当前阶段' : '查看全部'}
            </Button>
          </div>
        </div>

        <EvidenceStatusFilterControl
          statusFilter={statusFilter}
          statusCounts={statusCounts}
          onStatusFilterChange={onStatusFilterChange}
        />

        {Object.entries(groupedEvidence).map(([group, items]) => (
          <EvidenceGroup
            key={group}
            group={group}
            items={items}
            isExpanded={expandedGroups.has(group)}
            highlightedEvidenceName={highlightedEvidenceName}
            onToggleGroup={onToggleGroup}
            onParseFile={onParseFile}
            fileParseStates={fileParseStates}
            onVisionParseFile={onVisionParseFile}
            onReviewRelevance={onReviewRelevance}
            onAskEvidenceDetail={onAskEvidenceDetail}
            onCreateEvidenceSuggestion={onCreateEvidenceSuggestion}
            onPreviewResource={onPreviewResource}
          />
        ))}

        {Object.values(groupedEvidence).every((items) => items.length === 0) && (
          <div className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
            当前筛选条件下没有资料。可以切换状态筛选，或先上传/解析材料。
          </div>
        )}
      </div>
    </ScrollArea>
  )
}
