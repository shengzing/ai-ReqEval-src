export const DEFAULT_RIGHT_SIDEBAR_WIDTH = 360
export const MIN_RIGHT_SIDEBAR_WIDTH = 300
export const MAX_RIGHT_SIDEBAR_WIDTH = 640
export const MIN_MAIN_WORKSPACE_WIDTH = 480
export const RIGHT_SIDEBAR_WIDTH_STEP = 20

export function clampRightSidebarWidth(
  width: number,
  maxWidth = MAX_RIGHT_SIDEBAR_WIDTH,
): number {
  const safeWidth = Number.isFinite(width) ? width : DEFAULT_RIGHT_SIDEBAR_WIDTH
  const safeMaxWidth = Math.max(
    MIN_RIGHT_SIDEBAR_WIDTH,
    Math.min(MAX_RIGHT_SIDEBAR_WIDTH, maxWidth),
  )
  return Math.round(Math.min(safeMaxWidth, Math.max(MIN_RIGHT_SIDEBAR_WIDTH, safeWidth)))
}

export function getAvailableRightSidebarMaxWidth(input: {
  currentWidth: number
  mainWorkspaceWidth: number
}): number {
  return Math.min(
    MAX_RIGHT_SIDEBAR_WIDTH,
    Math.max(
      MIN_RIGHT_SIDEBAR_WIDTH,
      input.currentWidth + input.mainWorkspaceWidth - MIN_MAIN_WORKSPACE_WIDTH,
    ),
  )
}

export function resizeRightSidebarFromPointer(input: {
  pointerClientX: number
  sidebarRight: number
  maxWidth?: number
}): number {
  return clampRightSidebarWidth(
    input.sidebarRight - input.pointerClientX,
    input.maxWidth,
  )
}

export function adjustRightSidebarWidthFromKey(input: {
  key: string
  currentWidth: number
  maxWidth?: number
  step?: number
}): number | undefined {
  const maxWidth = input.maxWidth ?? MAX_RIGHT_SIDEBAR_WIDTH
  const step = input.step ?? RIGHT_SIDEBAR_WIDTH_STEP

  if (input.key === 'ArrowLeft') {
    return clampRightSidebarWidth(input.currentWidth + step, maxWidth)
  }
  if (input.key === 'ArrowRight') {
    return clampRightSidebarWidth(input.currentWidth - step, maxWidth)
  }
  if (input.key === 'Home') return MIN_RIGHT_SIDEBAR_WIDTH
  if (input.key === 'End') return clampRightSidebarWidth(maxWidth, maxWidth)
  return undefined
}
