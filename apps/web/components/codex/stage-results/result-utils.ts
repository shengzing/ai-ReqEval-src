export type ResultPayload = Record<string, unknown>

export function asRecord(value: unknown): ResultPayload | undefined {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as ResultPayload : undefined
}

export function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(4)))
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

export function getFirst(payload: ResultPayload | undefined, keys: string[]): unknown {
  if (!payload) return undefined
  for (const key of keys) {
    const value = payload[key]
    if (value !== undefined && value !== null && value !== '') return value
  }
  return undefined
}

export function hasRenderablePayload(payload?: ResultPayload) {
  return Boolean(payload && Object.keys(payload).length > 0)
}

export function getStageSuffix(stageId: string) {
  if (stageId.endsWith('stage-1') || stageId.includes('stage_1')) return 'stage-1'
  if (stageId.endsWith('stage-2') || stageId.includes('stage_2')) return 'stage-2'
  if (stageId.endsWith('stage-3') || stageId.includes('stage_3')) return 'stage-3'
  if (stageId.endsWith('stage-4') || stageId.includes('stage_4')) return 'stage-4'
  return undefined
}
