<script setup>
import { computed, onMounted, reactive, ref } from 'vue'

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
const busy = ref('')
const apiReady = ref(false)
const showKey = ref(false)
const confirmOpen = ref(false)
const dragActive = ref(false)
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
const revisionStale = computed(
  () => hasRevision.value
    && (sourceText.value !== reviewSource.value || config.profile !== reviewProfile.value),
)
const changedCount = computed(
  () => decisions.value.filter((item) => item.action === 'REWRITE').length,
)
const pendingCount = computed(
  () => decisions.value.filter((item) => ['VERIFY', 'ASK'].includes(item.action)).length,
)

function notify(message, kind = 'info') {
  toast.message = message
  toast.kind = kind
  toast.visible = true
  window.setTimeout(() => { toast.visible = false }, 3200)
}

async function callApi(method, payload) {
  const api = window.pywebview?.api
  if (!api || typeof api[method] !== 'function') {
    throw new Error('桌面桥接尚未就绪，请稍后重试')
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
}

async function openFile() {
  if (!apiReady.value || busy.value) return
  try {
    const result = await callApi('open_file')
    if (!result.ok) throw new Error(result.error)
    if (result.cancelled) return
    sourceText.value = result.content
    filename.value = result.filename
    filePath.value = result.path
    clearResults()
    notify(`已载入 ${result.filename}`, 'success')
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
    filename.value = file.name
    filePath.value = ''
    clearResults()
    notify(`已载入 ${file.name}`, 'success')
  } catch {
    notify('无法读取该文件，请使用 UTF-8 文本', 'error')
  }
}

function documentPayload() {
  return { text: sourceText.value, profile: config.profile, filename: filename.value }
}

async function runStaticScan() {
  if (!sourceText.value.trim()) {
    notify('请打开文件或粘贴待审查文本', 'error')
    return
  }
  busy.value = 'scan'
  try {
    const result = await callApi('static_scan', documentPayload())
    if (!result.ok) throw new Error(result.error)
    findings.value = result.findings
    activeTab.value = 'findings'
    notify(`本地检查完成：${result.count} 个候选问题`, 'success')
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    busy.value = ''
  }
}

function requestAgentReview() {
  if (!sourceText.value.trim()) return notify('请打开文件或粘贴待审查文本', 'error')
  if (!config.baseUrl.trim()) return notify('请填写 Base URL', 'error')
  if (!config.apiKey.trim()) return notify('请填写 API Key', 'error')
  if (!config.model.trim()) return notify('请填写模型名称', 'error')
  confirmOpen.value = true
}

async function runAgentReview() {
  confirmOpen.value = false
  busy.value = 'agent'
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
    activeTab.value = 'decisions'
    notify(`Agent 完成 ${result.decisions.length} 条裁决`, 'success')
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    busy.value = ''
  }
}

function applyRevision() {
  if (!hasRevision.value) return
  if (revisionStale.value) return notify('正文或场景已变化，请重新运行 Agent 后再应用', 'error')
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
    <header class="topbar">
      <div class="brand-block">
        <div class="logo-mark">文</div>
        <div>
          <div class="brand-line">文尺 <span>WenLint</span><em>v{{ version }}</em></div>
          <p>中文文档的静态检查与语义审查工作台</p>
        </div>
      </div>
      <div class="privacy-chip"><i></i> 密钥仅驻留本次运行内存</div>
    </header>

    <section class="flow-strip" aria-label="工作流">
      <div class="flow-step active"><b>01</b><span>载入文本</span></div>
      <div class="flow-line"></div>
      <div class="flow-step"><b>02</b><span>静态检查</span></div>
      <div class="flow-line"></div>
      <div class="flow-step"><b>03</b><span>Agent 裁决</span></div>
      <div class="flow-line"></div>
      <div class="flow-step"><b>04</b><span>确认修改</span></div>
    </section>

    <section class="config-card">
      <div class="section-heading">
        <div><span class="eyebrow">MODEL CONNECTION</span><h2>审查模型</h2></div>
        <span class="connection-state" :class="{ ready: apiReady }">
          {{ apiReady ? '桌面服务已连接' : '正在连接桌面服务' }}
        </span>
      </div>
      <div class="config-grid">
        <label class="field wide"><span>Base URL</span><input v-model="config.baseUrl" spellcheck="false" placeholder="https://api.example.com/v1" /></label>
        <label class="field key-field"><span>API Key</span><div class="input-action"><input v-model="config.apiKey" :type="showKey ? 'text' : 'password'" spellcheck="false" placeholder="sk-••••••••" /><button type="button" @click="showKey = !showKey">{{ showKey ? '隐藏' : '显示' }}</button></div></label>
        <label class="field"><span>模型名称</span><input v-model="config.model" spellcheck="false" placeholder="gpt-4.1-mini" /></label>
        <label class="field"><span>检查场景</span><select v-model="config.profile"><option v-for="(label, key) in profileNames" :key="key" :value="key">{{ label }}</option></select></label>
      </div>
    </section>

    <section class="workspace">
      <article class="panel editor-panel" @dragover.prevent="dragActive = true" @dragleave.prevent="dragActive = false" @drop.prevent="acceptDroppedFile">
        <div class="panel-head">
          <div><span class="eyebrow">SOURCE</span><h2>{{ filename }}</h2><small v-if="filePath" :title="filePath">{{ filePath }}</small></div>
          <button class="button secondary" :disabled="!apiReady || !!busy" @click="openFile"><span>＋</span> 打开文件</button>
        </div>
        <div class="editor-wrap" :class="{ dragging: dragActive }">
          <div v-if="dragActive" class="drop-overlay">松开以载入文本</div>
          <textarea v-model="sourceText" spellcheck="false" placeholder="在这里粘贴中文 PRD、论文、报告或 Markdown，也可以把文件拖进来……"></textarea>
        </div>
        <footer class="editor-footer"><span>{{ characterCount.toLocaleString() }} 字符</span><span>支持 TXT · MD · RST · MARKDOWN</span></footer>
      </article>

      <article class="panel result-panel">
        <div class="result-topline">
          <nav class="tabs">
            <button :class="{ active: activeTab === 'findings' }" @click="activeTab = 'findings'">静态发现 <b>{{ findings.length }}</b></button>
            <button :class="{ active: activeTab === 'decisions' }" @click="activeTab = 'decisions'">Agent 裁决 <b>{{ decisions.length }}</b></button>
            <button :class="{ active: activeTab === 'revision' }" @click="activeTab = 'revision'">完整修改稿</button>
          </nav>
        </div>

        <div class="result-scroll">
          <div v-if="revisionStale" class="stale-banner">正文或检查场景已变化；当前修改稿可另存，但不能覆盖编辑区。请重新运行 Agent。</div>
          <div v-if="activeTab === 'findings'">
            <div v-if="!findings.length" class="empty-state"><div class="empty-glyph">⌁</div><h3>等待本地检查</h3><p>规则引擎在本机运行，不会发送正文或密钥。</p></div>
            <div v-else class="item-list">
              <div v-for="(item, index) in findings" :key="`${item.rule_id}-${item.line}-${item.col}-${index}`" class="finding-card">
                <div class="item-meta"><span class="rule-tag">{{ item.rule_id }}</span><span :class="['severity', item.severity]">{{ item.severity }}</span><span>第 {{ item.line }} 行 · {{ item.col }} 列</span></div>
                <blockquote>{{ item.match || item.sentence }}</blockquote>
                <p>{{ item.message }}</p><small>{{ item.review_hint }}</small>
              </div>
            </div>
          </div>

          <div v-else-if="activeTab === 'decisions'">
            <div v-if="!decisions.length" class="empty-state"><div class="empty-glyph agent">AI</div><h3>等待 Agent 审查</h3><p>Agent 会裁决静态候选，并核对依赖旧上下文的表达。</p></div>
            <template v-else>
              <div class="summary-card"><span>审查结论</span><p>{{ summary }}</p><div><b>{{ changedCount }}</b> 处改写 · <b>{{ pendingCount }}</b> 处需人工处理</div></div>
              <div class="item-list">
                <div v-for="(item, index) in decisions" :key="index" class="decision-card">
                  <div class="item-meta"><span :class="['action-tag', item.action.toLowerCase()]">{{ actionName(item.action) }}</span><span>{{ item.rule }}</span></div>
                  <p class="reason">{{ item.reason }}</p>
                  <div v-if="item.before || item.after" class="mini-diff"><div><span>原文</span><p>{{ item.before || '—' }}</p></div><div><span>建议</span><p>{{ item.after || '—' }}</p></div></div>
                </div>
              </div>
            </template>
          </div>

          <div v-else class="revision-view">
            <div v-if="!hasRevision" class="empty-state"><div class="empty-glyph">稿</div><h3>尚无修改稿</h3><p>完成 Agent 审查后，可以在这里检查全文再决定是否应用。</p></div>
            <textarea v-else v-model="revisedText" spellcheck="false"></textarea>
          </div>
        </div>

        <footer class="action-bar">
          <button class="button secondary" :disabled="!!busy" @click="runStaticScan"><span v-if="busy === 'scan'" class="spinner"></span>{{ busy === 'scan' ? '检查中' : '本地静态检查' }}</button>
          <button class="button primary" :disabled="!!busy" @click="requestAgentReview"><span v-if="busy === 'agent'" class="spinner"></span>{{ busy === 'agent' ? 'Agent 审查中' : 'Agent 审查并修改' }}</button>
          <button v-if="hasRevision" class="button ghost" @click="saveRevision">另存为</button>
          <button v-if="hasRevision" class="button accept" :disabled="revisionStale" @click="applyRevision">应用到编辑区</button>
        </footer>
      </article>
    </section>

    <Transition name="toast"><div v-if="toast.visible" :class="['toast', toast.kind]">{{ toast.message }}</div></Transition>

    <div v-if="confirmOpen" class="modal-backdrop" @click.self="confirmOpen = false">
      <section class="modal-card">
        <div class="modal-icon">↗</div><span class="eyebrow">EXTERNAL REQUEST</span><h2>确认发送当前文本？</h2>
        <p>正文和静态检查结果将发送到你填写的模型服务：</p><code>{{ config.baseUrl }}</code>
        <ul><li>API Key 只用于本次请求，不写入文件或日志</li><li>Agent 不会自动覆盖原文</li><li>请确认该服务允许接收当前文档内容</li></ul>
        <div class="modal-actions"><button class="button ghost" @click="confirmOpen = false">取消</button><button class="button primary" @click="runAgentReview">确认并开始审查</button></div>
      </section>
    </div>
  </main>
</template>
