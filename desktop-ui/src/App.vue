<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import { buildApprovedRevision, changeContext, orderChanges, resolveSaveTarget } from './revision.js'

const sourceText = ref('')
const filename = ref('未命名文档.md')
const filePath = ref('')
const findings = ref([])
const summary = ref('')
const decisions = ref([])
const revisedText = ref('')
const reviewSource = ref('')
const reviewProfile = ref('')
const reviewState = ref('idle')
const reviewError = ref('')
const reviewedAt = ref('')
const reviewDurationMs = ref(0)
const modelCalls = ref(0)
const semanticIssueCount = ref(0)
const activeTab = ref('findings')
const revisionMode = ref('changes')
const selectedFindingIndex = ref(0)
const selectedDecisionIndex = ref(0)
const busy = ref('')
const apiReady = ref(false)
const showKey = ref(false)
const settingsOpen = ref(false)
const confirmOpen = ref(false)
const workspaceWriteConfirm = ref(false)
const saveOriginalConfirm = ref(false)
const dragActive = ref(false)
const editingStarted = ref(false)
const sourceEditor = ref(null)
const version = ref('0.5.0')
const standaloneSha256 = ref('')
const changeChoices = ref({})
const agentEvents = ref([])
const agentJobId = ref('')
const agentStartedAt = ref(0)
const elapsedMs = ref(0)
const useWorkspaceTools = ref(false)
const demoMode = ref(false)
const browserDemo = ref(false)
const cancelling = ref(false)
const progressFeed = ref(null)
let disposed = false
let elapsedTimer
const selectedChangeIndex = ref(0)
const limits = reactive({ maxFileBytes: 0, maxTextChars: 0 })
const workspaceQuery = ref('')
const workspace = reactive({
  connected: false,
  visible: false,
  root: '',
  name: '',
  files: [],
  selectedPath: '',
  selectedSha256: '',
  loadedText: '',
})
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
const selectedFinding = computed(() => findings.value[selectedFindingIndex.value] || null)
const selectedDecision = computed(() => decisions.value[selectedDecisionIndex.value] || null)
const rewriteChanges = computed(() => orderChanges(
  reviewSource.value,
  decisions.value
    .map((item, id) => ({ ...item, id }))
    .filter((item) => item.action === 'REWRITE'),
))
const rewriteDecisions = computed(() => rewriteChanges.value)
const activeRewriteChanges = computed(() => rewriteChanges.value.filter((item) => changeChoices.value[item.id] === 'accepted'))
const unconfirmedCount = computed(() => rewriteChanges.value.filter((item) => !changeChoices.value[item.id]).length)
const rejectedCount = computed(() => rewriteChanges.value.filter((item) => changeChoices.value[item.id] === 'rejected').length)
const hasAcceptedChanges = computed(() => activeRewriteChanges.value.length > 0)
const agentStatus = computed(() => ({ idle: '准备就绪', running: '审查进行中', complete: '审查完成', error: '审查未完成', cancelled: '审查已取消' }[reviewState.value]))
const visibleAgentEvents = computed(() => agentEvents.value.filter((event) => ['plan', 'tool_call', 'tool_start', 'tool_result', 'summary', 'decision', 'status', 'progress', 'lane_complete', 'error', 'complete', 'cancelled'].includes(event.kind)))
const selectedChange = computed(() => rewriteChanges.value[selectedChangeIndex.value] || null)
const selectedChangeContext = computed(() => (
  selectedChange.value ? changeContext(reviewSource.value, selectedChange.value.before) : null
))
const hasRevision = computed(() => reviewState.value === 'complete' && rewriteChanges.value.length > 0)
const pendingCount = computed(
  () => decisions.value.filter((item) => ['VERIFY', 'ASK'].includes(item.action)).length,
)
const reviewIsStale = computed(
  () => reviewState.value === 'complete'
    && (sourceText.value !== reviewSource.value || config.profile !== reviewProfile.value),
)
const revisionStale = computed(() => hasRevision.value && reviewIsStale.value)
const saveTarget = computed(() => resolveSaveTarget(
  workspace.selectedPath,
  workspace.selectedSha256,
  standaloneSha256.value,
))
const canSaveOriginal = computed(() => saveTarget.value !== null)
const workspaceDirty = computed(
  () => workspace.selectedPath && sourceText.value !== workspace.loadedText,
)
const filteredWorkspaceFiles = computed(() => {
  const query = workspaceQuery.value.trim().toLowerCase()
  if (!query) return workspace.files
  return workspace.files.filter((item) => item.path.toLowerCase().includes(query))
})
const reviewMeta = computed(() => {
  if (!reviewedAt.value) return ''
  const time = new Date(reviewedAt.value).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  const duration = reviewDurationMs.value >= 1000
    ? `${(reviewDurationMs.value / 1000).toFixed(1)} 秒`
    : `${reviewDurationMs.value} 毫秒`
  return `${time} 完成 · ${duration} · ${demoMode.value ? '离线演示，未调用模型' : `${modelCalls.value} 路模型调用`}`
})
const modelState = computed(() => (
  browserDemo.value ? '离线演示 · 不调用模型' : config.baseUrl.trim() && config.apiKey.trim() && config.model.trim() ? '模型已配置' : '模型未配置'
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
      browserDemo.value = info.browserDemo === true
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
  elapsedTimer = window.setInterval(() => {
    if (reviewState.value === 'running') elapsedMs.value = Date.now() - agentStartedAt.value
  }, 250)
})

onUnmounted(() => {
  disposed = true
  window.clearInterval(elapsedTimer)
  window.removeEventListener('pywebviewready', connectBridge)
})

function clearSemanticResults() {
  summary.value = ''
  decisions.value = []
  revisedText.value = ''
  reviewSource.value = ''
  reviewProfile.value = ''
  reviewState.value = 'idle'
  reviewError.value = ''
  reviewedAt.value = ''
  reviewDurationMs.value = 0
  modelCalls.value = 0
  semanticIssueCount.value = 0
  selectedDecisionIndex.value = 0
  changeChoices.value = {}
  agentEvents.value = []
  agentJobId.value = ''
  elapsedMs.value = 0
  selectedChangeIndex.value = 0
}

function clearResults() {
  findings.value = []
  selectedFindingIndex.value = 0
  clearSemanticResults()
}

function clearWorkspaceDocument() {
  workspace.selectedPath = ''
  workspace.selectedSha256 = ''
  workspace.loadedText = ''
}

function clearStandaloneDocument() {
  standaloneSha256.value = ''
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
    standaloneSha256.value = result.sha256
    clearWorkspaceDocument()
    clearResults()
    notify(`已打开 ${result.filename}`, 'success')
  } catch (error) {
    notify(error.message, 'error')
  }
}

async function toggleWorkspace() {
  if (workspace.connected) {
    workspace.visible = !workspace.visible
    return
  }
  await selectWorkspace()
}

async function selectWorkspace() {
  if (busy.value) return
  try {
    const result = await callApi('open_workspace')
    if (!result.ok) throw new Error(result.error)
    if (result.cancelled) return
    workspace.connected = true
    workspace.visible = true
    workspace.root = result.root
    workspace.name = result.name
    workspace.files = result.files
    workspaceQuery.value = ''
    clearWorkspaceDocument()
    clearStandaloneDocument()
    filePath.value = ''
    notify(`已关联工作区 ${result.name}`, 'success')
  } catch (error) {
    notify(error.message, 'error')
  }
}

async function refreshWorkspace() {
  try {
    const result = await callApi('workspace_index')
    if (!result.ok) throw new Error(result.error)
    workspace.files = result.files
    notify(`已刷新：${result.files.length} 个文本文件`, 'success')
  } catch (error) {
    notify(error.message, 'error')
  }
}

async function openWorkspaceFile(item) {
  if (busy.value) return
  try {
    const result = await callApi('workspace_read', { path: item.path })
    if (!result.ok) throw new Error(result.error)
    sourceText.value = result.content
    editingStarted.value = true
    filename.value = result.filename
    filePath.value = `${workspace.root}\\${result.path.replaceAll('/', '\\')}`
    workspace.selectedPath = result.path
    workspace.selectedSha256 = result.sha256
    workspace.loadedText = result.content
    clearStandaloneDocument()
    clearResults()
    notify(`已打开 ${result.path}`, 'success')
  } catch (error) {
    notify(error.message, 'error')
  }
}

async function writeWorkspaceFile() {
  workspaceWriteConfirm.value = false
  try {
    const result = await callApi('workspace_write', {
      path: workspace.selectedPath,
      text: sourceText.value,
      expectedSha256: workspace.selectedSha256,
      confirmed: true,
    })
    if (!result.ok) throw new Error(result.error)
    workspace.selectedSha256 = result.sha256
    workspace.loadedText = sourceText.value
    notify(`已写回 ${result.path}`, 'success')
  } catch (error) {
    notify(error.message, 'error')
  }
}

async function acceptDroppedFile(event) {
  dragActive.value = false
  if (busy.value) return notify('请等待当前检查完成，或先取消审查')
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
    clearWorkspaceDocument()
    clearStandaloneDocument()
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

async function startDemo() {
  if (busy.value) return
  if (sourceText.value.trim()) {
    demoMode.value = true
    await runSemanticReview(true)
    return
  }
  sourceText.value = '# 文尺发布说明\n\n为了更好地提升用户体验，我们将会对系统进行优化。\n\n所有用户都认为这个功能非常好，效率提升了 80%。\n\n请相关同事尽快处理这个问题。\n'
  filename.value = '体验示例.md'
  filePath.value = ''
  clearWorkspaceDocument()
  clearStandaloneDocument()
  editingStarted.value = true
  await runSemanticReview(true)
}

async function runStaticScan() {
  if (busy.value) return
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

async function requestSemanticReview() {
  if (busy.value) return
  if (!sourceText.value.trim()) return notify('请打开文件或粘贴待审查文本', 'error')
  if (browserDemo.value) return runSemanticReview(true)
  if (!config.baseUrl.trim() || !config.apiKey.trim() || !config.model.trim()) {
    settingsOpen.value = true
    return notify('请完整填写模型连接信息', 'error')
  }
  busy.value = 'prepare-review'
  try {
    const result = await callApi('static_scan', documentPayload())
    if (!result.ok) throw new Error(result.error)
    findings.value = result.findings
    selectedFindingIndex.value = 0
    confirmOpen.value = true
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    busy.value = ''
  }
}

async function runSemanticReview(demo = false) {
  confirmOpen.value = false
  if (busy.value) return
  busy.value = 'review'
  clearSemanticResults()
  reviewState.value = 'running'
  demoMode.value = demo === true || browserDemo.value
  cancelling.value = false
  activeTab.value = 'agent'
  agentStartedAt.value = Date.now()
  const requestedText = sourceText.value
  const requestedProfile = config.profile
  try {
    if (demoMode.value) {
      const scan = await callApi('static_scan', { text: requestedText, profile: requestedProfile, filename: filename.value })
      if (!scan.ok) throw new Error(scan.error)
      findings.value = scan.findings
      selectedFindingIndex.value = 0
    }
    const started = await callApi('start_agent_review', {
      text: requestedText,
      profile: requestedProfile,
      filename: filename.value,
      baseUrl: config.baseUrl,
      apiKey: config.apiKey,
      model: config.model,
      workspacePath: workspace.selectedPath || '',
      use_workspace_tools: useWorkspaceTools.value && workspace.connected && !demoMode.value,
      demo: demoMode.value,
    })
    if (!started.ok) throw new Error(started.error)
    agentJobId.value = started.job_id
    let after = 0
    let result
    while (!disposed) {
      const status = await callApi('agent_review_status', { job_id: agentJobId.value, after })
      if (!status.ok) throw new Error(status.error)
      for (const event of status.events || []) {
        if (event.sequence > after) {
          agentEvents.value.push(event)
          after = event.sequence
        }
      }
      await nextTick()
      if (progressFeed.value) progressFeed.value.scrollTop = progressFeed.value.scrollHeight
      if (status.state === 'cancelled') {
        reviewState.value = 'cancelled'
        notify('已取消审查，正文未修改')
        return
      }
      if (status.state === 'error') throw new Error(status.error || '审查失败，请检查模型设置后重试')
      if (status.state === 'complete') { result = status.result; break }
      await new Promise((resolve) => window.setTimeout(resolve, 250))
    }
    if (disposed) return
    if (!result) throw new Error('服务没有返回审查结果')
    if (!result.ok) throw new Error(result.error)
    demoMode.value = demoMode.value || result.demo === true
    summary.value = result.summary
    decisions.value = result.decisions
    revisedText.value = requestedText
    reviewSource.value = requestedText
    reviewProfile.value = requestedProfile
    reviewState.value = result.reviewStatus === 'completed' ? 'complete' : 'error'
    reviewedAt.value = result.reviewedAt || new Date().toISOString()
    reviewDurationMs.value = result.durationMs || 0
    modelCalls.value = result.modelCalls ?? 0
    semanticIssueCount.value = demoMode.value ? 0 : result.semanticIssueCount || 0
    selectedDecisionIndex.value = 0
    selectedChangeIndex.value = 0
    changeChoices.value = {}
    const message = demoMode.value
      ? `离线演示完成：${result.decisions.length} 条演示建议，未调用模型`
      : result.decisions.length
      ? `语义复核完成：${result.decisions.length} 条结论，其中 ${semanticIssueCount.value} 条为模型新发现`
      : '语义复核完成：未发现需要处理的问题'
    notify(message, 'success')
  } catch (error) {
    reviewState.value = 'error'
    reviewError.value = error.message
    notify(error.message, 'error')
  } finally {
    elapsedMs.value = Date.now() - agentStartedAt.value
    cancelling.value = false
    busy.value = ''
  }
}

async function cancelReview() {
  if (!agentJobId.value || cancelling.value) return
  cancelling.value = true
  try {
    const result = await callApi('cancel_agent_review', { job_id: agentJobId.value })
    if (!result.ok) throw new Error(result.error)
  } catch (error) {
    cancelling.value = false
    notify(error.message, 'error')
  }
}

function eventLabel(kind) {
  return { plan: '计划', tool_call: '调用工具', tool_start: '调用工具', tool_result: '工具结果', summary: '决策摘要', decision: '决策摘要', status: '进度', progress: '进度', lane_complete: '阶段完成', error: '错误', complete: '完成', cancelled: '已取消' }[kind] || '进度'
}

function formatToolData(value) {
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}

function choiceLabel(item) {
  return { accepted: '已采纳', rejected: '已保留原文' }[changeChoices.value[item.id]] || '待确认'
}

function originLabel(item) {
  if (item.origin === 'demo' || demoMode.value) return '演示建议'
  return item.origin === 'semantic' ? '模型新发现' : ''
}

function applyRevision() {
  if (!hasRevision.value || !hasAcceptedChanges.value) return
  if (revisionStale.value) return notify('正文或场景已变化，请重新复核后再应用', 'error')
  sourceText.value = revisedText.value
  clearResults()
  activeTab.value = 'findings'
  notify('修改稿已放入编辑区，原文件未覆盖', 'success')
}

function decideChange(item, choice) {
  if (revisionStale.value || busy.value) return
  const choices = { ...changeChoices.value }
  if (choice) choices[item.id] = choice
  else delete choices[item.id]
  try {
    revisedText.value = buildApprovedRevision(reviewSource.value, rewriteChanges.value, choices)
    changeChoices.value = choices
  } catch (error) {
    notify(error.message, 'error')
  }
}

function selectRelativeChange(offset) {
  const total = rewriteChanges.value.length
  if (!total) return
  selectedChangeIndex.value = (selectedChangeIndex.value + offset + total) % total
}

async function saveRevisionAs() {
  if (!hasRevision.value || !hasAcceptedChanges.value || revisionStale.value) return
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

async function saveToOriginal() {
  saveOriginalConfirm.value = false
  if (!canSaveOriginal.value || revisionStale.value || !hasRevision.value || !hasAcceptedChanges.value) return
  try {
    const target = saveTarget.value
    const result = target.method === 'workspace_write'
      ? await callApi(target.method, {
        path: target.path,
        text: revisedText.value,
        expectedSha256: target.expectedSha256,
        confirmed: true,
      })
      : await callApi(target.method, { text: revisedText.value, confirmed: true })
    if (!result.ok) throw new Error(result.error)
    if (workspace.selectedPath) workspace.selectedSha256 = result.sha256
    else standaloneSha256.value = result.sha256
    sourceText.value = revisedText.value
    workspace.loadedText = sourceText.value
    clearResults()
    activeTab.value = 'findings'
    notify(`已保存到原文件：${result.path}`, 'success')
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
      <div class="brand"><span class="brand-mark">文</span><strong>文尺</strong><span class="version">{{ version }}</span><span v-if="browserDemo" class="demo-badge">离线演示</span></div>
      <div class="document-title" :title="filePath || filename"><strong>{{ filename }}</strong><span>{{ filePath || '本地草稿' }}</span></div>
      <nav class="toolbar" aria-label="文档操作">
        <button class="tool-button" :class="{ active: workspace.visible }" :disabled="!apiReady || !!busy" @click="toggleWorkspace">{{ workspace.connected ? workspace.name : '工作区' }}</button>
        <button class="tool-button" :disabled="!apiReady || !!busy" @click="openFile">打开文件</button>
        <span class="toolbar-divider"></span>
        <label class="profile-select"><span>场景</span><select v-model="config.profile" :disabled="!!busy"><option v-for="(label, key) in profileNames" :key="key" :value="key">{{ label }}</option></select></label>
        <button class="tool-button" :disabled="!apiReady || !!busy || !sourceText.trim()" @click="runStaticScan"><span v-if="busy === 'scan'" class="spinner"></span>{{ busy === 'scan' ? '检查中' : '本地检查' }}</button>
        <button class="tool-button primary" :disabled="!apiReady || !!busy || !sourceText.trim()" @click="requestSemanticReview"><span v-if="['prepare-review', 'review'].includes(busy)" class="spinner"></span>{{ busy === 'prepare-review' ? '准备中' : busy === 'review' ? '复核中' : browserDemo ? '演示审查' : '语义复核' }}</button>
        <button v-if="reviewState === 'running'" class="tool-button" :disabled="!agentJobId || cancelling" @click="cancelReview">{{ cancelling ? '取消中' : '取消审查' }}</button>
        <button v-if="!browserDemo" class="icon-button" :class="{ active: settingsOpen }" title="模型设置" @click="settingsOpen = !settingsOpen">设置</button>
      </nav>
    </header>

    <section v-if="settingsOpen && !browserDemo" class="settings-drawer">
      <div class="settings-heading"><div><strong>模型连接</strong><span>仅用于语义复核；密钥只保留在当前进程内存中</span></div><button @click="settingsOpen = false">关闭</button></div>
      <div class="settings-grid">
        <label><span>Base URL</span><input v-model="config.baseUrl" spellcheck="false" placeholder="https://api.example.com/v1" /></label>
        <label><span>API Key</span><div class="key-input"><input v-model="config.apiKey" :type="showKey ? 'text' : 'password'" spellcheck="false" placeholder="sk-••••••••" /><button @click="showKey = !showKey">{{ showKey ? '隐藏' : '显示' }}</button></div></label>
        <label><span>模型名称</span><input v-model="config.model" spellcheck="false" placeholder="gpt-4.1-mini" /></label>
      </div>
    </section>

    <section :class="['workbench', { 'with-workspace': workspace.visible }]">
      <aside v-if="workspace.visible" class="workspace-panel">
        <header><div><span>工作区</span><strong :title="workspace.root">{{ workspace.name }}</strong></div><button title="收起工作区" @click="workspace.visible = false">‹</button></header>
        <div class="workspace-search"><input v-model="workspaceQuery" placeholder="筛选文件" spellcheck="false" /></div>
        <div class="workspace-files">
          <button v-for="item in filteredWorkspaceFiles" :key="item.path" :class="{ selected: workspace.selectedPath === item.path }" :title="item.path" @click="openWorkspaceFile(item)">
            <span class="file-mark">{{ item.name.split('.').pop()?.toUpperCase() }}</span><span><strong>{{ item.name }}</strong><small>{{ item.path }}</small></span>
          </button>
          <div v-if="!filteredWorkspaceFiles.length" class="workspace-empty">没有可审查的文本文件</div>
        </div>
        <footer><span>{{ workspace.files.length }} 个文本文件</span><div><button @click="refreshWorkspace">刷新</button><button @click="selectWorkspace">更换目录</button></div></footer>
      </aside>

      <article class="editor-pane" @dragover.prevent="dragActive = true" @dragleave.prevent="dragActive = false" @drop.prevent="acceptDroppedFile">
        <div class="pane-title"><div><strong>正文</strong><span>{{ demoMode ? '离线演示' : '编辑' }}</span></div><div><button class="text-button" :disabled="!apiReady || !!busy" @click="startDemo">免费体验</button><button v-if="workspaceDirty" class="workspace-save" :disabled="!!busy" @click="workspaceWriteConfirm = true">写回工作区</button></div></div>
        <div class="editor-wrap" :class="{ dragging: dragActive }">
          <div v-if="dragActive" class="drop-overlay">松开鼠标以打开文档</div>
          <div v-else-if="!sourceText && !editingStarted" class="editor-welcome">
            <span class="welcome-mark">文</span>
            <h1>从一篇文档开始</h1>
            <p>打开本地文件，或直接粘贴需要检查的中文内容。</p>
            <div><button class="welcome-primary" :disabled="!apiReady" @click="startDemo">体验示例 · 无需密钥</button><button class="welcome-secondary" :disabled="!apiReady" @click="openFile">打开文档</button><button class="welcome-secondary" @click="startBlankDocument">直接输入</button></div>
            <p class="demo-explanation">先体验：查看 Agent 过程 → 逐条确认建议 → 预览修改稿</p>
            <small>支持 TXT、Markdown、RST · 本地检查不会上传正文</small>
          </div>
          <textarea ref="sourceEditor" v-model="sourceText" :readonly="busy === 'review'" aria-label="待检查正文" spellcheck="false" placeholder="开始输入或粘贴正文……"></textarea>
        </div>
      </article>

      <aside class="review-pane">
        <nav class="review-tabs">
          <button :class="{ active: activeTab === 'findings' }" @click="activeTab = 'findings'">问题 <span>{{ findings.length }}</span></button>
          <button :class="{ active: activeTab === 'decisions' }" @click="activeTab = 'decisions'">复核结论 <span :class="{ complete: reviewState === 'complete' }">{{ reviewState === 'complete' ? '已完成' : decisions.length }}</span></button>
          <button :class="{ active: activeTab === 'revision' }" @click="activeTab = 'revision'">修改稿</button>
          <button :class="{ active: activeTab === 'agent' }" @click="activeTab = 'agent'">Agent 过程<span v-if="reviewState === 'running'" class="spinner"></span></button>
        </nav>

        <div v-if="reviewIsStale" class="stale-notice">正文或场景已经变化，当前语义复核结果已过期；请重新复核。</div>
        <div v-if="browserDemo || (demoMode && reviewState !== 'idle')" class="demo-notice">离线演示 · 使用本地规则和示例建议，不调用模型。{{ browserDemo ? '真实语义复核请使用桌面版并配置模型。' : '真实语义复核请配置模型。' }}</div>

        <section v-if="activeTab === 'agent'" class="tab-body agent-tab">
          <header class="agent-heading"><div><strong>{{ agentStatus }}</strong><span>{{ (elapsedMs / 1000).toFixed(1) }} 秒 · {{ visibleAgentEvents.length }} 个步骤</span></div><button v-if="reviewState === 'running'" class="tool-button" :disabled="!agentJobId || cancelling" @click="cancelReview">{{ cancelling ? '取消中…' : '取消审查' }}</button></header>
          <p class="agent-explanation">实时呈现审查计划、工具调用与结果、判断依据摘要。</p>
          <div ref="progressFeed" class="agent-feed" role="log" aria-label="Agent 执行过程" aria-live="polite">
            <div v-if="!visibleAgentEvents.length" class="empty-state"><strong>{{ reviewState === 'running' ? '正在启动审查…' : '每一步都有迹可循' }}</strong><p>开始语义复核或免费体验，即可在这里查看审查过程。</p></div>
            <article v-for="event in visibleAgentEvents" :key="event.sequence" :class="['agent-event', event.kind]"><div><b>{{ eventLabel(event.kind) }}</b><span v-if="event.lane">{{ event.lane }}</span><time>{{ ((event.elapsed_ms || 0) / 1000).toFixed(1) }}s</time></div><p>{{ event.message }}</p><details v-if="event.tool || event.arguments !== undefined || event.args !== undefined || event.result !== undefined" class="tool-details"><summary>{{ event.tool || '工具' }} · 查看{{ event.result !== undefined ? '结果' : '调用参数' }}</summary><pre v-if="event.arguments !== undefined || event.args !== undefined">{{ formatToolData(event.arguments ?? event.args) }}</pre><pre v-if="event.result !== undefined">{{ formatToolData(event.result) }}</pre></details></article>
          </div>
          <div v-if="reviewState === 'error'" class="agent-outcome error"><strong>本次审查未完成</strong><p>{{ reviewError }}</p><button v-if="!browserDemo" class="tool-button" @click="settingsOpen = true">检查模型设置</button><button v-else class="tool-button" @click="startDemo">重试演示</button></div>
          <div v-else-if="reviewState === 'cancelled'" class="agent-outcome"><strong>已取消，正文保持不变。</strong><p>可调整正文或模型设置后重新开始。</p></div>
          <div v-else-if="reviewState === 'complete'" class="agent-outcome"><strong>{{ rewriteChanges.length }} 条改写 · {{ unconfirmedCount }} 待确认 · {{ pendingCount }} 待核实或补充</strong><button class="tool-button primary" @click="activeTab = rewriteChanges.length ? 'revision' : 'decisions'">{{ rewriteChanges.length ? '查看修改建议' : '查看复核结论' }}</button></div>
        </section>

        <section v-else-if="activeTab === 'findings'" class="tab-body split-view">
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
          <div v-if="reviewState === 'idle'" class="empty-state review-idle"><span class="idle-mark">◇</span><strong>{{ browserDemo ? '尚未进行演示审查' : '尚未进行语义复核' }}</strong><p>{{ browserDemo ? '点击顶部“演示审查”，体验本地检查、示例建议和逐条确认。' : '点击顶部“语义复核”，模型会并发裁决规则候选并独立检查全文。' }}</p></div>
          <div v-else-if="reviewState === 'running'" class="empty-state review-running"><span class="large-spinner"></span><strong>正在审查文档</strong><p>已用 {{ (elapsedMs / 1000).toFixed(1) }} 秒，可随时查看进度或取消。</p><button class="tool-button" @click="activeTab = 'agent'">查看 Agent 过程</button></div>
          <div v-else-if="reviewState === 'cancelled'" class="empty-state"><strong>审查已取消</strong><p>正文未修改，可重新开始审查。</p></div>
          <div v-else-if="reviewState === 'error'" class="empty-state review-error"><span class="idle-mark">!</span><strong>本次语义复核未完成</strong><p>{{ reviewError }}</p></div>
          <div v-else-if="!decisions.length" class="review-complete">
            <span class="complete-mark">✓</span><h2>{{ demoMode ? '离线演示已完成' : '语义复核已完成' }}</h2><strong>{{ demoMode ? '当前内容未匹配演示建议' : '未发现需要修改或人工确认的问题' }}</strong><p>{{ summary }}</p><small>{{ reviewMeta }}</small>
          </div>
          <template v-else>
            <div class="review-summary"><div><span class="complete-dot">✓</span><p>{{ summary }}</p></div><span>{{ rewriteDecisions.length }} 处改写 · {{ pendingCount }} 处待人工处理 · {{ demoMode ? `${decisions.length} 条演示建议` : `${semanticIssueCount} 条模型新发现` }}</span><small>{{ reviewMeta }}</small></div>
            <div class="issue-list decision-list">
              <button v-for="(item, index) in decisions" :key="index" :class="['issue-row', { selected: selectedDecisionIndex === index }]" @click="selectedDecisionIndex = index">
                <span class="decision-tags"><span :class="['action-label', item.action.toLowerCase()]">{{ actionName(item.action) }}</span><em v-if="originLabel(item)">{{ originLabel(item) }}</em></span>
                <span class="issue-main"><strong>{{ item.rule }}</strong><small>{{ item.reason }}</small></span>
              </button>
            </div>
            <div v-if="selectedDecision" class="detail-pane">
              <div class="detail-heading"><span :class="['action-label', selectedDecision.action.toLowerCase()]">{{ actionName(selectedDecision.action) }}</span><strong>{{ selectedDecision.rule }}</strong></div>
              <h3>{{ selectedDecision.reason }}</h3>
              <div v-if="selectedDecision.before || selectedDecision.after" class="change-block"><div><span>− 原文</span><p>{{ selectedDecision.before || '—' }}</p></div><div><span>＋ 建议</span><p>{{ selectedDecision.after || '—' }}</p></div></div>
              <button v-if="selectedDecision.action === 'REWRITE'" class="tool-button decision-review" @click="selectedChangeIndex = rewriteChanges.findIndex(item => item.id === selectedDecisionIndex); activeTab = 'revision'; revisionMode = 'full'">查看上下文并确认这条建议</button>
            </div>
          </template>
        </section>

        <section v-else class="tab-body revision-tab">
          <div v-if="reviewState === 'idle'" class="empty-state"><strong>尚未生成修改稿</strong><p>完成语义复核后，可先查看变更，再决定是否应用或另存。</p></div>
          <div v-else-if="reviewState === 'complete' && !rewriteDecisions.length" class="review-complete"><span class="complete-mark">✓</span><h2>复核完成，正文无变化</h2><p>{{ demoMode ? '当前正文未匹配演示中的改写示例；这不代表文档没有问题。' : '模型没有提出可直接应用的改写。' }} 待核实或待补充的信息仍需在“复核结论”中人工处理。</p><small>{{ reviewMeta }}</small></div>
          <div v-else-if="!hasRevision" class="empty-state"><strong>没有可用修改稿</strong><p>本次复核未完成，请检查模型连接后重试。</p></div>
          <template v-else>
            <div class="revision-toolbar"><div><button :class="{ active: revisionMode === 'changes' }" @click="revisionMode = 'changes'">逐条确认</button><button :class="{ active: revisionMode === 'full' }" @click="revisionMode = 'full'">全文核对</button></div><span>{{ activeRewriteChanges.length }} 已采纳 · {{ unconfirmedCount }} 待确认 · {{ rejectedCount }} 保留</span></div>
            <p class="approval-hint">只有点击“采纳建议”的修改会进入修改稿。待确认和保留原文的内容不变。</p>
            <div v-if="revisionMode === 'changes'" class="changes-list">
              <div v-for="(item, index) in rewriteChanges" :key="item.id" :class="['diff-block', changeChoices[item.id] || 'pending']">
                <header><span>{{ item.rule }} · 建议 {{ index + 1 }}</span><strong :class="['choice-badge', changeChoices[item.id] || 'pending']">{{ choiceLabel(item) }}</strong></header>
                <div class="diff-reason"><strong>修改原因</strong><p>{{ item.reason }}</p></div>
                <p class="removed">− {{ item.before }}</p><p class="added">＋ {{ item.after }}</p>
                <div class="diff-actions"><button @click="selectedChangeIndex = index; revisionMode = 'full'">检查上下文</button><button v-if="changeChoices[item.id]" :disabled="revisionStale" @click="decideChange(item, null)">撤销决定</button><button :disabled="revisionStale || changeChoices[item.id] === 'rejected'" @click="decideChange(item, 'rejected')">保留原文</button><button class="accept-button" :disabled="revisionStale || changeChoices[item.id] === 'accepted'" @click="decideChange(item, 'accepted')">{{ changeChoices[item.id] === 'accepted' ? '已采纳' : '采纳建议' }}</button></div>
              </div>
            </div>
            <div v-else class="full-review">
              <section v-if="selectedChange && selectedChangeContext" class="context-inspector">
                <div class="context-heading"><div><strong>变更 {{ selectedChangeIndex + 1 }} / {{ rewriteChanges.length }}</strong><span>{{ selectedChange.rule }}</span><em v-if="originLabel(selectedChange)">{{ originLabel(selectedChange) }}</em></div><div><button title="上一处" @click="selectRelativeChange(-1)">←</button><button title="下一处" @click="selectRelativeChange(1)">→</button></div></div>
                <p class="context-reason"><strong>修改原因</strong>{{ selectedChange.reason }}</p>
                <div class="context-quote"><span>{{ selectedChangeContext.before }}</span><mark>{{ selectedChangeContext.focus }}</mark><span>{{ selectedChangeContext.after }}</span></div>
                <div class="context-proposal"><span>建议改为</span><p>{{ selectedChange.after }}</p><strong :class="['choice-badge', changeChoices[selectedChange.id] || 'pending']">{{ choiceLabel(selectedChange) }}</strong></div>
              </section>
              <div v-if="selectedChange" class="diff-actions context-actions"><span>建议 {{ selectedChangeIndex + 1 }} · {{ choiceLabel(selectedChange) }}</span><button v-if="changeChoices[selectedChange.id]" :disabled="revisionStale" @click="decideChange(selectedChange, null)">撤销决定</button><button :disabled="revisionStale || changeChoices[selectedChange.id] === 'rejected'" @click="decideChange(selectedChange, 'rejected')">保留原文</button><button class="accept-button" :disabled="revisionStale || changeChoices[selectedChange.id] === 'accepted'" @click="decideChange(selectedChange, 'accepted')">采纳建议</button></div>
              <textarea :value="revisedText" class="revision-editor" readonly spellcheck="false" aria-label="完整修改稿"></textarea>
            </div>
            <footer class="revision-actions"><span class="save-hint">{{ !hasAcceptedChanges ? '请先采纳一条建议' : `仅应用 ${activeRewriteChanges.length} 条已采纳建议` }}</span><button class="tool-button" :disabled="!canSaveOriginal || revisionStale || !hasAcceptedChanges" @click="saveOriginalConfirm = true">保存</button><button class="tool-button" :disabled="revisionStale || !hasAcceptedChanges" @click="saveRevisionAs">另存为</button><button class="tool-button primary" :disabled="revisionStale || !hasAcceptedChanges" @click="applyRevision">应用到正文</button></footer>
          </template>
        </section>
      </aside>
    </section>

    <footer class="status-bar"><div><span :class="['status-indicator', { online: apiReady }]"></span>{{ apiReady ? '本地服务已连接' : '正在连接' }}<span class="separator">|</span>{{ modelState }}</div><div>{{ characterCount.toLocaleString() }} 字符<span class="separator">|</span>{{ findings.length }} 个问题<span class="separator">|</span>{{ pendingCount }} 个待人工核实</div></footer>

    <Transition name="toast"><div v-if="toast.visible" :class="['toast', toast.kind]" role="status">{{ toast.message }}</div></Transition>

    <div v-if="confirmOpen" class="modal-backdrop" @click.self="confirmOpen = false">
      <section class="modal-card">
        <h2>发送文本进行语义复核</h2>
        <p>当前正文和静态检查结果将发送到以下模型服务：</p>
        <code>{{ config.baseUrl }}</code>
        <ul><li>{{ findings.length ? `将并发执行候选裁决和全文独立发现（${findings.length} 条候选）` : '当前没有规则候选，将单独执行全文语义复核' }}</li><li>API Key 不会写入配置文件或日志</li><li>修改稿不会自动覆盖原文件</li><li>请确认该服务可以接收当前文档内容</li></ul>
        <label v-if="workspace.connected" class="workspace-permission"><input v-model="useWorkspaceTools" type="checkbox" /><span>允许 Agent 检索工作区参考资料，并将相关片段发送给模型，帮助核实和完善文档。</span></label>
        <div class="modal-actions"><button class="tool-button" @click="confirmOpen = false">取消</button><button class="tool-button primary" @click="runSemanticReview(false)">确认发送</button></div>
      </section>
    </div>

    <div v-if="workspaceWriteConfirm" class="modal-backdrop" @click.self="workspaceWriteConfirm = false">
      <section class="modal-card">
        <h2>写回工作区文件</h2>
        <p>这会替换以下文件的当前内容：</p>
        <code>{{ workspace.selectedPath }}</code>
        <ul><li>写入前会校验文件是否被其他程序修改</li><li>只有本次明确确认后才会写入</li><li>建议工作区同时使用 Git 或其他版本管理</li></ul>
        <div class="modal-actions"><button class="tool-button" @click="workspaceWriteConfirm = false">取消</button><button class="tool-button primary" @click="writeWorkspaceFile">确认写回</button></div>
      </section>
    </div>

    <div v-if="saveOriginalConfirm" class="modal-backdrop" @click.self="saveOriginalConfirm = false">
      <section class="modal-card">
        <h2>保存到原文件</h2>
        <p>这会用当前修改稿替换以下文件：</p>
        <code>{{ filePath }}</code>
        <ul><li>仅写入 {{ activeRewriteChanges.length }} 条已采纳建议；待确认和保留原文的建议不会写入</li><li>写入前会校验文件是否被其他程序修改</li><li>该操作会覆盖原文件，建议使用 Git 或保留备份</li></ul>
        <div class="modal-actions"><button class="tool-button" @click="saveOriginalConfirm = false">取消</button><button class="tool-button primary" @click="saveToOriginal">确认保存</button></div>
      </section>
    </div>
  </main>
</template>
