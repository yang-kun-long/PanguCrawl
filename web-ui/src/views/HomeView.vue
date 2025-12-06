<template>
  <div class="app-container">
    <div class="nav-header">
      <el-button @click="drawer = true" circle>
        <el-icon><Clock /></el-icon>
      </el-button>
      <h2 class="app-title">🕸️ 盘古深网爬虫控制台 <span class="version-tag">Ultra</span></h2>
      <div style="width: 32px"></div>
    </div>

    <el-card class="search-card" shadow="hover">
      <div class="input-area">
        <el-input
          v-model="userInput"
          :placeholder="inputPlaceholder"
          class="search-input"
          @keyup.enter="startTask"
          :disabled="loading"
          size="large"
          clearable
        >
          <template #prepend>
            <el-select v-model="mode" placeholder="模式" style="width: 110px">
              <el-option label="🔗 URL模式" value="url" />
              <el-option label="🧭 主题模式" value="topic" />
            </el-select>
          </template>
          <template #append>
            <el-button type="primary" @click="startTask" :loading="loading">
              <el-icon class="mr-1"><VideoPlay /></el-icon> 启动
            </el-button>
          </template>
        </el-input>
      </div>
    </el-card>

    <div v-if="taskId" class="status-section">
      <el-steps :active="activeStep" finish-status="success" align-center class="mb-4">
        <el-step title="初始化" />
        <el-step title="AI 辩论" />
        <el-step title="去噪与提取" />
        <el-step title="完成" />
      </el-steps>

      <div v-if="taskStatus === 'RUNNING'" class="progress-box mb-4">
        <div class="progress-labels">
          <span>进度: {{ crawledCount }}/{{ totalEstimated }}</span>
          <!-- 🟢 新增：推理等待提示 -->
          <span class="loading-hint">
            <el-icon class="is-loading"><Loading /></el-icon>
            盘古大模型正在深度推理中，这可能需要 1-2 分钟...
          </span>
        </div>
        <el-progress :percentage="progressValue" :stroke-width="12" striped striped-flow :duration="10" />
      </div>

      <el-tabs type="border-card" v-model="activeTab" class="result-tabs">
        <el-tab-pane name="terminal" label="🔴 指挥中心">
          <div class="mac-terminal">
            <div class="mac-header">
              <div class="mac-buttons">
                <span class="mac-btn red"></span>
                <span class="mac-btn yellow"></span>
                <span class="mac-btn green"></span>
              </div>
              <div class="mac-title">ai_council_logs.sh — bash — 80x24</div>
            </div>
            <div class="terminal-window" ref="terminalRef">
              <div class="markdown-body terminal-text" v-html="renderMarkdown(debateLogs || '> 等待信号接入...')"></div>
              <div class="blinking-cursor">_</div>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane name="data" label="📊 结构化数据">
          <div v-if="tableData.length > 0">
            <div class="data-header">
              <el-tag size="large" effect="plain">实体: {{ currentSchemaType }}</el-tag>
              <el-button type="success" @click="exportJSON" plain>
                <el-icon class="mr-1"><Download /></el-icon> 导出 JSON
              </el-button>
            </div>

            <el-table :data="tableData" border stripe height="600" style="width: 100%">
              <el-table-column type="index" width="50" />
              <el-table-column
                v-for="col in tableColumns"
                :key="col"
                :prop="col"
                :label="col"
                min-width="150"
                show-overflow-tooltip
              >
                <template #default="scope">
                  {{ formatCell(scope.row[col]) }}
                </template>
              </el-table-column>
              <el-table-column label="来源" width="80" fixed="right">
                <template #default="scope">
                  <a :href="scope.row.source_url" target="_blank" class="link-icon">🔗</a>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <el-empty v-else description="数据提取中 (大模型思考较慢，请稍候)..." />
        </el-tab-pane>

        <el-tab-pane name="pages" label="📄 网页透视">
          <div class="mb-2 flex-end">
            <span class="switch-label">AI 视角(去噪):</span>
            <el-switch
              v-model="showCleaned"
              inline-prompt
              active-text="ON"
              inactive-text="OFF"
              style="--el-switch-on-color: #13ce66"
            />
          </div>
          <el-collapse accordion>
            <el-collapse-item v-for="(res, index) in taskResults" :key="index" :name="index">
              <template #title>
                <el-tag size="small" :type="res.status_code === 200 ? 'success' : 'danger'" class="mr-2">
                  {{ res.status_code }}
                </el-tag>
                <span class="url-text" :title="res.url">{{ res.title || res.url }}</span>
              </template>
              <div class="page-preview">
                <div v-if="showCleaned">
                   <el-alert v-if="!res.media_info?.cleaned_markdown" title="原始内容 (无需去噪)" type="info" :closable="false" simple />
                   <div class="markdown-body" v-html="renderMarkdown(res.media_info?.cleaned_markdown || '')"></div>
                </div>
                <div v-else>
                   <div class="markdown-body" v-html="renderMarkdown(res.markdown_content)"></div>
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </el-tab-pane>

        <el-tab-pane name="report" label="📝 最终简报" v-if="aiSummary">
          <div class="report-paper">
            <div class="markdown-body summary-body" v-html="renderMarkdown(aiSummary)"></div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <el-drawer v-model="drawer" title="📜 任务历史" direction="ltr" size="30%">
      <div class="history-list">
        <el-card
          v-for="task in historyTasks"
          :key="task.id"
          class="history-item"
          :class="{ active: task.id === taskId }"
          @click="loadHistoryTask(task.id)"
          shadow="hover"
        >
          <div class="history-header">
            <el-tag size="small" :type="getTaskStatusType(task.status)">{{ task.status }}</el-tag>
            <span class="history-time">{{ task.created_at }}</span>
          </div>
          <div class="history-body">
            {{ task.user_request }}
          </div>
        </el-card>
        <el-empty v-if="historyTasks.length === 0" description="暂无历史记录" />
      </div>
    </el-drawer>

    <el-empty v-if="!taskId" description="准备就绪，请输入目标以启动全自动信息获取..." />
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage, ElNotification } from 'element-plus'
import { Search, Download, Clock, VideoPlay, Loading } from '@element-plus/icons-vue'
import MarkdownIt from 'markdown-it'

const md = new MarkdownIt()

// 状态
const userInput = ref('')
const mode = ref('url')
const loading = ref(false)
const taskId = ref('')
const activeTab = ref('terminal')
const terminalRef = ref(null)
const showCleaned = ref(false)
const drawer = ref(false)
const historyTasks = ref([])

// 任务详情
const taskStatus = ref('')
const taskResults = ref([])
const aiSummary = ref('')
const debateLogs = ref('')
const structuredDataRaw = ref(null)
const crawledCount = ref(0)
const totalEstimated = ref(0)

let pollTimer = null

// --- 🟢 新增：动态 Placeholder ---
const inputPlaceholder = computed(() => {
  if (mode.value === 'url') {
    return "请输入目标网址 + 需求 (如: https://cs.bit.edu.cn/... 提取教授姓名邮箱)"
  } else {
    return "请输入主题 (如: 最新的人工智能论文) - 注意: 纯主题搜索可能不够准确"
  }
})

// --- 初始化与持久化 ---
onMounted(() => {
  fetchHistory()
  const lastId = localStorage.getItem('lastTaskId')
  if (lastId) {
    loadHistoryTask(lastId, false)
  }
})

const fetchHistory = async () => {
  try {
    const res = await axios.get('/api/tasks')
    historyTasks.value = res.data
  } catch (e) {
    console.error("Fetch history failed", e)
  }
}

// --- 核心逻辑 ---

const startTask = async () => {
  if (!userInput.value) return ElMessage.warning('请输入需求')

  // 🟢 新增：前置校验逻辑
  if (mode.value === 'url') {
    // 简单校验是否包含 http/https
    const urlPattern = /https?:\/\//i
    if (!urlPattern.test(userInput.value)) {
      ElMessage.error('❌ 未检测到有效链接！URL模式下请输入以 http:// 或 https:// 开头的网址。')
      return
    }
  } else if (mode.value === 'topic') {
    // 主题模式提醒
    ElNotification({
      title: '⚠️ 模式提示',
      message: '您选择了按主题爬取。请注意，盘古大模型暂不支持实时联网搜索，建议您提供具体的 Seed URL (种子链接) 以获得更精准的结果。',
      type: 'warning',
      duration: 6000
    })
  }

  loading.value = true
  resetState()

  try {
    const res = await axios.post('/api/tasks', {
      user_request: userInput.value,
      mode: mode.value
    })
    taskId.value = res.data.task_id
    localStorage.setItem('lastTaskId', taskId.value)
    taskStatus.value = res.data.status

    // 🟢 新增：推理等待提示
    ElMessage.success({
      message: '🚀 任务启动！盘古大模型正在进行深度推理，请耐心等待 1-2 分钟...',
      duration: 5000
    })

    startPolling()
    fetchHistory()
  } catch (error) {
    console.error(error)
    ElMessage.error('启动失败')
    loading.value = false
  }
}

const loadHistoryTask = (id, openDrawer = true) => {
  if (pollTimer) clearInterval(pollTimer)
  taskId.value = id
  localStorage.setItem('lastTaskId', id)
  loading.value = true

  axios.get(`/api/tasks/${id}`).then(res => {
    updateTaskData(res.data)
    loading.value = false
    if (res.data.status === 'RUNNING' || res.data.status === 'PENDING') {
      startPolling()
    }
  }).catch(e => {
    console.error(e)
    loading.value = false
  })

  if (openDrawer) drawer.value = false
}

const startPolling = () => {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    try {
      const res = await axios.get(`/api/tasks/${taskId.value}`)
      updateTaskData(res.data)

      if (res.data.status === 'COMPLETED' || res.data.status === 'FAILED') {
        clearInterval(pollTimer)
        loading.value = false
        if (res.data.status === 'COMPLETED') ElMessage.success('任务完成')
        fetchHistory()
      }
    } catch (e) { console.error(e) }
  }, 2000)
}

const updateTaskData = (data) => {
  taskStatus.value = data.status
  crawledCount.value = data.crawled_count || 0
  totalEstimated.value = data.total_estimated || 0

  if (data.results) taskResults.value = data.results
  if (data.summary) aiSummary.value = data.summary
  if (data.debate_logs) debateLogs.value = data.debate_logs

  if (data.structured_data) {
    structuredDataRaw.value = data.structured_data
    if (activeTab.value === 'terminal' && tableData.value.length > 0 && taskStatus.value === 'COMPLETED') {
       activeTab.value = 'data'
    }
  }
}

const resetState = () => {
  taskId.value = ''
  taskStatus.value = ''
  taskResults.value = []
  structuredDataRaw.value = null
  debateLogs.value = ''
  crawledCount.value = 0
  totalEstimated.value = 0
  activeTab.value = 'terminal'
  showCleaned.value = false
  if (pollTimer) clearInterval(pollTimer)
}

// --- 计算属性与工具 ---

const progressValue = computed(() => {
  if (taskStatus.value === 'COMPLETED') return 100
  if (totalEstimated.value === 0) return 0
  return Math.min(99, Math.round((crawledCount.value / totalEstimated.value) * 100))
})

const statusTagType = computed(() => {
  const map = { PENDING: 'info', RUNNING: 'primary', COMPLETED: 'success', FAILED: 'danger' }
  return map[taskStatus.value] || 'info'
})

const getTaskStatusType = (status) => {
  const map = { PENDING: 'info', RUNNING: 'primary', COMPLETED: 'success', FAILED: 'danger' }
  return map[status] || 'info'
}

const currentSchemaType = computed(() => {
  return structuredDataRaw.value?.templates?.[0]?.entity_type || '通用数据'
})

const tableData = computed(() => {
  if (!structuredDataRaw.value?.templates?.[0]?.records) return []
  return structuredDataRaw.value.templates[0].records.map(r => ({
    ...r.fields,
    source_url: r.fields.source_url || ''
  }))
})

const tableColumns = computed(() => {
  if (tableData.value.length === 0) return []
  const keys = new Set()
  tableData.value.forEach(row => {
    Object.keys(row).forEach(k => {
      if (k !== 'source_url' && k !== 'title') keys.add(k)
    })
  })
  return Array.from(keys)
})

const formatCell = (val) => {
  if (val === null || val === undefined) return ''
  if (typeof val === 'object') return JSON.stringify(val)
  if (String(val).length > 80) return String(val).substring(0, 80) + '...'
  return val
}

const renderMarkdown = (text) => text ? md.render(text) : ''

const exportJSON = () => {
  const blob = new Blob([JSON.stringify(tableData.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `data_${taskId.value}.json`
  a.click()
}

watch(debateLogs, () => {
  nextTick(() => {
    if (terminalRef.value) terminalRef.value.scrollTop = terminalRef.value.scrollHeight
  })
})
</script>

<style scoped>
.app-container { max-width: 1200px; margin: 0 auto; padding: 20px; background: #f5f7fa; min-height: 100vh; font-family: 'Inter', sans-serif; }

/* 头部 */
.nav-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.app-title { font-weight: 800; color: #2c3e50; margin: 0; font-size: 24px; }
.version-tag { font-size: 12px; background: #61dafb; color: #000; padding: 2px 6px; border-radius: 4px; vertical-align: top; }

/* 状态栏 */
.status-bar { display: flex; align-items: center; gap: 15px; margin-bottom: 15px; background: #fff; padding: 10px; border-radius: 8px; border: 1px solid #ebeef5; }
.progress-wrapper { flex: 1; display: flex; flex-direction: column; justify-content: center; gap: 5px; }
.progress-labels { display: flex; justify-content: space-between; width: 100%; font-size: 12px; color: #909399; }
.loading-hint { color: #e6a23c; display: flex; align-items: center; gap: 5px; animation: pulse 2s infinite; }
.custom-progress { width: 100%; }

/* Mac Terminal Style */
.mac-terminal { background: #1e1e1e; border-radius: 8px; box-shadow: 0 10px 30px rgba(0,0,0,0.2); overflow: hidden; }
.mac-header { background: #2d2d2d; padding: 8px 12px; display: flex; align-items: center; position: relative; }
.mac-buttons { display: flex; gap: 6px; }
.mac-btn { width: 12px; height: 12px; border-radius: 50%; }
.red { background: #ff5f56; }
.yellow { background: #ffbd2e; }
.green { background: #27c93f; }
.mac-title { position: absolute; left: 50%; transform: translateX(-50%); color: #999; font-size: 12px; font-family: sans-serif; }
.terminal-window { padding: 15px; height: 450px; overflow-y: auto; color: #d4d4d4; font-family: 'JetBrains Mono', monospace; font-size: 13px; line-height: 1.6; }
.terminal-text :deep(p) { margin-bottom: 8px; }
.terminal-text :deep(strong) { color: #61dafb; }
.blinking-cursor { display: inline-block; width: 8px; height: 15px; background: #ccc; animation: blink 1s infinite; }

/* 历史列表 */
.history-list { padding: 10px; }
.history-item { cursor: pointer; margin-bottom: 10px; border-left: 4px solid transparent; transition: all 0.2s; }
.history-item:hover { transform: translateX(5px); }
.history-item.active { border-left-color: #409eff; background: #ecf5ff; }
.history-header { display: flex; justify-content: space-between; margin-bottom: 5px; }
.history-time { font-size: 11px; color: #999; }
.history-body { font-size: 13px; color: #333; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* 其他样式 */
.data-header { display: flex; justify-content: space-between; margin-bottom: 10px; }
.url-text { max-width: 500px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: inline-block; vertical-align: bottom; }
.flex-end { display: flex; justify-content: flex-end; align-items: center; gap: 10px; }
.switch-label { font-size: 13px; color: #666; }
.mr-1 { margin-right: 4px; }
.mr-2 { margin-right: 8px; }
.mb-4 { margin-bottom: 16px; }
@keyframes blink { 50% { opacity: 0; } }
@keyframes pulse { 0% { opacity: 0.6; } 50% { opacity: 1; } 100% { opacity: 0.6; } }
</style>
