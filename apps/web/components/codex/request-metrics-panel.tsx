'use client'

import { useMemo, useState } from 'react'
import { Activity, ChevronDown, RotateCcw } from 'lucide-react'

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Button } from '@/components/ui/button'
import { useRequestMetrics } from '@/hooks/use-request-metrics'
import type { ClientRequestKind } from '@/lib/request-lifecycle'
import { cn } from '@/lib/utils'

/**
 * HCR-P1-05：dev-only 请求指标面板。
 * 订阅 request-lifecycle.ts 派发的 CLIENT_REQUEST_METRIC_EVENT，渲染
 * byKind 聚合（interactive / background_refresh / agent_execution）+ 近期
 * metric 列表，让开发者区分"后台刷新"与"再次执行智能体"。
 * 生产构建直接返回 null，不污染线上 UI。
 *
 * 两种形态：
 * - 默认 fixed 浮层（bottom-4 right-4）。
 * - `variant="inline"`：嵌入左侧边栏「设置」按钮上方，铺满侧栏宽度，
 *   面板内容向上展开；由父级（left-sidebar）自行保证 dev-only 渲染。
 */
const KIND_LABELS: Record<ClientRequestKind, string> = {
  interactive: '交互请求',
  background_refresh: '后台刷新',
  agent_execution: '智能体执行',
}

const KIND_BADGE_CLASS: Record<ClientRequestKind, string> = {
  interactive: 'bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300',
  background_refresh: 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300',
  agent_execution: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300',
}

function formatDuration(ms: number): string {
  if (ms < 1) return '<1ms'
  if (ms < 1000) return `${Math.round(ms * 10) / 10}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

export function RequestMetricsPanel({ variant = 'floating' }: { variant?: 'floating' | 'inline' }) {
  // Next.js 编译期替换 process.env.NODE_ENV；生产构建为 'production'，
  // 整个组件被树摇成 null，不会进入客户端 bundle。
  if (process.env.NODE_ENV !== 'development') return null

  const { summary, metrics, reset } = useRequestMetrics()
  const [open, setOpen] = useState(false)

  const recent = useMemo(() => [...metrics].reverse().slice(0, 20), [metrics])
  const kinds: ClientRequestKind[] = ['interactive', 'background_refresh', 'agent_execution']
  const inline = variant === 'inline'

  return (
    <div
      className={cn(
        'rounded-lg border border-border bg-background/95',
        inline
          ? 'relative mb-1 w-full overflow-hidden'
          : 'fixed bottom-4 right-4 z-50 w-80 max-w-[calc(100vw-2rem)] shadow-lg backdrop-blur',
      )}
    >
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left"
          >
            <span className="flex items-center gap-2 text-sm font-medium">
              <Activity className="h-4 w-4" />
              请求指标
              <span className="text-xs text-muted-foreground">{summary.requestCount} 次</span>
            </span>
            <ChevronDown
              className={cn(
                'h-4 w-4 text-muted-foreground transition-transform',
                // inline 嵌在侧栏底部，面板向上展开：收起时箭头朝上（rotate-180），展开后朝下。
                inline ? (open ? 'rotate-0' : 'rotate-180') : open && 'rotate-180',
              )}
            />
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="border-t border-border px-3 py-2">
            <div className="grid grid-cols-3 gap-2 text-xs">
              {kinds.map((kind) => {
                const entry = summary.byKind[kind]
                const avg = entry.requestCount > 0 ? entry.totalDurationMs / entry.requestCount : 0
                return (
                  <div
                    key={kind}
                    className="rounded border border-border bg-muted/30 p-1.5"
                    title={KIND_LABELS[kind]}
                  >
                    <div
                      className={cn(
                        'mb-0.5 inline-block rounded px-1 py-0.5 text-[10px] font-medium',
                        KIND_BADGE_CLASS[kind],
                      )}
                    >
                      {KIND_LABELS[kind]}
                    </div>
                    <div className="font-mono text-[11px] leading-tight">
                      {entry.requestCount} 次
                    </div>
                    <div className="font-mono text-[10px] text-muted-foreground">
                      均 {formatDuration(avg)}
                    </div>
                  </div>
                )
              })}
            </div>

            <div className={cn('mt-2 overflow-y-auto text-[11px]', inline ? 'max-h-36' : 'max-h-48')}>              {recent.length === 0 ? (
                <div className="py-2 text-center text-muted-foreground">暂无请求记录</div>
              ) : (
                <ul className="space-y-0.5 font-mono">
                  {recent.map((metric) => (
                    <li key={metric.id} className="flex items-center gap-1.5">
                      <span
                        className={cn(
                          'shrink-0 rounded px-1 py-0.5 text-[9px] font-medium',
                          KIND_BADGE_CLASS[metric.kind],
                        )}
                      >
                        {metric.kind === 'background_refresh'
                          ? 'BG'
                          : metric.kind === 'agent_execution'
                            ? 'AG'
                            : 'IN'}
                      </span>
                      <span className="truncate text-foreground" title={metric.operation}>
                        {metric.operation}
                      </span>
                      <span className="ml-auto shrink-0 text-muted-foreground">
                        {metric.status ?? metric.outcome} · {formatDuration(metric.durationMs)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="mt-2 flex items-center justify-between text-[10px] text-muted-foreground">
              <span>平均 {formatDuration(summary.averageDurationMs)} · 共 {formatDuration(summary.totalDurationMs)}</span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-6 gap-1 px-2 text-[10px]"
                onClick={reset}
              >
                <RotateCcw className="h-3 w-3" />
                清空
              </Button>
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  )
}
