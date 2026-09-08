import assert from 'node:assert/strict'
import test from 'node:test'

import { buildRevision, changeContext } from '../src/revision.js'

const changes = [
  { id: 2, before: '仍然需要复核', after: '该结论需要复核' },
  { id: 5, before: '之后再发布', after: '复核通过后发布' },
]

test('buildRevision applies active changes and restores an undone change', () => {
  const source = '文档仍然需要复核，之后再发布。'

  assert.equal(
    buildRevision(source, changes, new Set()),
    '文档该结论需要复核，复核通过后发布。',
  )
  assert.equal(
    buildRevision(source, changes, new Set([2])),
    '文档仍然需要复核，复核通过后发布。',
  )
})

test('buildRevision applies changes by source position, not model order', () => {
  const source = '甲需要修改，乙也需要修改。'
  const reversed = [
    { id: 2, before: '乙也需要修改', after: '乙已明确' },
    { id: 1, before: '甲需要修改', after: '甲已明确' },
  ]

  assert.equal(buildRevision(source, reversed, new Set()), '甲已明确，乙已明确。')
})

test('changeContext returns nearby original text around one change', () => {
  const source = '前置说明。这里仍然需要复核。后续说明。'
  const context = changeContext(source, '仍然需要复核', 5)

  assert.equal(context.focus, '仍然需要复核')
  assert.ok(context.before.endsWith('。这里'))
  assert.ok(context.after.startsWith('。后续'))
})
