'use client'

import * as React from 'react'

import { cn } from '@/lib/utils'

/**
 * 轻量 Markdown 渲染器。
 *
 * 支持：标题、段落、无序/有序列表、代码块、行内代码、加粗、
 * 链接、引用、分隔线、表格。
 * 不支持图片、嵌套强调、HTML 注释。
 */

interface MdNode {
  type:
    | 'h1' | 'h2' | 'h3' | 'h4' | 'h5' | 'h6'
    | 'p' | 'ul' | 'ol' | 'blockquote'
    | 'hr' | 'code' | 'table'
  text?: string
  items?: string[]
  lang?: string
  rows?: string[][]
  align?: Array<'left' | 'center' | 'right' | null>
}

const ATX = /^(#{1,6})\s+(.*)$/
const BULLET = /^[-*+]\s+(.*)$/
const ORDERED = /^\d+\.\s+(.*)$/
const FENCE = /^```(.*)$/
const HR = /^(?:---|\*\*\*|___)\s*$/
const QUOTE = /^>\s?(.*)$/
const TABLE_SEP = /^\|?(\s*:?[-]+:?\s*\|)+\s*:?[-]+:?\s*\|?$/

function parseTable(lines: string[], start: number): { node: MdNode; next: number } | null {
  // header row
  const headerLine = lines[start]
  const sepLine = lines[start + 1]
  if (!sepLine || !TABLE_SEP.test(sepLine)) return null
  const cells = (line: string) =>
    line.replace(/^\||\|$/g, '').split('|').map((c) => c.trim())
  const aligns = cells(sepLine).map((c) => {
    const l = c.startsWith(':')
    const r = c.endsWith(':')
    if (l && r) return 'center' as const
    if (r) return 'right' as const
    if (l) return 'left' as const
    return null
  })
  const rows = [cells(headerLine)]
  let i = start + 2
  while (i < lines.length && lines[i].trim().startsWith('|')) {
    rows.push(cells(lines[i]))
    i++
  }
  if (rows.length < 2) return null
  return { node: { type: 'table', rows, align: aligns }, next: i }
}

function parse(markdown: string): MdNode[] {
  const nodes: MdNode[] = []
  const lines = markdown.replace(/\r\n/g, '\n').split('\n')
  let i = 0
  while (i < lines.length) {
    const line = lines[i]

    // 代码块
    const fence = FENCE.exec(line)
    if (fence) {
      const lang = fence[1] || ''
      const buf: string[] = []
      i++
      while (i < lines.length && !FENCE.test(lines[i])) {
        buf.push(lines[i])
        i++
      }
      i++ // 跳过结尾 ```
      nodes.push({ type: 'code', lang, text: buf.join('\n') })
      continue
    }

    // 分隔线
    if (HR.test(line)) {
      nodes.push({ type: 'hr' })
      i++
      continue
    }

    // 标题
    const h = ATX.exec(line)
    if (h) {
      const level = h[1].length
      nodes.push({ type: `h${level}` as MdNode['type'], text: h[2].trim() })
      i++
      continue
    }

    // 引用块：连续的 > 行合并
    if (QUOTE.test(line)) {
      const buf: string[] = []
      while (i < lines.length && QUOTE.test(lines[i])) {
        buf.push(lines[i].replace(/^>\s?/, ''))
        i++
      }
      nodes.push({ type: 'blockquote', items: buf })
      continue
    }

    // 表格
    if (line.includes('|') && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1])) {
      const t = parseTable(lines, i)
      if (t) {
        nodes.push(t.node)
        i = t.next
        continue
      }
    }

    // 无序列表
    if (BULLET.test(line)) {
      const items: string[] = []
      while (i < lines.length && BULLET.test(lines[i])) {
        items.push(lines[i].replace(BULLET, '$1'))
        i++
      }
      nodes.push({ type: 'ul', items })
      continue
    }

    // 有序列表
    if (ORDERED.test(line)) {
      const items: string[] = []
      while (i < lines.length && ORDERED.test(lines[i])) {
        items.push(lines[i].replace(ORDERED, '$1'))
        i++
      }
      nodes.push({ type: 'ol', items })
      continue
    }

    // 空行
    if (!line.trim()) {
      i++
      continue
    }

    // 段落：连续非空行合并
    const buf: string[] = [line]
    i++
    while (
      i < lines.length &&
      lines[i].trim() &&
      !ATX.test(lines[i]) &&
      !BULLET.test(lines[i]) &&
      !ORDERED.test(lines[i]) &&
      !FENCE.test(lines[i]) &&
      !HR.test(lines[i]) &&
      !QUOTE.test(lines[i]) &&
      !(lines[i].includes('|') && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1]))
    ) {
      buf.push(lines[i])
      i++
    }
    nodes.push({ type: 'p', text: buf.join(' ') })
  }
  return nodes
}

// 行内：**加粗** `代码` [链接](url)
function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
  const out: React.ReactNode[] = []
  let rest = text
  let k = 0
  // 正则：捕获 **bold** 或 `code` 或 [text](url)
  const re = /(\*\*([^*]+)\*\*)|(`([^`]+)`)|(\[([^\]]+)\]\(([^)]+)\))/
  while (rest) {
    const m = re.exec(rest)
    if (!m) {
      out.push(rest)
      break
    }
    if (m.index > 0) out.push(rest.slice(0, m.index))
    if (m[1]) {
      // bold
      out.push(
        <strong key={`${keyPrefix}-b-${k}`} className="font-semibold">
          {m[2]}
        </strong>
      )
    } else if (m[3]) {
      // inline code
      out.push(
        <code
          key={`${keyPrefix}-c-${k}`}
          className="break-all rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]"
        >
          {m[4]}
        </code>
      )
    } else if (m[5]) {
      // link
      out.push(
        <a
          key={`${keyPrefix}-a-${k}`}
          href={m[7]}
          target="_blank"
          rel="noopener noreferrer"
          className="break-all text-primary underline decoration-primary/40 underline-offset-2 hover:decoration-primary"
        >
          {m[6]}
        </a>
      )
    }
    rest = rest.slice(m.index + m[0].length)
    k++
  }
  return out
}

const HEADING_CLASS: Record<string, string> = {
  h1: 'mt-1 mb-2 text-xl font-semibold tracking-tight',
  h2: 'mt-5 mb-2 text-lg font-semibold tracking-tight',
  h3: 'mt-4 mb-1.5 text-base font-medium',
  h4: 'mt-3 mb-1 text-sm font-medium',
  h5: 'mt-3 mb-1 text-sm font-medium',
  h6: 'mt-3 mb-1 text-xs font-medium uppercase text-muted-foreground',
}

function renderNode(node: MdNode, idx: number): React.ReactNode {
  const key = `md-${idx}`
  switch (node.type) {
    case 'h1':
    case 'h2':
    case 'h3':
    case 'h4':
    case 'h5':
    case 'h6':
      return (
        <h2 key={key} className={HEADING_CLASS[node.type]} id={`${node.type}-${idx}`}>
          {node.text && renderInline(node.text, key)}
        </h2>
      )
    case 'p':
      return (
        <p key={key} className="mb-3 text-sm leading-6 text-foreground/90">
          {node.text && renderInline(node.text, key)}
        </p>
      )
    case 'ul':
      return (
        <ul key={key} className="mb-3 list-disc space-y-1 pl-5 text-sm leading-6">
          {node.items?.map((item, i) => (
            <li key={`${key}-li-${i}`}>{renderInline(item, `${key}-li-${i}`)}</li>
          ))}
        </ul>
      )
    case 'ol':
      return (
        <ol key={key} className="mb-3 list-decimal space-y-1 pl-5 text-sm leading-6">
          {node.items?.map((item, i) => (
            <li key={`${key}-li-${i}`}>{renderInline(item, `${key}-li-${i}`)}</li>
          ))}
        </ol>
      )
    case 'blockquote':
      return (
        <blockquote
          key={key}
          className="mb-3 border-l-2 border-primary/40 bg-muted/30 px-3 py-2 text-sm text-muted-foreground"
        >
          {node.items?.map((item, i) => (
            <p key={`${key}-q-${i}`} className="leading-6">
              {renderInline(item, `${key}-q-${i}`)}
            </p>
          ))}
        </blockquote>
      )
    case 'hr':
      return <hr key={key} className="my-4 border-border" />
    case 'code':
      return (
        <pre
          key={key}
          className="mb-3 overflow-x-auto rounded-md border border-border bg-muted/40 p-3 text-xs"
        >
          <code className="font-mono">{node.text}</code>
        </pre>
      )
    case 'table': {
      const rows = node.rows ?? []
      const align = node.align ?? []
      const alignClass = (i: number) =>
        align[i] === 'center' ? 'text-center' : align[i] === 'right' ? 'text-right' : 'text-left'
      return (
        <div key={key} className="mb-3 overflow-x-auto">
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="border-b border-border bg-muted/30">
                {rows[0]?.map((c, i) => (
                  <th key={i} className={cn('px-2 py-1.5 font-medium', alignClass(i))}>
                    {renderInline(c, `${key}-th-${i}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(1).map((row, r) => (
                <tr key={r} className="border-b border-border/50 last:border-0">
                  {row.map((c, i) => (
                    <td key={i} className={cn('px-2 py-1.5 align-top', alignClass(i))}>
                      {renderInline(c, `${key}-td-${r}-${i}`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
    }
    default:
      return null
  }
}

export function MarkdownRenderer({ content, className }: { content: string; className?: string }) {
  const nodes = React.useMemo(() => parse(content), [content])
  return (
    <div className={cn('prose-sm max-w-none break-words text-foreground', className)}>
      {nodes.map((node, idx) => renderNode(node, idx))}
    </div>
  )
}
