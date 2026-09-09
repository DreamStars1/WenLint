<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { diffText, locateChange } from './revision.js'

const props = defineProps({ source: { type: String, required: true }, change: { type: Object, required: true } })
const target = ref(null)
const context = computed(() => {
  const start = locateChange(props.source, props.change)
  return { before: props.source.slice(0, start), after: props.source.slice(start + props.change.before.length) }
})
const parts = computed(() => diffText(props.change.before, props.change.after))
watch(() => [props.source, props.change], async () => {
  await nextTick()
  target.value?.scrollIntoView({ block: 'center', behavior: 'auto' })
}, { immediate: true })
</script>

<template>
  <div class="document-context" tabindex="0" aria-label="全文上下文，可滚动阅读所有段落">
    <div class="document-context-text"><span>{{ context.before }}</span><mark ref="target" class="document-change" aria-label="当前建议的变更位置"><template v-for="(part, index) in parts" :key="index"><del v-if="part.kind === 'delete'">{{ part.text }}</del><ins v-else-if="part.kind === 'insert'">{{ part.text }}</ins><span v-else>{{ part.text }}</span></template></mark><span>{{ context.after }}</span></div>
  </div>
</template>
