'use client'

import { useEffect, useMemo, useRef, useState } from 'react'

import { HomeProjectList } from './home-project-list'
import { RawResourcePreviewSidebar } from './evidence/raw-resource-preview-sidebar'
import { RightSidebar } from './right-sidebar'
import { StageWorkspace } from './stage-workspace'
import { WorkspaceStateView } from './workspace-state-view'
import { ApiError } from '@/lib/api-error'
import { encodeProjectFile } from '@/lib/file-encoding'
import { cn } from '@/lib/utils'
import { loadFilePreview } from '@/lib/api-client'
import type { Conversation, EvidenceItem, FilePreview, Project, RunStatus, Stage, StageSkill, SuggestionCard, SuggestionConfirmationResult, ToolCall } from '@/lib/types'
import { buildEnrichedStage, resolveActiveConversation } from '@/lib/workspace-state'

interface WorkspaceContentProps {
  loading: boolean
  error: string | null
  projects: Project[]
  activeProject?: string
  activeStage?: string
  activeConversation?: string
  currentProject?: Project
  currentStage?: Stage
  currentConversation?: Conversation
  currentConversationError?: string | null
  currentConversationLoading?: boolean
  toolCalls: ToolCall[]
  suggestions: SuggestionCard[]
  skills: StageSkill[]
  evidenceItems: EvidenceItem[]
  currentRunStatus?: RunStatus
  stageResultPayload?: Record<string, unknown>
  rightSidebarOpen: boolean
  highlightEvidenceName?: string
  onSetActiveProject: (projectId: string) => void
  onSetActiveStage: (stageId: string) => void
  onSetActiveConversation: (conversationId?: string) => void
  onSetRightSidebarOpen: (open: boolean) => void
  onSelectConversation: (conversationId: string, stageId: string) => void
  onCreateConversation: (
    stageId: string,
    input?: { title?: string; initialMessage?: string }
  ) => Promise<{ projectId?: string; stageId: string; conversationId: string }>
  onStartTask: (input: {
    projectId?: string
    stageId?: string
    goal: string
    conversationId?: string
  }) => Promise<{ projectId?: string; stageId?: string; conversationId?: string } | undefined>
  onUploadEvidenceFiles: (input: {
    projectId: string
    stageId: string
    files: Array<{ filename: string; contentType?: string; content?: string; contentBase64?: string }>
  }) => Promise<void>
  onCreateEvidenceSuggestion: (input: {
    projectId: string
    stageId: string
    title: string
    description: string
    action: string
    impact?: string
    risk?: 'low' | 'medium' | 'high'
    source?: string
    context?: Record<string, unknown>
  }) => Promise<SuggestionCard>
  onParseEvidenceFile: (input: { fileId: string; projectId: string; stageId: string }) => Promise<void>
  onVisionParseEvidenceFile: (input: { fileId: string; projectId: string; stageId: string; stageName?: string }) => Promise<void>
  onGenerateReport: (input: { projectId: string; stageId: string; title: string }) => Promise<NonNullable<Stage['reportInfo']>>
  onLoadReportContent: (reportId: string) => Promise<{ id: string; title: string; status: string; content: string }>
  onSendMessageInConversation: (conversationId: string, content: string) => Promise<void>
  onConfirmConversationAction: (conversationId: string, proposalId: string) => Promise<void>
  onRejectConversationAction: (conversationId: string, proposalId: string) => Promise<void>
  onLockCurrentStage: (projectId: string, stageId: string) => Promise<void>
  onResumePausedRun?: (
    runId: string,
    humanInput?: Record<string, unknown>
  ) => Promise<void>
  currentRunId?: string
  conversationSending?: boolean
  onRetryLoad?: () => Promise<Project[]> | void
  onCreateProject: () => void
  onDeleteProject?: (projectId: string) => void
  onRenameProject?: (projectId: string, name: string) => Promise<void> | void
  onConfirmSuggestion: (input: {
    recordId: string
    decision: 'accepted' | 'accepted_with_edits' | 'rejected' | 'follow_up'
    note?: string
    editedDescription?: string
    projectId: string
    stageId: string
  }) => Promise<SuggestionConfirmationResult>
}

export function WorkspaceContent({
  loading,
  error,
  projects,
  activeProject,
  activeStage,
  activeConversation,
  currentProject,
  currentStage,
  currentConversation,
  currentConversationError,
  currentConversationLoading,
  toolCalls,
  suggestions,
  skills,
  evidenceItems,
  currentRunStatus,
  stageResultPayload,
  rightSidebarOpen,
  highlightEvidenceName,
  onSetActiveProject,
  onSetActiveStage,
  onSetActiveConversation,
  onSetRightSidebarOpen,
  onSelectConversation,
  onCreateConversation,
  onStartTask,
  onUploadEvidenceFiles,
  onCreateEvidenceSuggestion,
  onParseEvidenceFile,
  onVisionParseEvidenceFile,
  onGenerateReport,
  onLoadReportContent,
  onSendMessageInConversation,
  onConfirmConversationAction,
  onRejectConversationAction,
  onLockCurrentStage,
  onResumePausedRun,
  currentRunId,
  conversationSending,
  onRetryLoad,
  onCreateProject,
  onDeleteProject,
  onRenameProject,
  onConfirmSuggestion,
}: WorkspaceContentProps) {
  const [latestReportInfo, setLatestReportInfo] = useState<Stage['reportInfo'] | undefined>()
  const [previewItem, setPreviewItem] = useState<EvidenceItem | undefined>()
  const [previewContent, setPreviewContent] = useState<FilePreview | undefined>()
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const previewRequestIdRef = useRef(0)

  // Reset cached report info when the user navigates to a different project or
  // stage. Without this, buildEnrichedStage (below) keeps leaking the previous
  // stage's gate status and content into the freshly selected stage.
  useEffect(() => {
    setLatestReportInfo(undefined)
    setPreviewItem(undefined)
    setPreviewContent(undefined)
    setPreviewError(null)
    setPreviewLoading(false)
  }, [activeProject, activeStage])

  const resolvedConversation = resolveActiveConversation({
    currentConversation,
    stageConversations: currentStage?.conversations,
    activeConversationId: activeConversation,
  })
  const enrichedStage = useMemo(() => {
    return buildEnrichedStage({
      currentStage,
      resultPayload: stageResultPayload,
      reportInfo: latestReportInfo,
      skills,
      suggestions,
      currentRunStatus,
    })
  }, [currentStage, stageResultPayload, latestReportInfo, skills, suggestions, currentRunStatus])

  const handlePreviewResource = async (item: EvidenceItem) => {
    const fileId = item.sourceFileId ?? item.id
    const requestId = previewRequestIdRef.current + 1
    previewRequestIdRef.current = requestId
    setPreviewItem(item)
    setPreviewContent(undefined)
    setPreviewError(null)
    setPreviewLoading(true)
    try {
      const preview = await loadFilePreview(fileId)
      if (previewRequestIdRef.current !== requestId) return
      setPreviewContent(preview)
    } catch (loadError) {
      if (previewRequestIdRef.current !== requestId) return
      setPreviewError(loadError instanceof Error ? loadError.message : '文件预览失败，请重试。')
    } finally {
      if (previewRequestIdRef.current === requestId) setPreviewLoading(false)
    }
  }

  const mainContent = (() => {
    if (loading) {
      return <WorkspaceStateView type="loading" message="加载项目中..." />
    }

    if (error) {
      return <WorkspaceStateView type="error" message={error} onRetry={onRetryLoad} />
    }

    if (activeStage && enrichedStage) {
      return (
        <StageWorkspace
          projectId={activeProject}
          stage={enrichedStage}
          conversation={resolvedConversation}
          activeConversationId={activeConversation}
          stageConversations={currentStage?.conversations}
          conversationLoading={currentConversationLoading}
          conversationLoadError={currentConversationError}
          toolCalls={toolCalls}
          suggestionCards={suggestions}
          evidenceItems={evidenceItems}
          runStatus={currentRunStatus}
          stageCommandHint={
            activeConversation
              ? '当前会话内继续输入，将沿用这个会话。'
              : '在阶段页发送会先创建新的阶段会话，再打开该会话页。'
          }
          onSelectConversation={(conversationId) => onSelectConversation(conversationId, activeStage!)}
          onCreateConversation={async () => {
            const selection = await onCreateConversation(activeStage!)
            if (selection.projectId) onSetActiveProject(selection.projectId)
            onSelectConversation(selection.conversationId, selection.stageId)
          }}
          onOpenRightSidebar={() => onSetRightSidebarOpen(true)}
          onStartRun={async (goal) => {
            if (!activeConversation) {
              const selection = await onCreateConversation(activeStage!, {
                title: goal.slice(0, 24),
                initialMessage: goal,
              })
              if (selection.projectId) onSetActiveProject(selection.projectId)
              onSelectConversation(selection.conversationId, selection.stageId)
              await onStartTask({
                projectId: selection.projectId ?? activeProject,
                stageId: selection.stageId,
                goal,
                conversationId: selection.conversationId,
              })
              return
            }

            const selection = await onStartTask({
              projectId: activeProject,
              stageId: activeStage,
              goal,
              conversationId: activeConversation,
            })
            if (selection?.conversationId) {
              onSetActiveConversation(selection.conversationId)
            }
          }}
          onUploadFiles={
            activeProject && activeStage
              ? async (files) => {
                  const encodedFiles = await Promise.all(files.map(encodeProjectFile))
                  await onUploadEvidenceFiles({
                    projectId: activeProject,
                    stageId: activeStage,
                    files: encodedFiles,
                  })
                  onSetRightSidebarOpen(true)
                }
              : undefined
          }
          onGenerateReport={
            activeProject && activeStage
              ? async () => {
                  const title = `${enrichedStage.name} 报告草稿`
                  try {
                    const report = await onGenerateReport({
                      projectId: activeProject,
                      stageId: activeStage,
                      title,
                    })
                    setLatestReportInfo(report)
                  } catch (generateError) {
                    const message =
                      generateError instanceof ApiError
                        ? generateError.message
                        : generateError instanceof Error
                          ? generateError.message
                          : '报告生成失败'
                    setLatestReportInfo({
                      title,
                      status: generateError instanceof ApiError && generateError.status === 409 ? 'blocked' : 'failed',
                      gateMessage: message,
                    })
                  }
                  onSetRightSidebarOpen(true)
                }
              : undefined
          }
          onPreviewReport={
            latestReportInfo?.id
              ? async () => {
                  const report = await onLoadReportContent(latestReportInfo.id!)
                  // Guard: if the user navigated to a different stage while
                  // the preview was loading, discard the result instead of
                  // overwriting the new stage's reportInfo.
                  setLatestReportInfo((previous) => {
                    if (!previous?.id || previous.id !== latestReportInfo.id) return previous
                    return {
                      ...previous,
                      id: report.id,
                      title: report.title,
                      status: report.status,
                      content: report.content,
                    }
                  })
                }
              : undefined
          }
          onSendMessage={activeConversation ? onSendMessageInConversation : undefined}
          onConfirmConversationAction={onConfirmConversationAction}
          onRejectConversationAction={onRejectConversationAction}
          onLockStage={
            activeProject && activeStage
              ? () => onLockCurrentStage(activeProject, activeStage)
              : undefined
          }
          onResumeRun={
            currentRunId && activeProject && activeStage && activeConversation && onResumePausedRun
              ? (runId, humanInput) => onResumePausedRun(runId, humanInput)
              : undefined
          }
          conversationSending={conversationSending}
          onConfirmExecutionOutput={
            activeProject && activeStage
              ? async (toolCall) => {
                  if (!toolCall.details) return
                  const suggestion = await onCreateEvidenceSuggestion({
                    projectId: activeProject,
                    stageId: activeStage,
                    title: `确认写回：${toolCall.name}`,
                    description: toolCall.output ?? `${toolCall.name} 已返回可写入阶段的结果。`,
                    action: '人工确认后将该过程节点结果登记到阶段数据中。',
                    impact: '确认后写回当前阶段结果',
                    risk: 'medium',
                    source: toolCall.source === 'conversation' ? 'conversation_tool' : 'stage_tool',
                    context: {
                      execution_node: {
                        tool_name: toolCall.name,
                        output: toolCall.details,
                        evidence_refs: toolCall.evidenceRefs ?? [],
                      },
                    },
                  })
                  if (!suggestion.recordId) throw new Error('未能创建阶段写回确认项。')
                  await onConfirmSuggestion({
                    recordId: suggestion.recordId,
                    decision: 'accepted',
                    projectId: activeProject,
                    stageId: activeStage,
                  })
                }
              : undefined
          }
        />
      )
    }

    return (
      <HomeProjectList
        projects={projects}
        activeProject={activeProject}
        onSelectProject={(projectId) => {
          onSetActiveProject(projectId)
          const firstStageId = projects.find((p) => p.id === projectId)?.stages[0]?.id
          if (firstStageId) onSetActiveStage(firstStageId)
          onSetActiveConversation(undefined)
        }}
        onCreateProject={onCreateProject}
        onDeleteProject={onDeleteProject}
        onRenameProject={onRenameProject}
      />
    )
  })()

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden lg:flex-row">
      <main className={cn('min-h-0 min-w-0 flex-1 overflow-hidden', (rightSidebarOpen || previewItem) && 'lg:border-r lg:border-border')}>
        {mainContent}
      </main>
      {previewItem && (
        <RawResourcePreviewSidebar
          item={previewItem}
          preview={previewContent}
          loading={previewLoading}
          error={previewError}
          onClose={() => {
            previewRequestIdRef.current += 1
            setPreviewItem(undefined)
            setPreviewContent(undefined)
            setPreviewError(null)
            setPreviewLoading(false)
          }}
        />
      )}
      <RightSidebar
        isOpen={rightSidebarOpen}
        onClose={() => onSetRightSidebarOpen(false)}
        currentStage={activeStage}
        currentStageData={enrichedStage}
        evidenceItems={evidenceItems}
        highlightedEvidenceName={highlightEvidenceName}
        onParseFile={
          activeProject && activeStage
            ? async (fileId) => {
                await onParseEvidenceFile({
                  fileId,
                  projectId: activeProject,
                  stageId: activeStage,
                })
              }
            : undefined
        }
        onVisionParseFile={
          activeProject && activeStage
            ? async (fileId) => {
                await onVisionParseEvidenceFile({
                  fileId,
                  projectId: activeProject,
                  stageId: activeStage,
                  stageName: enrichedStage?.name,
                })
              }
            : undefined
        }
        onAskEvidenceDetail={
          activeProject && activeStage
            ? async (prompt) => {
                const selection = await onStartTask({
                  projectId: activeProject,
                  stageId: activeStage,
                  goal: prompt,
                  conversationId: activeConversation,
                })
                if (selection?.conversationId) {
                  onSetActiveConversation(selection.conversationId)
                }
              }
            : undefined
        }
        onCreateEvidenceSuggestion={
          activeProject && activeStage
            ? async (input) => {
                await onCreateEvidenceSuggestion({
                  projectId: activeProject,
                  stageId: activeStage,
                  ...input,
                })
              }
            : undefined
        }
        onPreviewResource={handlePreviewResource}
      />
    </div>
  )
}
