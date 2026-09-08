const visibleKinds = new Set(['plan', 'tool_call', 'tool_start', 'tool_result', 'summary', 'decision', 'status', 'progress', 'retry', 'lane_complete', 'error', 'complete', 'cancelled'])
const requestPattern = /^正在请求模型，第\s*(\d+)\s*次[。.]?$/u
const outputPattern = /^已收到\s*(\d+)\s*个输出字符[。.]?$/u
const requestBoundaries = new Set(['tool_call', 'tool_start', 'tool_result', 'decision', 'retry', 'lane_complete', 'error', 'complete', 'cancelled'])

// Keep the raw event history untouched. Only collapse transport progress in the
// display projection; interleaved lanes and subsequent model requests stay distinct.
export function projectAgentEvents(events, reviewState = 'running') {
  const rows = []
  const requests = new Map()

  for (const event of events) {
    if (!visibleKinds.has(event.kind)) continue
    const lane = event.lane || ''
    const output = event.kind === 'progress'
      && (Number.isFinite(event.output_chars) || outputPattern.test(event.message || ''))
    const request = event.kind === 'progress' && !output
      && (Number.isFinite(event.model_call) || requestPattern.test(event.message || ''))

    if (request) {
      if (requests.has(lane)) requests.get(lane).active = false
      const row = { ...event, kind: 'model_request', active: true }
      rows.push(row)
      requests.set(lane, row)
      continue
    }
    if (output) {
      let row = requests.get(lane)
      if (!row || !row.active) {
        row = { ...event, kind: 'model_request', message: '模型请求：接收输出', active: true }
        rows.push(row)
        requests.set(lane, row)
      }
      row.outputMessage = event.message
      row.outputElapsedMs = event.elapsed_ms
      continue
    }

    if (requestBoundaries.has(event.kind)) {
      if (!lane && ['error', 'complete', 'cancelled'].includes(event.kind)) {
        for (const row of requests.values()) row.active = false
      } else if (requests.has(lane)) requests.get(lane).active = false
    }
    rows.push({ ...event })
  }
  if (reviewState !== 'running') {
    for (const row of requests.values()) row.active = false
  }
  return rows
}
