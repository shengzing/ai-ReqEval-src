'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import type { Conversation, ConversationMessage, EvidenceItem, Project, RunStatus, Stage, StageSkill, SuggestionCard, SuggestionConfirmationResult, ToolCall } from '@/lib/types'
import {
  confirmAutoResearchRecord,
  confirmConversationActionProposal,
  createAutoResearchRecord,
  createManualAutoResearchRecord,
  createProject,
  createRun,
  createStageConversation,
  deleteConversation,
  deleteProject,
  generateReport,
  rejectConversationActionProposal,
  loadConversationDetail,
  loadRun,
  loadReportContent,
  loadAutoResearchRecords,
  loadStageLockCheck,
  loadProjectEvidence,
  loadProjectTree,
  loadStage,
  loadLatestStageResult,
  loadLatestStageVersion,
  loadStageSkills,
  lockStage,
  mapRunEventsToConversation,
  mapConversationToolCalls,
  mapRunEventsToSuggestions,
  mapRunEventsToToolCalls,
  mapRunStatus,
  parseProjectFile,
  visionParseProjectFile,
  appendConversationMessage,
  resumeRun,
  type RunEventFrame,
  streamRunEvents,
  updateProject,
  uploadProjectFile,
} from '@/lib/api-client'

export function useCodexData() {
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([])
  const [suggestions, setSuggestions] = useState<SuggestionCard[]>([])
  const [skills, setSkills] = useState<StageSkill[]>([])
  const [evidenceItems, setEvidenceItems] = useState<EvidenceItem[]>([])
  const [currentConversation, setCurrentConversation] = useState<Conversation | undefined>()
  const [currentConversationError, setCurrentConversationError] = useState<string | null>(null)
  const [currentConversationLoading, setCurrentConversationLoading] = useState(false)
  const [conversationSending, setConversationSending] = useState(false)
  const [currentRunId, setCurrentRunId] = useState<string | undefined>()
  const [currentRunStatus, setCurrentRunStatus] = useState<RunStatus | undefined>()
  const streamAbortRef = useRef<AbortController | null>(null)

  const reloadProjects = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const nextProjects = await loadProjectTree()
      setProjects(nextProjects)
      return nextProjects
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : 'Failed to load projects')
      return []
    } finally {
      setLoading(false)
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
    async (projectId: string, stageId: string) => {
      // Reset ALL stage-related state to prevent stale data from the
      // previous stage from leaking into the newly selected stage.
      setCurrentRunStatus(undefined)
      setToolCalls([])
      setSkills([])
      setSuggestions([])
      setEvidenceItems([])

      const [stage, nextSkills, nextSuggestions, lockCheck] = await Promise.all([
        loadStage(stageId),
        loadStageSkills(stageId),
        loadAutoResearchRecords(stageId),
        loadStageLockCheck(stageId),
      ])
      const resultPayload = await loadLatestStageResult(stageId)
      const versionLog = await loadLatestStageVersion(projectId, stageId)
      const nextEvidence = await loadProjectEvidence(projectId, stage.name)
      setSkills(nextSkills)
      setEvidenceItems(nextEvidence)
      setSuggestions(nextSuggestions.filter((item) => item.status === 'pending'))
      return { stage: { ...stage, resultPayload, versionLog, lockCheck }, nextSkills, nextEvidence, nextSuggestions }
    },
    []
  )

  const followRun = useCallback(
    async ({
      run,
      projectId,
      stageId,
      conversationId,
      title,
    }: {
      run: { id: string; status: string }
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
      setToolCalls([])
      setSuggestions([])
      setCurrentConversationError(null)
      setCurrentConversationLoading(false)
      const liveFrames: RunEventFrame[] = []

      let frames: RunEventFrame[]
      try {
        frames = await streamRunEvents(run.id, {
          signal: controller.signal,
          onEvent: (frame) => {
            liveFrames.push(frame)
            setCurrentRunStatus((previous) => {
              if (frame.event === 'run.running') return 'running'
              if (frame.event === 'run.waiting_user') return 'waiting_user'
              if (frame.event === 'run.completed') return 'completed'
              if (frame.event === 'run.failed') return 'failed'
              return previous
            })
            setToolCalls(mapRunEventsToToolCalls(liveFrames))
            setCurrentConversation(mapRunEventsToConversation(liveFrames, title, conversationId))
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

      if (frames.some((frame) => frame.event === 'run.completed')) {
        try {
          const autoResearchSuggestion = await createAutoResearchRecord(stageId, run.id)
          setSuggestions((previous) => [...previous.filter((item) => item.status === 'pending'), autoResearchSuggestion])
        } catch {
          // Suggestions are a non-critical follow-up to a completed Run.
        }
      }
      setCurrentConversation(mapRunEventsToConversation(frames, title, conversationId))
      setToolCalls(mapRunEventsToToolCalls(frames))
      const terminalRunStatus = frames.some((frame) => frame.event === 'run.completed')
        ? 'completed'
        : frames.some((frame) => frame.event === 'run.failed')
          ? 'failed'
          : mapRunStatus(run.status)

      try {
        await reloadProjects()
        await hydrateStageContext(projectId, stageId)
        const detail = await loadConversationDetail(conversationId)
        setCurrentConversation(detail)
        // hydrateStageContext clears stage state to avoid stale data when
        // navigating. Restore the terminal state for the Run just observed.
        setCurrentRunStatus(terminalRunStatus)
      } catch {
        // Preserve streamed state when a post-run refresh is unavailable.
      }
    },
    [hydrateStageContext, reloadProjects]
  )

  useEffect(() => {
    return () => {
      streamAbortRef.current?.abort()
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
    try {
      const detail = await loadConversationDetail(conversationId)
      setCurrentConversation(detail)
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
    setToolCalls([])
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
      await resumeRun(runId, humanInput)
      // Re-attach the SSE stream so the UI reflects the resumed graph execution.
      await followRun({
        run: { id: runId, status: 'waiting_user' },
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
            intent: response.harness?.intent,
            harnessWarnings: response.harness?.warnings,
            actionProposals: response.harness?.action_proposals?.map((p) => ({
              id: p.id,
              actionType: p.action_type,
              title: p.title,
              requiresConfirmation: p.requires_confirmation,
              status: p.status as 'pending' | 'accepting' | 'accepted' | 'rejected',
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
  }, [followRun])

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
      suggestions,
      skills,
      evidenceItems,
      currentConversation,
      currentConversationError,
      currentConversationLoading,
      currentRunId,
      currentRunStatus,
      conversationSending,
      reloadProjects,
      hydrateStageContext,
      createEmptyProject,
      startTask,
      lockCurrentStage,
      resumePausedRun,
      confirmSuggestion,
      createEvidenceSuggestion,
      parseEvidenceFile,
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
      suggestions,
      skills,
      evidenceItems,
      currentConversation,
      currentConversationError,
      currentConversationLoading,
      currentRunId,
      currentRunStatus,
      conversationSending,
      reloadProjects,
      hydrateStageContext,
      createEmptyProject,
      startTask,
      lockCurrentStage,
      confirmSuggestion,
      createEvidenceSuggestion,
      parseEvidenceFile,
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
