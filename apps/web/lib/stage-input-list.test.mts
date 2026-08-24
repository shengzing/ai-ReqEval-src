import assert from 'node:assert/strict'
import test from 'node:test'

import {
  COLLAPSED_STAGE_INPUT_COUNT,
  getHiddenStageInputCount,
  getVisibleStageInputItems,
} from './stage-input-list.ts'

test('stage input list shows three materials by default', () => {
  const items = ['a', 'b', 'c', 'd', 'e', 'f']

  assert.equal(COLLAPSED_STAGE_INPUT_COUNT, 3)
  assert.deepEqual(getVisibleStageInputItems(items, false), ['a', 'b', 'c'])
  assert.equal(getHiddenStageInputCount(items.length), 3)
})

test('stage input list reveals all materials when expanded', () => {
  const items = ['a', 'b', 'c', 'd']

  assert.deepEqual(getVisibleStageInputItems(items, true), items)
  assert.equal(getHiddenStageInputCount(2), 0)
})
