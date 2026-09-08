import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildRevision,
  buildApprovedRevision,
  changeContext,
  diffText,
  diffRows,
  locateChange,
  orderChanges,
  resolveSaveTarget,
} from '../src/revision.js'

const changes = [
  { id: 2, before: '仍然需要复核', after: '该结论需要复核' },
  { id: 5, before: '之后再发布', after: '复核通过后发布' },
]

test('word diff identifies insertion, deletion, and replacement without coloring unchanged words', () => {
  assert.deepEqual(diffText('进行分析', '分析'), [{ kind: 'delete', text: '进行' }, { kind: 'equal', text: '分析' }])
  assert.deepEqual(diffText('请提交报告', '请周五提交报告'), [{ kind: 'equal', text: '请' }, { kind: 'insert', text: '周五' }, { kind: 'equal', text: '提交报告' }])
  assert.deepEqual(diffText('周一提交报告', '周五提交报告'), [{ kind: 'equal', text: '周' }, { kind: 'delete', text: '一' }, { kind: 'insert', text: '五' }, { kind: 'equal', text: '提交报告' }])
  assert.deepEqual(diffText('全部删除', ''), [{ kind: 'delete', text: '全部删除' }])
})

test('separated edits preserve the unchanged middle and reconstruct both versions', () => {
  const before = '请尽快提交报告，并尽快核对结果。'
  const after = '请周五提交报告，并在发布前核对结果。'
  const parts = diffText(before, after)
  assert.equal(parts.filter(part => part.kind !== 'insert').map(part => part.text).join(''), before)
  assert.equal(parts.filter(part => part.kind !== 'delete').map(part => part.text).join(''), after)
  assert.ok(parts.some(part => part.kind === 'equal' && part.text.includes('提交报告，并')))
  assert.deepEqual(diffText('复核复核结果', '复核结果'), [{ kind: 'equal', text: '复核' }, { kind: 'delete', text: '复核' }, { kind: 'equal', text: '结果' }])
})

test('Unicode grapheme clusters stay whole and context columns count visible characters', () => {
  const family = '👨‍👩‍👧‍👦'
  const parts = diffText(`你好${family}，cafe\u0301。`, '你好🙂，café。')
  assert.ok(parts.some(part => part.kind === 'delete' && part.text === family))
  assert.ok(parts.some(part => part.kind === 'delete' && part.text === 'e\u0301'))
  const context = changeContext(`第一行\n${family}需要复核。\n结束`, '需要复核', 1)
  assert.equal(context.line, 2)
  assert.equal(context.column, 2)
  assert.equal(context.before, family)
})

test('large near-identical paragraphs keep the stable middle neutral; fallback remains lossless', () => {
  const middle = '稳定内容'.repeat(2000)
  const parts = diffText(`甲${middle}乙`, `丙${middle}丁`)
  assert.ok(parts.some(part => part.kind === 'equal' && part.text === middle))
  const before = '甲'.repeat(500)
  const after = '乙'.repeat(500)
  const rewritten = diffText(before, after)
  assert.equal(rewritten.filter(part => part.kind !== 'insert').map(part => part.text).join(''), before)
  assert.equal(rewritten.filter(part => part.kind !== 'delete').map(part => part.text).join(''), after)
})

test('unified diff includes accurate old/new line numbers and shows unchanged context once', () => {
  const rows = diffRows('标题\n周一提交\n保持这行\n尾注', '标题\n周五提交\n新增一行\n保持这行\n尾注', 12)
  assert.deepEqual(rows.map(({ kind, oldLine, newLine }) => ({ kind, oldLine, newLine })), [
    { kind: 'equal', oldLine: 12, newLine: 12 },
    { kind: 'delete', oldLine: 13, newLine: null },
    { kind: 'insert', oldLine: null, newLine: 13 },
    { kind: 'insert', oldLine: null, newLine: 14 },
    { kind: 'equal', oldLine: 14, newLine: 15 },
    { kind: 'equal', oldLine: 15, newLine: 16 },
  ])
  assert.ok(rows[1].parts.some(part => part.kind === 'delete' && part.text === '一'))
  assert.ok(rows[2].parts.some(part => part.kind === 'insert' && part.text === '五'))
})

test('unified insertion, whole deletion, and empty lines remain explicit', () => {
  assert.deepEqual(diffRows('', '新增'), [{ kind: 'insert', oldLine: null, newLine: 1, parts: [{ kind: 'insert', text: '新增' }] }])
  assert.deepEqual(diffRows('删除', ''), [{ kind: 'delete', oldLine: 1, newLine: null, parts: [{ kind: 'delete', text: '删除' }] }])
  const rows = diffRows('前\n\n后', '前\n后')
  assert.equal(rows[1].kind, 'delete')
  assert.equal(rows[1].oldLine, 2)
  assert.deepEqual(rows[1].parts, [])
})

test('Python code-point anchors target the correct repeated phrase after astral Unicode', () => {
  const source = '😀重复。\n重复。'
  const changes = [{ id: 'later', before: '重复', after: '后句', source_start: 5 }, { id: 'first', before: '重复', after: '前句', source_start: 1 }]
  assert.equal(locateChange(source, changes[0]), 6)
  assert.deepEqual(orderChanges(source, changes).map(item => item.id), ['first', 'later'])
  assert.equal(buildApprovedRevision(source, changes, { later: 'accepted' }), '😀重复。\n后句。')
  const context = changeContext(source, '重复', 8, 5)
  assert.equal(context.line, 2)
  assert.equal(context.column, 1)
})

test('invalid anchors fail closed instead of silently selecting an earlier duplicate', () => {
  for (const source_start of [-1, 100, 1.5, 0]) {
    assert.throws(() => buildApprovedRevision('😀重复。重复', [{ id: 1, before: '重复', after: '新文', source_start }], { 1: 'accepted' }), /修改位置/)
  }
})

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
