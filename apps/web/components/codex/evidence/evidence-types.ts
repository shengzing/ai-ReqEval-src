import { Archive, Check, ClipboardList, Database, File, FileOutput, Link2, Lock, Paperclip, Upload } from 'lucide-react'

import type { EvidenceItem } from '@/lib/types'

export type EvidenceStatusFilter = 'all' | EvidenceItem['status']

export interface EvidenceSuggestionInput {
  title: string
  description: string
  action: string
  impact?: string
  risk?: 'low' | 'medium' | 'high'
  source?: string
  context?: Record<string, unknown>
}

export const statusConfig = {
  uploaded: { label: '待解析', icon: Upload, className: 'text-muted-foreground' },
  parsed: { label: '已解析', icon: Check, className: 'text-blue-500' },
  referenced: { label: '已引用', icon: Link2, className: 'text-emerald-500' },
  locked: { label: '已锁定', icon: Lock, className: 'text-amber-500' },
  archived: { label: '已归档', icon: Archive, className: 'text-muted-foreground' },
}

export const typeIcons = {
  file: File,
  record: Database,
  result: ClipboardList,
  attachment: Paperclip,
  report: FileOutput,
}

export function canVisionParseEvidence(item: EvidenceItem) {
  const name = item.name.toLowerCase()
  return item.type === 'file' && /\.(png|jpe?g|webp|gif|bmp|tiff?|heic|pdf)$/i.test(name)
}
