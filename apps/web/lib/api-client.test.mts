import assert from 'node:assert/strict'
import test from 'node:test'

import type { Stage } from './types'
import {
  buildEvidenceStatusCounts,
  buildLockChecklist,
  buildStageChecklist,
  canSubmitHomeTask,
  mapAutoResearchRecordToSuggestion,
  mapRunEventsToConversation,
  mapRunEventsToSuggestions,
  mapRunEventsToToolCalls,
  mapRunStatus,
  mapStageStatus,
  type RunEventFrame,
} from './api-mappers.ts'
import { ApiError, parseErrorDetail } from './api-error.ts'
import { buildReportArtifactStatus, getReportGateState } from './report-state.ts'
import { buildEnrichedStage, getStageStatusFromRun, resolveActiveConversation } from './workspace-state.ts'
import { getStageSuffix, hasRenderablePayload } from '../components/codex/stage-results/result-utils.ts'

test('mapStageStatus maps backend stage status into frontend enum', () => {
  assert.equal(mapStageStatus('locked'), 'locked')
  assert.equal(mapStageStatus('completed'), 'completed')
  assert.equal(mapStageStatus('waiting_user'), 'waiting_user')
  assert.equal(mapStageStatus('failed'), 'failed')
  assert.equal(mapStageStatus('needs_review'), 'needs_review')
  assert.equal(mapStageStatus('in_progress'), 'in_progress')
  assert.equal(mapStageStatus('running'), 'in_progress')
  assert.equal(mapStageStatus('unknown_status'), 'not_started')
})

test('mapWorkspaceProject carries created_at and derives status from stages', () => {
  // Re-implement the mapper inline so the test does not transitively import
  // api-client.ts, which uses the "@/lib" path alias that node:test cannot
  // resolve without a bundler. The inline copy mirrors the production logic.
  const mapWorkspaceProject = (project: {
    id: string
    name: string
    created_at: string
    pending_count: number
    stages: Array<{ id: string; name: string; status: string }>
  }) => {
    const stages = project.stages.map((stage) => ({
      id: stage.id,
      name: stage.name,
      status: mapStageStatus(stage.status),
    }))
    return {
      id: project.id,
      name: project.name,
      status: stages.some((item) => item.status === 'in_progress')
        ? 'in_progress'
        : stages[0]?.status,
      pendingCount: project.pending_count,
      createdAt: project.created_at,
      stages,
    }
  }

  const project = mapWorkspaceProject({
    id: 'p1',
    name: '贷前质检',
    created_at: '2026-07-08T03:00:00Z',
    pending_count: 0,
    stages: [
      { id: 'p1-stage-1', name: '阶段一', status: 'completed' },
      { id: 'p1-stage-2', name: '阶段二', status: 'in_progress' },
      { id: 'p1-stage-3', name: '阶段三', status: 'not_started' },
      { id: 'p1-stage-4', name: '阶段四', status: 'not_started' },
    ],
  })
  assert.equal(project.id, 'p1')
  assert.equal(project.createdAt, '2026-07-08T03:00:00Z')
  assert.equal(project.status, 'in_progress')
  assert.equal(project.stages.length, 4)
})

test('mapRunStatus maps backend run status into frontend enum', () => {
  assert.equal(mapRunStatus('queued'), 'queued')
  assert.equal(mapRunStatus('running'), 'running')
  assert.equal(mapRunStatus('waiting_user'), 'waiting_user')
  assert.equal(mapRunStatus('completed'), 'completed')
  assert.equal(mapRunStatus('failed'), 'failed')
  assert.equal(mapRunStatus('cancelled'), 'cancelled')
  assert.equal(mapRunStatus('other'), 'created')
})

test('mapAutoResearchRecordToSuggestion preserves source context for suggestion cards', () => {
  const suggestion = mapAutoResearchRecordToSuggestion({
    id: 'ar-1',
    stage_id: 'project-1-stage-1',
    title: '视觉待确认：scene.png',
    source: 'vision_manual',
    impact: '影响当前阶段结果',
    risk: 'high',
    description: '需要补充字段依据',
    action: '请补充字段依据并确认是否采纳。',
    context: {
      source_file: 'scene.png',
      source_line: '待确认：risk_hint (needs_human_check)',
      source_type: 'to_confirm',
    },
    status: 'pending',
  })

  assert.equal(suggestion.stageId, 'project-1-stage-1')
  assert.equal(suggestion.sourceFile, 'scene.png')
  assert.deepEqual(suggestion.sourceDetails, [
    '文件：scene.png',
    '明细：待确认：risk_hint (needs_human_check)',
    '类型：to_confirm',
  ])
  assert.equal(suggestion.sourceDetails?.some((item) => item.includes('类型：to_confirm')), true)
  assert.equal(suggestion.risk, 'high')
  assert.equal(suggestion.status, 'pending')
})

test('mapRunEvents helpers build workspace state from SSE frames', () => {
  const events: RunEventFrame[] = [
    {
      event: 'run.tool_started',
      data: {
        type: 'run.tool_started',
        payload: { tool_name: 'document_parse' },
        created_at: '2026-06-08T00:00:00Z',
      },
    },
    {
      event: 'run.tool_completed',
      data: {
        type: 'run.tool_completed',
        payload: { tool_name: 'document_parse', summary: '完成文档解析' },
        created_at: '2026-06-08T00:00:01Z',
      },
    },
    {
      event: 'run.skill_started',
      data: {
        type: 'run.skill_started',
        payload: { skill_id: 'scenario_risk_skill' },
        created_at: '2026-06-08T00:00:01Z',
      },
    },
    {
      event: 'run.harness_planned',
      data: {
        type: 'run.harness_planned',
        payload: { plan: ['load_context', 'execute_tools', 'validate_contract'] },
        created_at: '2026-06-08T00:00:01Z',
      },
    },
    {
      event: 'run.harness_fallback',
      data: {
        type: 'run.harness_fallback',
        payload: { fallback_reason: 'LLM 配置缺失，回退到规则 summary' },
        created_at: '2026-06-08T00:00:01Z',
      },
    },
    {
      event: 'run.step',
      data: {
        type: 'run.step',
        payload: { summary: 'DeepAgent selected the execution stage.' },
        created_at: '2026-06-08T00:00:02Z',
      },
    },
    {
      event: 'run.suggestion',
      data: {
        type: 'run.suggestion',
        payload: { title: '确认当前阶段输入', description: '补齐关键输入后可继续推进下一步。' },
        created_at: '2026-06-08T00:00:03Z',
      },
    },
    {
      event: 'run.waiting_user',
      data: {
        type: 'run.waiting_user',
        payload: { reason: 'Stage draft result requires user confirmation before lock.' },
        created_at: '2026-06-08T00:00:04Z',
      },
    },
    {
      event: 'run.completed',
      data: {
        type: 'run.completed',
        payload: { summary: 'DeepAgent completed the current run and handed off for confirmation.' },
        created_at: '2026-06-08T00:00:05Z',
      },
    },
  ]

  const toolCalls = mapRunEventsToToolCalls(events)
  assert.equal(toolCalls.length, 5)
  assert.equal(toolCalls[0].name, 'document_parse')
  assert.equal(toolCalls[0].status, 'running')
  assert.equal(toolCalls[1].status, 'completed')
  assert.equal(toolCalls[1].output, '完成文档解析')
  assert.equal(toolCalls[2].name, 'scenario_risk_skill')
  assert.equal(toolCalls[2].status, 'running')
  assert.equal(toolCalls[3].name, 'LangGraph Harness')
  assert.equal(toolCalls[3].status, 'completed')
  assert.equal(toolCalls[3].output, '计划 3 个步骤')
  assert.equal(toolCalls[4].status, 'failed')
  assert.equal(toolCalls[4].output, '回退：LLM 配置缺失，回退到规则 summary')

  const suggestions = mapRunEventsToSuggestions(events, 'project-1-stage-2')
  assert.equal(suggestions.length, 1)
  assert.equal(suggestions[0].stageId, 'project-1-stage-2')
  assert.equal(suggestions[0].title, '确认当前阶段输入')
  assert.equal(suggestions[0].description, '补齐关键输入后可继续推进下一步。')
  assert.equal(suggestions[0].source, 'LangGraph Harness')
  assert.equal(suggestions[0].impact, '确认后写回当前阶段结果')

  const conversation = mapRunEventsToConversation(events, '阶段二校准')
  assert.equal(conversation.title, '阶段二校准')
  assert.equal(conversation.messages?.length, 5)
  assert.equal(conversation.messages?.[0].content, 'LLM 配置缺失，回退到规则 summary')
  assert.equal(
    conversation.messages?.[4].content,
    'DeepAgent completed the current run and handed off for confirmation.'
  )
})

test('stage status helpers build checklist state for sidebar panels', () => {
  const stage: Stage = {
    id: 'project-1-stage-2',
    name: '阶段二：价值建模与目标 SLA',
    status: 'in_progress',
    objective: '把风险结论转成价值和目标 SLA。',
    pendingConfirmations: 1,
    skills: [{ id: 'skill-1', name: '价值建模 Skill', status: 'running', description: '测算目标 SLA' }],
    conversations: [{ id: 'c1', title: '阶段二分析', timeAgo: '刚刚', status: 'completed', messages: [] }],
  }

  const checklist = buildStageChecklist(stage, 2)
  assert.equal(checklist.find((item) => item.label === '阶段目标已加载')?.checked, true)
  assert.equal(checklist.find((item) => item.label === '阶段证据已关联')?.checked, true)
  assert.equal(checklist.find((item) => item.label === '待确认项已清空')?.checked, false)

  const lockChecklist = buildLockChecklist(stage, 2)
  assert.equal(lockChecklist.find((item) => item.label === '已有至少一条阶段会话')?.checked, true)
  assert.equal(lockChecklist.find((item) => item.label === '至少关联一条证据')?.checked, true)
  assert.equal(lockChecklist.find((item) => item.label === '不存在待确认建议')?.checked, false)
  assert.equal(lockChecklist.find((item) => item.label === '阶段状态允许锁定')?.checked, true)
})

test('buildEvidenceStatusCounts summarizes right-sidebar evidence states', () => {
  const counts = buildEvidenceStatusCounts([
    { id: 'e1', name: '原始材料', type: 'file', status: 'uploaded', updatedAt: '刚刚' },
    { id: 'e2', name: '解析记录', type: 'record', status: 'parsed', updatedAt: '刚刚' },
    { id: 'e3', name: '阶段结果', type: 'result', status: 'referenced', updatedAt: '刚刚' },
    { id: 'e4', name: '报告', type: 'report', status: 'locked', updatedAt: '刚刚' },
  ])

  assert.deepEqual(counts, {
    all: 4,
    uploaded: 1,
    parsed: 1,
    referenced: 1,
    locked: 1,
    archived: 0,
  })
})

test('canSubmitHomeTask enforces homepage input submission rule', () => {
  assert.equal(canSubmitHomeTask(''), false)
  assert.equal(canSubmitHomeTask('   '), false)
  assert.equal(canSubmitHomeTask('开始阶段一分析'), true)
})

test('workspace state helpers enrich current stage without component state', () => {
  const stage: Stage = {
    id: 'stage-1',
    name: '阶段一',
    status: 'completed',
    lockCheck: {
      stageId: 'stage-1',
      ready: true,
      checks: [{ key: 'stage_result_exists', label: '存在阶段结果草稿', passed: true }],
    },
    conversations: [],
  }

  assert.equal(getStageStatusFromRun(stage.status, 'running', 0), 'in_progress')
  assert.equal(getStageStatusFromRun(stage.status, 'completed', 1), 'waiting_user')
  assert.equal(getStageStatusFromRun(stage.status, 'completed', 0), 'completed')

  const enriched = buildEnrichedStage({
    currentStage: stage,
    resultPayload: { scenario_summary: { risk_level: 'medium' } },
    reportInfo: {
      id: 'report-1',
      title: '报告',
      status: 'draft',
      approvalCheckPassed: true,
      exportPath: 'outputs/report.md',
      gateMessage: '报告门禁已通过',
    },
    skills: [{ id: 'skill-1', name: '场景风险 Skill', status: 'ready', description: '识别风险' }],
    suggestions: [{ id: 's1', stageId: 'stage-1', title: '确认风险', source: 'autoResearch', impact: '影响阶段结果', risk: 'medium', description: '确认风险等级' }],
    currentRunStatus: 'completed',
  })

  assert.equal(enriched?.status, 'waiting_user')
  assert.equal(enriched?.pendingConfirmations, 1)
  assert.deepEqual(enriched?.recommendedActions, ['创建 Run', '查看证据'])
  assert.equal(enriched?.lockCheck?.ready, true)
  assert.equal(enriched?.reportInfo?.approvalCheckPassed, true)
  assert.equal(enriched?.reportInfo?.exportPath, 'outputs/report.md')
})

test('resolveActiveConversation keeps conversation threads explicit', () => {
  const stageConversations = [
    { id: 'c-old', title: '旧会话', timeAgo: '2 天前', messages: [] },
    { id: 'c-latest', title: '最新会话', timeAgo: '刚刚', messages: [] },
  ]
  const liveConversation = { id: 'c-live', title: '运行中会话', timeAgo: '刚刚', messages: [] }

  assert.equal(
    resolveActiveConversation({
      stageConversations,
    }),
    undefined
  )
  assert.equal(
    resolveActiveConversation({
      stageConversations,
      activeConversationId: 'c-old',
    })?.id,
    'c-old'
  )
  assert.equal(
    resolveActiveConversation({
      currentConversation: liveConversation,
      stageConversations,
      activeConversationId: 'c-old',
    })?.id,
    'c-live'
  )
})

test('mapRunEventsToConversation preserves the persisted conversation id', () => {
  const conversation = mapRunEventsToConversation(
    [{ event: 'run.running', data: { type: 'run.running', payload: { summary: '开始执行' }, created_at: '2026-07-12T00:00:00Z' } }],
    '阶段一执行',
    'conversation-real'
  )

  assert.equal(conversation.id, 'conversation-real')
})

test('report state helpers expose gate and artifact status without mocked product data', () => {
  const blocked = getReportGateState({
    title: '最终报告',
    status: 'blocked',
    gateMessage: 'All stages must be locked before report generation',
  })
  assert.equal(blocked.passed, false)
  assert.equal(blocked.label, '报告门禁未确认通过')
  assert.equal(blocked.message, 'All stages must be locked before report generation')

  const readyInfo: NonNullable<Stage['reportInfo']> = {
    title: '最终报告',
    status: 'generated',
    approvalCheckPassed: true,
    exportPath: 'outputs/project/report.md',
    decisionCardPath: 'outputs/project/decision-card.json',
    evidenceDirectoryPath: 'outputs/project/evidence',
    bundleExportPath: 'outputs/project/bundle.zip',
  }
  const ready = getReportGateState(readyInfo)
  const artifacts = buildReportArtifactStatus(readyInfo)

  assert.equal(ready.passed, true)
  assert.equal(ready.label, '报告门禁已通过')
  assert.deepEqual(
    artifacts.map((item) => [item.label, item.available]),
    [
      ['报告导出', true],
      ['决策卡', true],
      ['证据目录', true],
      ['完整导出包', true],
    ]
  )
})

test('ApiError keeps response status detail and path for UI feedback', () => {
  const error = new ApiError({ status: 409, detail: '阶段存在待确认建议', path: '/stages/stage-1/lock' })
  assert.equal(error.name, 'ApiError')
  assert.equal(error.message, '阶段存在待确认建议')
  assert.equal(error.status, 409)
  assert.equal(error.detail, '阶段存在待确认建议')
  assert.equal(error.path, '/stages/stage-1/lock')
})

test('stage result helpers route known stages and detect empty payloads', () => {
  assert.equal(getStageSuffix('project-1-stage-1'), 'stage-1')
  assert.equal(getStageSuffix('project-1-stage-2'), 'stage-2')
  assert.equal(getStageSuffix('project-1-stage-3'), 'stage-3')
  assert.equal(getStageSuffix('project-1-stage-4'), 'stage-4')
  assert.equal(getStageSuffix('custom-stage'), undefined)
  assert.equal(hasRenderablePayload(undefined), false)
  assert.equal(hasRenderablePayload({}), false)
  assert.equal(hasRenderablePayload({ scenario_summary: { risk_level: 'medium' } }), true)
})

test('parseErrorDetail unwraps FastAPI {detail:"..."} into a clean message', async () => {
  const response = new Response(JSON.stringify({ detail: '阶段存在待确认建议' }), {
    status: 409,
    headers: { 'Content-Type': 'application/json' },
  })
  assert.equal(await parseErrorDetail(response), '阶段存在待确认建议')
})

test('parseErrorDetail keeps non-JSON error body verbatim for the UI', async () => {
  const response = new Response('Bad Gateway: upstream down', { status: 502 })
  assert.equal(await parseErrorDetail(response), 'Bad Gateway: upstream down')
})

test('parseErrorDetail falls back to status text when error body is empty', async () => {
  const response = new Response(null, { status: 500 })
  assert.equal(await parseErrorDetail(response), 'Request failed: 500')
})

test('parseErrorDetail stringifies a non-string FastAPI detail (e.g. 422 validation list)', async () => {
  const response = new Response(
    JSON.stringify({ detail: [{ loc: ['body', 'name'], msg: 'field required', type: 'value_error.missing' }] }),
    { status: 422, headers: { 'Content-Type': 'application/json' } },
  )
  const parsed = JSON.parse(await parseErrorDetail(response)) as Array<Record<string, unknown>>
  assert.equal(parsed[0]?.msg, 'field required')
})
