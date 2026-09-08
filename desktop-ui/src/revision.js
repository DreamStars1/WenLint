export function buildRevision(source, changes, undoneIds) {
  const replacements = orderChanges(source, changes)
    .filter((item) => !undoneIds.has(item.id))
    .map((item) => ({
      start: source.indexOf(item.before),
      end: source.indexOf(item.before) + item.before.length,
      after: item.after,
    }))
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
    .map((item) => {
      const start = source.indexOf(item.before)
      if (start < 0 || start !== source.lastIndexOf(item.before)) {
        throw new Error('修改位置无法在原文中唯一定位')
      }
      return { item, start }
    })
    .sort((left, right) => left.start - right.start)
    .map(({ item }) => item)
}

export function changeContext(source, before, radius = 70) {
  const start = source.indexOf(before)
  if (start < 0) return { before: '', focus: before, after: '' }
  const end = start + before.length
  return {
    before: source.slice(Math.max(0, start - radius), start),
    focus: source.slice(start, end),
    after: source.slice(end, Math.min(source.length, end + radius)),
  }
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
