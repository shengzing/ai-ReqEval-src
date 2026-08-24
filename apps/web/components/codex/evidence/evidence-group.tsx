'use client'

import { ChevronDown, ChevronRight } from 'lucide-react'

import type { EvidenceItem } from '@/lib/types'
import type { FileParseStateMap } from '@/lib/file-parse-lifecycle'
import type { EvidenceSuggestionInput } from './evidence-types'
import { EvidenceItemRow } from './evidence-item-row'

interface EvidenceGroupProps {
  group: string
  items: EvidenceItem[]
  isExpanded: boolean
  highlightedEvidenceName?: string
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

export function EvidenceGroup({
  group,
  items,
  isExpanded,
  highlightedEvidenceName,
  onToggleGroup,
  onParseFile,
  fileParseStates,
  onVisionParseFile,
  onReviewRelevance,
  onAskEvidenceDetail,
  onCreateEvidenceSuggestion,
  onPreviewResource,
}: EvidenceGroupProps) {
  if (!items.length) return null

  return (
    <div className="rounded-lg border border-border">
      <button
        type="button"
        onClick={() => onToggleGroup(group)}
        className="flex w-full items-center gap-2 px-3 py-2 text-sm font-medium text-foreground hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-expanded={isExpanded}
      >
        {isExpanded ? <ChevronDown className="size-4 text-muted-foreground" /> : <ChevronRight className="size-4 text-muted-foreground" />}
        <span className="flex-1 text-left">{group}</span>
        <span className="text-xs text-muted-foreground">{items.length}</span>
      </button>

      {isExpanded && (
        <div className="border-t border-border">
          {items.map((item) => (
            <EvidenceItemRow
              key={item.id}
              item={item}
              highlighted={item.name.includes(highlightedEvidenceName ?? '') && Boolean(highlightedEvidenceName)}
              onParseFile={onParseFile}
              parseState={item.sourceFileId ? fileParseStates[item.sourceFileId] : undefined}
              onVisionParseFile={onVisionParseFile}
              onReviewRelevance={onReviewRelevance}
              onAskEvidenceDetail={onAskEvidenceDetail}
              onCreateEvidenceSuggestion={onCreateEvidenceSuggestion}
              onPreviewResource={onPreviewResource}
            />
          ))}
        </div>
      )}
    </div>
  )
}
