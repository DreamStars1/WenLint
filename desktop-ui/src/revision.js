export function buildRevision(source, changes, undoneIds) {
  const replacements = orderChanges(source, changes)
    .filter((item) => !undoneIds.has(item.id))
    .map((item) => {
      const start = locateChange(source, item)
      return { start, end: start + item.before.length, after: item.after }
    })
    .sort((left, right) => right.start - left.start)

  for (let index = 0; index < replacements.length - 1; index += 1) {
    if (replacements[index + 1].end > replacements[index].start) {
      throw new Error('修改范围发生重叠')
    }
  }

  return replacements.reduce(
    (text, item) => text.slice(0, item.start) + item.after + text.slice(item.end),
    source,
  )
}

// No proposal changes the document until the user explicitly accepts it.
export function buildApprovedRevision(source, changes, choices = {}) {
  return buildRevision(source, changes.filter((item) => choices[item.id] === 'accepted'), new Set())
}

export function orderChanges(source, changes) {
  return changes
    .map((item) => ({ item, start: locateChange(source, item) }))
    .sort((left, right) => left.start - right.start)
    .map(({ item }) => item)
}

export function locateChange(source, change) {
  if (change.source_start !== undefined && change.source_start !== null) {
    const points = Array.from(source)
    if (!Number.isInteger(change.source_start) || change.source_start < 0 || change.source_start > points.length) throw new Error('修改位置无效')
    const start = points.slice(0, change.source_start).join('').length
    if (source.slice(start, start + change.before.length) !== change.before) throw new Error('修改位置与原文不匹配')
    return start
  }
  const start = source.indexOf(change.before)
  if (start < 0 || start !== source.lastIndexOf(change.before)) throw new Error('修改位置无法在原文中唯一定位')
  return start
}

export function changeContext(source, before, radius = 70, sourceStart) {
  const start = sourceStart === undefined || sourceStart === null ? source.indexOf(before) : locateChange(source, { before, source_start: sourceStart })
  if (start < 0) return { before: '', focus: before, after: '' }
  const end = start + before.length
  const preceding = source.slice(0, start)
  const following = source.slice(end)
  const lead = graphemes(preceding)
  const trail = graphemes(following)
  return {
    before: lead.slice(-radius).join(''),
    focus: source.slice(start, end),
    after: trail.slice(0, radius).join(''),
    line: preceding.split('\n').length,
    column: graphemes(preceding.slice(preceding.lastIndexOf('\n') + 1)).length + 1,
    endLine: source.slice(0, end).split('\n').length,
    clippedBefore: lead.length > radius,
    clippedAfter: trail.length > radius,
  }
}

const segmenter = typeof Intl.Segmenter === 'function' ? new Intl.Segmenter('zh', { granularity: 'grapheme' }) : null
function graphemes(text) {
  return segmenter ? Array.from(segmenter.segment(text), (item) => item.segment) : Array.from(text)
}

// Myers diff preserves unchanged words between multiple edits. Bound work for
// wholesale rewrites; even the fallback retains common prefix/suffix and is exact.
export function diffText(before, after) {
  return diffTokens(graphemes(before), graphemes(after))
}

function diffTokens(left, right) {
  let prefix = 0
  while (prefix < left.length && prefix < right.length && left[prefix] === right[prefix]) prefix += 1
  let suffix = 0
  while (suffix < left.length - prefix && suffix < right.length - prefix && left[left.length - suffix - 1] === right[right.length - suffix - 1]) suffix += 1
  const a = left.slice(prefix, left.length - suffix)
  const b = right.slice(prefix, right.length - suffix)
  const raw = [{ kind: 'equal', text: left.slice(0, prefix).join('') }]
  const trace = []
  const frontier = new Map([[1, 0]])
  let edits = null
  let work = 0
  search: for (let distance = 0; distance <= Math.min(a.length + b.length, 256); distance += 1) {
    trace.push(new Map(frontier))
    for (let diagonal = -distance; diagonal <= distance; diagonal += 2) {
      if (++work > 1_000_000) break search
      let x = diagonal === -distance || (diagonal !== distance && (frontier.get(diagonal - 1) ?? -1) < (frontier.get(diagonal + 1) ?? -1))
        ? (frontier.get(diagonal + 1) ?? 0) : (frontier.get(diagonal - 1) ?? 0) + 1
      let y = x - diagonal
      while (x < a.length && y < b.length && a[x] === b[y]) {
        x += 1; y += 1
        if (++work > 1_000_000) break search
      }
      frontier.set(diagonal, x)
      if (x >= a.length && y >= b.length) {
        edits = []
        for (let step = distance; step >= 0; step -= 1) {
          const previous = trace[step]
          const k = x - y
          const previousK = k === -step || (k !== step && (previous.get(k - 1) ?? -1) < (previous.get(k + 1) ?? -1)) ? k + 1 : k - 1
          const previousX = previous.get(previousK) ?? 0
          const previousY = previousX - previousK
          while (x > previousX && y > previousY) {
            edits.push({ kind: 'equal', text: a[--x] }); y -= 1
          }
          if (step === 0) break
          if (x === previousX) edits.push({ kind: 'insert', text: b[--y] })
          else edits.push({ kind: 'delete', text: a[--x] })
        }
        edits.reverse()
        break search
      }
    }
  }
  for (const part of edits || [{ kind: 'delete', text: a.join('') }, { kind: 'insert', text: b.join('') }]) raw.push(part)
  if (suffix) raw.push({ kind: 'equal', text: left.slice(-suffix).join('') })
  return raw.filter((part) => part.text).reduce((parts, part) => {
    const last = parts[parts.length - 1]
    if (last?.kind === part.kind) last.text += part.text
    else parts.push({ ...part })
    return parts
  }, [])
}

function lines(text) {
  return text.match(/[^\n]*\n|[^\n]+$/gu) || []
}

function sideLines(parts, excludedKind) {
  const result = []
  let line = []
  for (const part of parts) {
    if (part.kind === excludedKind) continue
    const pieces = part.text.split('\n')
    for (let index = 0; index < pieces.length; index += 1) {
      if (pieces[index]) line.push({ kind: part.kind, text: pieces[index] })
      if (index < pieces.length - 1) { result.push(line); line = [] }
    }
  }
  if (line.length) result.push(line)
  return result
}

// Unified hunks: unchanged lines appear once; each changed block contains
// deletion rows followed by insertion rows, with word emphasis inside the rows.
export function diffRows(before, after, startLine = 1) {
  const blocks = diffTokens(lines(before), lines(after))
  const rows = []
  let oldLine = startLine
  let newLine = startLine
  for (let index = 0; index < blocks.length; index += 1) {
    const block = blocks[index]
    if (block.kind === 'equal') {
      for (const line of lines(block.text)) rows.push({ kind: 'equal', oldLine: oldLine++, newLine: newLine++, parts: [{ kind: 'equal', text: line.replace(/\n$/u, '') }] })
      continue
    }
    let removed = ''
    let inserted = ''
    while (index < blocks.length && blocks[index].kind !== 'equal') {
      if (blocks[index].kind === 'delete') removed += blocks[index].text
      else inserted += blocks[index].text
      index += 1
    }
    index -= 1
    const detail = diffText(removed, inserted)
    for (const parts of sideLines(detail, 'insert')) rows.push({ kind: 'delete', oldLine: oldLine++, newLine: null, parts })
    for (const parts of sideLines(detail, 'delete')) rows.push({ kind: 'insert', oldLine: null, newLine: newLine++, parts })
  }
  return rows
}

export function resolveSaveTarget(workspacePath, workspaceSha256, standaloneSha256) {
  if (workspacePath) {
    return {
      method: 'workspace_write',
      path: workspacePath,
      expectedSha256: workspaceSha256,
    }
  }
  if (standaloneSha256) return { method: 'save_original' }
  return null
}
