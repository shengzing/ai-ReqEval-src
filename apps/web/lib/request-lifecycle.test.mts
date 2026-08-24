import assert from 'node:assert/strict'
import test from 'node:test'

import {
  CLIENT_REQUEST_METRIC_EVENT,
  createLatestRequestGate,
  getClientRequestMetrics,
  getClientRequestMetricSummary,
  resetClientRequestMetrics,
  startClientRequest,
} from './request-lifecycle.ts'

test('latest request gate aborts and rejects the previous request token', () => {
  const gate = createLatestRequestGate()
  const first = gate.begin('project-1:stage-1')
  const second = gate.begin('project-1:stage-2')

  assert.equal(first.signal.aborted, true)
  assert.equal(gate.isCurrent(first), false)
  assert.equal(gate.isCurrent(second), true)

  gate.finish(second)
  assert.equal(gate.isCurrent(second), false)
})

test('request metrics keep background refresh separate from agent execution', () => {
  resetClientRequestMetrics()
  startClientRequest({
    kind: 'background_refresh',
    operation: 'hydrate_stage',
    requestKey: 'project-1:stage-1',
    method: 'GET',
    path: '/stages/stage-1',
  })('success', 200)
  startClientRequest({
    kind: 'agent_execution',
    operation: 'stream_run_events',
    requestKey: 'run-1',
    method: 'GET',
    path: '/runs/run-1/events',
  })('aborted')

  const captured = getClientRequestMetrics()
  const summary = getClientRequestMetricSummary()
  assert.equal(captured.length, 2)
  assert.equal(captured[0]?.requestKey, 'project-1:stage-1')
  assert.equal(captured[1]?.outcome, 'aborted')
  assert.equal(summary.byKind.background_refresh.requestCount, 1)
  assert.equal(summary.byKind.agent_execution.requestCount, 1)
  assert.equal(summary.byKind.interactive.requestCount, 0)
  assert.equal(summary.requestCount, 2)
})

test('CLIENT_REQUEST_METRIC_EVENT listeners receive the emitted metric detail', () => {
  // node:test has no DOM; emulate the minimal window surface that
  // request-lifecycle.ts uses (dispatchEvent + CustomEvent). In the browser
  // this is the real window; here we only validate the subscription contract
  // the dev panel relies on.
  const handlers: Array<(event: { detail: unknown }) => void> = []
  const fakeWindow = {
    addEventListener: (_type: string, handler: (event: { detail: unknown }) => void) => handlers.push(handler),
    removeEventListener: (_type: string, handler: (event: { detail: unknown }) => void) => {
      const idx = handlers.indexOf(handler)
      if (idx >= 0) handlers.splice(idx, 1)
    },
    dispatchEvent: (event: { detail: unknown }) => {
      for (const handler of handlers) handler(event)
    },
  }
  const globalObj = globalThis as unknown as { window?: typeof fakeWindow; CustomEvent?: unknown }
  const previousWindow = globalObj.window
  const previousCustomEvent = globalObj.CustomEvent
  globalObj.window = fakeWindow
  globalObj.CustomEvent = class CustomEvent<T> {
    detail: T
    constructor(_type: string, init: { detail: T }) {
      this.detail = init.detail
    }
  }

  resetClientRequestMetrics()
  const received: Array<{ kind: string; operation: string; outcome: string }> = []
  const listener: EventListener = (event) => {
    const detail = (event as CustomEvent).detail as { kind: string; operation: string; outcome: string }
    received.push(detail)
  }
  try {
    window.addEventListener(CLIENT_REQUEST_METRIC_EVENT, listener)
    startClientRequest({
      kind: 'interactive',
      operation: 'load_stage_version',
      method: 'GET',
      path: '/version-logs',
    })('success', 200)
    assert.equal(received.length, 1)
    assert.equal(received[0]?.kind, 'interactive')
    assert.equal(received[0]?.operation, 'load_stage_version')
    assert.equal(received[0]?.outcome, 'success')
  } finally {
    window.removeEventListener(CLIENT_REQUEST_METRIC_EVENT, listener)
    globalObj.window = previousWindow
    globalObj.CustomEvent = previousCustomEvent
  }
})
