import assert from 'node:assert/strict'
import test from 'node:test'

import { formatDateZh } from './utils.ts'

test('formatDateZh formats a valid ISO date into zh-CN YYYY/MM/DD', () => {
  // In zh-CN the toLocaleDateString yields "YYYY/MM/DD".
  // We assert it looks like a slash-separated date with the right year/month/day.
  const formatted = formatDateZh('2026-07-08T03:00:00Z')
  assert.match(formatted, /^2026\/\d{2}\/\d{2}$/)
})

test('formatDateZh returns "—" for undefined or empty input', () => {
  assert.equal(formatDateZh(undefined), '—')
  assert.equal(formatDateZh(''), '—')
})

test('formatDateZh returns "—" for an invalid date string', () => {
  assert.equal(formatDateZh('not-a-date'), '—')
})
