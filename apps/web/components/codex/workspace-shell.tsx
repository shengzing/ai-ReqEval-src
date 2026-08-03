'use client'

import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

interface WorkspaceShellProps {
  leftSidebar: ReactNode | null
  mainContent: ReactNode
  rightSidebar: ReactNode
  rightSidebarOpen: boolean
  dialogSlot?: ReactNode
}

export function WorkspaceShell({
  leftSidebar,
  mainContent,
  rightSidebar,
  rightSidebarOpen,
  dialogSlot,
}: WorkspaceShellProps) {
  return (
    <div data-codex-workspace-shell className="flex h-dvh min-h-0 flex-col overflow-hidden bg-background lg:flex-row">
      {leftSidebar}

      {rightSidebar === null ? (
        <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">{mainContent}</div>
      ) : (
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden lg:flex-row">
          <main className={cn('min-w-0 flex-1 overflow-hidden', rightSidebarOpen && 'border-r border-border')}>
            {mainContent}
          </main>
          {rightSidebar}
        </div>
      )}

      {dialogSlot}
    </div>
  )
}
