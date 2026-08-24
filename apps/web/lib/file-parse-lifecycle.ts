export type FileParseStatus = 'parsing' | 'success' | 'error'

export interface FileParseState {
  status: FileParseStatus
  message: string
}

export type FileParseStateMap = Record<string, FileParseState>

export function createFileParseCoordinator() {
  const inFlight = new Set<string>()

  return {
    isRunning(fileId: string): boolean {
      return inFlight.has(fileId)
    },

    async run(
      fileId: string,
      task: () => Promise<void>,
      onStateChange: (state: FileParseState) => void,
    ): Promise<boolean> {
      if (inFlight.has(fileId)) return false

      inFlight.add(fileId)
      onStateChange({ status: 'parsing', message: '正在重新解析…' })
      try {
        await task()
        onStateChange({ status: 'success', message: '重新解析完成，相关性已更新。' })
        return true
      } catch (error) {
        onStateChange({
          status: 'error',
          message: error instanceof Error ? error.message : '文件解析失败，请重试。',
        })
        return false
      } finally {
        inFlight.delete(fileId)
      }
    },
  }
}
