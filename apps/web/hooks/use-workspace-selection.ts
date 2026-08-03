'use client'

import { useState } from 'react'

export function useWorkspaceSelection() {
  const [activeProject, setActiveProject] = useState<string | undefined>()
  const [activeStage, setActiveStage] = useState<string | undefined>()
  const [activeConversation, setActiveConversation] = useState<string | undefined>()
  const [rightSidebarOpen, setRightSidebarOpen] = useState(false)
  const [highlightEvidenceName, setHighlightEvidenceName] = useState<string | undefined>()

  return {
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
  }
}
