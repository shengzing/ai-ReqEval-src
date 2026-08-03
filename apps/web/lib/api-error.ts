export class ApiError extends Error {
  readonly status: number
  readonly detail: string
  readonly path: string

  constructor(input: { status: number; detail: string; path: string }) {
    super(input.detail || `Request failed: ${input.status}`)
    this.name = 'ApiError'
    this.status = input.status
    this.detail = input.detail
    this.path = input.path
  }
}

export async function parseErrorDetail(response: Response): Promise<string> {
  let raw = ''
  try {
    raw = await response.text()
  } catch {
    return `Request failed: ${response.status}`
  }
  if (!raw) return `Request failed: ${response.status}`
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown } | null
    if (parsed && typeof parsed === 'object') {
      const inner = (parsed as { detail?: unknown }).detail
      if (typeof inner === 'string' && inner.length > 0) return inner
      if (inner !== undefined && inner !== null) return JSON.stringify(inner)
    }
  } catch {
    // body was not JSON — keep raw text
  }
  return raw
}
