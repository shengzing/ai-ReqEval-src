import type { Stage } from '@/lib/types'

type ReportInfo = NonNullable<Stage['reportInfo']>

export function getReportGateState(reportInfo: ReportInfo | undefined) {
  if (!reportInfo) {
    return {
      passed: false,
      label: '报告门禁未确认通过',
      message: '尚未生成报告，后端未返回审批结束检查结果。',
    }
  }

  return {
    passed: Boolean(reportInfo.approvalCheckPassed),
    label: reportInfo.approvalCheckPassed ? '报告门禁已通过' : '报告门禁未确认通过',
    message: reportInfo.gateMessage ?? '报告生成由后端检查阶段结果、阶段锁定和待处理 autoResearch 后返回。',
  }
}

export function buildReportArtifactStatus(reportInfo: ReportInfo | undefined) {
  return [
    { key: 'export', label: '报告导出', value: reportInfo?.exportPath, available: Boolean(reportInfo?.exportPath) },
    { key: 'decision-card', label: '决策卡', value: reportInfo?.decisionCardPath, available: Boolean(reportInfo?.decisionCardPath) },
    { key: 'evidence-directory', label: '证据目录', value: reportInfo?.evidenceDirectoryPath, available: Boolean(reportInfo?.evidenceDirectoryPath) },
    { key: 'bundle', label: '完整导出包', value: reportInfo?.bundleExportPath, available: Boolean(reportInfo?.bundleExportPath) },
  ]
}
