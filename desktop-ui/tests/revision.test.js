import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildRevision,
  buildApprovedRevision,
  changeContext,
  orderChanges,
  resolveSaveTarget,
} from '../src/revision.js'

const changes = [
  { id: 2, before: '仍然需要复核', after: '该结论需要复核' },
  { id: 5, before: '之后再发布', after: '复核通过后发布' },
]

test('new proposals remain pending and do not change the document', () => {
  const source = '文档仍然需要复核，之后再发布。'
  assert.equal(buildApprovedRevision(source, changes), source)
  assert.equal(buildApprovedRevision(source, changes, { 2: 'rejected' }), source)
})

test('only explicitly accepted proposals enter the saved revision', () => {
  const source = '文档仍然需要复核，之后再发布。'
  assert.equal(buildApprovedRevision(source, changes, { 2: 'accepted', 5: 'rejected' }), '文档该结论需要复核，之后再发布。')
  assert.equal(buildApprovedRevision(source, changes, { 2: 'accepted' }), '文档该结论需要复核，之后再发布。')
  assert.equal(buildApprovedRevision(source, changes, {}), source)
})

test('accepted proposals must have unique, non-overlapping anchors', () => {
  assert.throws(() => buildApprovedRevision('重复重复', [{ id: 1, before: '重复', after: '新文' }], { 1: 'accepted' }), /唯一定位/)
  assert.throws(() => buildApprovedRevision('甲乙丙', [{ id: 1, before: '甲乙', after: '一' }, { id: 2, before: '乙丙', after: '二' }], { 1: 'accepted', 2: 'accepted' }), /重叠/)
})

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

test('orderChanges follows document order while preserving stable ids', () => {
  const source = '甲需要修改，乙也需要修改。'
  const unordered = [
    { id: 5, before: '乙也需要修改' },
    { id: 2, before: '甲需要修改' },
  ]

  assert.deepEqual(orderChanges(source, unordered).map((item) => item.id), [2, 5])
})

test('resolveSaveTarget separates workspace, opened file, and transient text', () => {
  assert.deepEqual(resolveSaveTarget('docs/a.md', 'workspace-hash', 'file-hash'), {
    method: 'workspace_write',
    path: 'docs/a.md',
    expectedSha256: 'workspace-hash',
  })
  assert.deepEqual(resolveSaveTarget('', '', 'file-hash'), { method: 'save_original' })
  assert.equal(resolveSaveTarget('', '', ''), null)
})
