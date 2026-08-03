'use client'

import type { Stage } from '@/lib/types'

export function StageVersionPanel({ stage }: { stage: Stage }) {
  if (!stage.versionLog?.versionId) return null

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-foreground">阶段版本</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            版本：{stage.versionLog.versionId}
            {stage.versionLog.lockedAt ? ` · 已锁定 ${new Date(stage.versionLog.lockedAt).toLocaleString('zh-CN')}` : ' · 草稿版本'}
          </p>
        </div>
      </div>
      {stage.versionLog.diffFields && stage.versionLog.diffFields.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {stage.versionLog.diffFields.map((field) => (
            <span key={field} className="rounded-md bg-muted px-2 py-1 text-[11px] text-muted-foreground">
              {field}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
