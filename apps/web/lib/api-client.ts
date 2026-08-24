import type {
  Conversation,
  EvidenceItem,
  FilePreview,
  Project,
  Stage,
  StageSkill,
  SuggestionCard,
  SuggestionConfirmationResult,
} from '@/lib/types'
import type {
  ApiAutoResearchRecord,
  ApiConversation,
  ApiEvidenceItem,
  ApiFileArtifact,
  ApiFilePreview,
  ApiModelOption,
  ApiModelTestRequest,
  ApiModelTestResponse,
  ApiProject,
  ApiProjectSettings,
  ApiProjectSettingsBundle,
  ApiProjectSettingsList,
  ApiReport,
  ApiReportContent,
  ApiRun,
  ApiRunPolicy,
  ApiSettingsImpact,
  ApiSkill,
  ApiSkillOption,
  ApiStage,
  ApiStageCompletionSnapshot,
  ApiStageLockCheck,
  ApiStageResult,
  ApiStageSkillProfile,
  ApiVersionLog,
  ApiVisionResultSummary,
  ApiAppendMessageResponse,
  ApiConfirmConversationActionProposalResponse,
  ApiWorkspaceProject,
  ApiWorkspaceStage,
  StreamRunEventsOptions,
} from '@/lib/api-types'
import { ApiError, parseErrorDetail } from '@/lib/api-error'
import {
  getLatestConversationRunId,
  mapAutoResearchRecordToSuggestion,
  mapConversationToolCalls,
  mapEvidenceRelevanceStatus,
  mapRunEventsToConversation,
  mapRunEventsToSuggestions,
  mapRunEventsToExecutionTrace,
  mapVersionLog,
  mergeVisionEvidenceDetails,
  selectLatestValidStageResult,
  mapRunEventsToToolCalls,
  mapRunStatus,
  mapStageStatus,
  type RunEventFrame,
} from '@/lib/api-mappers'
import {
  isAbortError,
  startClientRequest,
  type ClientRequestKind,
} from '@/lib/request-lifecycle'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://127.0.0.1:8899/api/v1'

export interface ApiRequestOptions {
  signal?: AbortSignal
  requestKind?: ClientRequestKind
  requestKey?: string
}

interface RequestTelemetry extends ApiRequestOptions {
  operation: string
}

async function fetchJson<T>(path: string, init?: RequestInit, telemetry?: RequestTelemetry): Promise<T> {
  const method = init?.method ?? 'GET'
  const finishMetric = startClientRequest({
    kind: telemetry?.requestKind ?? 'interactive',
    operation: telemetry?.operation ?? `${method} ${path}`,
    requestKey: telemetry?.requestKey,
    method,
    path,
  })
  let response: Response | undefined
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal: telemetry?.signal ?? init?.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(init?.headers ?? {}),
      },
      cache: 'no-store',
    })
    if (!response.ok) {
      throw new ApiError({
        status: response.status,
        detail: await parseErrorDetail(response),
        path,
      })
    }
    const result = response.status === 204 ? undefined as T : await response.json() as T
    finishMetric('success', response.status)
    return result
  } catch (error) {
    finishMetric(isAbortError(error) ? 'aborted' : 'failed', response?.status)
    throw error
  }
}

function timeAgo(isoText: string): string {
  const date = new Date(isoText)
  const diff = Date.now() - date.getTime()
  const mins = Math.max(1, Math.floor(diff / 60000))
  if (mins < 60) return `${mins} 分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  return `${days} 天前`
}

export async function loadProjectTree(options: ApiRequestOptions = {}): Promise<Project[]> {
  const workspaceResponse = await fetchJson<{ items: ApiWorkspaceProject[] }>(
    '/workspace/tree',
    undefined,
    { ...options, operation: 'load_project_tree' },
  )
  return workspaceResponse.items.map(mapWorkspaceProject)
}

export function mapWorkspaceProject(project: ApiWorkspaceProject): Project {
  const stages = project.stages.map(mapWorkspaceStage)
  return {
    id: project.id,
    name: project.name,
    status: stages.some((item) => item.status === 'in_progress') ? 'in_progress' : stages[0]?.status,
    pendingCount: project.pending_count,
    fileCount: project.file_count,
    createdAt: project.created_at,
    stages,
  }
}

function mapWorkspaceStage(stage: ApiWorkspaceStage): Stage {
  return {
    id: stage.id,
    name: stage.name,
    status: mapStageStatus(stage.status),
    objective: stage.objective ?? undefined,
    pendingConfirmations: stage.pending_confirmations,
    conversations: stage.conversations.map(mapConversation),
  }
}

export function mapConversation(item: ApiConversation): Conversation {
  // Preserve the backend status so the UI can show running / waiting_user
  // conversations with the correct colored dot in the sidebar.
  const mappedStatus = item.status === 'archived'
    ? 'archived'
    : mapRunStatus(item.status)
  return {
    id: item.id,
    title: item.title,
    timeAgo: timeAgo(item.created_at),
    status: mappedStatus,
    messages: item.messages?.map((message, index) => ({
      id: `${item.id}-message-${index}`,
      role: message.role,
      content: message.content,
      created_at: message.created_at,
      runId: message.run_id ?? undefined,
      citations: message.citations,
      harnessWarnings: message.harness_warnings,
      toolCalls: mapConversationToolCalls(message.tool_calls),
      processOnly: message.process_only,
      actionProposals: message.action_proposals?.map((proposal) => ({
        id: proposal.id,
        actionType: proposal.action_type,
        title: proposal.title,
        requiresConfirmation: proposal.requires_confirmation,
        status: proposal.status as 'pending' | 'accepting' | 'accepted' | 'rejected',
        confirmationId: proposal.confirmation_id ?? undefined,
      })),
    })) ?? [],
  }
}

export async function loadStage(
  stageId: string,
  options: ApiRequestOptions = {},
): Promise<Pick<Stage, 'id' | 'name' | 'status' | 'objective'>> {
  const stage = await fetchJson<ApiStage>(
    `/stages/${stageId}`,
    undefined,
    { ...options, operation: 'load_stage' },
  )
  return {
    id: stage.id,
    name: stage.name,
    status: mapStageStatus(stage.status),
    objective: stage.objective ?? undefined,
  }
}

export async function loadLatestStageResult(
  stageId: string,
  options: ApiRequestOptions = {},
): Promise<Record<string, unknown> | undefined> {
  const response = await fetchJson<{ items: ApiStageResult[] }>(
    `/stages/${stageId}/results`,
    undefined,
    { ...options, operation: 'load_stage_results' },
  )
  // The API retains invalid/waiting drafts for audit. They must never hydrate
  // the current stage output or make an old AML conclusion look authoritative.
  const latest = selectLatestValidStageResult(response.items, stageId.endsWith('stage-1'))
  return latest?.result_payload
}

export async function loadLatestStageVersion(
  projectId: string,
  stageId: string,
  options: ApiRequestOptions = {},
): Promise<{ versionId?: string; lockedAt?: string; diffFields?: string[] } | undefined> {
  const response = await fetchJson<{ items: ApiVersionLog[] }>(
    `/version-logs?project_id=${projectId}`,
    undefined,
    { ...options, operation: 'load_stage_version' },
  )
  const matched = response.items
    .filter((item) => item.details?.stage_id === stageId || item.resource_id === stageId)
    .at(-1)
  if (!matched) return undefined
  const diffSummary = matched.details?.diff_summary as Record<string, unknown> | undefined
  return {
    versionId: typeof matched.details?.version_id === 'string' ? matched.details.version_id : undefined,
    lockedAt: matched.change_type === 'locked' ? matched.created_at : undefined,
    diffFields: Array.isArray(diffSummary?.field_changes)
      ? diffSummary.field_changes.map((item) => String(item))
      : undefined,
  }
}

export async function loadStageLockCheck(
  stageId: string,
  options: ApiRequestOptions = {},
): Promise<Stage['lockCheck']> {
  const response = await fetchJson<ApiStageLockCheck>(
    `/stages/${stageId}/lock-check`,
    undefined,
    { ...options, operation: 'load_stage_lock_check' },
  )
  return {
    stageId: response.stage_id,
    ready: response.ready,
    checks: response.checks.map((item) => ({
      key: item.key,
      label: item.label,
      passed: item.passed,
      machineCode: item.machine_code,
      hint: item.hint,
      objectId: item.object_id ?? null,
    })),
  }
}

export async function loadStageSkills(
  stageId: string,
  options: ApiRequestOptions = {},
): Promise<StageSkill[]> {
  const response = await fetchJson<{ items: ApiSkill[] }>(
    `/skills?stage_id=${stageId}`,
    undefined,
    { ...options, operation: 'load_stage_skills' },
  )
  return response.items.map((item) => ({
    id: item.name,
    name: item.name,
    status: 'ready',
    description: item.description,
  }))
}

function mapSnapshotEvidence(
  evidence: ApiEvidenceItem[],
  files: ApiFileArtifact[],
  currentStageName?: string,
): EvidenceItem[] {
  const evidenceSourceFileIds = new Set(
    evidence.flatMap((item) => item.source_file_id ? [item.source_file_id] : []),
  )
  const evidenceItems = evidence.map((item) => ({
    id: item.id,
    name: item.name,
    type: (item.source_type === 'vision' ? 'record' : 'file') as EvidenceItem['type'],
    sourceFileId: item.source_file_id ?? undefined,
    stage: currentStageName,
    status: (['uploaded', 'parsed', 'referenced', 'locked', 'archived'].includes(item.status) ? item.status : 'parsed') as EvidenceItem['status'],
    updatedAt: timeAgo(item.updated_at),
    isReferenced: item.status === 'referenced',
    attachmentPath: item.attachment_path ?? undefined,
    reviewNote: item.review_note ?? undefined,
    summaryLines: item.review_note ? [`处理说明：${item.review_note}`] : undefined,
    relevanceStatus: mapEvidenceRelevanceStatus(item.relevance_status),
    relevanceScore: item.relevance_score ?? 0,
    relevanceReasons: item.relevance_reasons ?? [],
    relevanceRuleVersion: item.relevance_rule_version || undefined,
    relevanceSource: item.relevance_source ?? 'machine',
    relevanceReviewReason: item.relevance_review_reason ?? undefined,
    relevanceReviewedBy: item.relevance_reviewed_by ?? undefined,
    relevanceReviewedAt: item.relevance_reviewed_at ?? undefined,
    relevancePreviousStatus: item.relevance_previous_status ?? undefined,
  }))
  const uploadedFiles = files
    .filter((item) => !evidenceSourceFileIds.has(item.id))
    .map((item) => ({
      id: item.id,
      name: item.filename,
      type: 'file' as const,
      sourceFileId: item.id,
      stage: currentStageName,
      status: (item.status === 'rejected' ? 'archived' : 'uploaded') as EvidenceItem['status'],
      updatedAt: timeAgo(item.created_at),
      isReferenced: false,
      relevanceStatus: mapEvidenceRelevanceStatus(item.relevance_status),
      relevanceScore: item.relevance_score ?? 0,
      relevanceReasons: item.relevance_reasons ?? [],
      relevanceRuleVersion: item.relevance_rule_version || undefined,
      relevanceSource: item.relevance_source ?? 'machine',
      relevanceReviewReason: item.relevance_review_reason ?? undefined,
      relevanceReviewedBy: item.relevance_reviewed_by ?? undefined,
      relevanceReviewedAt: item.relevance_reviewed_at ?? undefined,
      relevancePreviousStatus: item.relevance_previous_status ?? undefined,
      securityRejected: Boolean(item.security_rejected || item.status === 'rejected'),
    }))
  return [...uploadedFiles, ...evidenceItems]
}

export interface CompletionSnapshot {
  projects: Project[]
  stage: Stage
  resultPayload?: Record<string, unknown>
  evidenceItems: EvidenceItem[]
  suggestions: SuggestionCard[]
  conversation?: Conversation
  /** HCR-P1-05：富集字段，让前端完成 Run 后只读一次快照。 */
  versionLog?: Stage['versionLog']
  visionResults?: ApiVisionResultSummary[]
}

export async function loadStageCompletionSnapshot(
  stageId: string,
  runId: string,
  options: ApiRequestOptions = {},
): Promise<CompletionSnapshot> {
  const snapshot = await fetchJson<ApiStageCompletionSnapshot>(
    `/stages/${stageId}/completion-snapshot?run_id=${encodeURIComponent(runId)}`,
    undefined,
    { ...options, operation: 'load_stage_completion_snapshot' },
  )
  // HCR-P1-05：在快照返回时一次性合并 vision 详情 + 映射 version_log，
  // 让 followRun 完成分支不再发 /vision-results + /version-logs。
  const evidenceItems = mergeVisionEvidenceDetails(
    mapSnapshotEvidence(snapshot.evidence, snapshot.files, snapshot.stage.name),
    snapshot.vision_results ?? [],
  )
  return {
    projects: snapshot.workspace.items.map(mapWorkspaceProject),
    stage: {
      id: snapshot.stage.id,
      name: snapshot.stage.name,
      status: mapStageStatus(snapshot.stage.status),
      objective: snapshot.stage.objective ?? undefined,
      lockCheck: {
        stageId: snapshot.lock_check.stage_id,
        ready: snapshot.lock_check.ready,
        checks: snapshot.lock_check.checks.map((item) => ({ key: item.key, label: item.label, passed: item.passed, machineCode: item.machine_code, hint: item.hint, objectId: item.object_id ?? null })),
      },
      resultPayload: snapshot.latest_result?.result_payload,
      conversations: [],
    },
    resultPayload: snapshot.latest_result?.result_payload,
    evidenceItems,
    suggestions: snapshot.suggestions
      .filter((item) => item.status === 'pending')
      .map(mapAutoResearchRecordToSuggestion),
    conversation: snapshot.conversation ? mapConversation(snapshot.conversation) : undefined,
    versionLog: mapVersionLog(snapshot.version_log ?? null),
    visionResults: snapshot.vision_results ?? [],
  }
}

export async function loadProjectEvidence(
  projectId: string,
  currentStageName?: string,
  options: ApiRequestOptions = {},
): Promise<EvidenceItem[]> {
  const [evidenceResponse, filesResponse] = await Promise.all([
    fetchJson<{ items: ApiEvidenceItem[] }>(
      `/evidence?project_id=${projectId}`,
      undefined,
      { ...options, operation: 'load_project_evidence' },
    ),
    fetchJson<{ items: ApiFileArtifact[] }>(
      `/files?project_id=${projectId}`,
      undefined,
      { ...options, operation: 'load_project_files' },
    ),
  ])
  return mapSnapshotEvidence(evidenceResponse.items, filesResponse.items, currentStageName)
}

export async function loadProjectVisionDetails(
  projectId: string,
  evidenceItems: EvidenceItem[],
  options: ApiRequestOptions = {},
): Promise<EvidenceItem[]> {
  const response = await fetchJson<{ items: ApiVisionResultSummary[] }>(
    `/vision-results?project_id=${projectId}`,
    undefined,
    { ...options, operation: 'load_project_vision_details' },
  )
  return mergeVisionEvidenceDetails(evidenceItems, response.items)
}

export async function createRun(input: {
  projectId: string
  stageId?: string
  conversationId?: string
  goal: string
}): Promise<ApiRun> {
  return fetchJson<ApiRun>('/runs', {
    method: 'POST',
    body: JSON.stringify({
      project_id: input.projectId,
      stage_id: input.stageId,
      conversation_id: input.conversationId,
      goal: input.goal,
    }),
  })
}

export async function loadRun(runId: string): Promise<ApiRun> {
  return fetchJson<ApiRun>(`/runs/${runId}`)
}

export async function createProject(input: { name: string; goal: string }): Promise<ApiProject> {
  return fetchJson<ApiProject>('/projects', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export async function updateProject(
  projectId: string,
  input: { name: string },
): Promise<ApiProject> {
  return fetchJson<ApiProject>(`/projects/${projectId}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
}

export async function deleteProject(projectId: string): Promise<void> {
  await fetchJson<void>(`/projects/${projectId}`, {
    method: 'DELETE',
  })
}

export async function uploadProjectFile(input: {
  projectId: string
  filename: string
  contentType?: string
  content?: string
  contentBase64?: string
}) {
  return fetchJson<{
    id: string
    project_id: string
    filename: string
    content_type: string
    status: string
    storage_path?: string | null
    created_at: string
  }>('/files/upload', {
    method: 'POST',
    body: JSON.stringify({
      project_id: input.projectId,
      filename: input.filename,
      content_type: input.contentType ?? 'application/octet-stream',
      content: input.content ?? '',
      content_base64: input.contentBase64,
    }),
  })
}

export async function parseProjectFile(fileId: string) {
  return fetchJson<{
    id: string
    project_id: string
    filename: string
    content_type: string
    status: string
    storage_path?: string | null
    created_at: string
  }>(`/files/${fileId}/parse`, {
    method: 'POST',
  })
}

export async function reviewProjectFileRelevance(input: {
  fileId: string
  decision: 'related' | 'unrelated' | 'rejected'
  reason: string
  reviewer?: string
}): Promise<ApiFileArtifact> {
  return fetchJson<ApiFileArtifact>(`/files/${input.fileId}/relevance-review`, {
    method: 'POST',
    body: JSON.stringify({
      decision: input.decision,
      reason: input.reason,
      reviewer: input.reviewer ?? 'workspace_user',
    }),
  })
}

export async function loadFilePreview(fileId: string): Promise<FilePreview> {
  const preview = await fetchJson<ApiFilePreview>(`/files/${fileId}/preview`)
  return {
    id: preview.id,
    projectId: preview.project_id,
    filename: preview.filename,
    contentType: preview.content_type,
    previewType: preview.preview_type,
    content: preview.content,
    encoding: preview.encoding,
    sizeBytes: preview.size_bytes,
    truncated: preview.truncated,
  }
}

export async function visionParseProjectFile(input: {
  fileId: string
  prompt: string
  targetSchema: Record<string, string>
  projectContext?: Record<string, unknown>
}) {
  return fetchJson<{
    file_id: string
    project_id: string
    model: string
    structured_fields: Record<string, unknown>
    evidence_fragments: Array<Record<string, unknown>>
    uncertainties: string[]
    to_confirm: Array<Record<string, unknown>>
    raw_response: string
  }>(`/files/${input.fileId}/vision-parse`, {
    method: 'POST',
    body: JSON.stringify({
      prompt: input.prompt,
      target_schema: input.targetSchema,
      project_context: input.projectContext ?? {},
    }),
  })
}

export async function createStageConversation(stageId: string, input: { title: string; initialMessage?: string }): Promise<ApiConversation> {
  return fetchJson<ApiConversation>(`/stages/${stageId}/conversations`, {
    method: 'POST',
    body: JSON.stringify({
      title: input.title,
      initial_message: input.initialMessage,
    }),
  })
}

export async function loadConversationDetail(conversationId: string): Promise<Conversation> {
  const detail = await fetchJson<ApiConversation>(`/conversations/${conversationId}`)
  return mapConversation(detail)
}

export async function archiveConversation(conversationId: string): Promise<void> {
  await fetchJson(`/conversations/${conversationId}/archive`, { method: 'POST' })
}

export async function restoreConversation(conversationId: string): Promise<void> {
  await fetchJson(`/conversations/${conversationId}/restore`, { method: 'POST' })
}

export async function deleteConversation(conversationId: string): Promise<void> {
  await fetchJson<void>(`/conversations/${conversationId}`, {
    method: 'DELETE',
  })
}

export async function lockStage(stageId: string): Promise<void> {
  await fetchJson(`/stages/${stageId}/lock`, {
    method: 'POST',
  })
}

export async function generateReport(projectId: string, title: string): Promise<ApiReport> {
  return fetchJson<ApiReport>('/reports/generate', {
    method: 'POST',
    body: JSON.stringify({
      project_id: projectId,
      title,
    }),
  })
}

export async function loadReportContent(reportId: string): Promise<ApiReportContent> {
  return fetchJson<ApiReportContent>(`/reports/${reportId}/content`)
}

function parseSseBlock(block: string): RunEventFrame | undefined {
  const lines = block
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  const eventLine = lines.find((line) => line.startsWith('event: '))
  const dataLine = lines.find((line) => line.startsWith('data: '))
  if (!dataLine) return undefined
  return {
    event: eventLine?.replace('event: ', '') ?? 'message',
    data: JSON.parse(dataLine.replace('data: ', '')),
  }
}

export async function streamRunEvents(
  runId: string,
  options: StreamRunEventsOptions = {}
): Promise<RunEventFrame[]> {
  const frames: RunEventFrame[] = []
  const maxReconnects = options.maxReconnects ?? 1
  let reconnectCount = 0
  let terminalSeen = false

  while (reconnectCount <= maxReconnects && !terminalSeen) {
    const path = `/runs/${runId}/events`
    const finishMetric = startClientRequest({
      kind: 'agent_execution',
      operation: 'stream_run_events',
      requestKey: runId,
      method: 'GET',
      path,
    })
    let response: Response
    try {
      response = await fetch(`${API_BASE_URL}${path}`, {
        cache: 'no-store',
        signal: options.signal,
        headers: {
          Accept: 'text/event-stream',
        },
      })
    } catch (error) {
      finishMetric(isAbortError(error) ? 'aborted' : 'failed')
      throw error
    }
    if (!response.ok || !response.body) {
      finishMetric('failed', response.status)
      throw new ApiError({
        status: response.status,
        detail: await parseErrorDetail(response),
        path,
      })
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const blocks = buffer.split('\n\n')
        buffer = blocks.pop() ?? ''

        for (const block of blocks) {
          const frame = parseSseBlock(block)
          if (!frame) continue
          frames.push(frame)
          options.onEvent?.(frame)
          if (['run.completed', 'run.failed', 'run.cancelled', 'run.waiting_user', 'run.waiting_inputs'].includes(frame.event)) {
            terminalSeen = true
          }
        }
      }
      finishMetric('success', response.status)
    } catch (error) {
      finishMetric(isAbortError(error) ? 'aborted' : 'failed', response.status)
      throw error
    }

    const trailingFrame = parseSseBlock(buffer)
    if (trailingFrame) {
      frames.push(trailingFrame)
      options.onEvent?.(trailingFrame)
      if (['run.completed', 'run.failed', 'run.cancelled', 'run.waiting_user', 'run.waiting_inputs'].includes(trailingFrame.event)) {
        terminalSeen = true
      }
    }

    if (!terminalSeen && !options.signal?.aborted) {
      reconnectCount += 1
      if (reconnectCount <= maxReconnects) {
        await new Promise((resolve) => window.setTimeout(resolve, 300))
      }
    } else {
      break
    }
  }

  return frames
}

export async function loadAutoResearchRecords(
  stageId: string,
  options: ApiRequestOptions = {},
): Promise<SuggestionCard[]> {
  const response = await fetchJson<{ items: ApiAutoResearchRecord[] }>(
    `/autoresearch?stage_id=${stageId}`,
    undefined,
    { ...options, operation: 'load_autoresearch_records' },
  )
  return response.items.map(mapAutoResearchRecordToSuggestion)
}

export async function createAutoResearchRecord(stageId: string, runId: string): Promise<SuggestionCard> {
  const response = await fetchJson<ApiAutoResearchRecord>('/autoresearch/run', {
    method: 'POST',
    body: JSON.stringify({
      stage_id: stageId,
      run_id: runId,
    }),
  })
  return mapAutoResearchRecordToSuggestion(response)
}

export async function createManualAutoResearchRecord(input: {
  stageId: string
  title: string
  description: string
  action: string
  impact?: string
  risk?: 'low' | 'medium' | 'high'
  source?: string
  runId?: string
  context?: Record<string, unknown>
}): Promise<SuggestionCard> {
  const response = await fetchJson<ApiAutoResearchRecord>('/autoresearch/manual', {
    method: 'POST',
    body: JSON.stringify({
      stage_id: input.stageId,
      title: input.title,
      description: input.description,
      action: input.action,
      impact: input.impact ?? '影响当前阶段结果',
      risk: input.risk ?? 'medium',
      source: input.source ?? 'vision_manual',
      run_id: input.runId,
      context: input.context ?? {},
    }),
  })
  return mapAutoResearchRecordToSuggestion(response)
}

export async function confirmAutoResearchRecord(input: {
  recordId: string
  decision: 'accepted' | 'accepted_with_edits' | 'rejected' | 'follow_up'
  note?: string
  editedDescription?: string
}): Promise<SuggestionConfirmationResult> {
  const response = await fetchJson<{ record: ApiAutoResearchRecord; stage_result?: ApiStageResult | null }>(`/autoresearch/${input.recordId}/confirm`, {
    method: 'POST',
    body: JSON.stringify({
      decision: input.decision,
      note: input.note,
      edited_description: input.editedDescription,
    }),
  })
  return {
    suggestion: mapAutoResearchRecordToSuggestion(response.record),
    stageResultPayload: response.stage_result?.result_payload,
  }
}

export { getLatestConversationRunId, mapAutoResearchRecordToSuggestion, mapConversationToolCalls, mapRunEventsToConversation, mapRunEventsToSuggestions, mapRunEventsToExecutionTrace, mapRunEventsToToolCalls, mapRunStatus, mapStageStatus }
export type { RunEventFrame }

export async function loadProjectSettingsBundle(projectId: string): Promise<ApiProjectSettingsBundle> {
  return fetchJson<ApiProjectSettingsBundle>(`/projects/${projectId}/settings`)
}

export async function loadProjectSettingsVersions(projectId: string): Promise<ApiProjectSettingsList> {
  return fetchJson<ApiProjectSettingsList>(`/projects/${projectId}/settings/versions`)
}

export async function loadProjectSettingsImpact(projectId: string): Promise<ApiSettingsImpact> {
  return fetchJson<ApiSettingsImpact>(`/projects/${projectId}/settings/impact`)
}

export async function loadModelOptions(): Promise<{ items: ApiModelOption[] }> {
  return fetchJson<{ items: ApiModelOption[] }>('/model-options')
}

export async function loadSkillOptions(): Promise<{ items: ApiSkillOption[] }> {
  return fetchJson<{ items: ApiSkillOption[] }>('/skill-options')
}

export async function saveProjectSettingsDraft(
  projectId: string,
  payload: {
    models: ApiProjectSettings['models']
    prompts: ApiProjectSettings['prompts']
    stage_skill_profiles: ApiStageSkillProfile[]
    run_policy: ApiRunPolicy
    change_reason?: string
  }
): Promise<ApiProjectSettings> {
  return fetchJson<ApiProjectSettings>(`/projects/${projectId}/settings/draft`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function publishProjectSettings(
  projectId: string,
  payload: { draft_id?: string; change_reason: string }
): Promise<ApiProjectSettings> {
  return fetchJson<ApiProjectSettings>(`/projects/${projectId}/settings/publish`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function resetProjectSettings(projectId: string): Promise<ApiProjectSettings> {
  return fetchJson<ApiProjectSettings>(`/projects/${projectId}/settings/reset`, {
    method: 'POST',
  })
}

export async function testProjectModelConnection(
  projectId: string,
  payload: ApiModelTestRequest
): Promise<ApiModelTestResponse> {
  return fetchJson<ApiModelTestResponse>(`/projects/${projectId}/settings/models/test`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

/** Append a message to a conversation.
 *
 * 当 `runHarness` 为 true 时，后端会触发对话 Harness 生成 assistant 回复，
 * 返回体中 `assistant_message` 与 `harness` 字段会被填充。
 */
export async function appendConversationMessage(
  conversationId: string,
  role: 'user' | 'assistant',
  content: string,
  options?: {
    runHarness?: boolean
    configVersionId?: string
  }
): Promise<ApiAppendMessageResponse> {
  const body: Record<string, unknown> = { role, content }
  if (options?.runHarness) {
    body.run_harness = true
    if (options.configVersionId) body.config_version_id = options.configVersionId
  }
  return fetchJson<ApiAppendMessageResponse>(`/conversations/${conversationId}/messages`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function confirmConversationActionProposal(
  conversationId: string,
  proposalId: string
): Promise<ApiConfirmConversationActionProposalResponse> {
  return fetchJson<ApiConfirmConversationActionProposalResponse>(
    `/conversations/${conversationId}/action-proposals/${proposalId}/confirm`,
    { method: 'POST' }
  )
}

export async function rejectConversationActionProposal(
  conversationId: string,
  proposalId: string
): Promise<void> {
  await fetchJson(`/conversations/${conversationId}/action-proposals/${proposalId}/reject`, {
    method: 'POST',
  })
}

/** Resume a paused run with human input */
export async function resumeRun(
  runId: string,
  humanInput?: Record<string, unknown>
): Promise<ApiRun> {
  return fetchJson(`/runs/${runId}/resume`, {
    method: 'POST',
    body: JSON.stringify({ human_input: humanInput ?? {} }),
  })
}
