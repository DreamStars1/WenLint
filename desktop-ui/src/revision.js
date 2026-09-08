export function buildRevision(source, changes, undoneIds) {
  const replacements = changes
    .filter((item) => !undoneIds.has(item.id))
    .map((item) => {
      const start = source.indexOf(item.before)
      if (start < 0 || start !== source.lastIndexOf(item.before)) {
        throw new Error('修改位置无法在原文中唯一定位')
      }
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
