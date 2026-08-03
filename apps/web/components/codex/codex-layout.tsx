'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { LeftSidebar } from './left-sidebar'
import { ProjectCreateDialog } from './project-create-dialog'
import { SettingsWorkspace } from './settings-workspace'
import { WorkspaceContent } from './workspace-content'
import { WorkspaceShell } from './workspace-shell'
import { useCodexData } from '@/hooks/use-codex-data'
import { useWorkspaceSelection } from '@/hooks/use-workspace-selection'

export function CodexLayout() {
  const {
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
    conversationSending,
    getProject,
    getStage,
  } = useCodexData()
  const {
    activeProject,
    setActiveProject,
    activeStage,
    setActiveStage,
    activeConversation,
    setActiveConversation,
    rightSidebarOpen,
    setRightSidebarOpen,
    highlightEvidenceName,
    setHighlightEvidenceName,
  } = useWorkspaceSelection()
  const [stageResultPayload, setStageResultPayload] = useState<Record<string, unknown> | undefined>()
  const [createProjectOpen, setCreateProjectOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [settingsDirty, setSettingsDirty] = useState(false)
  const [unsavedDialogOpen, setUnsavedDialogOpen] = useState(false)
  const pendingNavigationRef = useRef<(() => void) | null>(null)

  const handleCreateProject = async (input: {
    name: string
    goal?: string
    files?: Array<{ filename: string; contentType?: string; content?: string; contentBase64?: string }>
  }) => {
    const selection = await createEmptyProject({
      name: input.name,
      goal: input.goal,
      files: input.files,
    })
    if (selection?.projectId) setActiveProject(selection.projectId)
    if (selection?.stageId) setActiveStage(selection.stageId)
    setActiveConversation(undefined)
  }

  // Shared delete handler for both the left sidebar and the home project
  // cards. Confirms, removes the project from the workspace, and reselects
  // the next remaining project (or clears selection) when the active one is
  // removed.
  const handleDeleteProject = useCallback(async (projectId: string) => {
    const project = getProject(projectId)
    const projectName = project?.name ?? '当前项目'
    if (!window.confirm(`删除项目“${projectName}”？删除后会从项目列表移除，项目文件和历史产物不会被物理删除。`)) return
    const nextProjects = await deleteProjectFromWorkspace(projectId)
    if (activeProject === projectId) {
      const nextProject = nextProjects.find((item) => item.id !== projectId)
      if (nextProject) {
        setActiveProject(nextProject.id)
        setActiveStage(nextProject.stages[0]?.id)
      } else {
        setActiveProject(undefined)
        setActiveStage(undefined)
      }
      setActiveConversation(undefined)
      clearActiveConversation()
      setSettingsOpen(false)
    }
  }, [activeProject, clearActiveConversation, deleteProjectFromWorkspace, getProject])

  // Rename handler shared by the home project cards. Persists the new name
  // via the API and refreshes the workspace list so the sidebar + cards
  // reflect the update. No selection change — rename keeps the project in
  // place, so we just need the list to reload.
  const handleRenameProject = useCallback(
    async (projectId: string, name: string) => {
      await renameProjectInWorkspace(projectId, name)
    },
    [renameProjectInWorkspace]
  )

  useEffect(() => {
    if (!activeProject || !activeStage) return
    // Immediately clear stale payload so the new stage doesn't briefly
    // render the previous stage's resultPayload before hydrateStageContext
    // resolves.
    setStageResultPayload(undefined)
    void hydrateStageContext(activeProject, activeStage).then((context) => {
      setStageResultPayload(context.stage.resultPayload)
    })
  }, [activeProject, activeStage, hydrateStageContext])

  const currentProject = getProject(activeProject)
  const currentStage = getStage(activeProject, activeStage)

  // Guarded navigation: if settings are dirty, show confirmation dialog
  // before allowing any sidebar navigation that would close settings.
  const guardedNav = useCallback((navFn: () => void) => {
    if (settingsOpen && settingsDirty) {
      // If dialog is already open, queue the latest nav (user may have
      // clicked another item while the dialog is showing). This avoids
      // stale refs — the most recent click is what the user wants.
      pendingNavigationRef.current = navFn
      setUnsavedDialogOpen(true)
    } else {
      navFn()
    }
  }, [settingsOpen, settingsDirty])

  const confirmLeaveSettings = () => {
    setUnsavedDialogOpen(false)
    setSettingsDirty(false)
    const nav = pendingNavigationRef.current
    pendingNavigationRef.current = null
    if (nav) {
      // Run navigation in a microtask to avoid calling setState during
      // the Dialog's onOpenChange batch — React can warn otherwise.
      queueMicrotask(nav)
    }
  }

  const cancelLeaveSettings = () => {
    setUnsavedDialogOpen(false)
    pendingNavigationRef.current = null
  }

  // Clear pending navigation when the dialog closes via Escape or outside click
  // (onOpenChange fires with false for both cases)
  const handleDialogOpenChange = useCallback((open: boolean) => {
    if (!open) {
      pendingNavigationRef.current = null
    }
    setUnsavedDialogOpen(open)
  }, [])

  return (
    <WorkspaceShell
      rightSidebarOpen={rightSidebarOpen}
      leftSidebar={(
        <LeftSidebar
          projects={projects}
          activeProject={activeProject}
          activeStage={activeStage}
          activeConversation={activeConversation}
          settingsActive={settingsOpen}
          onGoHome={() => {
            const nav = () => {
              setActiveProject(undefined)
              setActiveStage(undefined)
              setActiveConversation(undefined)
              clearActiveConversation()
              setSettingsOpen(false)
            }
            guardedNav(nav)
          }}
          onProjectChange={(projectId) => {
            const nav = () => {
              setActiveProject(projectId)
              setActiveStage(getProject(projectId)?.stages[0]?.id)
              setActiveConversation(undefined)
              clearActiveConversation()
              setSettingsOpen(false)
            }
            guardedNav(nav)
          }}
          onStageChange={(stageId) => {
            const nav = () => {
              // Find the project that owns this stage — if the user clicked a
              // stage under a *different* project, activeProject must also be
              // updated so getStage(activeProject, activeStage) resolves correctly.
              const owningProject = projects.find((p) =>
                p.stages.some((s) => s.id === stageId)
              )
              if (owningProject && owningProject.id !== activeProject) {
                setActiveProject(owningProject.id)
              }
              setActiveStage(stageId)
              setActiveConversation(undefined)
              clearActiveConversation()
              setSettingsOpen(false)
            }
            guardedNav(nav)
          }}
          onConversationChange={(conversationId, stageId) => {
            const nav = () => {
              // Sync activeProject when the conversation belongs to a
              // different project (same issue as onStageChange).
              const owningProject = projects.find((p) =>
                p.stages.some((s) => s.id === stageId)
              )
              if (owningProject && owningProject.id !== activeProject) {
                setActiveProject(owningProject.id)
              }
              setActiveStage(stageId)
              setActiveConversation(conversationId)
              setSettingsOpen(false)
              void loadConversation(conversationId)
            }
            guardedNav(nav)
          }}
          onCreateProject={() => {
            const nav = () => {
              setCreateProjectOpen(true)
              setSettingsOpen(false)
            }
            guardedNav(nav)
          }}
          onOpenSettings={() => setSettingsOpen(true)}
          onCreateConversation={async (stageId) => {
            const nav = async () => {
              const result = await createConversationInStage(stageId)
              if (result.projectId) setActiveProject(result.projectId)
              setActiveStage(result.stageId)
              setActiveConversation(result.conversationId)
              setSettingsOpen(false)
              void loadConversation(result.conversationId)
            }
            if (settingsOpen && settingsDirty) {
              pendingNavigationRef.current = () => void nav()
              setUnsavedDialogOpen(true)
            } else {
              void nav()
            }
          }}
          onDeleteConversation={async (conversationId, stageId) => {
            if (!window.confirm('删除该阶段会话？删除后会从阶段树中移除。')) return
            await deleteConversationInStage(conversationId)
            if (activeConversation === conversationId) {
              setActiveStage(stageId)
              setActiveConversation(undefined)
              clearActiveConversation()
            }
          }}
          onDeleteProject={handleDeleteProject}
        />
      )}
      mainContent={
        settingsOpen ? (
          <SettingsWorkspace
            projectId={activeProject}
            projectName={currentProject?.name}
            onBack={() => {
              if (settingsDirty) {
                pendingNavigationRef.current = () => setSettingsOpen(false)
                setUnsavedDialogOpen(true)
              } else {
                setSettingsOpen(false)
              }
            }}
            onDirtyChange={setSettingsDirty}
          />
        ) : (
          <WorkspaceContent
            loading={loading}
            error={error}
            projects={projects}
            activeProject={activeProject}
            activeStage={activeStage}
            activeConversation={activeConversation}
            currentProject={currentProject}
            currentStage={currentStage}
            currentConversation={currentConversation}
            currentConversationError={currentConversationError}
            currentConversationLoading={currentConversationLoading}
            currentRunId={currentRunId}
            toolCalls={toolCalls}
            suggestions={suggestions}
            skills={skills}
            evidenceItems={evidenceItems}
            currentRunStatus={currentRunStatus}
            stageResultPayload={stageResultPayload}
            rightSidebarOpen={rightSidebarOpen}
            highlightEvidenceName={highlightEvidenceName}
            onSetActiveProject={setActiveProject}
            onSetActiveStage={setActiveStage}
            onSetActiveConversation={setActiveConversation}
            onSetRightSidebarOpen={setRightSidebarOpen}
            onSelectConversation={(conversationId, stageId) => {
              setActiveStage(stageId)
              setActiveConversation(conversationId)
              void loadConversation(conversationId)
            }}
            onCreateConversation={createConversationInStage}
            onStartTask={startTask}
            onUploadEvidenceFiles={uploadEvidenceFiles}
            onCreateEvidenceSuggestion={createEvidenceSuggestion}
            onParseEvidenceFile={parseEvidenceFile}
            onVisionParseEvidenceFile={visionParseEvidenceFile}
            onGenerateReport={generateProjectReport}
            onLoadReportContent={loadProjectReportContent}
            onSendMessageInConversation={sendMessageInConversation}
            onConfirmConversationAction={async (conversationId, proposalId) => {
              await confirmConversationAction(conversationId, proposalId)
            }}
            onRejectConversationAction={async (conversationId, proposalId) => {
              await rejectConversationAction(conversationId, proposalId)
            }}
            onLockCurrentStage={lockCurrentStage}
            onResumePausedRun={
              activeProject && activeStage && activeConversation
                ? (runId, humanInput) =>
                    resumePausedRun({
                      runId,
                      projectId: activeProject,
                      stageId: activeStage,
                      conversationId: activeConversation,
                      title: currentConversation?.title ?? activeConversation,
                      humanInput,
                    })
                : undefined
            }
            conversationSending={conversationSending}
            onRetryLoad={reloadProjects}
            onCreateProject={() => {
              const nav = () => {
                setCreateProjectOpen(true)
                setSettingsOpen(false)
              }
              guardedNav(nav)
            }}
            onDeleteProject={handleDeleteProject}
            onRenameProject={handleRenameProject}
          />
        )
      }
      rightSidebar={null}
      dialogSlot={
        <>
          <ProjectCreateDialog
            open={createProjectOpen}
            onOpenChange={setCreateProjectOpen}
            onCreateProject={handleCreateProject}
          />
          <Dialog open={unsavedDialogOpen} onOpenChange={handleDialogOpenChange}>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>未保存的设置更改</DialogTitle>
                <DialogDescription>
                  您有未保存的设置草稿。离开将丢弃这些更改，此操作不可撤销。确定要离开吗？
                </DialogDescription>
              </DialogHeader>
              <DialogFooter className="gap-2 sm:gap-0">
                <Button variant="outline" onClick={cancelLeaveSettings}>
                  继续编辑
                </Button>
                <Button variant="destructive" onClick={confirmLeaveSettings}>
                  不保存，直接离开
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </>
      }
    />
  )
}
