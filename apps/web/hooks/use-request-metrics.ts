'use client'

import { useEffect, useState } from 'react'

import {
  CLIENT_REQUEST_METRIC_EVENT,
  getClientRequestMetrics,
  getClientRequestMetricSummary,
  resetClientRequestMetrics,
  type ClientRequestMetric,
  type ClientRequestMetricSummary,
} from '@/lib/request-lifecycle'

/**
 * HCR-P1-05：订阅 CLIENT_REQUEST_METRIC_EVENT 并暴露聚合 summary + 近期
 * metrics 列表 + reset。仅在浏览器运行（request-lifecycle.ts 内部已
 * guard typeof window）。让 dev 面板区分"后台刷新"与"再次执行智能体"。
 */
export function useRequestMetrics(): {
  summary: ClientRequestMetricSummary
  metrics: ClientRequestMetric[]
  reset: () => void
} {
  const [tick, setTick] = useState(0)

  useEffect(() => {
    const handler = () => setTick((value) => value + 1)
    window.addEventListener(CLIENT_REQUEST_METRIC_EVENT, handler)
    return () => window.removeEventListener(CLIENT_REQUEST_METRIC_EVENT, handler)
  }, [])

  // tick 仅作重渲染触发；读最新值。
  void tick
  return {
    summary: getClientRequestMetricSummary(),
    metrics: getClientRequestMetrics(),
    reset: resetClientRequestMetrics,
  }
}
