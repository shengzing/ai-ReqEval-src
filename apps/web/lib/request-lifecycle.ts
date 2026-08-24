export type ClientRequestKind = 'interactive' | 'background_refresh' | 'agent_execution'
export type ClientRequestOutcome = 'success' | 'failed' | 'aborted'

export interface ClientRequestMetric {
  id: string
  kind: ClientRequestKind
  operation: string
  requestKey?: string
  method: string
  path: string
  status?: number
  outcome: ClientRequestOutcome
  durationMs: number
  startedAt: string
}

export interface ClientRequestMetricSummary {
  requestCount: number
  totalDurationMs: number
  averageDurationMs: number
  byKind: Record<ClientRequestKind, { requestCount: number; totalDurationMs: number }>
}

export const CLIENT_REQUEST_METRIC_EVENT = 'codex:client-request-metric'

const MAX_METRICS = 200
const metrics: ClientRequestMetric[] = []
let metricSequence = 0

function nowMs(): number {
  return typeof performance !== 'undefined' ? performance.now() : Date.now()
}

function emitMetric(metric: ClientRequestMetric): void {
  metrics.push(metric)
  if (metrics.length > MAX_METRICS) metrics.splice(0, metrics.length - MAX_METRICS)

  if (typeof window !== 'undefined' && typeof CustomEvent !== 'undefined') {
    window.dispatchEvent(new CustomEvent<ClientRequestMetric>(CLIENT_REQUEST_METRIC_EVENT, { detail: metric }))
  }
}

export function startClientRequest(input: {
  kind: ClientRequestKind
  operation: string
  requestKey?: string
  method: string
  path: string
}): (outcome: ClientRequestOutcome, status?: number) => void {
  const started = nowMs()
  const startedAt = new Date().toISOString()
  const id = `client-request-${++metricSequence}`
  let finished = false

  return (outcome, status) => {
    if (finished) return
    finished = true
    emitMetric({
      id,
      ...input,
      status,
      outcome,
      durationMs: Math.max(0, Math.round((nowMs() - started) * 100) / 100),
      startedAt,
    })
  }
}

export function getClientRequestMetrics(): ClientRequestMetric[] {
  return metrics.map((metric) => ({ ...metric }))
}

export function getClientRequestMetricSummary(): ClientRequestMetricSummary {
  const byKind: ClientRequestMetricSummary['byKind'] = {
    interactive: { requestCount: 0, totalDurationMs: 0 },
    background_refresh: { requestCount: 0, totalDurationMs: 0 },
    agent_execution: { requestCount: 0, totalDurationMs: 0 },
  }
  for (const metric of metrics) {
    byKind[metric.kind].requestCount += 1
    byKind[metric.kind].totalDurationMs += metric.durationMs
  }
  const totalDurationMs = metrics.reduce((total, metric) => total + metric.durationMs, 0)
  return {
    requestCount: metrics.length,
    totalDurationMs,
    averageDurationMs: metrics.length > 0 ? totalDurationMs / metrics.length : 0,
    byKind,
  }
}

export function resetClientRequestMetrics(): void {
  metrics.splice(0, metrics.length)
  metricSequence = 0
}

export interface LatestRequestToken {
  id: number
  key: string
  signal: AbortSignal
}

export interface LatestRequestGate {
  begin: (key: string) => LatestRequestToken
  isCurrent: (token: LatestRequestToken) => boolean
  finish: (token: LatestRequestToken) => void
  cancel: () => void
}

export function createLatestRequestGate(): LatestRequestGate {
  let sequence = 0
  let active: { id: number; key: string; controller: AbortController } | undefined

  return {
    begin(key) {
      active?.controller.abort()
      const controller = new AbortController()
      active = { id: ++sequence, key, controller }
      return { id: active.id, key, signal: controller.signal }
    },
    isCurrent(token) {
      return Boolean(
        active
        && active.id === token.id
        && active.key === token.key
        && !token.signal.aborted,
      )
    },
    finish(token) {
      if (active?.id === token.id) active = undefined
    },
    cancel() {
      active?.controller.abort()
      active = undefined
    },
  }
}

export function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError'
}
