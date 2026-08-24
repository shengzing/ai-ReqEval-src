import assert from 'node:assert/strict'
import test from 'node:test'

import { getProjectStageExecutionStatus, getProjectStageShortName } from './project-overview.ts'
import { getStageRerunAvailability } from '../components/codex/stage/stage-status.ts'

test('project overview identifies an unstarted stage as not executed', () => {
  assert.deepEqual(getProjectStageExecutionStatus('not_started'), {
    label: '未执行',
    tone: 'neutral',
  })
})

test('project overview prefers a live Run state for the selected stage', () => {
  assert.deepEqual(getProjectStageExecutionStatus('not_started', 'waiting_inputs'), {
    label: '等待材料',
    tone: 'warning',
  })
  assert.deepEqual(getProjectStageExecutionStatus('in_progress', 'completed'), {
    label: '已完成',
    tone: 'success',
  })
})

test('project overview treats locked stages as completed and shortens stage names', () => {
  assert.equal(getProjectStageExecutionStatus('locked').label, '已完成')
  assert.equal(getProjectStageShortName({ name: '阶段一：场景解构与风险定级' }), '阶段一')
})

test('stage rerun stays disabled while stage one still lacks related evidence', () => {
  assert.deepEqual(
    getStageRerunAvailability('project-1-stage-1', 'waiting_inputs', 0),
    {
      disabled: true,
      reason: '请先解析材料并确认与项目相关，再重新运行。',
    },
  )
  assert.equal(getStageRerunAvailability('project-1-stage-1', 'waiting_inputs', 1).disabled, false)
  assert.equal(getStageRerunAvailability('project-1-stage-1', undefined, 0).disabled, true)
  assert.equal(getStageRerunAvailability('project-1-stage-2', 'waiting_inputs', 0).disabled, false)
})
