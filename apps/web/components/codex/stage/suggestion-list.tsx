'use client'

import type { SuggestionCard as SuggestionCardModel } from '@/lib/types'
import { SuggestionActionInput, SuggestionCard } from './suggestion-card'

interface SuggestionListProps {
  suggestions: SuggestionCardModel[]
  mode?: 'default' | 'stage1'
  onConfirmSuggestion?: (input: SuggestionActionInput) => Promise<void> | void
  onFollowUpSuggestion?: (input: { title: string; note: string; description: string }) => Promise<void> | void
  onOpenSuggestionSource?: (card: SuggestionCardModel) => void
}

export function SuggestionList({
  suggestions,
  mode = 'default',
  onConfirmSuggestion,
  onFollowUpSuggestion,
  onOpenSuggestionSource,
}: SuggestionListProps) {
  return (
    <div className="space-y-3">
      {suggestions.length > 0 ? (
        suggestions.map((card) => (
          <SuggestionCard
            key={card.id}
            card={card}
            mode={mode}
            onConfirmSuggestion={onConfirmSuggestion}
            onFollowUpSuggestion={onFollowUpSuggestion}
            onOpenSuggestionSource={onOpenSuggestionSource}
          />
        ))
      ) : (
        <div className="text-sm text-muted-foreground">
          {mode === 'stage1'
            ? '当前没有待确认补丁。可以上传材料运行阶段一，或通过底部输入补充修正，但写回前仍需要人工确认。'
            : '当前阶段暂时没有待确认建议。可以继续对话，或让 Agent 运行本阶段推荐动作。'}
        </div>
      )}
    </div>
  )
}
