/**
 * Highlights matching substrings in text for search results.
 * Returns an array of React nodes with matched portions wrapped in mark spans.
 */
export function highlightMatch(text: string, query?: string): React.ReactNode {
  if (!query || !query.trim()) return text

  const lowerText = text.toLowerCase()
  const lowerQuery = query.toLowerCase()
  const index = lowerText.indexOf(lowerQuery)

  if (index === -1) return text

  const before = text.slice(0, index)
  const match = text.slice(index, index + query.length)
  const after = text.slice(index + query.length)

  return (
    <>
      {before}
      <mark className="bg-primary/20 rounded px-0.5 text-inherit">{match}</mark>
      {after}
    </>
  )
}
