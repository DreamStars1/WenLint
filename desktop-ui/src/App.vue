<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'

const sourceText = ref('')
const filename = ref('未命名文档.md')
const filePath = ref('')
const findings = ref([])
const summary = ref('')
const decisions = ref([])
const revisedText = ref('')
const reviewSource = ref('')
const reviewProfile = ref('')
const activeTab = ref('findings')
const revisionMode = ref('changes')
const selectedFindingIndex = ref(0)
const selectedDecisionIndex = ref(0)
const busy = ref('')
const apiReady = ref(false)
const showKey = ref(false)
const settingsOpen = ref(false)
const confirmOpen = ref(false)
const dragActive = ref(false)
const editingStarted = ref(false)
const sourceEditor = ref(null)
const version = ref('0.3.0')
const limits = reactive({ maxFileBytes: 0, maxTextChars: 0 })
const toast = reactive({ visible: false, kind: 'info', message: '' })
const config = reactive({
  baseUrl: 'https://api.openai.com/v1',
  apiKey: '',
  model: 'gpt-4.1-mini',
  profile: 'general',
})

const profileNames = {
  general: '通用文档',
  product: '产品 / PRD',
  academic: '论文 / 学术',
  formal: '正式材料',
  instruction: '指令文档',
}

const characterCount = computed(() => sourceText.value.length)
const hasRevision = computed(() => revisedText.value.length > 0)
const selectedFinding = computed(() => findings.value[selectedFindingIndex.value] || null)
const selectedDecision = computed(() => decisions.value[selectedDecisionIndex.value] || null)
const rewriteDecisions = computed(() => decisions.value.filter((item) => item.action === 'REWRITE'))
const pendingCount = computed(
  () => decisions.value.filter((item) => ['VERIFY', 'ASK'].includes(item.action)).length,
)
const revisionStale = computed(
  () => hasRevision.value
    && (sourceText.value !== reviewSource.value || config.profile !== reviewProfile.value),
)
const modelState = computed(() => (
  config.baseUrl.trim() && config.apiKey.trim() && config.model.trim() ? '模型已配置' : '模型未配置'
))

function notify(message, kind = 'info') {
  toast.message = message
  toast.kind = kind
  toast.visible = true
  window.setTimeout(() => { toast.visible = false }, 3200)
}

async function callApi(method, payload) {
  const api = window.pywebview?.api
  if (!api || typeof api[method] !== 'function') {
    throw new Error('桌面服务尚未就绪，请稍后重试')
  }
  return payload === undefined ? api[method]() : api[method](payload)
}

async function connectBridge() {
  apiReady.value = true
  try {
    const info = await callApi('app_info')
    if (info?.ok) {
      version.value = info.version
      limits.maxFileBytes = info.maxFileBytes
      limits.maxTextChars = info.maxTextChars
    }
  } catch (error) {
    notify(error.message, 'error')
  }
}

onMounted(() => {
  if (window.pywebview?.api) connectBridge()
  else window.addEventListener('pywebviewready', connectBridge, { once: true })
})

function clearResults() {
  findings.value = []
  summary.value = ''
  decisions.value = []
  revisedText.value = ''
  reviewSource.value = ''
  reviewProfile.value = ''
  selectedFindingIndex.value = 0
  selectedDecisionIndex.value = 0
}

async function openFile() {
  if (!apiReady.value || busy.value) return
  try {
    const result = await callApi('open_file')
    if (!result.ok) throw new Error(result.error)
    if (result.cancelled) return
    sourceText.value = result.content
    editingStarted.value = true
    filename.value = result.filename
    filePath.value = result.path
    clearResults()
    notify(`已打开 ${result.filename}`, 'success')
  } catch (error) {
    notify(error.message, 'error')
  }
}

async function acceptDroppedFile(event) {
  dragActive.value = false
  const file = event.dataTransfer?.files?.[0]
  if (!file) return
  if (!apiReady.value) return notify('桌面服务尚未就绪', 'error')
  if (limits.maxFileBytes && file.size > limits.maxFileBytes) {
    notify('文件超过 2 MB，请拆分后再处理', 'error')
    return
  }
  try {
    const content = await file.text()
    if (limits.maxTextChars && content.length > limits.maxTextChars) {
      notify(`文本超过 ${limits.maxTextChars.toLocaleString()} 个字符，请拆分后再处理`, 'error')
      return
    }
    sourceText.value = content
    editingStarted.value = true
    filename.value = file.name
    filePath.value = ''
    clearResults()
    notify(`已打开 ${file.name}`, 'success')
  } catch {
    notify('无法读取该文件，请使用 UTF-8 文本', 'error')
  }
}

function documentPayload() {
  return { text: sourceText.value, profile: config.profile, filename: filename.value }
}

async function startBlankDocument() {
  editingStarted.value = true
  await nextTick()
  sourceEditor.value?.focus()
}

async function runStaticScan() {
  if (!sourceText.value.trim()) return notify('请打开文件或粘贴待审查文本', 'error')
  busy.value = 'scan'
  try {
    const result = await callApi('static_scan', documentPayload())
    if (!result.ok) throw new Error(result.error)
    findings.value = result.findings
    selectedFindingIndex.value = 0
    activeTab.value = 'findings'
    notify(`检查完成：${result.count} 个候选问题`, 'success')
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    busy.value = ''
  }
}

function requestSemanticReview() {
  if (!sourceText.value.trim()) return notify('请打开文件或粘贴待审查文本', 'error')
  if (!config.baseUrl.trim() || !config.apiKey.trim() || !config.model.trim()) {
    settingsOpen.value = true
    return notify('请完整填写模型连接信息', 'error')
  }
  confirmOpen.value = true
}

async function runSemanticReview() {
  confirmOpen.value = false
  busy.value = 'review'
  const requestedText = sourceText.value
  const requestedProfile = config.profile
  try {
    const result = await callApi('agent_review', {
      text: requestedText,
      profile: requestedProfile,
      filename: filename.value,
      baseUrl: config.baseUrl,
      apiKey: config.apiKey,
      model: config.model,
    })
    if (!result.ok) throw new Error(result.error)
    summary.value = result.summary
    decisions.value = result.decisions
    revisedText.value = result.revisedText
    reviewSource.value = requestedText
    reviewProfile.value = requestedProfile
    selectedDecisionIndex.value = 0
    activeTab.value = 'decisions'
    notify(`语义复核完成：${result.decisions.length} 条结论`, 'success')
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    busy.value = ''
  }
}

function applyRevision() {
  if (!hasRevision.value) return
  if (revisionStale.value) return notify('正文或场景已变化，请重新复核后再应用', 'error')
  sourceText.value = revisedText.value
  reviewSource.value = revisedText.value
  notify('修改稿已放入编辑区，原文件未覆盖', 'success')
}

async function saveRevision() {
  if (!hasRevision.value) return
  const dot = filename.value.lastIndexOf('.')
  const stem = dot > 0 ? filename.value.slice(0, dot) : filename.value
  const suffix = dot > 0 ? filename.value.slice(dot) : '.md'
  try {
    const result = await callApi('save_revision', {
      text: revisedText.value,
      suggestedName: `${stem}.revised${suffix}`,
    })
    if (!result.ok) throw new Error(result.error)
    if (!result.cancelled) notify(`已保存到 ${result.path}`, 'success')
  } catch (error) {
    notify(error.message, 'error')
  }
}

function actionName(action) {
  return { KEEP: '保留', REWRITE: '改写', VERIFY: '待核实', ASK: '待确认' }[action] || action
}
</script>

<template>
  <main class="app-shell">
    <header class="app-bar">
      <div class="brand"><span class="brand-mark">文</span><strong>文尺</strong><span class="version">{{ version }}</span></div>
      <div class="document-title" :title="filePath || filename"><strong>{{ filename }}</strong><span>{{ filePath || '本地草稿' }}</span></div>
      <nav class="toolbar" aria-label="文档操作">
        <button class="tool-button" :disabled="!apiReady || !!busy" @click="openFile">打开文件</button>
        <span class="toolbar-divider"></span>
        <label class="profile-select"><span>场景</span><select v-model="config.profile"><option v-for="(label, key) in profileNames" :key="key" :value="key">{{ label }}</option></select></label>
        <button class="tool-button" :disabled="!!busy" @click="runStaticScan"><span v-if="busy === 'scan'" class="spinner"></span>{{ busy === 'scan' ? '检查中' : '本地检查' }}</button>
        <button class="tool-button primary" :disabled="!!busy" @click="requestSemanticReview"><span v-if="busy === 'review'" class="spinner"></span>{{ busy === 'review' ? '复核中' : '语义复核' }}</button>
        <button class="icon-button" :class="{ active: settingsOpen }" title="模型设置" @click="settingsOpen = !settingsOpen">设置</button>
      </nav>
    </header>

    <section v-if="settingsOpen" class="settings-drawer">
      <div class="settings-heading"><div><strong>模型连接</strong><span>仅用于语义复核；密钥只保留在当前进程内存中</span></div><button @click="settingsOpen = false">关闭</button></div>
      <div class="settings-grid">
        <label><span>Base URL</span><input v-model="config.baseUrl" spellcheck="false" placeholder="https://api.example.com/v1" /></label>
        <label><span>API Key</span><div class="key-input"><input v-model="config.apiKey" :type="showKey ? 'text' : 'password'" spellcheck="false" placeholder="sk-••••••••" /><button @click="showKey = !showKey">{{ showKey ? '隐藏' : '显示' }}</button></div></label>
        <label><span>模型名称</span><input v-model="config.model" spellcheck="false" placeholder="gpt-4.1-mini" /></label>
      </div>
    </section>

    <section class="workbench">
      <article class="editor-pane" @dragover.prevent="dragActive = true" @dragleave.prevent="dragActive = false" @drop.prevent="acceptDroppedFile">
        <div class="pane-title"><strong>正文</strong><span>编辑</span></div>
        <div class="editor-wrap" :class="{ dragging: dragActive }">
          <div v-if="dragActive" class="drop-overlay">松开鼠标以打开文档</div>
          <div v-else-if="!sourceText && !editingStarted" class="editor-welcome">
            <span class="welcome-mark">文</span>
            <h1>从一篇文档开始</h1>
            <p>打开本地文件，或直接粘贴需要检查的中文内容。</p>
            <div><button class="welcome-primary" :disabled="!apiReady" @click="openFile">打开文档</button><button class="welcome-secondary" @click="startBlankDocument">直接输入</button></div>
            <small>支持 TXT、Markdown、RST · 本地检查不会上传正文</small>
          </div>
          <textarea ref="sourceEditor" v-model="sourceText" spellcheck="false" placeholder="开始输入或粘贴正文……"></textarea>
        </div>
      </article>

      <aside class="review-pane">
        <nav class="review-tabs">
          <button :class="{ active: activeTab === 'findings' }" @click="activeTab = 'findings'">问题 <span>{{ findings.length }}</span></button>
          <button :class="{ active: activeTab === 'decisions' }" @click="activeTab = 'decisions'">复核结论 <span>{{ decisions.length }}</span></button>
          <button :class="{ active: activeTab === 'revision' }" @click="activeTab = 'revision'">修改稿</button>
        </nav>

        <div v-if="revisionStale" class="stale-notice">正文或场景已经变化，当前修改稿不能应用；请重新复核。</div>

        <section v-if="activeTab === 'findings'" class="tab-body split-view">
          <div v-if="!findings.length" class="review-welcome"><span class="review-mark">✓</span><h2>检查你的文档</h2><p>先运行本地检查，快速发现含糊表达、过程痕迹、冗余和结构问题。</p><ol><li><b>本地检查</b><span>规则引擎在本机完成</span></li><li><b>语义复核</b><span>逐项判断并生成修改建议</span></li><li><b>确认修改</b><span>预览差异后再应用或保存</span></li></ol></div>
          <template v-else>
            <div class="issue-list">
              <button v-for="(item, index) in findings" :key="`${item.rule_id}-${item.line}-${item.col}-${index}`" :class="['issue-row', { selected: selectedFindingIndex === index }]" @click="selectedFindingIndex = index">
                <span :class="['severity-dot', item.severity]"></span>
                <span class="issue-main"><strong>{{ item.rule_id }} · {{ item.message }}</strong><small>{{ item.match || item.sentence || '结构问题' }}</small></span>
                <span class="location">{{ item.line }}:{{ item.col }}</span>
              </button>
            </div>
            <div v-if="selectedFinding" class="detail-pane">
              <div class="detail-heading"><span :class="['severity-label', selectedFinding.severity]">{{ selectedFinding.severity }}</span><strong>{{ selectedFinding.rule_id }}</strong><span>第 {{ selectedFinding.line }} 行，第 {{ selectedFinding.col }} 列</span></div>
              <h3>{{ selectedFinding.message }}</h3>
              <div class="quote-block">{{ selectedFinding.sentence || selectedFinding.match }}</div>
              <div class="detail-section"><strong>审查提示</strong><p>{{ selectedFinding.review_hint || '请结合上下文判断是否需要修改。' }}</p></div>
            </div>
          </template>
        </section>

        <section v-else-if="activeTab === 'decisions'" class="tab-body split-view">
          <div v-if="!decisions.length" class="empty-state"><strong>没有复核结论</strong><p>配置模型后运行“语义复核”，系统会逐项判断静态候选。</p></div>
          <template v-else>
            <div class="review-summary"><p>{{ summary }}</p><span>{{ rewriteDecisions.length }} 处改写 · {{ pendingCount }} 处待人工处理</span></div>
            <div class="issue-list decision-list">
              <button v-for="(item, index) in decisions" :key="index" :class="['issue-row', { selected: selectedDecisionIndex === index }]" @click="selectedDecisionIndex = index">
                <span :class="['action-label', item.action.toLowerCase()]">{{ actionName(item.action) }}</span>
                <span class="issue-main"><strong>{{ item.rule }}</strong><small>{{ item.reason }}</small></span>
              </button>
            </div>
            <div v-if="selectedDecision" class="detail-pane">
              <div class="detail-heading"><span :class="['action-label', selectedDecision.action.toLowerCase()]">{{ actionName(selectedDecision.action) }}</span><strong>{{ selectedDecision.rule }}</strong></div>
              <h3>{{ selectedDecision.reason }}</h3>
              <div v-if="selectedDecision.before || selectedDecision.after" class="change-block"><div><span>− 原文</span><p>{{ selectedDecision.before || '—' }}</p></div><div><span>＋ 建议</span><p>{{ selectedDecision.after || '—' }}</p></div></div>
            </div>
          </template>
        </section>

        <section v-else class="tab-body revision-tab">
          <div v-if="!hasRevision" class="empty-state"><strong>没有修改稿</strong><p>语义复核完成后，可先查看变更，再决定是否应用或另存。</p></div>
          <template v-else>
            <div class="revision-toolbar"><div><button :class="{ active: revisionMode === 'changes' }" @click="revisionMode = 'changes'">仅看变更</button><button :class="{ active: revisionMode === 'full' }" @click="revisionMode = 'full'">查看全文</button></div><span>{{ rewriteDecisions.length }} 处变更</span></div>
            <div v-if="revisionMode === 'changes'" class="changes-list">
              <div v-if="!rewriteDecisions.length" class="empty-state compact"><strong>正文无变化</strong></div>
              <div v-for="(item, index) in rewriteDecisions" :key="index" class="diff-block"><header>{{ item.rule }} · 变更 {{ index + 1 }}</header><p class="removed">− {{ item.before }}</p><p class="added">＋ {{ item.after }}</p></div>
            </div>
            <textarea v-else v-model="revisedText" class="revision-editor" spellcheck="false"></textarea>
            <footer class="revision-actions"><button class="tool-button" @click="saveRevision">另存为</button><button class="tool-button primary" :disabled="revisionStale" @click="applyRevision">应用到编辑区</button></footer>
          </template>
        </section>
      </aside>
    </section>

    <footer class="status-bar"><div><span :class="['status-indicator', { online: apiReady }]"></span>{{ apiReady ? '本地服务已连接' : '正在连接' }}<span class="separator">|</span>{{ modelState }}</div><div>{{ characterCount.toLocaleString() }} 字符<span class="separator">|</span>{{ findings.length }} 个问题<span class="separator">|</span>{{ pendingCount }} 个待人工核实</div></footer>

    <Transition name="toast"><div v-if="toast.visible" :class="['toast', toast.kind]">{{ toast.message }}</div></Transition>

    <div v-if="confirmOpen" class="modal-backdrop" @click.self="confirmOpen = false">
      <section class="modal-card">
        <h2>发送文本进行语义复核</h2>
        <p>当前正文和静态检查结果将发送到以下模型服务：</p>
        <code>{{ config.baseUrl }}</code>
        <ul><li>API Key 不会写入配置文件或日志</li><li>修改稿不会自动覆盖原文件</li><li>请确认该服务可以接收当前文档内容</li></ul>
        <div class="modal-actions"><button class="tool-button" @click="confirmOpen = false">取消</button><button class="tool-button primary" @click="runSemanticReview">确认发送</button></div>
      </section>
    </div>
  </main>
</template>
