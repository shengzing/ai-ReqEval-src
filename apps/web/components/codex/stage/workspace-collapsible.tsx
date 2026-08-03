'use client'

import { useEffect, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { cn } from '@/lib/utils'

interface WorkspaceCollapsibleProps {
  title: string
  icon?: React.ReactNode
  badge?: string
  defaultOpen?: boolean
  forceOpen?: boolean
  children: React.ReactNode
  className?: string
}

export function WorkspaceCollapsible({
  title,
  icon,
  badge,
  defaultOpen = false,
  forceOpen = false,
  children,
  className,
}: WorkspaceCollapsibleProps) {
  const [open, setOpen] = useState(defaultOpen || forceOpen)

  // Sync internal open state when forceOpen changes — using useEffect
  // instead of setState during render to avoid React warnings.
  useEffect(() => {
    if (forceOpen) setOpen(true)
  }, [forceOpen])

  // When defaultOpen flips from false → true (data arrived), expand the section.
  // useState only reads the initial value, so we need an effect to react.
  useEffect(() => {
    if (defaultOpen && !open && !forceOpen) setOpen(true)
    // Only trigger when defaultOpen becomes true; avoid infinite loop by
    // not including `open` in the dependency array — the guard `!open`
    // inside the effect body prevents repeated triggers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaultOpen, forceOpen])

  return (
    <Collapsible open={forceOpen || open} onOpenChange={forceOpen ? undefined : setOpen}>
      <div className={cn('rounded-lg border border-border bg-card', className)}>
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="flex w-full items-center gap-2 px-4 py-3 text-left transition-colors hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
          >
            {(forceOpen || open) ? (
              <ChevronDown className="size-3.5 text-muted-foreground" />
            ) : (
              <ChevronRight className="size-3.5 text-muted-foreground" />
            )}
            {icon}
            <span className="text-sm font-medium text-foreground">{title}</span>
            {badge && (
              <span className="ml-auto rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
                {badge}
              </span>
            )}
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="border-t border-border px-4 py-4">
            {children}
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  )
}
