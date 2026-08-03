import type { SuggestedTask } from '@/lib/types'

export const defaultSuggestedTasks: SuggestedTask[] = [
  { id: 'run-current-stage', icon: 'zap', title: '运行当前阶段并生成待确认建议' },
  { id: 'review-evidence', icon: 'zap', title: '检查当前项目资料与证据缺口' },
  { id: 'summarize-next-step', icon: 'zap', title: '根据当前阶段状态生成下一步行动' },
]
