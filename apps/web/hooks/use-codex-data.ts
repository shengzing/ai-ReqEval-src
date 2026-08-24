'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import type { Conversation, ConversationMessage, EvidenceItem, ExecutionTraceNode, Project, RunStatus, Stage, StageSkill, SuggestionCard, SuggestionConfirmationResult, ToolCall } from '@/lib/types'
import {
  confirmAutoResearchRecord,
  confirmConversationActionProposal,
  createManualAutoResearchRecord,
  createProject,
  createRun,
  createStageConversation,
  deleteConversation,
  deleteProject,
  generateReport,
  getLatestConversationRunId,
  rejectConversationActionProposal,
  loadConversationDetail,
  loadRun,
  loadReportContent,
  loadAutoResearchRecords,
  loadStageLockCheck,
  loadProjectEvidence,
  loadProjectTree,
  loadStage,
  loadStageCompletionSnapshot,
  loadLatestStageResult,
  loadLatestStageVersion,
  loadStageSkills,
  loadProjectVisionDetails,
  lockStage,
  mapRunEventsToConversation,
  mapConversationToolCalls,
  mapRunEventsToSuggestions,
  mapRunEventsToToolCalls,
  mapRunEventsToExecutionTrace,
  mapRunStatus,
  parseProjectFile,
  reviewProjectFileRelevance,
  visionParseProjectFile,
  appendConversationMessage,
  resumeRun,
  type RunEventFrame,
  streamRunEvents,
  updateProject,
  uploadProjectFile,
} from '@/lib/api-client'
import { createLatestRequestGate, isAbortError } from '@/lib/request-lifecycle'

/**
 * HCR-P1-03：run-scoped 证据过滤快照。
 * 从 run.evidence_filtered / run.waiting_inputs 事件载荷提取，
 * 让 StageInputList 显示该 Run 冻结的纳入/排除列表，而非当前派生。
 */
export interface RunEvidenceFilter {
  includedEvidenceIds: string[]
  excludedEvidence: Array<{
    id: string
    name: string
    relevanceStatus: EvidenceItem['relevanceStatus']
    relevanceReasons: string[]
  }>
  reason?: string
}

function extractRunEvidenceFilter(frames: RunEventFrame[]): RunEvidenceFilter | undefined {
  // 取最后一个 evidence_filtered / waiting_inputs 事件——Run 可能多次过滤。
  const filteredFrame = [...frames].reverse().find((frame) => frame.event === 'run.evidence_filtered')
  const waitingFrame = [...frames].reverse().find((frame) => frame.event === 'run.waiting_inputs')
  const sourceFrame = filteredFrame ?? waitingFrame
  if (!sourceFrame) return undefined
  const payload = sourceFrame.data.payload as Record<string, unknown>
  const included = Array.isArray(payload.included_evidence_ids) ? payload.included_evidence_ids : []
  const excludedRaw = Array.isArray(payload.excluded_evidence) ? payload.excluded_evidence : []
  const reason = typeof payload.reason === 'string' ? payload.reason : undefined
  const excluded = excludedRaw.map((entry) => {
    const record = (entry ?? {}) as Record<string, unknown>
    return {
      id: typeof record.id === 'string' ? record.id : '',
      name: typeof record.name === 'string' ? record.name : '',
      relevanceStatus: mapEvidenceRelevanceStatus(record.relevance_status as string | undefined),
      relevanceReasons: Array.isArray(record.relevance_reasons) ? record.relevance_reasons as string[] : [],
    }
  })
  return {
    includedEvidenceIds: included.filter((id): id is string => typeof id === 'string'),
    excludedEvidence: excluded,
    reason,
  }
}

function mapEvidenceRelevanceStatus(value: string | undefined): EvidenceItem['relevanceStatus'] {
  if (value === 'related' || value === 'needs_review' || value === 'unrelated' || value === 'rejected' || value === 'pending_parse') {
    return value
  }
  return 'pending_parse'
}

export function useCodexData() {
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([])
  const [executionTrace, setExecutionTrace] = useState<ExecutionTraceNode[]>([])
  const [suggestions, setSuggestions] = useState<SuggestionCard[]>([])
  const [skills, setSkills] = useState<StageSkill[]>([])
  const [evidenceItems, setEvidenceItems] = useState<EvidenceItem[]>([])
  const [stageResultPayload, setStageResultPayload] = useState<Record<string, unknown> | undefined>()
  const [stageVersionLog, setStageVersionLog] = useState<Stage['versionLog']>()
  const [stageLockCheck, setStageLockCheck] = useState<Stage['lockCheck']>()
  const [currentConversation, setCurrentConversation] = useState<Conversation | undefined>()
  const [currentConversationError, setCurrentConversationError] = useState<string | null>(null)
  const [currentConversationLoading, setCurrentConversationLoading] = useState(false)
  const [conversationSending, setConversationSending] = useState(false)
  const [currentRunId, setCurrentRunId] = useState<string | undefined>()
  const [currentRunStatus, setCurrentRunStatus] = useState<RunStatus | undefined>()
  const [currentRunCheckpointStatus, setCurrentRunCheckpointStatus] = useState<string | undefined>()
  // HCR-P1-03：当前 Run 的证据过滤快照（无 Run / 旧 Run 为 undefined）。
  const [runEvidenceFilter, setRunEvidenceFilter] = useState<RunEvidenceFilter | undefined>()
  const streamAbortRef = useRef<AbortController | null>(null)
  const workspaceRequestGateRef = useRef(createLatestRequestGate())
  const stageRequestGateRef = useRef(createLatestRequestGate())
  const deferredStageRequestGateRef = useRef(createLatestRequestGate())
  const deferredStageLoadedKeyRef = useRef<string | undefined>(undefined)
  const hydratedStageKeyRef = useRef<string | undefined>(undefined)

  const reloadProjects = useCallback(async () => {
    const token = workspaceRequestGateRef.current.begin('workspace-tree')
    setLoading(true)
    setError(null)
    try {
      const nextProjects = await loadProjectTree({
        signal: token.signal,
        requestKind: 'background_refresh',
        requestKey: token.key,
      })
      if (!workspaceRequestGateRef.current.isCurrent(token)) return []
      setProjects(nextProjects)
      return nextProjects
    } catch (fetchError) {
      if (isAbortError(fetchError)) return []
      setError(fetchError instanceof Error ? fetchError.message : 'Failed to load projects')
      return []
    } finally {
      if (workspaceRequestGateRef.current.isCurrent(token)) setLoading(false)
      workspaceRequestGateRef.current.finish(token)
    }
  }, [])

  const createEmptyProject = useCallback(
    async (input: {
      name: string
      goal?: string
      files?: Array<{ filename: string; contentType?: string; content?: string; contentBase64?: string }>
    }) => {
      const created = await createProject({
        name: input.name,
        goal: input.goal?.trim() || input.name,
      })
      if (input.files?.length) {
        await Promise.all(
          input.files.map((file) =>
            uploadProjectFile({
              projectId: created.id,
              filename: file.filename,
              contentType: file.contentType,
              content: file.content,
              contentBase64: file.contentBase64,
            })
          )
        )
      }
      const nextProjects = await reloadProjects()
      const project = nextProjects.find((item) => item.id === created.id)
      return {
        projectId: created.id,
        stageId: project?.stages[0]?.id,
      }
    },
    [reloadProjects]
  )

  useEffect(() => {
    void reloadProjects()
  }, [reloadProjects])

  const getProject = useCallback(
    (projectId?: string) => projects.find((item) => item.id === projectId),
    [projects]
  )

  const getStage = useCallback(
    (projectId?: string, stageId?: string) => getProject(projectId)?.stages.find((item) => item.id === stageId),
    [getProject]
  )

  const hydrateStageContext = useCallback(
    async (projectId: string, stageId: string, options: { preserveExisting?: boolean } = {}) => {
      const requestKey = `${projectId}:${stageId}`
      const preserveExisting = options.preserveExisting === true
      const token = stageRequestGateRef.current.begin(requestKey)
      deferredStageRequestGateRef.current.cancel()
      deferredStageLoadedKeyRef.current = undefined
      if (!preserveExisting) {
        hydratedStageKeyRef.current = undefined
        // A real navigation must clear the previous stage. A same-stage
        // refresh (for example after re-parsing one file) keeps the current
        // content mounted until the replacement data arrives.
        setCurrentRunStatus(undefined)
        setCurrentRunCheckpointStatus(undefined)
        setToolCalls([])
        setExecutionTrace([])
        setSkills([])
        setSuggestions([])
        setEvidenceItems([])
        setStageResultPayload(undefined)
        setStageVersionLog(undefined)
        setStageLockCheck(undefined)
        // HCR-P1-03：切换阶段时清空旧 Run 的过滤快照。
        setRunEvidenceFilter(undefined)
      }

      const requestOptions = {
        signal: token.signal,
        requestKind: 'background_refresh' as const,
        requestKey,
      }
      try {
        const stage = await loadStage(stageId, requestOptions)
        if (!stageRequestGateRef.current.isCurrent(token)) return undefined
        const [nextSkills, nextSuggestions, lockCheck, resultPayload, nextEvidence] = await Promise.all([
          loadStageSkills(stageId, requestOptions),
          loadAutoResearchRecords(stageId, requestOptions),
          loadStageLockCheck(stageId, requestOptions),
          loadLatestStageResult(stageId, requestOptions),
          loadProjectEvidence(projectId, stage.name, requestOptions),
        ])
        if (!stageRequestGateRef.current.isCurrent(token)) return undefined
        setSkills(nextSkills)
        setEvidenceItems(nextEvidence)
        setSuggestions(nextSuggestions.filter((item) => item.status === 'pending'))
        setStageResultPayload(resultPayload)
        setStageLockCheck(lockCheck)
        hydratedStageKeyRef.current = requestKey
        return { stage: { ...stage, resultPayload, lockCheck }, nextSkills, nextEvidence, nextSuggestions }
      } catch (loadError) {
        if (isAbortError(loadError)) return undefined
        throw loadError
      } finally {
        stageRequestGateRef.current.finish(token)
      }
    },
    []
  )

  const loadStageDeferredContext = useCallback(
    async (projectId: string, stageId: string) => {
      const requestKey = `${projectId}:${stageId}:deferred`
      if (hydratedStageKeyRef.current !== `${projectId}:${stageId}`) return
      if (deferredStageLoadedKeyRef.current === requestKey) return
      const token = deferredStageRequestGateRef.current.begin(requestKey)
      try {
        const options = {
          signal: token.signal,
          requestKind: 'background_refresh' as const,
          requestKey,
        }
        const [versionLog, nextEvidence] = await Promise.all([
          loadLatestStageVersion(projectId, stageId, options),
          loadProjectVisionDetails(projectId, evidenceItems, options),
        ])
        if (!deferredStageRequestGateRef.current.isCurrent(token)) return
        setStageVersionLog(versionLog)
        setEvidenceItems(nextEvidence)
        deferredStageLoadedKeyRef.current = requestKey
      } catch (loadError) {
        if (!isAbortError(loadError)) {
          setError(loadError instanceof Error ? loadError.message : 'Failed to load deferred stage details')
        }
      } finally {
        deferredStageRequestGateRef.current.finish(token)
      }
    },
    [evidenceItems]
  )

  const followRun = useCallback(
    async ({
      run,
      projectId,
      stageId,
      conversationId,
      title,
    }: {
      run: { id: string; status: string; harness_checkpoint_status?: string | null }
      projectId: string
      stageId: string
      conversationId: string
      title: string
    }) => {
      streamAbortRef.current?.abort()
      const controller = new AbortController()
      streamAbortRef.current = controller
      setCurrentRunId(run.id)
      setCurrentRunStatus(mapRunStatus(run.status))
      setCurrentRunCheckpointStatus(run.harness_checkpoint_status ?? undefined)
      setToolCalls([])
      setExecutionTrace([])
      setSuggestions([])
      // HCR-P1-03：新 Run 开始时清空旧 Run 的过滤快照，避免短暂残留。
      setRunEvidenceFilter(undefined)
      setCurrentConversationError(null)
      setCurrentConversationLoading(false)
      // 保留既有会话历史：re-run/恢复都在同一 conversation 上追加 run，
      // 不再整体替换而清空历史消息。
      // 仅当当前会话与本次 run 所属会话不一致（切换会话/首跑）时载入真实历史一次。
      if (currentConversation?.id !== conversationId) {
        try {
          const detail = await loadConversationDetail(conversationId)
          if (controller.signal.aborted || streamAbortRef.current !== controller) return
          setCurrentConversation(detail)
        } catch {
          // 载入失败不阻塞 run 流；保持原会话或空态，由后续快照对账。
        }
      }
      const liveFrames: RunEventFrame[] = []

      let frames: RunEventFrame[]
      try {
        frames = await streamRunEvents(run.id, {
          signal: controller.signal,
          onEvent: (frame) => {
            liveFrames.push(frame)
            setCurrentRunStatus((previous) => {
              if (frame.event === 'run.running') return 'running'
              if (frame.event === 'run.waiting_inputs') return 'waiting_inputs'
              if (frame.event === 'run.waiting_user') return 'waiting_user'
              if (frame.event === 'run.completed') return 'completed'
              if (frame.event === 'run.failed') return 'failed'
              return previous
            })
            if (frame.event === 'run.waiting_user') {
              const decision = frame.data.payload.decision
              const checkpoint = decision && typeof decision === 'object' && !Array.isArray(decision)
                ? (decision as Record<string, unknown>).checkpoint
                : undefined
              const checkpointStatus = checkpoint && typeof checkpoint === 'object' && !Array.isArray(checkpoint)
                ? (checkpoint as Record<string, unknown>).status
                : undefined
              setCurrentRunCheckpointStatus(typeof checkpointStatus === 'string' ? checkpointStatus : undefined)
            }
            if (['run.completed', 'run.failed', 'run.waiting_inputs'].includes(frame.event)) {
              setCurrentRunCheckpointStatus(undefined)
            }
            // HCR-P1-03：过滤事件到达即刷新 run-scoped 快照。
            if (frame.event === 'run.evidence_filtered' || frame.event === 'run.waiting_inputs') {
              setRunEvidenceFilter(extractRunEvidenceFilter(liveFrames))
            }
            setToolCalls(mapRunEventsToToolCalls(liveFrames))
            setExecutionTrace(mapRunEventsToExecutionTrace(liveFrames))
            setSuggestions((previous) => {
              const runSuggestions = mapRunEventsToSuggestions([frame], stageId)
              return runSuggestions.length > 0 ? [...previous, ...runSuggestions] : previous
            })
          },
        })
      } catch (streamError) {
        if (streamError instanceof DOMException && streamError.name === 'AbortError') return
        setCurrentRunStatus('failed')
        frames = liveFrames
      }

      setToolCalls(mapRunEventsToToolCalls(frames))
      setExecutionTrace(mapRunEventsToExecutionTrace(frames))
      // HCR-P1-03：流结束后用全量 frames 计算最终过滤快照（兼容流中已收到
      // 但 state 未刷新的边界情况）。
      setRunEvidenceFilter(extractRunEvidenceFilter(frames))
      const terminalRunStatus = frames.some((frame) => frame.event === 'run.completed')
        ? 'completed'
        : frames.some((frame) => frame.event === 'run.failed')
          ? 'failed'
          : frames.some((frame) => frame.event === 'run.waiting_inputs')
            ? 'waiting_inputs'
            : frames.some((frame) => frame.event === 'run.waiting_user')
              ? 'waiting_user'
          : mapRunStatus(run.status)
      const waitingFrame = [...frames].reverse().find((frame) => frame.event === 'run.waiting_user')
      const waitingDecision = waitingFrame?.data.payload.decision
      const waitingCheckpoint = waitingDecision && typeof waitingDecision === 'object' && !Array.isArray(waitingDecision)
        ? (waitingDecision as Record<string, unknown>).checkpoint
        : undefined
      const checkpointStatus = waitingCheckpoint && typeof waitingCheckpoint === 'object' && !Array.isArray(waitingCheckpoint)
        ? (waitingCheckpoint as Record<string, unknown>).status
        : undefined
      const terminalCheckpointStatus = terminalRunStatus === 'waiting_user' && typeof checkpointStatus === 'string'
        ? checkpointStatus
        : undefined

      // A completed Run gets exactly one completion read model. Waiting,
      // failed, and input-gated Runs preserve their streamed state instead of
      // refreshing the latest result (which may belong to another Run).
      if (terminalRunStatus === 'completed') {
        // HCR-P1-05：取消在飞的延迟加载（其写 evidenceItems/versionLog 会
        // 覆盖快照新鲜值），并在快照写入后标记 deferred key 已满足，使
        // 右栏 useEffect 不再重触发 /version-logs + /vision-results。
        deferredStageRequestGateRef.current.cancel()
        try {
          const snapshot = await loadStageCompletionSnapshot(stageId, run.id, {
            signal: controller.signal,
            requestKind: 'background_refresh',
            requestKey: `${run.id}:completion`,
          })
          if (controller.signal.aborted || streamAbortRef.current !== controller) return
          setProjects(snapshot.projects)
          setEvidenceItems(snapshot.evidenceItems)
          setSuggestions(snapshot.suggestions)
          setStageResultPayload(snapshot.resultPayload)
          setStageLockCheck(snapshot.stage.lockCheck)
          if (snapshot.conversation) setCurrentConversation(snapshot.conversation)
          if (snapshot.versionLog) setStageVersionLog(snapshot.versionLog)
          deferredStageLoadedKeyRef.current = `${projectId}:${stageId}:deferred`
          hydratedStageKeyRef.current = `${projectId}:${stageId}`
        } catch {
          // Preserve the streamed trace if the completion snapshot is not
          // available. Do not fall back to a request fan-out here.
        }
      }
      setCurrentRunStatus(terminalRunStatus)
      setCurrentRunCheckpointStatus(terminalCheckpointStatus)
    },
    []
  )

  useEffect(() => {
    return () => {
      streamAbortRef.current?.abort()
      workspaceRequestGateRef.current.cancel()
      stageRequestGateRef.current.cancel()
      deferredStageRequestGateRef.current.cancel()
    }
  }, [])

  const startTask = useCallback(
    async ({
      projectId,
      stageId,
      goal,
      conversationId,
    }: {
      projectId?: string
      stageId?: string
      goal: string
      conversationId?: string
    }) => {
      if (!goal.trim()) return undefined

      let resolvedProjectId = projectId
      let projectSnapshot = projects
      if (!resolvedProjectId) {
        const created = await createProject({
          name: goal.slice(0, 24),
          goal,
        })
        resolvedProjectId = created.id
        projectSnapshot = await reloadProjects()
      }

      if (!resolvedProjectId) return undefined

      const project = (projectSnapshot.length ? projectSnapshot : projects).find((item) => item.id === resolvedProjectId)
      // Validate that the provided stageId actually belongs to the resolved project.
      // If it doesn't (e.g., stale activeStage from a different project), fall back to
      // the project's first stage instead of sending a mismatched pair to the backend.
      const projectStageIds = project?.stages.map((s) => s.id) ?? []
      const resolvedStageId = (stageId && projectStageIds.includes(stageId)) ? stageId : project?.stages[0]?.id
      const finalStageId = resolvedStageId ?? project?.stages[0]?.id
      if (!finalStageId) return undefined

      const conversation =
        conversationId ||
        (
          await createStageConversation(finalStageId, {
            title: goal.slice(0, 24),
            initialMessage: goal,
          })
        ).id

      const run = await createRun({
        projectId: resolvedProjectId,
        stageId: finalStageId,
        conversationId: conversation,
        goal,
      })
      await followRun({
        run,
        projectId: resolvedProjectId,
        stageId: finalStageId,
        conversationId: conversation,
        title: goal.slice(0, 24),
      })

      return {
        projectId: resolvedProjectId,
        stageId: finalStageId,
        conversationId: conversation,
      }
    },
    [followRun, getProject, reloadProjects]
  )

  const lockCurrentStage = useCallback(
    async (projectId: string, stageId: string) => {
      await lockStage(stageId)
      await reloadProjects()
      await hydrateStageContext(projectId, stageId)
    },
    [hydrateStageContext, reloadProjects]
  )

  const confirmSuggestion = useCallback(
    async (input: {
      recordId: string
      decision: 'accepted' | 'accepted_with_edits' | 'rejected' | 'follow_up'
      note?: string
      editedDescription?: string
      projectId: string
      stageId: string
    }) => {
      const result = await confirmAutoResearchRecord({
        recordId: input.recordId,
        decision: input.decision,
        note: input.note,
        editedDescription: input.editedDescription,
      })
      setSuggestions((previous) => previous.filter((item) => item.recordId !== result.suggestion.recordId))
      await reloadProjects()
      await hydrateStageContext(input.projectId, input.stageId)
      return result
    },
    [hydrateStageContext, reloadProjects]
  )

  const createEvidenceSuggestion = useCallback(
    async (input: {
      projectId: string
      stageId: string
      title: string
      description: string
      action: string
      impact?: string
      risk?: 'low' | 'medium' | 'high'
      source?: string
      context?: Record<string, unknown>
    }) => {
      const record = await createManualAutoResearchRecord({
        stageId: input.stageId,
        title: input.title,
        description: input.description,
        action: input.action,
        impact: input.impact,
        risk: input.risk,
        source: input.source,
        context: input.context,
      })
      setSuggestions((previous) => [...previous, record])
      await reloadProjects()
      await hydrateStageContext(input.projectId, input.stageId)
      return record
    },
    [hydrateStageContext, reloadProjects]
  )

  const parseEvidenceFile = useCallback(
    async (input: { fileId: string; projectId: string; stageId: string }) => {
      await parseProjectFile(input.fileId)
      const requestKey = `${input.projectId}:${input.stageId}`
      let evidence: EvidenceItem[] | undefined
      // 复用 hydrate：重新加载 evidence 并按当前 stage 打 stage 标签，
      // 避免右栏因 stage=undefined 回退到"全部资料"。
      if (hydratedStageKeyRef.current === requestKey) {
        const hydrated = await hydrateStageContext(input.projectId, input.stageId, { preserveExisting: true })
        evidence = hydrated?.nextEvidence
      }
      if (!evidence) {
        evidence = await loadProjectEvidence(input.projectId, undefined, {
          requestKind: 'background_refresh',
          requestKey: `${requestKey}:refresh`,
        })
      }
      // 补 vision 合并：mapSnapshotEvidence 不合并 vision，需显式调用，
      // 否则重新解析会丢掉 vision 记录的 detailLines/summaryLines。
      evidence = await loadProjectVisionDetails(input.projectId, evidence, {
        requestKind: 'background_refresh',
        requestKey: `${requestKey}:vision`,
      })
      setEvidenceItems(evidence)
    },
    [hydrateStageContext]
  )

  const reviewEvidenceFileRelevance = useCallback(
    async (input: {
      fileId: string
      projectId: string
      stageId: string
      decision: 'related' | 'unrelated' | 'rejected'
      reason: string
    }) => {
      await reviewProjectFileRelevance({
        fileId: input.fileId,
        decision: input.decision,
        reason: input.reason,
      })
      await reloadProjects()
      await hydrateStageContext(input.projectId, input.stageId)
    },
    [hydrateStageContext, reloadProjects]
  )

  const uploadEvidenceFiles = useCallback(
    async (input: {
      projectId: string
      stageId: string
      files: Array<{ filename: string; contentType?: string; content?: string; contentBase64?: string }>
    }) => {
      await Promise.all(
        input.files.map((file) =>
          uploadProjectFile({
            projectId: input.projectId,
            filename: file.filename,
            contentType: file.contentType,
            content: file.content,
            contentBase64: file.contentBase64,
          })
        )
      )
      await reloadProjects()
      await hydrateStageContext(input.projectId, input.stageId)
    },
    [hydrateStageContext, reloadProjects]
  )

  const generateProjectReport = useCallback(
    async (input: { projectId: string; stageId: string; title: string }) => {
      const report = await generateReport(input.projectId, input.title)
      await reloadProjects()
      await hydrateStageContext(input.projectId, input.stageId)
      return {
        id: report.id,
        title: report.title,
        status: report.status,
        approvalCheckPassed: report.approval_check_passed,
        exportPath: report.export_path ?? undefined,
        decisionCardPath: report.decision_card_path ?? undefined,
        evidenceDirectoryPath: report.evidence_directory_path ?? undefined,
        bundleExportPath: report.bundle_export_path ?? undefined,
      }
    },
    [hydrateStageContext, reloadProjects]
  )

  const loadProjectReportContent = useCallback(async (reportId: string) => {
    return loadReportContent(reportId)
  }, [])

  const loadConversation = useCallback(async (conversationId: string) => {
    setCurrentConversationLoading(true)
    setCurrentConversationError(null)
    setCurrentRunId(undefined)
    setCurrentRunStatus(undefined)
    setCurrentRunCheckpointStatus(undefined)
    try {
      const detail = await loadConversationDetail(conversationId)
      setCurrentConversation(detail)
      const latestRunId = getLatestConversationRunId(detail)
      if (latestRunId) {
        try {
          const latestRun = await loadRun(latestRunId)
          setCurrentRunId(latestRun.id)
          setCurrentRunStatus(mapRunStatus(latestRun.status))
          setCurrentRunCheckpointStatus(latestRun.harness_checkpoint_status ?? undefined)
          // 恢复历史执行轨迹：从 SSE 事件重新构建 toolCalls 和 executionTrace
          try {
            const frames = await streamRunEvents(latestRunId, {
              maxReconnects: 0, // 历史 Run 不需要重连
            })
            setToolCalls(mapRunEventsToToolCalls(frames))
            setExecutionTrace(mapRunEventsToExecutionTrace(frames))
          } catch {
            // 历史 Run 事件流不可用，静默降级
          }
        } catch {
          // Conversation content remains usable even if its historical Run
          // can no longer be loaded.
        }
      }
      return detail
    } catch (loadError) {
      const message = loadError instanceof Error ? loadError.message : 'Failed to load conversation'
      setCurrentConversationError(message)
      setCurrentConversation(undefined)
      return undefined
    } finally {
      setCurrentConversationLoading(false)
    }
  }, [])

  const clearActiveConversation = useCallback(() => {
    // Abort any running SSE stream — navigating away should not leave it hanging
    streamAbortRef.current?.abort()
    streamAbortRef.current = null
    setCurrentConversation(undefined)
    setCurrentConversationError(null)
    setCurrentConversationLoading(false)
    // Reset run-specific state so stale data from a previous stage doesn't leak
    setCurrentRunId(undefined)
    setCurrentRunStatus(undefined)
    setCurrentRunCheckpointStatus(undefined)
    setToolCalls([])
    setExecutionTrace([])
    setStageResultPayload(undefined)
  }, [])

  const resumePausedRun = useCallback(
    async (input: {
      runId: string
      projectId: string
      stageId: string
      conversationId: string
      title: string
      humanInput?: Record<string, unknown>
    }) => {
      const { runId, projectId, stageId, conversationId, title, humanInput } = input
      const resumedRun = await resumeRun(runId, humanInput)
      setCurrentRunCheckpointStatus(resumedRun.harness_checkpoint_status ?? undefined)
      // Re-attach the SSE stream so the UI reflects the resumed graph execution.
      await followRun({
        run: resumedRun,
        projectId,
        stageId,
        conversationId,
        title,
      })
    },
    [followRun]
  )

  const createConversationInStage = useCallback(
    async (stageId: string, input?: { title?: string; initialMessage?: string }) => {
      const result = await createStageConversation(stageId, {
        title: input?.title?.trim() || '新会话',
        initialMessage: input?.initialMessage,
      })
      const nextProjects = await reloadProjects()
      // Find the project that owns this stage so we can set activeProject too
      const owningProject = nextProjects.find((p) =>
        p.stages.some((s) => s.id === stageId)
      )
      return {
        conversationId: result.id,
        stageId,
        projectId: owningProject?.id,
      }
    },
    [reloadProjects]
  )

  const deleteConversationInStage = useCallback(
    async (conversationId: string) => {
      await deleteConversation(conversationId)
      await reloadProjects()
      setCurrentConversation((previous) => (previous?.id === conversationId ? undefined : previous))
      setCurrentConversationError(null)
      setCurrentConversationLoading(false)
    },
    [reloadProjects]
  )

  const deleteProjectFromWorkspace = useCallback(
    async (projectId: string) => {
      await deleteProject(projectId)
      return reloadProjects()
    },
    [reloadProjects]
  )

  const renameProjectInWorkspace = useCallback(
    async (projectId: string, name: string) => {
      await updateProject(projectId, { name })
      return reloadProjects()
    },
    [reloadProjects]
  )

  const visionParseEvidenceFile = useCallback(
    async (input: { fileId: string; projectId: string; stageId: string; stageName?: string }) => {
      await visionParseProjectFile({
        fileId: input.fileId,
        prompt: `请解析该文件中的需求评估关键信息，并标出待人工确认字段。当前阶段：${input.stageName ?? input.stageId}`,
        targetSchema: {
          process_name: '业务流程名称',
          risk_hint: '风险提示或异常点',
          actor: '主要参与角色',
        },
        projectContext: {
          stage_id: input.stageId,
          stage_name: input.stageName,
        },
      })
      await reloadProjects()
      await hydrateStageContext(input.projectId, input.stageId)
    },
    [hydrateStageContext, reloadProjects]
  )

  const sendMessageInConversation = useCallback(
    async (conversationId: string, content: string) => {
      const trimmed = content.trim()
      if (!trimmed) return
      // 乐观追加 user 消息
      const userMessage = {
        id: `${conversationId}-user-${Date.now()}`,
        role: 'user' as const,
        content: trimmed,
      }
      const stampConversation = (
        prev: Conversation | undefined,
        messages: ConversationMessage[]
      ): Conversation =>
        prev
          ? { ...prev, messages: [...(prev.messages ?? []), ...messages] }
          : { id: conversationId, title: '当前会话', timeAgo: '刚刚', messages }
      setCurrentConversation((prev) => stampConversation(prev, [userMessage]))
      setConversationSending(true)
      try {
        const response = await appendConversationMessage(conversationId, 'user', trimmed, {
          runHarness: true,
        })
        const assistantMessages: ConversationMessage[] = []
        if (response.assistant_message) {
          assistantMessages.push({
            id: `${conversationId}-assistant-${response.assistant_message.created_at}`,
            role: 'assistant',
            content: response.assistant_message.content,
            created_at: response.assistant_message.created_at,
            toolCalls: mapConversationToolCalls(response.assistant_message.tool_calls),
            citations: response.assistant_message.citations ?? response.harness?.citations,
            intent: response.harness?.intent,
            harnessWarnings: response.harness?.warnings,
            actionProposals: response.harness?.action_proposals?.map((p) => ({
              id: p.id,
              actionType: p.action_type,
              title: p.title,
              requiresConfirmation: p.requires_confirmation,
              status: p.status as 'pending' | 'accepting' | 'accepted' | 'rejected',
              confirmationId: p.confirmation_id ?? undefined,
            })),
          })
        }
        setCurrentConversation((prev) => stampConversation(prev, assistantMessages))
      } catch (sendError) {
        const failureMessage: ConversationMessage = {
          id: `${conversationId}-error-${Date.now()}`,
          role: 'assistant',
          content: `抱歉,对话处理失败: ${sendError instanceof Error ? sendError.message : '未知错误'}`,
        }
        setCurrentConversation((prev) => stampConversation(prev, [failureMessage]))
      } finally {
        setConversationSending(false)
      }
    },
    []
  )

  const confirmConversationAction = useCallback(async (conversationId: string, proposalId: string) => {
    const result = await confirmConversationActionProposal(conversationId, proposalId)
    if (!result.run_id) {
      await loadConversation(conversationId)
      await reloadProjects()
      return undefined
    }
    const run = await loadRun(result.run_id)
    if (!run.stage_id) throw new Error('已创建任务但未返回阶段标识。')
    await followRun({
      run,
      projectId: run.project_id,
      stageId: run.stage_id,
      conversationId,
      title: run.goal.slice(0, 24),
    })
    return result.run_id
  }, [followRun, loadConversation, reloadProjects])

  const rejectConversationAction = useCallback(async (conversationId: string, proposalId: string) => {
    await rejectConversationActionProposal(conversationId, proposalId)
    await loadConversation(conversationId)
    await reloadProjects()
  }, [loadConversation, reloadProjects])

  return useMemo(
    () => ({
      projects,
      loading,
      error,
      toolCalls,
      executionTrace,
      suggestions,
      skills,
      evidenceItems,
      stageResultPayload,
      stageVersionLog,
      stageLockCheck,
      setStageResultPayload,
      currentConversation,
      currentConversationError,
      currentConversationLoading,
      currentRunId,
      currentRunStatus,
      currentRunCheckpointStatus,
      runEvidenceFilter,
      conversationSending,
      reloadProjects,
      hydrateStageContext,
      loadStageDeferredContext,
      createEmptyProject,
      startTask,
      lockCurrentStage,
      resumePausedRun,
      confirmSuggestion,
      createEvidenceSuggestion,
      parseEvidenceFile,
      reviewEvidenceFileRelevance,
      uploadEvidenceFiles,
      visionParseEvidenceFile,
      generateProjectReport,
      loadProjectReportContent,
      loadConversation,
      clearActiveConversation,
      createConversationInStage,
      deleteConversationInStage,
      deleteProjectFromWorkspace,
      renameProjectInWorkspace,
      sendMessageInConversation,
      confirmConversationAction,
      rejectConversationAction,
      getProject,
      getStage,
    }),
    [
      projects,
      loading,
      error,
      toolCalls,
      executionTrace,
      suggestions,
      skills,
      evidenceItems,
      stageResultPayload,
      stageVersionLog,
      stageLockCheck,
      currentConversation,
      currentConversationError,
      currentConversationLoading,
      currentRunId,
      currentRunStatus,
      currentRunCheckpointStatus,
      runEvidenceFilter,
      conversationSending,
      reloadProjects,
      hydrateStageContext,
      loadStageDeferredContext,
      createEmptyProject,
      startTask,
      lockCurrentStage,
      confirmSuggestion,
      createEvidenceSuggestion,
      parseEvidenceFile,
      reviewEvidenceFileRelevance,
      uploadEvidenceFiles,
      visionParseEvidenceFile,
      generateProjectReport,
      loadProjectReportContent,
      loadConversation,
      clearActiveConversation,
      createConversationInStage,
      deleteConversationInStage,
      deleteProjectFromWorkspace,
      renameProjectInWorkspace,
      sendMessageInConversation,
      confirmConversationAction,
      rejectConversationAction,
      getProject,
      getStage,
    ]
  )
}
