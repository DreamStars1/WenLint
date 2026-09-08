<script setup>
import { computed } from 'vue'
import { changeContext, diffRows } from './revision.js'

const props = defineProps({ source: { type: String, default: '' }, before: { type: String, default: '' }, after: { type: String, default: '' }, sourceStart: { type: Number, default: undefined } })
const context = computed(() => changeContext(props.source, props.before, 28, props.sourceStart))
const rows = computed(() => diffRows(props.before, props.after, context.value.line || 1))
const operation = computed(() => {
  const deleted = rows.value.some((row) => row.parts.some((part) => part.kind === 'delete'))
  const inserted = rows.value.some((row) => row.parts.some((part) => part.kind === 'insert'))
  return deleted && inserted ? '替换' : deleted ? '删除' : inserted ? '新增' : props.before !== props.after ? '换行调整' : '无变化'
})
</script>

<template>
  <section class="precise-diff" aria-label="原文与建议的字词差异">
    <div class="diff-location"><strong>{{ operation }}</strong><span v-if="context.line">第 {{ context.line }}{{ context.endLine > context.line ? `–${context.endLine}` : '' }} 行 · 第 {{ context.column }} 列起</span><span class="diff-legend">删除线：删除 · 下划线：新增</span></div>
    <p v-if="context.before" class="surrounding-context"><b>上文</b>{{ context.clippedBefore ? '…' : '' }}{{ context.before }}</p>
    <div class="unified-column-heading"><span>原行</span><span>新行</span><span></span><b>− 原文 / ＋ 建议</b></div>
    <div v-for="(row, rowIndex) in rows" :key="rowIndex" :class="['unified-diff-row', row.kind]" :aria-label="row.kind === 'delete' ? `原文第 ${row.oldLine} 行` : row.kind === 'insert' ? `建议第 ${row.newLine} 行` : `未改动第 ${row.oldLine} 行`"><span class="diff-line-number">{{ row.oldLine }}</span><span class="diff-line-number">{{ row.newLine }}</span><b class="diff-line-sign" aria-hidden="true">{{ row.kind === 'delete' ? '−' : row.kind === 'insert' ? '+' : ' ' }}</b><p><template v-for="(part, partIndex) in row.parts" :key="partIndex"><del v-if="part.kind === 'delete'" :aria-label="`删除：${part.text}`">{{ part.text }}</del><ins v-else-if="part.kind === 'insert'" :aria-label="`新增：${part.text}`">{{ part.text }}</ins><span v-else>{{ part.text }}</span></template><span v-if="!row.parts.length" class="empty-diff-line">空行</span></p></div>
    <p v-if="!after" class="diff-empty-result">建议：删除后此处为空</p>
    <p v-if="before.endsWith('\n') !== after.endsWith('\n')" class="diff-empty-result">{{ after.endsWith('\n') ? '＋ 新增末尾换行' : '− 删除末尾换行' }}</p>
    <p v-if="context.after" class="surrounding-context"><b>下文</b>{{ context.after }}{{ context.clippedAfter ? '…' : '' }}</p>
  </section>
</template>
