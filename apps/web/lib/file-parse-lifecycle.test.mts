import assert from 'node:assert/strict'
import test from 'node:test'

import { createFileParseCoordinator, type FileParseState } from './file-parse-lifecycle.ts'

test('file parse coordinator keeps one request in flight per file', async () => {
  const coordinator = createFileParseCoordinator()
  const states: FileParseState[] = []
  let resolveTask: (() => void) | undefined
  let taskCount = 0
  const task = () => {
    taskCount += 1
    return new Promise<void>((resolve) => {
      resolveTask = resolve
    })
  }

  const firstRun = coordinator.run('file-1', task, (state) => states.push(state))
  const duplicateRun = await coordinator.run('file-1', task, (state) => states.push(state))

  assert.equal(duplicateRun, false)
  assert.equal(taskCount, 1)
  assert.equal(coordinator.isRunning('file-1'), true)
  assert.deepEqual(states, [{ status: 'parsing', message: '正在重新解析…' }])

  resolveTask?.()
  assert.equal(await firstRun, true)
  assert.equal(coordinator.isRunning('file-1'), false)
  assert.equal(states.at(-1)?.status, 'success')
})

test('file parse coordinator exposes the request error and allows retry', async () => {
  const coordinator = createFileParseCoordinator()
  const states: FileParseState[] = []

  assert.equal(
    await coordinator.run(
      'file-2',
      async () => { throw new Error('解析器暂不可用') },
      (state) => states.push(state),
    ),
    false,
  )
  assert.deepEqual(states.at(-1), { status: 'error', message: '解析器暂不可用' })

  assert.equal(
    await coordinator.run('file-2', async () => undefined, (state) => states.push(state)),
    true,
  )
  assert.equal(states.at(-1)?.status, 'success')
})
