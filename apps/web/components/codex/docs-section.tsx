'use client'

import { useEffect, useState } from 'react'
import { ChevronRight, Loader2 } from 'lucide-react'

import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'
import { MarkdownRenderer } from '@/lib/markdown-renderer'

interface DocEntry {
  slug: string
  title: string
  file: string
}

const DOC_ENTRIES: DocEntry[] = [
  { slug: 'quickstart', title: '快速开始', file: '01-quickstart.md' },
  { slug: 'models', title: '模型配置', file: '02-models.md' },
  { slug: 'prompts', title: '提示词模板', file: '03-prompts.md' },
  { slug: 'skills', title: '阶段 Skills', file: '04-skills.md' },
  { slug: 'policy', title: '配置发布', file: '05-policy.md' },
  { slug: 'faq', title: '常见问题', file: '06-faq.md' },
]

export function DocsSection() {
  const [activeSlug, setActiveSlug] = useState<string>(DOC_ENTRIES[0].slug)
  const [content, setContent] = useState<string>('')
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string>('')

  useEffect(() => {
    const entry = DOC_ENTRIES.find((d) => d.slug === activeSlug)
    if (!entry) return
    let cancelled = false
    setLoading(true)
    setError('')
    fetch(`/docs/${entry.file}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.text()
      })
      .then((text) => {
        if (cancelled) return
        setContent(text)
        setLoading(false)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err?.message ?? '文档加载失败')
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [activeSlug])

  return (
    <section className="flex min-h-0 flex-1 overflow-hidden rounded-lg border border-border bg-card">
      <aside className="w-[200px] shrink-0 border-r border-border bg-muted/20">
        <ScrollArea className="h-full">
          <nav className="space-y-0.5 p-2">
            <div className="px-2 pb-1.5 pt-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              使用手册
            </div>
            {DOC_ENTRIES.map((entry, idx) => {
              const active = entry.slug === activeSlug
              return (
                <button
                  key={entry.slug}
                  type="button"
                  onClick={() => setActiveSlug(entry.slug)}
                  className={cn(
                    'group flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-sm transition-colors',
                    active
                      ? 'bg-primary/10 text-primary'
                      : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                  )}
                >
                  <span
                    className={cn(
                      'font-mono text-[10px] tabular-nums',
                      active ? 'text-primary/60' : 'text-muted-foreground/60'
                    )}
                  >
                    {String(idx + 1).padStart(2, '0')}
                  </span>
                  <span className="flex-1 truncate">{entry.title}</span>
                  <ChevronRight
                    className={cn(
                      'size-3.5 opacity-0 transition-opacity group-hover:opacity-100',
                      active && 'opacity-100'
                    )}
                  />
                </button>
              )
            })}
          </nav>
        </ScrollArea>
      </aside>

      <main className="flex min-h-0 min-w-0 flex-1 flex-col">
        <ScrollArea className="h-full">
          <div className="mx-auto max-w-3xl px-6 py-5">
            {loading ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                文档加载中...
              </div>
            ) : error ? (
              <div className="rounded-md border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                文档加载失败：{error}
                <div className="mt-1 text-xs text-muted-foreground">
                  请确认 public/docs/ 下存在对应文件。
                </div>
              </div>
            ) : (
              <MarkdownRenderer content={content} />
            )}
          </div>
        </ScrollArea>
      </main>
    </section>
  )
}
