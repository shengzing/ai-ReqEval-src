'use client'

import { CheckCircle2, FileOutput, FileText, ShieldCheck, XCircle } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { buildReportArtifactStatus, getReportGateState } from '@/lib/report-state'
import type { Stage } from '@/lib/types'

interface StageReportPanelProps {
  stage: Stage
  onPreviewReport?: () => Promise<void> | void
}

export function StageReportPanel({ stage, onPreviewReport }: StageReportPanelProps) {
  if (!stage.reportInfo?.title) return null

  const reportInfo = stage.reportInfo
  const gateState = getReportGateState(reportInfo)
  const exportItems = buildReportArtifactStatus(reportInfo).map((item) => ({
    ...item,
    icon: item.key === 'decision-card' ? ShieldCheck : item.key === 'evidence-directory' ? FileText : FileOutput,
  }))
  const ApprovalIcon = gateState.passed ? CheckCircle2 : XCircle

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <FileText className="size-4 text-primary" />
          <h3 className="text-sm font-medium text-foreground">报告产物</h3>
        </div>
        {onPreviewReport && (
          <Button variant="outline" size="sm" className="h-8 gap-1.5" onClick={() => void onPreviewReport()}>
            <FileText className="size-3.5" />
            预览报告
          </Button>
        )}
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div className="rounded-md bg-muted/40 p-3">
          <p className="text-xs text-muted-foreground">报告标题</p>
          <p className="mt-1 text-sm text-foreground">{reportInfo.title}</p>
        </div>
        <div className="rounded-md bg-muted/40 p-3">
          <p className="text-xs text-muted-foreground">生成状态</p>
          <p className="mt-1 text-sm text-foreground">{reportInfo.status}</p>
        </div>
      </div>

      <div className="mt-3 flex items-start gap-2 rounded-md bg-muted/30 p-3 text-xs">
        <ApprovalIcon className={gateState.passed ? 'mt-0.5 size-3.5 text-emerald-500' : 'mt-0.5 size-3.5 text-amber-500'} />
        <div>
          <p className="font-medium text-foreground">{gateState.label}</p>
          <p className="mt-1 text-muted-foreground">{gateState.message}</p>
        </div>
      </div>

      <div className="mt-3 grid gap-2 md:grid-cols-2">
        {exportItems.map((item) => {
          const Icon = item.icon
          return (
            <div key={item.label} className="rounded-md border border-border bg-background/60 p-3">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Icon className="size-3.5" />
                {item.label}
              </div>
              <p className="mt-1 break-all text-xs text-foreground">{item.available ? item.value : '后端暂未返回'}</p>
            </div>
          )
        })}
      </div>

      {reportInfo.content && (
        <div className="mt-3 rounded-md border border-border bg-muted/20 p-3">
          <p className="mb-2 text-xs text-muted-foreground">报告正文预览</p>
          <pre className="max-h-80 overflow-auto whitespace-pre-wrap text-xs leading-6 text-foreground">{reportInfo.content}</pre>
        </div>
      )}
    </div>
  )
}
