export const COLLAPSED_STAGE_INPUT_COUNT = 3

export function getVisibleStageInputItems<T>(items: T[], expanded: boolean): T[] {
  return expanded ? items : items.slice(0, COLLAPSED_STAGE_INPUT_COUNT)
}

export function getHiddenStageInputCount(total: number): number {
  return Math.max(0, total - COLLAPSED_STAGE_INPUT_COUNT)
}
