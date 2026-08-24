import assert from 'node:assert/strict'
import test from 'node:test'

import { isActionableNode } from './execution-trace-filter.ts'
import type { ExecutionTraceNode } from './types'

test('hides pure lifecycle state node', () => {
  const node: ExecutionTraceNode = {
    id: 'e1',
    kind: 'state',
    name: '已创建运行',
    status: 'completed',
  }
  assert.equal(isActionableNode(node), false)
})

test('keeps failed state node', () => {
  const node: ExecutionTraceNode = {
    id: 'e2',
    kind: 'state',
    name: '运行失败',
    status: 'failed',
  }
  assert.equal(isActionableNode(node), true)
})

test('keeps human-intervention state nodes by name', () => {
  // run.cancelled 在 getTraceStatus 中归为 'completed'，此处靠 name 兜底保留
  for (const name of ['等待人工确认', '等待补充输入', '运行已取消']) {
    const node: ExecutionTraceNode = {
      id: 'e',
      kind: 'state',
      name,
      status: 'completed',
    }
    assert.equal(isActionableNode(node), true)
  }
})

test('hides routing node without content, keeps harness_planned with summary', () => {
  assert.equal(
    isActionableNode({ id: 'r1', kind: 'routing', name: '路由阶段', status: 'completed' }),
    false,
  )
  assert.equal(
    isActionableNode({
      id: 'r2',
      kind: 'routing',
      name: 'Harness 执行规划',
      status: 'completed',
      summary: '计划 3 个步骤',
    }),
    true,
  )
})

test('always keeps tool / subagent / decision / validation / skill', () => {
  const kinds = ['tool', 'subagent', 'decision', 'validation', 'skill'] as const
  for (const kind of kinds) {
    const node = {
      id: 'k',
      kind,
      name: 'x',
      status: 'completed',
    } as ExecutionTraceNode
    assert.equal(isActionableNode(node), true)
  }
})

test('keeps skipped terminal state and state node with details', () => {
  assert.equal(
    isActionableNode({ id: 's1', kind: 'state', name: '已跳过', status: 'skipped' }),
    true,
  )
  assert.equal(
    isActionableNode({
      id: 's2',
      kind: 'state',
      name: '某状态',
      status: 'completed',
      details: { reason: 'something' },
    }),
    true,
  )
})
