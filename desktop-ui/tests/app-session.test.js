import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { createRenderer, nextTick } from 'vue'
import { compileScript, parse } from 'vue/compiler-sfc'

// Execute the real App setup and bridge functions with an in-memory Vue host.
// No browser, native window, model call or filesystem write is needed.
const source = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
let script = compileScript(parse(source).descriptor, { id: 'session-integration' }).content
script = script.replace("import ChangeDiff from './ChangeDiff.vue'", 'const ChangeDiff = {}')
script = script.replaceAll("from 'vue'", `from '${import.meta.resolve('vue')}'`)
for (const file of ['revision.js', 'agent-events.js', 'review-session.js']) {
  script = script.replaceAll(`from './${file}'`, `from '${new URL(`../src/${file}`, import.meta.url).href}'`)
}
const { default: App } = await import(`data:text/javascript;base64,${Buffer.from(script).toString('base64')}`)

function mountApp(statuses) {
  const requests = []
  const clarifications = []
  const saves = []
  const priorWindow = globalThis.window
  globalThis.window = {
    pywebview: { api: {
      app_info: async () => ({ ok: true, version: 'test', maxTextChars: 200000, segmentThresholdChars: 6000, segmentsPerBatch: 2 }),
      start_agent_review: async (payload) => { requests.push({ ...payload }); return { ok: true, job_id: `job-${requests.length}`, reviewSessionId: 'session-1' } },
      start_clarification: async (payload) => { clarifications.push(JSON.parse(JSON.stringify(payload))); return { ok: true, job_id: `clarification-${clarifications.length}` } },
      agent_review_status: async () => {
        const status = statuses.shift()
        assert.ok(status, 'Unexpected extra bridge poll')
        return typeof status === 'function' ? status() : status
      },
      save_revision: async (payload) => { saves.push({ ...payload }); return { ok: true, path: 'document.revised.md' } },
    } },
    setInterval: () => 0,
    clearInterval: () => {},
    setTimeout: (fn) => { queueMicrotask(fn); return 0 },
    addEventListener: () => {},
    removeEventListener: () => {},
  }
  let state
  const renderer = createRenderer({ createComment: () => ({}), insert: () => {}, remove: () => {}, parentNode: () => null, nextSibling: () => null })
  const app = renderer.createApp({ setup(props, context) { state = App.setup(props, context); return () => null } })
  app.mount({})
  return { state, requests, clarifications, saves, close() { app.unmount(); globalThis.window = priorWindow } }
}

const first = { id: 'first', action: 'REWRITE', before: '重复', after: '前文', source_start: 1, reason: '前句建议' }
const later = { id: 'later', action: 'REWRITE', before: '重复', after: '后文', source_start: 5, reason: '后句建议' }
const result = (status, decisions) => ({ ok: true, state: 'complete', events: [{ sequence: 1, kind: 'plan', message: '本轮开始', elapsed_ms: 0 }], result: {
  ok: true, reviewStatus: status, reviewSessionId: 'session-1', decisions, summary: '测试建议', modelCalls: 1,
  coverage: { status: status === 'partial' ? 'partial' : 'complete', completed_segments: status === 'partial' ? 1 : 2, total_segments: 2, reviewed_chars: status === 'partial' ? 5 : 8, total_chars: 8 },
  canContinue: status === 'partial',
} })

test('real Vue flow preserves approval across partial → cancelled → resumed cumulative results', async () => {
  const harness = mountApp([result('partial', [first]), { ok: true, state: 'cancelled', events: [] }, result('completed', [later, first])])
  try {
    await nextTick()
    const { state, requests } = harness
    state.sourceText.value = '😀重复。\n重复。'
    await state.runSemanticReview(false)
    assert.equal(state.reviewState.value, 'partial')
    assert.equal(state.canResume.value, true)
    state.decideChange(state.rewriteChanges.value[0], 'accepted')
    assert.equal(state.revisedText.value, '😀前文。\n重复。')
    await state.continueReview()
    assert.equal(state.reviewState.value, 'cancelled')
    assert.equal(state.canResume.value, true)
    assert.equal(state.changeChoices.value.first, 'accepted')
    await state.continueReview()
    assert.equal(state.reviewState.value, 'complete')
    assert.equal(state.changeChoices.value.first, 'accepted')
    assert.equal(state.changeChoices.value.later, undefined)
    assert.equal(state.revisedText.value, '😀前文。\n重复。')
    assert.equal(state.sourceText.value, '😀重复。\n重复。')
    assert.equal(requests[0].reviewSessionId, undefined)
    assert.equal(requests[1].reviewSessionId, 'session-1')
    assert.equal(requests[2].reviewSessionId, 'session-1')
    assert.equal(new Set(state.agentEvents.value.map(event => event.sequence)).size, state.agentEvents.value.length)
  } finally { harness.close() }
})

test('real Vue continuation refuses changed model or document before invoking the bridge', async () => {
  const harness = mountApp([result('partial', [first])])
  try {
    await nextTick()
    const { state, requests } = harness
    state.sourceText.value = '😀重复。\n重复。'
    await state.runSemanticReview(false)
    state.config.model = 'different-model'
    assert.equal(state.canResume.value, false)
    await state.continueReview()
    assert.equal(requests.length, 1)
    state.config.model = 'deepseek-v4-flash'
    state.sourceText.value += '新正文'
    assert.equal(state.canResume.value, false)
    await state.continueReview()
    assert.equal(requests.length, 1)
  } finally { harness.close() }
})

const draft = '重复。下月上线。'
const acceptedEdit = { id: 'accepted', action: 'REWRITE', rule: 'C001', before: '重复', after: '简洁', source_start: 0, reason: '减少冗余' }
const question = { id: 'ask-date', action: 'ASK', rule: 'C002', before: '下月', after: '', source_start: 3, reason: '具体是哪一天上线？' }
const clarified = { ...question, action: 'REWRITE', after: '9月15日', reason: '使用作者补充的日期' }
const clarificationResult = (decision = clarified) => ({ ok: true, state: 'complete', events: [], result: { ok: true, decision, modelCalls: 1 } })

test('offline example cannot send an ASK answer while claiming no model calls', async () => {
  const harness = mountApp([result('completed', [question])])
  try {
    await nextTick()
    const { state } = harness
    state.sourceText.value = draft
    await state.runSemanticReview(false)
    state.config.apiKey = 'test-key'
    state.demoMode.value = true
    state.selectedDecisionIndex.value = 0
    state.clarificationDrafts.value[question.id] = '9月15日'
    await state.submitClarification()
    assert.equal(harness.clarifications.length, 0)
    assert.equal(state.clarificationDrafts.value[question.id], '9月15日')
  } finally { harness.close() }
})

test('default DeepSeek configuration survives connection failure and a successful retry', async () => {
  const harness = mountApp([
    { ok: true, state: 'error', events: [], error: '模型连接超时，请检查代理设置后重试' },
    result('completed', [acceptedEdit, question]),
  ])
  try {
    await nextTick()
    const { state, requests } = harness
    assert.equal(state.config.baseUrl, 'https://api.deepseek.com')
    assert.equal(state.config.model, 'deepseek-v4-flash')
    state.sourceText.value = draft
    await state.runSemanticReview(false)
    assert.equal(state.reviewState.value, 'error')
    assert.match(state.reviewError.value, /代理/)
    assert.equal(state.busy.value, '')
    assert.equal(state.sourceText.value, draft)
    await state.runSemanticReview(false)
    assert.equal(state.reviewState.value, 'complete')
    assert.equal(state.reviewError.value, '')
    assert.equal(requests.length, 2)
    assert.equal(requests[1].model, 'deepseek-v4-flash')
  } finally { harness.close() }
})

test('ASK failure preserves answer and approvals; retry produces a pending diff whose approval and export are explicit', async () => {
  const harness = mountApp([
    result('completed', [acceptedEdit, question]),
    { ok: true, state: 'error', events: [], error: '模型暂时无法连接' },
    clarificationResult(),
  ])
  try {
    await nextTick()
    const { state, clarifications, saves } = harness
    state.config.apiKey = 'offline-test-placeholder'
    state.sourceText.value = draft
    state.filename.value = '计划.md'
    await state.runSemanticReview(false)
    state.decideChange(state.rewriteChanges.value[0], 'accepted')
    state.selectedDecisionIndex.value = 1
    state.clarificationDrafts.value[question.id] = '  确定于9月15日上线。  '
    await state.submitClarification()
    assert.equal(state.clarificationError.value, '模型暂时无法连接')
    assert.equal(state.clarificationDrafts.value[question.id], '  确定于9月15日上线。  ')
    assert.equal(state.selectedDecision.value.action, 'ASK')
    assert.equal(state.changeChoices.value.accepted, 'accepted')
    assert.equal(state.revisedText.value, '简洁。下月上线。')
    await state.submitClarification()
    assert.equal(clarifications.length, 2)
    assert.equal(clarifications[1].answer, '确定于9月15日上线。')
    assert.equal(clarifications[1].text, draft)
    assert.equal(clarifications[1].decision.id, question.id)
    assert.equal(state.clarificationError.value, '')
    assert.equal(state.activeTab.value, 'revision')
    assert.equal(state.revisionMode.value, 'full')
    assert.equal(state.selectedChange.value.id, question.id)
    assert.equal(state.changeChoices.value[question.id], undefined)
    assert.equal(state.changeChoices.value.accepted, 'accepted')
    assert.equal(state.revisedText.value, '简洁。下月上线。')
    assert.equal(state.sourceText.value, draft)
    assert.equal(saves.length, 0)
    await state.saveRevisionAs()
    assert.deepEqual(saves.pop(), { text: '简洁。下月上线。', suggestedName: '计划.revised.md' })
    state.decideChange(state.selectedChange.value, 'accepted')
    assert.equal(state.revisedText.value, '简洁。9月15日上线。')
    state.decideChange(state.selectedChange.value, null)
    assert.equal(state.revisedText.value, '简洁。下月上线。')
    state.decideChange(state.selectedChange.value, 'accepted')
    await state.saveRevisionAs()
    assert.deepEqual(saves.pop(), { text: '简洁。9月15日上线。', suggestedName: '计划.revised.md' })
    assert.equal(state.sourceText.value, draft)
  } finally { harness.close() }
})

test('ASK refuses incomplete long-document review and stale source without calling the model bridge', async () => {
  const harness = mountApp([result('partial', [question])])
  try {
    await nextTick()
    const { state, clarifications } = harness
    state.sourceText.value = draft
    state.config.apiKey = 'offline-test-placeholder'
    await state.runSemanticReview(false)
    state.clarificationDrafts.value[question.id] = '9月15日'
    await state.submitClarification()
    assert.equal(clarifications.length, 0)
    state.canContinue.value = false
    state.sourceText.value += '修改正文'
    await state.submitClarification()
    assert.equal(clarifications.length, 0)
    assert.equal(state.clarificationDrafts.value[question.id], '9月15日')
  } finally { harness.close() }
})

test('ASK rejects a whole-line proposal overlapping an accepted edit and preserves all prior author decisions', async () => {
  const wholeLine = { ...clarified, before: draft, after: '重复。9月15日上线。', source_start: 0 }
  const harness = mountApp([
    result('completed', [acceptedEdit, question]),
    clarificationResult(wholeLine),
  ])
  try {
    await nextTick()
    const { state } = harness
    state.config.apiKey = 'offline-test-placeholder'
    state.sourceText.value = draft
    await state.runSemanticReview(false)
    state.decideChange(state.rewriteChanges.value[0], 'accepted')
    state.selectedDecisionIndex.value = 1
    state.activeTab.value = 'decisions'
    state.clarificationDrafts.value[question.id] = '确定于9月15日上线。'
    const originalDecisions = JSON.parse(JSON.stringify(state.decisions.value))
    const originalChoices = { ...state.changeChoices.value }
    await state.submitClarification()
    assert.match(state.clarificationError.value, /与已采纳的建议重叠/)
    assert.deepEqual(JSON.parse(JSON.stringify(state.decisions.value)), originalDecisions)
    assert.deepEqual({ ...state.changeChoices.value }, originalChoices)
    assert.equal(state.selectedDecision.value.action, 'ASK')
    assert.equal(state.selectedDecision.value.id, question.id)
    assert.equal(state.clarificationDrafts.value[question.id], '确定于9月15日上线。')
    assert.equal(state.revisedText.value, '简洁。下月上线。')
    assert.equal(state.sourceText.value, draft)
    assert.equal(state.activeTab.value, 'decisions')
    assert.equal(state.busy.value, '')
    assert.equal(state.reviewState.value, 'complete')
    assert.equal(harness.clarifications.length, 1)
    assert.equal(harness.saves.length, 0)
  } finally { harness.close() }
})

test('ASK discards a returned proposal when the document changed while waiting', async () => {
  let state
  const harness = mountApp([
    result('completed', [acceptedEdit, question]),
    () => { state.sourceText.value += '新内容'; return clarificationResult() },
  ])
  try {
    await nextTick()
    state = harness.state
    state.config.apiKey = 'offline-test-placeholder'
    state.sourceText.value = draft
    await state.runSemanticReview(false)
    state.decideChange(state.rewriteChanges.value[0], 'accepted')
    state.selectedDecisionIndex.value = 1
    state.clarificationDrafts.value[question.id] = '9月15日'
    await state.submitClarification()
    assert.match(state.clarificationError.value, /正文或场景已变化/)
    assert.equal(state.selectedDecision.value.action, 'ASK')
    assert.equal(state.changeChoices.value.accepted, 'accepted')
    assert.equal(state.clarificationDrafts.value[question.id], '9月15日')
    await state.saveRevisionAs()
    assert.equal(harness.saves.length, 0)
  } finally { harness.close() }
})

test('ASK cancellation keeps the draft; a follow-up question shows prior answer and accepts a separate new answer', async () => {
  const followupQuestion = { ...question, reason: '9月15日是哪一年？' }
  const harness = mountApp([
    result('completed', [question]),
    { ok: true, state: 'cancelled', events: [] },
    clarificationResult(followupQuestion),
    clarificationResult(),
  ])
  try {
    await nextTick()
    const { state } = harness
    state.config.apiKey = 'offline-test-placeholder'
    state.sourceText.value = draft
    await state.runSemanticReview(false)
    state.clarificationDrafts.value[question.id] = '9月15日'
    await state.submitClarification()
    assert.equal(state.clarificationDrafts.value[question.id], '9月15日')
    assert.equal(state.selectedDecision.value.action, 'ASK')
    assert.equal(state.busy.value, '')
    await state.submitClarification()
    assert.equal(state.selectedDecision.value.reason, '9月15日是哪一年？')
    assert.equal(state.selectedDecision.value.author_information, '9月15日')
    assert.equal(state.clarificationDrafts.value[question.id], '')
    assert.equal(state.activeTab.value, 'decisions')
    state.clarificationDrafts.value[question.id] = '2026年'
    await state.submitClarification()
    assert.equal(harness.clarifications[2].decision.author_information, '9月15日')
    assert.equal(harness.clarifications[2].answer, '2026年')
    assert.equal(state.changeChoices.value[question.id], undefined)
  } finally { harness.close() }
})
