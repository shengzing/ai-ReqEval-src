import assert from 'node:assert/strict'
import test from 'node:test'

import type { Conversation, Stage } from './types'
import { buildEnrichedStage, getStageStatusFromRun, resolveActiveConversation } from './workspace-state.ts'

// ---------------------------------------------------------------------------
// resolveActiveConversation — project / stage / conversation switching
// ---------------------------------------------------------------------------

test('resolveActiveConversation returns undefined when no conversation selected and no activeConversationId', () => {
  const stageConversations: Conversation[] = [
    { id: 'c1', title: '会话一', timeAgo: '1 分钟前', messages: [] },
    { id: 'c2', title: '会话二', timeAgo: '5 分钟前', messages: [] },
  ]
  assert.equal(
    resolveActiveConversation({ stageConversations }),
    undefined
  )
})

test('resolveActiveConversation returns currentConversation (live stream) even when activeConversationId differs', () => {
  const liveConversation: Conversation = { id: 'c-live', title: '运行中', timeAgo: '刚刚', messages: [] }
  const stageConversations: Conversation[] = [
    { id: 'c1', title: '会话一', timeAgo: '1 分钟前', messages: [] },
  ]
  // currentConversation (from streaming) takes precedence
  const result = resolveActiveConversation({
    currentConversation: liveConversation,
    stageConversations,
    activeConversationId: 'c1',
  })
  assert.equal(result?.id, 'c-live')
})

test('resolveActiveConversation falls back to stageConversations lookup when no currentConversation', () => {
  const stageConversations: Conversation[] = [
    { id: 'c-old', title: '旧会话', timeAgo: '2 天前', messages: [] },
    { id: 'c-latest', title: '最新会话', timeAgo: '刚刚', messages: [] },
  ]
  const result = resolveActiveConversation({
    stageConversations,
    activeConversationId: 'c-latest',
  })
  assert.equal(result?.id, 'c-latest')
  assert.equal(result?.title, '最新会话')
})

test('resolveActiveConversation returns undefined when activeConversationId does not match any stage conversation', () => {
  const stageConversations: Conversation[] = [
    { id: 'c1', title: '会话一', timeAgo: '1 分钟前', messages: [] },
  ]
  const result = resolveActiveConversation({
    stageConversations,
    activeConversationId: 'c-nonexistent',
  })
  assert.equal(result, undefined)
})

test('resolveActiveConversation returns undefined when stageConversations is empty (fresh stage)', () => {
  const result = resolveActiveConversation({
    stageConversations: [],
    activeConversationId: 'c-any',
  })
  assert.equal(result, undefined)
})

// ---------------------------------------------------------------------------
// Switching boundaries — project/stage/conversation clearance
// ---------------------------------------------------------------------------
// These test the pure-function contracts that the React layer depends on:
//   - Switching project → activeConversationId becomes undefined → resolved is undefined
//   - Switching stage   → activeConversationId becomes undefined → resolved is undefined
//   - Selecting a new conversation → resolveActiveConversation returns the chosen one

test('switching project clears resolved conversation (activeConversationId set to undefined)', () => {
  // Simulate: user was on project-A, stage-S1, conversation C1.
  // Switches to project-B → activeConversationId = undefined
  const stageConversations: Conversation[] = [
    { id: 'c1', title: '会话一', timeAgo: '1 分钟前', messages: [] },
  ]
  // Before switch: conversation resolved
  assert.equal(
    resolveActiveConversation({ stageConversations, activeConversationId: 'c1' })?.id,
    'c1'
  )
  // After switch: conversation cleared
  assert.equal(
    resolveActiveConversation({ stageConversations, activeConversationId: undefined }),
    undefined
  )
})

test('switching stage clears resolved conversation (activeConversationId set to undefined)', () => {
  // Same as project switch but within same project
  const stage1Conversations: Conversation[] = [
    { id: 'c1', title: '阶段一会话', timeAgo: '1 分钟前', messages: [] },
  ]
  const stage2Conversations: Conversation[] = [
    { id: 'c2', title: '阶段二会话', timeAgo: '刚刚', messages: [] },
  ]
  // On stage 1, conversation c1 selected
  assert.equal(
    resolveActiveConversation({ stageConversations: stage1Conversations, activeConversationId: 'c1' })?.id,
    'c1'
  )
  // Switch to stage 2 — conversation reset
  assert.equal(
    resolveActiveConversation({ stageConversations: stage2Conversations, activeConversationId: undefined }),
    undefined
  )
})

test('post-Run auto-selects conversation returned by startTask', () => {
  // After startTask returns { conversationId: 'c-new' }, the UI should
  // resolve to that conversation. Since currentConversation from SSE
  // takes precedence, verify both paths:
  const newConversation: Conversation = { id: 'c-new', title: '新运行会话', timeAgo: '刚刚', messages: [] }
  const stageConversations: Conversation[] = [
    { id: 'c-old', title: '旧会话', timeAgo: '1 小时前', messages: [] },
    newConversation,
  ]
  // Path A: live stream populates currentConversation
  assert.equal(
    resolveActiveConversation({
      currentConversation: newConversation,
      stageConversations,
      activeConversationId: 'c-new',
    })?.id,
    'c-new'
  )
  // Path B: no live stream, just activeConversationId lookup
  assert.equal(
    resolveActiveConversation({
      stageConversations,
      activeConversationId: 'c-new',
    })?.id,
    'c-new'
  )
})

test('archived conversation is excluded from resolve when filtered out of stageConversations', () => {
  const stageConversations: Conversation[] = [
    { id: 'c1', title: '活跃会话', timeAgo: '1 分钟前', status: 'completed', messages: [] },
    // c-archived is not included because list_conversations filters deleted
  ]
  // Trying to resolve an archived conversation that is no longer in the tree
  assert.equal(
    resolveActiveConversation({ stageConversations, activeConversationId: 'c-archived' }),
    undefined
  )
  // Active conversation resolves fine
  assert.equal(
    resolveActiveConversation({ stageConversations, activeConversationId: 'c1' })?.id,
    'c1'
  )
})
