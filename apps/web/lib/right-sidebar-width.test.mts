import assert from 'node:assert/strict'
import test from 'node:test'

import {
  DEFAULT_RIGHT_SIDEBAR_WIDTH,
  MAX_RIGHT_SIDEBAR_WIDTH,
  MIN_RIGHT_SIDEBAR_WIDTH,
  adjustRightSidebarWidthFromKey,
  clampRightSidebarWidth,
  getAvailableRightSidebarMaxWidth,
  resizeRightSidebarFromPointer,
} from './right-sidebar-width.ts'

test('right sidebar width stays within its supported range', () => {
  assert.equal(clampRightSidebarWidth(120), MIN_RIGHT_SIDEBAR_WIDTH)
  assert.equal(clampRightSidebarWidth(480.4), 480)
  assert.equal(clampRightSidebarWidth(900), MAX_RIGHT_SIDEBAR_WIDTH)
  assert.equal(clampRightSidebarWidth(Number.NaN), DEFAULT_RIGHT_SIDEBAR_WIDTH)
})

test('right sidebar growth preserves the minimum main workspace width', () => {
  assert.equal(
    getAvailableRightSidebarMaxWidth({ currentWidth: 360, mainWorkspaceWidth: 720 }),
    600,
  )
  assert.equal(
    getAvailableRightSidebarMaxWidth({ currentWidth: 360, mainWorkspaceWidth: 960 }),
    MAX_RIGHT_SIDEBAR_WIDTH,
  )
  assert.equal(
    getAvailableRightSidebarMaxWidth({ currentWidth: 360, mainWorkspaceWidth: 420 }),
    MIN_RIGHT_SIDEBAR_WIDTH,
  )
})

test('pointer and keyboard resizing use the same width limits', () => {
  assert.equal(
    resizeRightSidebarFromPointer({ pointerClientX: 700, sidebarRight: 1200, maxWidth: 560 }),
    500,
  )
  assert.equal(
    resizeRightSidebarFromPointer({ pointerClientX: 100, sidebarRight: 1200, maxWidth: 560 }),
    560,
  )
  assert.equal(
    adjustRightSidebarWidthFromKey({ key: 'ArrowLeft', currentWidth: 360 }),
    380,
  )
  assert.equal(
    adjustRightSidebarWidthFromKey({ key: 'ArrowRight', currentWidth: 305 }),
    MIN_RIGHT_SIDEBAR_WIDTH,
  )
  assert.equal(
    adjustRightSidebarWidthFromKey({ key: 'Escape', currentWidth: 360 }),
    undefined,
  )
})
