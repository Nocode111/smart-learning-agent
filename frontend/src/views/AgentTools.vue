<template>
  <div class="agent-tools">
    <h2>🤖 Agent 工具箱</h2>

    <el-row :gutter="20">
      <el-col :span="14">
        <el-card>
          <template #header><span>📝 练习题生成</span></template>
          <el-form label-width="100px">
            <el-form-item label="课程">
              <el-select v-model="form.course_id" placeholder="选择课程" style="width: 100%">
                <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
              </el-select>
            </el-form-item>

            <el-form-item label="生成指令">
              <el-input
                v-model="form.prompt"
                type="textarea"
                :rows="3"
                placeholder="例如：生成一份5道有关栈的练习题"
                maxlength="500"
                show-word-limit
              />
            </el-form-item>

            <el-form-item label="难度">
              <el-select v-model="form.difficulty" style="width: 100%">
                <el-option label="自适应（根据画像）" value="adaptive" />
                <el-option label="基础" value="easy" />
                <el-option label="中等" value="medium" />
                <el-option label="较难" value="hard" />
              </el-select>
            </el-form-item>

            <el-form-item>
              <el-checkbox v-model="form.include_answer">包含答案</el-checkbox>
              <el-checkbox v-model="form.include_explanation" style="margin-left: 20px">包含解析</el-checkbox>
            </el-form-item>

            <el-button type="primary" :loading="loading" @click="generate">
              🚀 生成练习题文档
            </el-button>
          </el-form>
        </el-card>

        <!-- Agent 执行过程 -->
        <el-card v-if="agentSteps.length" style="margin-top: 20px">
          <template #header><span>🔍 Agent 执行过程</span></template>
          <el-steps direction="vertical" :active="agentSteps.length" finish-status="success">
            <el-step
              v-for="step in agentSteps"
              :key="step.title"
              :title="step.title"
              :description="step.detail"
            />
          </el-steps>
        </el-card>

        <!-- 生成结果 -->
        <el-card v-if="result" style="margin-top: 20px">
          <template #header>
            <div class="result-header">
              <span>📄 {{ result.title }}</span>
              <div>
                <el-button type="success" @click="download">
                  <el-icon><Download /></el-icon> 下载 Markdown
                </el-button>
              </div>
            </div>
          </template>
          <pre class="markdown-preview">{{ result.preview_content }}</pre>
        </el-card>
      </el-col>

      <!-- 右侧：历史记录 -->
      <el-col :span="10">
        <el-card>
          <template #header>
            <div class="history-header">
              <span>📋 历史生成记录</span>
              <el-select v-model="historyCourseId" placeholder="筛选课程" @change="fetchHistory" size="small" style="width: 140px" clearable>
                <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
              </el-select>
            </div>
          </template>
          <div v-if="historyList.length === 0" class="empty-tip">暂无生成记录</div>
          <div v-for="doc in historyList" :key="doc.id" class="history-item" @click="viewHistory(doc)">
            <div class="history-title">{{ doc.title }}</div>
            <div class="history-meta">
              <el-tag size="small" :type="doc.status === 'completed' ? 'success' : 'danger'">
                {{ doc.status === 'completed' ? '已完成' : '失败' }}
              </el-tag>
              <span class="history-time">{{ formatDate(doc.created_at) }}</span>
            </div>
            <div class="history-count">{{ doc.question_count }} 道题 · {{ doc.difficulty || '自适应' }}</div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Download } from '@element-plus/icons-vue'
import { courseAPI, exerciseGenerationAPI } from '../api'

const courses = ref([])
const loading = ref(false)
const agentSteps = ref([])
const result = ref(null)

const form = reactive({
  course_id: null,
  prompt: '',
  difficulty: 'adaptive',
  include_answer: true,
  include_explanation: true,
})

const historyCourseId = ref(null)
const historyList = ref([])

const fetchCourses = async () => {
  try {
    courses.value = await courseAPI.list()
    if (courses.value.length > 0) {
      form.course_id = courses.value[0].id
      historyCourseId.value = courses.value[0].id
      await fetchHistory()
    }
  } catch (e) {}
}

const fetchHistory = async () => {
  try {
    historyList.value = await exerciseGenerationAPI.list(historyCourseId.value || undefined)
  } catch (e) {}
}

const generate = async () => {
  if (!form.course_id) { ElMessage.warning('请选择课程'); return }
  if (!form.prompt.trim()) { ElMessage.warning('请输入生成指令'); return }

  loading.value = true
  agentSteps.value = []
  result.value = null

  try {
    result.value = await exerciseGenerationAPI.generate({
      course_id: form.course_id,
      prompt: form.prompt,
      difficulty: form.difficulty,
      include_answer: form.include_answer,
      include_explanation: form.include_explanation,
    })
    agentSteps.value = result.value.agent_steps || []
    ElMessage.success('练习题文档生成成功')
    await fetchHistory()
  } catch (e) {
    agentSteps.value = []
  }
  loading.value = false
}

const download = () => {
  if (!result.value) return
  const token = localStorage.getItem('token')
  const url = exerciseGenerationAPI.downloadUrl(result.value.id)
  fetch(url, { headers: { Authorization: `Bearer ${token}` } })
    .then(res => res.blob())
    .then(blob => {
      const blobUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = blobUrl
      a.download = result.value.file_name
      a.click()
      URL.revokeObjectURL(blobUrl)
    })
}

const viewHistory = async (doc) => {
  try {
    const detail = await exerciseGenerationAPI.get(doc.id)
    result.value = {
      id: detail.id,
      title: detail.title,
      file_name: detail.file_name,
      preview_content: detail.preview_content,
    }
    agentSteps.value = []
    ElMessage.success('已加载历史文档')
  } catch (e) {}
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return d.toLocaleString('zh-CN')
}

onMounted(() => {
  fetchCourses()
})
</script>

<style scoped>
.agent-tools h2 {
  margin-bottom: 20px;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.markdown-preview {
  background: #fafafa;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 24px;
  max-height: 600px;
  overflow: auto;
  line-height: 1.8;
  font-size: 14px;
}

.markdown-preview :deep(h1) {
  font-size: 22px;
  border-bottom: 2px solid #409eff;
  padding-bottom: 8px;
  margin-bottom: 16px;
}

.markdown-preview :deep(h2) {
  font-size: 18px;
  margin-top: 20px;
  margin-bottom: 10px;
}

.markdown-preview :deep(h3) {
  font-size: 15px;
  margin-top: 16px;
  margin-bottom: 8px;
}

.markdown-preview :deep(strong) {
  color: #409eff;
}

.markdown-preview :deep(hr) {
  margin: 16px 0;
  border: none;
  border-top: 1px solid #dcdfe6;
}

.markdown-preview :deep(code) {
  background: #f0f2f5;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 13px;
}

.history-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.empty-tip {
  color: #909399;
  text-align: center;
  padding: 30px;
}

.history-item {
  padding: 12px;
  border-bottom: 1px solid #ebeef5;
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.2s;
}

.history-item:hover {
  background: #f5f7fa;
}

.history-title {
  font-size: 14px;
  font-weight: 500;
  color: #303133;
  margin-bottom: 6px;
}

.history-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 4px;
}

.history-time {
  font-size: 12px;
  color: #909399;
}

.history-count {
  font-size: 12px;
  color: #606266;
}
</style>
