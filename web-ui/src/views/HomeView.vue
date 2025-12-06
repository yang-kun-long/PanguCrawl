<template>
  <div class="app-container">
    <el-card class="search-card">
      <h1 class="title">🕸️ 盘古深网爬虫控制台 (Ultimate)</h1>
      <div class="input-area">
        <el-input
          v-model="userInput"
          placeholder="请输入目标 + 需求 (如: 北理工计算机学院 教授名单)"
          class="search-input"
          @keyup.enter="startTask"
          :disabled="loading"
          size="large"
        >
          <template #prepend>
            <el-select v-model="mode" placeholder="模式" style="width: 110px">
              <el-option label="🔗 URL模式" value="url" />
              <el-option label="🧭 主题模式" value="topic" />
            </el-select>
          </template>
          <template #append>
            <el-button type="primary" @click="startTask" :loading="loading">
              <el-icon><Search /></el-icon> 启动
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
        </div>
        <el-progress :percentage="progressValue" :stroke-width="18" striped striped-flow :duration="10" />
      </div>

      <el-tabs type="border-card" v-model="activeTab" class="result-tabs">
        <!-- 🔴 直播 Tab -->
        <el-tab-pane name="terminal" label="🔴 实时日志">
          <div class="terminal-window" ref="terminalRef">
            <div class="markdown-body terminal-text" v-html="renderMarkdown(debateLogs)"></div>
          </div>
        </el-tab-pane>

        <!-- 📊 数据 Tab -->
        <el-tab-pane name="data" label="📊 结构化数据">
          <div v-if="tableData.length > 0">
            <div class="data-header">
              <el-tag size="large" effect="dark">实体: {{ currentSchemaType }}</el-tag>
              <el-button type="success" @click="exportJSON">
                <el-icon><Download /></el-icon> 导出 JSON
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
                  <a :href="scope.row.source_url" target="_blank">🔗</a>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <el-empty v-else description="数据提取中 或 未找到符合需求的数据..." />
        </el-tab-pane>

        <!-- 📄 网页 Tab (包含去噪开关) -->
        <el-tab-pane name="pages" label="📄 网页内容透视">
          <div class="mb-2" style="text-align: right;">
            <el-switch
              v-model="showCleaned"
              active-text="显示去噪后内容 (AI视角)"
              inactive-text="显示原始网页"
              inline-prompt
              size="large"
              style="--el-switch-on-color: #13ce66; --el-switch-off-color: #ff4949"
            />
          </div>
          <el-collapse accordion>
            <el-collapse-item v-for="(res, index) in taskResults" :key="index" :name="index">
              <template #title>
                <el-tag size="small" class="mr-2">{{ res.status_code }}</el-tag>
                <span class="url-text">{{ res.title || res.url }}</span>
              </template>

              <!-- 内容显示区域 -->
              <div class="page-preview">
                <!-- 显示去噪后 -->
                <div v-if="showCleaned">
                   <el-alert v-if="!res.media_info?.cleaned_markdown" title="该页面尚未去噪或无需去噪" type="info" :closable="false" />
                   <div class="markdown-body" v-html="renderMarkdown(res.media_info?.cleaned_markdown || '')"></div>
                </div>
                <!-- 显示原始 -->
                <div v-else>
                   <div class="markdown-body" v-html="renderMarkdown(res.markdown_content)"></div>
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </el-tab-pane>

        <!-- 📝 报告 Tab -->
        <el-tab-pane name="report" label="📝 最终简报" v-if="aiSummary">
          <div class="markdown-body summary-body" v-html="renderMarkdown(aiSummary)"></div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { Search, Download } from '@element-plus/icons-vue'
import MarkdownIt from 'markdown-it'

const md = new MarkdownIt()

const userInput = ref('')
const mode = ref('url')
const loading = ref(false)
const taskId = ref('')
const activeTab = ref('terminal')
const terminalRef = ref(null)
const showCleaned = ref(false) // 控制是否显示去噪内容

const taskStatus = ref('')
const taskResults = ref([])
const aiSummary = ref('')
const debateLogs = ref('')
const structuredDataRaw = ref(null)
const crawledCount = ref(0)
const totalEstimated = ref(0)

let pollTimer = null

const progressValue = computed(() => {
  if (taskStatus.value === 'COMPLETED') return 100
  if (totalEstimated.value === 0) return 0
  return Math.min(99, Math.round((crawledCount.value / totalEstimated.value) * 100))
})

const activeStep = computed(() => {
  if (!taskId.value) return 0
  if (taskStatus.value === 'RUNNING') return structuredDataRaw.value ? 3 : 2
  if (taskStatus.value === 'COMPLETED') return 4
  return 1
})

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
  if (String(val).length > 100) return String(val).substring(0, 100) + '...'
  return val
}

const startTask = async () => {
  if (!userInput.value) return ElMessage.warning('请输入需求')
  loading.value = true
  taskId.value = ''
  taskStatus.value = ''
  taskResults.value = []
  structuredDataRaw.value = null
  debateLogs.value = ''
  crawledCount.value = 0
  activeTab.value = 'terminal'
  showCleaned.value = false

  if (pollTimer) clearInterval(pollTimer)

  try {
    const res = await axios.post('/api/tasks', {
      user_request: userInput.value,
      mode: mode.value
    })
    taskId.value = res.data.task_id
    taskStatus.value = res.data.status
    ElMessage.success('任务启动')
    startPolling()
  } catch (error) {
    console.error(error)
    loading.value = false
  }
}

const startPolling = () => {
  pollTimer = setInterval(async () => {
    try {
      const res = await axios.get(`/api/tasks/${taskId.value}`)
      const data = res.data
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

      if (data.status === 'COMPLETED' || data.status === 'FAILED') {
        clearInterval(pollTimer)
        loading.value = false
        if (data.status === 'COMPLETED') ElMessage.success('任务完成')
      }
    } catch (e) { console.error(e) }
  }, 2000)
}

watch(debateLogs, () => {
  nextTick(() => {
    if (terminalRef.value) terminalRef.value.scrollTop = terminalRef.value.scrollHeight
  })
})

const renderMarkdown = (text) => text ? md.render(text) : ''

const exportJSON = () => {
  const blob = new Blob([JSON.stringify(tableData.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `data_${taskId.value}.json`
  a.click()
}
</script>

<style scoped>
.app-container { max-width: 1200px; margin: 0 auto; padding: 20px; font-family: sans-serif; background: #f5f7fa; min-height: 100vh; }
.title { text-align: center; margin-bottom: 20px; color: #333; }
.data-header { display: flex; justify-content: space-between; margin-bottom: 10px; }
.terminal-window { background: #1e1e1e; padding: 15px; height: 400px; overflow-y: auto; border-radius: 4px; color: #ccc; font-family: monospace; font-size: 13px; }
.url-text { max-width: 500px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: inline-block; vertical-align: bottom; }
.mb-4 { margin-bottom: 16px; }
.mr-2 { margin-right: 8px; }
.mb-2 { margin-bottom: 8px; }
</style>
