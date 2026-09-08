import assert from 'node:assert/strict'
import test from 'node:test'
import { normalizeDecisions, retainChangeChoices, reviewCompletionState, reviewFingerprint, requiresSegmentedReview } from '../src/review-session.js'
import { buildApprovedRevision } from '../src/revision.js'

test('continuing a session preserves stable accepted/rejected decisions despite reordered cumulative results', () => {
  const first = { id: 'segment-1-a', action: 'REWRITE', before: '甲句', after: '甲文', source_start: 0 }
  const second = { id: 'segment-1-b', action: 'REWRITE', before: '乙句', after: '乙文', source_start: 3 }
  const third = { id: 'segment-2-a', action: 'REWRITE', before: '丙句', after: '丙文', source_start: 6 }
  const next = normalizeDecisions([third, second, first])
  const retained = retainChangeChoices([first, second], next, { 'segment-1-a': 'accepted', 'segment-1-b': 'rejected' })
  assert.deepEqual(retained, { 'segment-1-a': 'accepted', 'segment-1-b': 'rejected' })
  assert.equal(buildApprovedRevision('甲句。乙句。丙句。', next, retained), '甲文。乙句。丙句。')
})

test('changed proposal content, action or position resets its previous approval', () => {
  const original = { id: 'stable', action: 'REWRITE', before: '旧文', after: '新文', source_start: 10 }
  for (const patch of [{ before: '其他原文' }, { after: '其他建议' }, { action: 'VERIFY' }, { source_start: 20 }]) {
    assert.deepEqual(retainChangeChoices([original], [{ ...original, ...patch }], { stable: 'accepted' }), {})
  }
})

test('partial successful responses are neither failures nor a claim of full coverage', () => {
  assert.equal(reviewCompletionState({ ok: true, reviewStatus: 'partial' }), 'partial')
  assert.equal(reviewCompletionState({ ok: true, reviewStatus: 'completed', coverage: { status: 'partial' } }), 'partial')
  assert.equal(reviewCompletionState({ ok: true, reviewStatus: 'completed', coverage: { status: 'complete' } }), 'complete')
})

test('continuation identity changes with document, profile, model, workspace or tool consent', () => {
  const base = { text: '原文', profile: 'general', filename: 'a.md', baseUrl: 'https://example.test', model: 'model-a', workspaceRoot: 'workspace', workspacePath: 'a.md', use_workspace_tools: false }
  for (const patch of [{ text: '改文' }, { profile: 'academic' }, { model: 'model-b' }, { baseUrl: 'https://other.test' }, { workspaceRoot: 'other' }, { workspacePath: 'b.md' }, { use_workspace_tools: true }]) {
    assert.notEqual(reviewFingerprint(base), reviewFingerprint({ ...base, ...patch }))
  }
  assert.equal(reviewFingerprint(base), reviewFingerprint({ ...base, apiKey: 'transient-only' }))
})

test('segment threshold matches Python Unicode code points, including exact boundaries and emoji', () => {
  assert.equal(requiresSegmentedReview('😀'.repeat(6000)), false)
  assert.equal(requiresSegmentedReview('😀'.repeat(6000) + '字'), true)
  assert.equal(requiresSegmentedReview('文字', 2), false)
  assert.equal(requiresSegmentedReview('文字😀', 2), true)
})
