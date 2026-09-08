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
  const priorWindow = globalThis.window
  globalThis.window = {
    pywebview: { api: {
      app_info: async () => ({ ok: true, version: 'test', maxTextChars: 200000, segmentThresholdChars: 6000, segmentsPerBatch: 2 }),
      start_agent_review: async (payload) => { requests.push({ ...payload }); return { ok: true, job_id: `job-${requests.length}`, reviewSessionId: 'session-1' } },
      agent_review_status: async () => statuses.shift(),
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
  return { state, requests, close() { app.unmount(); globalThis.window = priorWindow } }
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
    state.config.model = 'gpt-4.1-mini'
    state.sourceText.value += '新正文'
    assert.equal(state.canResume.value, false)
    await state.continueReview()
    assert.equal(requests.length, 1)
  } finally { harness.close() }
})
