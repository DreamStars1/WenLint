import assert from 'node:assert/strict'
import test from 'node:test'
import { projectAgentEvents } from '../src/agent-events.js'

const request = (sequence, lane, call = 1) => ({ sequence, lane, kind: 'progress', message: `正在请求模型，第 ${call} 次。`, elapsed_ms: sequence * 100 })
const output = (sequence, lane, count) => ({ sequence, lane, kind: 'progress', message: `已收到 ${count} 个输出字符。`, elapsed_ms: sequence * 100 })

test('hundreds of character updates become one stable request step without changing history', () => {
  const history = [request(1, 'semantic'), ...Array.from({ length: 323 }, (_, index) => output(index + 2, 'semantic', (index + 1) * 10))]
  const before = structuredClone(history)
  const rows = projectAgentEvents(history)
  assert.equal(rows.length, 1)
  assert.equal(rows[0].sequence, 1)
  assert.equal(rows[0].outputMessage, '已收到 3230 个输出字符。')
  assert.equal(rows[0].active, true)
  assert.deepEqual(history, before)
})

test('interleaved lanes update their own requests and preserve every tool detail and decision', () => {
  const tool = { sequence: 6, lane: 'semantic', kind: 'tool_start', tool: 'workspace_read', args: { path: 'facts.md' }, message: '读取参考资料' }
  const result = { sequence: 7, lane: 'semantic', kind: 'tool_result', result: { content: '事实依据' }, message: '工具完成' }
  const decision = { sequence: 10, lane: 'static', kind: 'decision', message: '保留原文' }
  const rows = projectAgentEvents([
    { sequence: 1, kind: 'plan', message: '开始检查' }, request(2, 'semantic'), request(3, 'static'),
    output(4, 'semantic', 80), output(5, 'static', 40), tool, result,
    request(8, 'semantic', 2), output(9, 'semantic', 12), decision,
  ])
  assert.equal(rows.length, 7)
  assert.equal(rows[1].outputMessage, '已收到 80 个输出字符。')
  assert.equal(rows[1].active, false)
  assert.equal(rows[2].outputMessage, '已收到 40 个输出字符。')
  assert.equal(rows[2].active, false)
  assert.deepEqual(rows[3], tool)
  assert.deepEqual(rows[4], result)
  assert.equal(rows[5].message, '正在请求模型，第 2 次。')
  assert.equal(rows[5].outputMessage, '已收到 12 个输出字符。')
  assert.equal(rows[5].active, true)
  assert.deepEqual(rows[6], decision)
})

test('terminal review states stop activity without hiding the last output or failure', () => {
  const history = [request(1, 'semantic'), output(2, 'semantic', 100)]
  for (const state of ['complete', 'error', 'cancelled']) {
    const rows = projectAgentEvents(history, state)
    assert.equal(rows[0].active, false)
    assert.equal(rows[0].outputMessage, '已收到 100 个输出字符。')
  }
  const error = { sequence: 3, kind: 'error', message: '模型超时' }
  const rows = projectAgentEvents([...history, error])
  assert.equal(rows[0].active, false)
  assert.deepEqual(rows[1], error)
})

test('unknown progress remains visible and private reasoning is not projected', () => {
  const progress = { sequence: 2, kind: 'progress', lane: 'semantic', message: '正在核对引用' }
  const rows = projectAgentEvents([
    request(1, 'semantic'), progress,
    { sequence: 3, kind: 'reasoning_delta', message: 'private' }, output(4, 'semantic', 20),
  ])
  assert.equal(rows.length, 2)
  assert.deepEqual(rows[1], progress)
})

test('structured counters and a missing start event still produce one row per request', () => {
  const rows = projectAgentEvents([
    { sequence: 1, kind: 'progress', lane: 'semantic', output_chars: 10, message: '10 characters' },
    { sequence: 2, kind: 'progress', lane: 'semantic', output_chars: 20, message: '20 characters' },
    { sequence: 3, kind: 'progress', lane: 'semantic', model_call: 2, message: 'Request 2' },
    { sequence: 4, kind: 'progress', lane: 'semantic', output_chars: 3, message: '3 characters' },
  ])
  assert.equal(rows.length, 2)
  assert.equal(rows[0].outputMessage, '20 characters')
  assert.equal(rows[0].active, false)
  assert.equal(rows[1].outputMessage, '3 characters')
})

test('format repair is visible and separates the original request from the retry', () => {
  const retry = { sequence: 3, kind: 'retry', lane: 'semantic', message: '返回格式无效，正在修复一次。' }
  const history = [request(1, 'semantic'), output(2, 'semantic', 100), retry]
  const duringRetry = projectAgentEvents(history)
  assert.equal(duringRetry[0].active, false)
  assert.deepEqual(duringRetry[1], retry)

  const rows = projectAgentEvents([...history,
    { sequence: 4, kind: 'progress', lane: 'semantic', model_call: 2, message: '正在请求模型，第 2 次（格式修复）。' },
    { sequence: 5, kind: 'progress', lane: 'semantic', output_chars: 8, message: '已收到 8 个输出字符。' },
    { sequence: 6, kind: 'progress', lane: 'semantic', output_chars: 20, message: '已收到 20 个输出字符。' },
  ])
  assert.equal(rows.length, 3)
  assert.equal(rows[0].outputMessage, '已收到 100 个输出字符。')
  assert.equal(rows[2].message, '正在请求模型，第 2 次（格式修复）。')
  assert.equal(rows[2].outputMessage, '已收到 20 个输出字符。')
  assert.equal(rows[2].active, true)
})

test('segment progress remains visible and closes model activity at coordinator boundaries', () => {
  const start = { sequence: 1, kind: 'segment_start', lane: 'coordinator', message: '检查第 1/3 段', segment: 1, total_segments: 3 }
  const completed = { sequence: 4, kind: 'segment_complete', lane: 'coordinator', message: '第 1 段完成' }
  const rows = projectAgentEvents([start, request(2, 'semantic'), output(3, 'semantic', 20), completed])
  assert.deepEqual(rows[0], start)
  assert.equal(rows[1].active, false)
  assert.deepEqual(rows[2], completed)
})

test('continuous previews replace their own request summary without growing the visible timeline', () => {
  const history = [request(1, 'semantic'), request(2, 'static')]
  for (let index = 0; index < 120; index++) {
    history.push({ sequence: history.length + 1, kind: 'preview', lane: 'semantic', message: `需要补充上线日期，已核对 ${index + 1} 项` })
    history.push({ sequence: history.length + 1, kind: 'preview', lane: 'static', message: `已确认 ${index + 1} 条表达建议` })
  }
  const before = structuredClone(history)
  const rows = projectAgentEvents(history)
  assert.equal(rows.length, 2)
  assert.equal(rows[0].preview, '需要补充上线日期，已核对 120 项')
  assert.equal(rows[1].preview, '已确认 120 条表达建议')
  assert.equal(rows[0].active, true)
  assert.deepEqual(history, before)
  const completed = projectAgentEvents(history, 'complete')
  assert.equal(completed[0].preview, rows[0].preview)
  assert.equal(completed[0].active, false)
})

test('a repair or follow-up request never inherits an earlier request preview', () => {
  const rows = projectAgentEvents([
    request(1, 'semantic'),
    { sequence: 2, kind: 'preview', lane: 'semantic', message: '未校验的旧摘要' },
    { sequence: 3, kind: 'retry', lane: 'semantic', message: '修复格式' },
    { sequence: 4, kind: 'preview', lane: 'semantic', message: '已结束请求的迟到内容' },
    request(5, 'semantic', 2),
    output(6, 'semantic', 20),
  ])
  assert.equal(rows.length, 3)
  assert.equal(rows[0].preview, '未校验的旧摘要')
  assert.equal(rows[0].active, false)
  assert.equal(rows[2].preview, undefined)
  assert.equal(rows[2].active, true)
})
