<template>
  <div class="qa-chat">
    <div class="chat-header">
      <el-select v-model="courseId" placeholder="选择课程" @change="onCourseChange" style="width: 240px">
        <el-option-group v-if="teacherCourses.length > 0" label="教师课程">
          <el-option v-for="c in teacherCourses" :key="c.id" :label="c.name" :value="c.id" />
        </el-option-group>
        <el-option-group v-if="studentCourses.length > 0" label="我的课程">
          <el-option v-for="c in studentCourses" :key="c.id" :label="c.name" :value="c.id" />
        </el-option-group>
      </el-select>
      <el-button size="small" type="primary" @click="showCreateDialog = true">+ 添加课程</el-button>
      <el-tag type="success" effect="plain">统一 Agent 入口 · 自动识别答疑 / 练习题生成</el-tag>
      <el-button size="small" @click="newConversation" :disabled="messages.length === 0">新建对话</el-button>
    </div>

    <div class="chat-messages" ref="chatBox">
      <div v-if="messages.length === 0" class="chat-welcome">
        <h3>🤖 统一 AI Agent</h3>
        <p>直接告诉我你的需求：</p>
        <div class="welcome-examples">
          <div class="example-item" @click="fillExample('栈和队列有什么区别？')">
            💬 栈和队列有什么区别？
          </div>
          <div class="example-item" @click="fillExample('帮我生成一份5道有关栈的练习题，要答案和解析')">
            📝 帮我生成一份5道有关栈的练习题，要答案和解析
          </div>
          <div class="example-item" @click="fillExample('帮我出5道栈的练习题，不要答案')">
            📝 帮我出5道栈的练习题，不要答案
          </div>
          <div class="example-item" @click="fillExample('再出3道题，不需要答案和解析，也不用出文档，只需要用文字发给我，然后我把答案发给你，你来看我是否正确理解了这个知识点')">
            💬 出3道题，不用文档，文字发给我，我答完你批改
          </div>
          <div class="example-item" @click="fillExample('帮我制定一份数据结构期末复习计划，目标60分')">
            🎯 帮我制定一份数据结构期末复习计划，目标 60 分
          </div>
          <div class="example-item" @click="fillExample('继续推进我的数据结构期末目标')">
            🔄 继续推进我的数据结构期末目标
          </div>
          <div style="margin-top: 12px; color: #909399; font-size: 13px;">
            📎 你也可以上传文档（PDF/Word/PPT/TXT），然后提问"总结这个文档"或"根据上传的资料出几道题"
          </div>
        </div>
      </div>

      <div v-for="(msg, index) in messages" :key="index" :class="['message', msg.role]">
        <div class="message-avatar">
          <el-avatar :size="36" :style="{ background: msg.role === 'user' ? '#409eff' : '#67c23a' }">
            {{ msg.role === 'user' ? '我' : 'AI' }}
          </el-avatar>
        </div>
        <div class="message-content">
          <!-- 普通文本回答 -->
          <div
            v-if="(msg.type === 'answer' || msg.type === 'text' || !msg.type) && msg.status !== 'canceled'"
            class="message-text"
            v-html="formatMessage(msg.content)"
          ></div>

          <!-- 附件上传卡片 -->
          <div v-if="msg.type === 'attachment_upload' && msg.attachments?.length" class="attachment-list">
            <div v-for="attachment in msg.attachments" :key="attachment.id" class="attachment-card">
              <div class="attachment-icon">📄</div>
              <div class="attachment-info">
                <div class="attachment-title">{{ attachment.title }}</div>
                <div class="attachment-meta">
                  {{ attachment.original_file_name }} · {{ formatFileSize(attachment.file_size) }}
                </div>
                <div class="attachment-status" :class="{ 'attachment-removed-status': isAttachmentRemoved(attachment) }">
                  <span v-if="isAttachmentRemoved(attachment)">🗑 已移除</span>
                  <span v-else-if="attachment.status === 'deleting'">⏳ 正在移除</span>
                  <span v-else-if="attachment.status === 'delete_failed'">❌ 移除失败，可重试</span>
                  <span v-else-if="attachment.index_status === 'indexed'">✅ 已读入</span>
                  <span v-else-if="attachment.index_status === 'pending'">⏳ 处理中</span>
                  <span v-else-if="attachment.index_status === 'failed'">❌ 索引失败</span>
                  <span v-else>📤 已上传</span>
                </div>
              </div>
              <div class="attachment-actions">
                <el-button size="small" @click="previewAttachment(attachment)" :disabled="isAttachmentRemoved(attachment)">预览</el-button>
                <el-button size="small" @click="downloadAttachment(attachment)" :disabled="isAttachmentRemoved(attachment)">下载</el-button>
                <el-button
                  v-if="!isAttachmentRemoved(attachment)"
                  class="attachment-remove-btn"
                  text
                  type="danger"
                  :loading="removingAttachmentIds[attachment.id]"
                  @click="removeAttachment(attachment)"
                >×</el-button>
              </div>
            </div>
          </div>

          <!-- 练习批改结果（文档 Section 19.3） -->
          <div v-if="msg.practiceResult" class="practice-result-card">
            <div class="practice-result-header">
              <span :class="msg.practiceResult.is_correct ? 'correct-badge' : 'wrong-badge'">
                {{ msg.practiceResult.is_correct ? '✓ 回答正确' : '✗ 回答错误' }}
              </span>
              <span class="practice-question-no">第 {{ msg.practiceResult.question_no }} 题</span>
            </div>
            <div class="practice-result-body">
              <div class="practice-answer-row">
                <span>你的答案：<strong>{{ msg.practiceResult.submitted_answer }}</strong></span>
                <span v-if="!msg.practiceResult.is_correct">
                  正确答案：<strong>{{ msg.practiceResult.correct_answer }}</strong>
                </span>
              </div>
              <div v-if="msg.practiceResult.feedback_text" class="practice-feedback">
                {{ msg.practiceResult.feedback_text }}
              </div>
              <div v-if="msg.practiceResult.completed" class="practice-completed">
                🎉 这组练习已完成！
              </div>
            </div>
          </div>

          <!-- 本地文件修改预览卡片（文档 Section 16.3） -->
          <div
            v-if="msg.type === 'local_file_edit_preview' && msg.localFileOperation"
            class="local-file-card"
          >
            <div class="local-file-card-header">
              <strong>📝 本地文件修改预览</strong>
              <el-tag size="small" :type="localFileStatusType(msg.localFileOperation.status)">
                {{ localFileStatusText(msg.localFileOperation.status) }}
              </el-tag>
            </div>

            <div class="local-file-meta">
              <div>📄 文件：{{ msg.localFileOperation.file_name }}</div>
              <div>📂 路径：{{ msg.localFileOperation.display_path }}</div>
              <div v-if="msg.localFileOperation.summary">
                ✏️ 修改摘要：{{ msg.localFileOperation.summary }}
              </div>
            </div>

            <pre class="local-file-diff">{{ msg.localFileOperation.diff_text }}</pre>

            <div class="local-file-actions">
              <el-button
                size="small"
                type="primary"
                :disabled="msg.localFileOperation.status !== 'preview_ready'"
                @click="confirmLocalFileEdit(msg)"
              >
                确认修改
              </el-button>
              <el-button
                size="small"
                :disabled="msg.localFileOperation.status !== 'preview_ready'"
                @click="cancelLocalFileEdit(msg)"
              >
                取消修改
              </el-button>
              <el-button
                v-if="msg.localFileOperation.status === 'applied'"
                size="small"
                type="warning"
                @click="restoreLocalFileEdit(msg)"
              >
                恢复备份
              </el-button>
            </div>
          </div>

          <!-- 目标自主推进循环卡片（文档 Section 24.1） -->
          <div v-if="msg.type === 'goal_loop_result' && msg.goalLoop" class="goal-loop-card">
            <div class="goal-loop-card-header">
              <strong>🎯 目标已推进</strong>
              <el-tag size="small" :type="loopStatusType(msg.goalLoop.status)">
                {{ loopStatusLabel(msg.goalLoop.status) }}
              </el-tag>
            </div>
            <div class="goal-loop-summary">
              {{ msg.goalLoop.summary }}
            </div>
            <div class="goal-loop-meta">
              <span>本次推进 {{ msg.goalLoop.completed_iterations }} 轮</span>
              <span v-if="msg.goalLoop.stop_reason" style="margin-left: 12px">
                暂停原因：{{ loopStopReasonLabel(msg.goalLoop.stop_reason) }}
              </span>
            </div>
            <div class="goal-loop-actions">
              <el-button size="small" type="primary" @click="goLearningGoal(msg.goalLoop.goal_id)">
                查看目标
              </el-button>
              <el-button
                v-if="msg.goalLoop.action_type === 'practice_session' && msg.goalLoop.action_payload?.session_id"
                size="small"
                type="success"
                @click="openLoopPractice(msg.goalLoop)"
              >
                开始练习
              </el-button>
              <el-button
                v-else-if="msg.goalLoop.action_type === 'read_document'"
                size="small"
                type="success"
                @click="goLearningGoal(msg.goalLoop.goal_id)"
              >
                阅读文档
              </el-button>
              <el-button
                v-else-if="msg.goalLoop.status === 'completed' || msg.goalLoop.status === 'budget_exhausted'"
                size="small"
                type="success"
                @click="goLearningGoal(msg.goalLoop.goal_id)"
              >
                继续推进
              </el-button>
            </div>
          </div>

          <!-- 学习目标卡片（对话式目标创建阶段 Section 17.3） -->
          <div v-if="msg.type === 'learning_goal_created' && msg.learningGoal" class="learning-goal-card">
            <div class="learning-goal-card-header">
              <strong>🎯 学习目标已创建</strong>
              <el-tag size="small" type="success">已生成计划</el-tag>
            </div>
            <div class="learning-goal-title">{{ msg.learningGoal.title }}</div>
            <div class="learning-goal-summary" v-if="msg.goalPlan?.plan_summary">
              {{ msg.goalPlan.plan_summary }}
            </div>
            <div class="learning-goal-actions">
              <el-button size="small" type="primary" @click="goLearningGoal(msg.learningGoal.id)">
                查看学习计划
              </el-button>
              <el-button size="small" type="success" @click="goLearningGoal(msg.learningGoal.id, 'advance')">
                开始第一步
              </el-button>
            </div>
          </div>

          <!-- 澄清提示 -->
          <div v-if="msg.type === 'clarification'" class="message-text clarification-text">
            <el-icon style="margin-right: 6px"><InfoFilled /></el-icon>
            {{ msg.content }}
          </div>

          <!-- 文档卡片 -->
          <div v-if="msg.type === 'document' && msg.document" class="document-card">
            <div class="document-card-header">
              <el-icon size="20" color="#409eff"><Document /></el-icon>
              <span class="document-title">{{ msg.document.title }}</span>
            </div>
            <div class="document-file">📄 {{ msg.document.file_name }}</div>
            <div class="document-actions">
              <el-button size="small" @click="previewDocument(msg.document)">🔍 预览</el-button>
              <el-button size="small" type="success" @click="downloadDocument(msg.document)">⬇ 下载 Markdown</el-button>
            </div>
          </div>

          <!-- Agent 工作过程 -->
          <div v-if="msg.agentSteps?.length" class="agent-trace">
            <div class="agent-trace-title">🔍 Agent 执行过程</div>
            <el-steps direction="vertical" :active="msg.agentSteps.length" finish-status="success">
              <el-step
                v-for="step in msg.agentSteps"
                :key="step.title"
                :title="step.title"
                :description="step.detail"
              />
            </el-steps>
          </div>

          <!-- 二期：取消后操作 -->
          <div v-if="msg.status === 'canceled'" class="canceled-message">
            <div class="canceled-text">本次提问已停止。</div>
            <div class="canceled-actions">
              <el-button size="small" @click="continueAsk">继续提问</el-button>
              <el-button size="small" type="primary" @click="retryCanceledQuestion">修改后重问</el-button>
            </div>
          </div>

          <!-- 反馈按钮（仅答疑类型） -->
          <div v-if="msg.qaId" class="message-actions">
            <el-button size="small" type="success" @click="submitFeedback(msg.qaId, true)">已解决</el-button>
            <el-button size="small" type="danger" @click="submitFeedback(msg.qaId, false)">未解决</el-button>
          </div>
        </div>
      </div>

      <div v-if="loading && !activeTaskUuid" class="message assistant">
        <div class="message-avatar">
          <el-avatar :size="36" style="background: #67c23a">AI</el-avatar>
        </div>
        <div class="message-content">
          <div class="agent-running">
            <div>Agent 正在执行：识别意图 → 抽取参数 → 读取画像 → 检索知识库 → 生成结果</div>
            <div class="typing-indicator"><span></span><span></span><span></span></div>
          </div>
        </div>
      </div>
    </div>

    <div class="chat-input">
      <div class="chat-input-row">
        <el-upload
          :show-file-list="false"
          :http-request="uploadAttachment"
          :before-upload="beforeAttachmentUpload"
          accept=".txt,.md,.pdf,.docx,.pptx"
        >
          <el-button :disabled="loading || uploading || !courseId" :loading="uploading">
            📎 上传
          </el-button>
        </el-upload>

        <el-input
          v-model="question"
          placeholder="输入你的问题，也可以先上传文档后提问"
          size="large"
          @keyup.enter="askQuestion"
          :disabled="loading || !courseId"
          clearable
        />

        <el-button
          v-if="sendingState !== 'sending' && sendingState !== 'canceling'"
          type="primary"
          @click="askQuestion"
          :disabled="loading || !courseId || !question.trim()"
        >
          发送
        </el-button>
        <el-button
          v-if="sendingState === 'sending' || sendingState === 'canceling'"
          type="danger"
          :loading="sendingState === 'canceling'"
          :disabled="sendingState === 'canceling'"
          @click="stopQuestion"
        >
          停止
        </el-button>
      </div>
    </div>

    <!-- 添加课程弹窗 -->
    <el-dialog v-model="showCreateDialog" title="添加课程" width="480px" top="10vh">
      <el-form :model="createForm" label-width="100px">
        <el-form-item label="课程名称" required>
          <el-input v-model="createForm.name" placeholder="例如：操作系统" />
        </el-form-item>
        <el-form-item label="课程描述">
          <el-input v-model="createForm.description" type="textarea" :rows="2" placeholder="准备期末考试，重点学习进程、内存和文件系统" />
        </el-form-item>
        <el-form-item label="学习目标">
          <el-input v-model="createForm.learning_goal" placeholder="例如：期末复习" />
        </el-form-item>
        <el-form-item label="自动生成大纲">
          <el-switch v-model="createForm.auto_generate_outline" />
          <span style="margin-left: 8px; color: #909399; font-size: 13px;">开启后 AI 自动生成知识点大纲</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="createStudentCourse" :loading="creating">创建</el-button>
      </template>
    </el-dialog>

    <!-- 文档预览弹窗 -->
    <el-dialog v-model="previewVisible" title="文档预览" width="760px" top="5vh">
      <pre class="markdown-preview">{{ previewContent }}</pre>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { InfoFilled, Document } from '@element-plus/icons-vue'
import { useUserStore } from '../stores/user'
import { courseAPI, qaAPI, agentAPI, exerciseGenerationAPI, agentAttachmentAPI, agentTaskAPI, agentLocalFileAPI } from '../api'

const userStore = useUserStore()
const route = useRoute()
const router = useRouter()
const courses = ref([])
const courseId = ref(null)
const question = ref('')
const messages = ref([])
const loading = ref(false)
const uploading = ref(false)
const chatBox = ref(null)

const previewVisible = ref(false)
const previewContent = ref('')
const conversationId = ref(null)

// 添加课程弹窗
const showCreateDialog = ref(false)
const creating = ref(false)
const createForm = ref({
  name: '',
  description: '',
  learning_goal: '',
  auto_generate_outline: true,
})

// 二期：附件移除状态
const removingAttachmentIds = ref({})

// 二期：提问取消状态
const sendingState = ref('idle') // idle | sending | canceling | canceled
const stoppedQuestion = ref('')
const activeTaskUuid = ref(null)
const activeEventSource = ref(null)
const activeAssistantMessageId = ref(null)
const pendingStopRequested = ref(false)
const locallyCanceledTaskUuids = ref(new Set())

// 课程分组（文档 Section 18.2）
const teacherCourses = computed(() => courses.value.filter(c => c.course_type === 'teacher'))
const studentCourses = computed(() => courses.value.filter(c => c.course_type === 'student'))

const getConversationStorageKey = () => {
  return `agent_conversation_${userStore.user?.id}_${courseId.value}`
}

const restoreConversationMessages = async (savedConvId) => {
  const conversationMessages = await agentAPI.messages(savedConvId)
  if (!conversationMessages || conversationMessages.length === 0) {
    return false
  }

  messages.value = conversationMessages
    .filter((m) => m.role === 'user' || m.role === 'assistant')
    .map((m) => {
      const msg = {
        id: m.id,
        role: m.role,
        type: m.role === 'user' ? (m.message_type === 'attachment_upload' ? 'attachment_upload' : 'text') : (m.message_type || 'answer'),
        content: m.content,
        qaId: m.qa_id,
        document: m.metadata_json?.document || null,
        agentSteps: m.agent_steps_json || [],
        retrievedChunks: m.retrieved_chunks_json || [],
        practiceSession: m.metadata_json?.practice_session || null,
        practiceResult: m.metadata_json?.practice_result || null,
        attachments: m.metadata_json?.attachments || [],
        localFileOperation: m.metadata_json?.local_file_operation || null,
        learningGoal: m.metadata_json?.learning_goal || null,
        goalPlan: m.metadata_json?.goal_plan || null,
        goalLoop: m.metadata_json?.goal_loop || null,
        status: m.status || 'completed',
        taskId: m.task_id,
        clientRequestId: m.client_request_id,
        errorMessage: m.error_message,
      }
      // 刷新恢复：pending/running 消息说明上次未完成（文档 Section 16）
      if (msg.status === 'pending' || msg.status === 'running') {
        return {
          ...msg,
          status: 'failed',
          content: '上次提问未完成，请重新提问。',
        }
      }
      return msg
    })
  conversationId.value = savedConvId
  localStorage.setItem(getConversationStorageKey(), String(savedConvId))
  await scrollToBottom()
  return true
}

const fetchCourses = async () => {
  try {
    courses.value = await courseAPI.list()
    if (courses.value.length > 0) {
      const queryCourseId = Number(route.query.courseId)
      courseId.value = courses.value.some((c) => c.id === queryCourseId) ? queryCourseId : courses.value[0].id
      if (route.query.prompt) {
        question.value = String(route.query.prompt)
      }
      await onCourseChange(courseId.value)
    }
  } catch (e) {}
}

const createStudentCourse = async () => {
  if (!createForm.value.name.trim()) {
    ElMessage.warning('请输入课程名称')
    return
  }
  creating.value = true
  try {
    await courseAPI.createStudentCourse({
      name: createForm.value.name.trim(),
      description: createForm.value.description || null,
      learning_goal: createForm.value.learning_goal || null,
      auto_generate_outline: createForm.value.auto_generate_outline,
    })
    ElMessage.success('课程创建成功')
    showCreateDialog.value = false
    // 重置表单
    createForm.value = { name: '', description: '', learning_goal: '', auto_generate_outline: true }
    // 重新拉取课程列表
    await fetchCourses()
    // 自动切换到新课程
    if (courses.value.length > 0) {
      courseId.value = courses.value[courses.value.length - 1].id
      await onCourseChange(courseId.value)
    }
  } catch (e) {
    // 错误已在拦截器处理
  } finally {
    creating.value = false
  }
}

const onCourseChange = async (val) => {
  // 尝试恢复最近会话
  const saved = localStorage.getItem(getConversationStorageKey())
  const savedConvId = saved ? Number(saved) : null

  if (savedConvId) {
    try {
      if (await restoreConversationMessages(savedConvId)) {
        return
      }
    } catch (e) {
      // 会话过期或不存在，清除本地记录
      localStorage.removeItem(getConversationStorageKey())
      conversationId.value = null
    }
  }

  // 本地没有 conversation_id 时，从后端恢复当前课程最近的 Agent 会话
  try {
    const recent = await agentAPI.recentConversation(val)
    if (recent?.id && await restoreConversationMessages(recent.id)) {
      return
    }
  } catch (e) {
    conversationId.value = null
  }

  // 兜底：加载旧历史
  try {
    const [qaHistory, documentHistory] = await Promise.all([
      qaAPI.history(val),
      exerciseGenerationAPI.list(val),
    ])

    const qaEvents = qaHistory.map((r) => ({
      createdAt: r.created_at,
      messages: [
        { role: 'user', content: r.question },
        { role: 'assistant', type: 'answer', content: r.answer, qaId: r.id },
      ],
    }))

    const documentEvents = documentHistory.map((doc) => ({
      createdAt: doc.created_at,
      messages: [
        { role: 'user', content: doc.prompt },
        {
          role: 'assistant',
          type: 'document',
          content: `已生成《${doc.file_name}》。`,
          document: {
            id: doc.id,
            title: doc.title,
            file_name: doc.file_name,
            preview_content: doc.preview_content,
            download_url: exerciseGenerationAPI.downloadUrl(doc.id),
          },
          agentSteps: doc.agent_steps_json || [],
          retrievedChunks: [],
        },
      ],
    }))

    messages.value = [...qaEvents, ...documentEvents]
      .sort((a, b) => new Date(a.createdAt) - new Date(b.createdAt))
      .flatMap((event) => event.messages)
  } catch (e) {
    messages.value = []
  }
  await scrollToBottom()
}

const askQuestion = async () => {
  if (!question.value.trim() || !courseId.value || sendingState.value === 'sending' || sendingState.value === 'canceling') return
  const q = question.value.trim()
  question.value = ''
  sendingState.value = 'sending'
  stoppedQuestion.value = q
  pendingStopRequested.value = false
  loading.value = true

  try {
    const res = await agentTaskAPI.create({
      course_id: courseId.value,
      conversation_id: conversationId.value,
      message: q,
      attachment_ids: [],
      client_request_id: createClientRequestId(),
    })

    conversationId.value = res.conversation_id
    localStorage.setItem(getConversationStorageKey(), String(res.conversation_id))

    messages.value.push({
      id: res.user_message?.id,
      role: 'user',
      type: 'text',
      content: res.user_message?.content || q,
      status: 'completed',
    })

    const assistantMessage = {
      id: res.assistant_message?.id,
      role: 'assistant',
      type: res.assistant_message?.message_type || 'answer',
      content: '正在思考...',
      agentSteps: [],
      retrievedChunks: [],
      status: res.assistant_message?.status || 'pending',
    }
    messages.value.push(assistantMessage)
    await scrollToBottom()

    activeTaskUuid.value = res.task_uuid
    activeAssistantMessageId.value = assistantMessage.id

    if (pendingStopRequested.value) {
      await stopQuestion()
      return
    }

    connectTaskEvents(res.task_uuid, assistantMessage.id)
  } catch (e) {
    // 会话不存在或过期，清除并重试
    if (e.response?.status === 400 || e.response?.status === 404) {
      localStorage.removeItem(getConversationStorageKey())
      conversationId.value = null
    }
    sendingState.value = 'idle'
    loading.value = false
    ElMessage.error(e.response?.data?.detail || e.message || '请求失败，请稍后重试')
    await scrollToBottom()
  }
}

const submitFeedback = async (qaId, resolved) => {
  try {
    await qaAPI.feedback(qaId, { resolved, comment: '' })
    ElMessage.success(resolved ? '已记录：问题解决' : '已记录：未解决，画像会继续更新')
  } catch (e) {}
}

const previewDocument = (doc) => {
  previewContent.value = doc.preview_content || ''
  previewVisible.value = true
}

const downloadDocument = (doc) => {
  const token = localStorage.getItem('token')
  const url = doc.download_url
  if (url.startsWith('/')) {
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then(res => {
        if (!res.ok) {
          throw new Error('下载失败，请稍后重试')
        }
        return res.blob()
      })
      .then(blob => {
        const blobUrl = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = blobUrl
        a.download = doc.file_name
        a.click()
        URL.revokeObjectURL(blobUrl)
      })
      .catch((e) => ElMessage.error(e.message || '下载失败，请稍后重试'))
  } else {
    window.open(url, '_blank')
  }
}

// ── 附件上传/预览/下载（文档 Section 18.3-18.7） ──────────

const beforeAttachmentUpload = (file) => {
  const allowedTypes = ['.txt', '.md', '.pdf', '.docx', '.pptx']
  const suffix = '.' + file.name.split('.').pop().toLowerCase()
  if (!allowedTypes.includes(suffix)) {
    ElMessage.error(`不支持的文件类型。允许：${allowedTypes.join(', ')}`)
    return false
  }
  if (file.size > 20 * 1024 * 1024) {
    ElMessage.error('文件大小不能超过 20MB')
    return false
  }
  return true
}

const uploadAttachment = async ({ file }) => {
  if (!courseId.value) {
    ElMessage.warning('请先选择课程')
    return
  }

  uploading.value = true
  try {
    const formData = new FormData()
    formData.append('course_id', courseId.value)
    if (conversationId.value) {
      formData.append('conversation_id', conversationId.value)
    }
    formData.append('title', file.name.replace(/\.[^.]+$/, ''))
    formData.append('auto_index', 'true')
    formData.append('file', file)

    const res = await agentAttachmentAPI.upload(formData)

    conversationId.value = res.conversation_id
    localStorage.setItem(getConversationStorageKey(), String(res.conversation_id))

    messages.value.push({
      role: 'user',
      type: 'attachment_upload',
      content: `我上传了附件《${res.attachment.title}》。`,
      attachments: [res.attachment],
    })

    ElMessage.success('附件上传成功，可以继续提问')
    await scrollToBottom()
  } catch (e) {
    // 错误已在拦截器处理
  } finally {
    uploading.value = false
  }
}

const previewAttachment = async (attachment) => {
  try {
    const res = await agentAttachmentAPI.preview(attachment.id)
    previewContent.value = res.content_preview || '（无可预览文本）'
    previewVisible.value = true
  } catch (e) {
    ElMessage.error('预览失败')
  }
}

const downloadAttachment = (attachment) => {
  const token = localStorage.getItem('token')
  fetch(agentAttachmentAPI.downloadUrl(attachment.id), {
    headers: { Authorization: `Bearer ${token}` },
  })
    .then(res => {
      if (!res.ok) throw new Error('下载失败')
      return res.blob()
    })
    .then(blob => {
      const blobUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = blobUrl
      a.download = attachment.original_file_name
      a.click()
      URL.revokeObjectURL(blobUrl)
    })
    .catch(() => ElMessage.error('下载失败'))
}

// ── 二期：附件移除方法 ──────────────────────────────────

const isAttachmentRemoved = (attachment) => {
  return attachment.status === 'removed' || attachment.index_status === 'removed' || attachment.removed === true
}

const removeAttachment = async (attachment) => {
  try {
    await ElMessageBox.confirm(
      `确定从当前对话移除《${attachment.title}》吗？移除后 AI 不会再基于该文件回答。`,
      '移除附件',
      { type: 'warning', confirmButtonText: '移除', cancelButtonText: '取消' }
    )
  } catch {
    return // 用户取消
  }

  removingAttachmentIds.value[attachment.id] = true
  try {
    const res = await agentAttachmentAPI.remove(attachment.id, {
      delete_physical_file: false,
      reason: 'user_removed',
    })
    if (!res.already_removed) {
      markAttachmentRemovedInMessages(res.attachment)
      ElMessage.success('附件已移除')
    }
  } catch (e) {
    ElMessage.error('附件移除失败')
  } finally {
    removingAttachmentIds.value[attachment.id] = false
  }
}

const markAttachmentRemovedInMessages = (removedAttachment) => {
  messages.value = messages.value.map((msg) => {
    if (!msg.attachments?.length) return msg
    return {
      ...msg,
      attachments: msg.attachments.map((a) => {
        if (a.id !== removedAttachment.id) return a
        return {
          ...a,
          status: 'removed',
          index_status: 'removed',
          removed: true,
          removed_at: removedAttachment.deleted_at,
        }
      }),
    }
  })
}

// ── 二期：提问取消方法 ──────────────────────────────────

const createClientRequestId = () => {
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID()
  }
  return `req_${Date.now()}_${Math.random().toString(16).slice(2)}`
}

const patchMessageById = (messageId, patch) => {
  if (!messageId) return
  messages.value = messages.value.map((msg) => {
    if (msg.id !== messageId) return msg
    const nextPatch = typeof patch === 'function' ? patch(msg) : patch
    return { ...msg, ...nextPatch }
  })
}

const markCurrentTaskCanceledLocally = () => {
  if (activeTaskUuid.value) {
    locallyCanceledTaskUuids.value.add(activeTaskUuid.value)
  }
  patchMessageById(activeAssistantMessageId.value, {
    content: '本次提问已停止。',
    status: 'canceled',
    type: 'answer',
    qaId: null,
    document: null,
    agentSteps: [],
    retrievedChunks: [],
    practiceSession: null,
    practiceResult: null,
    attachments: [],
  })
}

const finishCanceledTaskLocally = () => {
  markCurrentTaskCanceledLocally()
  sendingState.value = 'idle'
  cleanupActiveTask()
}

const connectTaskEvents = (taskUuid, assistantMessageId) => {
  cleanupActiveTask({ closeOnly: true, keepLoading: true })

  const token = localStorage.getItem('token') || ''
  const url = `${agentTaskAPI.eventsUrl(taskUuid)}?token=${encodeURIComponent(token)}`
  const eventSource = new EventSource(url)
  activeEventSource.value = eventSource

  eventSource.addEventListener('stage', (event) => {
    if (locallyCanceledTaskUuids.value.has(taskUuid)) return
    if (activeTaskUuid.value !== taskUuid) return
    const data = JSON.parse(event.data || '{}')
    patchMessageById(assistantMessageId, (msg) => ({
      status: 'running',
      agentSteps: [
        ...(msg.agentSteps || []),
        {
          title: data.text || data.stage || '处理中',
          detail: data.stage || '',
        },
      ],
    }))
  })

  eventSource.addEventListener('token', (event) => {
    if (locallyCanceledTaskUuids.value.has(taskUuid)) return
    if (activeTaskUuid.value !== taskUuid) return
    const data = JSON.parse(event.data || '{}')
    const tokenText = data.text || ''
    patchMessageById(assistantMessageId, (msg) => ({
      status: 'running',
      content: `${msg.content === '正在思考...' ? '' : (msg.content || '')}${tokenText}`,
    }))
    scrollToBottom()
  })

  // 工具结果事件（文档 Section 12.4）
  eventSource.addEventListener('tool_result', (event) => {
    if (locallyCanceledTaskUuids.value.has(taskUuid)) return
    if (activeTaskUuid.value !== taskUuid) return
    const data = JSON.parse(event.data || '{}')
    patchMessageById(assistantMessageId, {
      status: 'running',
      type: data.message_type || 'answer',
      content: data.text || '',
      localFileOperation: data.local_file_operation || null,
      practiceSession: data.practice_session || null,
      practiceResult: data.practice_result || null,
      document: data.document || null,
      attachments: data.attachments || [],
      learningGoal: data.learning_goal || null,
      goalPlan: data.goal_plan || null,
      goalLoop: data.goal_loop || null,
    })
    scrollToBottom()
  })

  // 心跳事件 — 直接忽略，仅用于保活（文档 Section 4.1）
  eventSource.addEventListener('heartbeat', () => {})

  eventSource.addEventListener('task_completed', (event) => {
    if (locallyCanceledTaskUuids.value.has(taskUuid)) return
    if (activeTaskUuid.value !== taskUuid) return
    const data = JSON.parse(event.data || '{}')
    const message = data.message || {}
    patchMessageById(assistantMessageId, {
      content: message.content || '',
      type: message.message_type || message.type || 'answer',
      qaId: message.qa_id,
      document: message.document || null,
      agentSteps: message.agent_steps || [],
      retrievedChunks: message.retrieved_chunks || [],
      practiceSession: message.practice_session || null,
      practiceResult: message.practice_result || null,
      attachments: message.attachments || [],
      localFileOperation: message.local_file_operation || null,
      learningGoal: message.learning_goal || null,
      goalPlan: message.goal_plan || null,
      goalLoop: message.goal_loop || null,
      status: 'completed',
    })
    sendingState.value = 'idle'
    cleanupActiveTask()
    scrollToBottom()
  })

  eventSource.addEventListener('task_canceled', (event) => {
    if (locallyCanceledTaskUuids.value.has(taskUuid)) return
    if (activeTaskUuid.value !== taskUuid) return
    const data = JSON.parse(event.data || '{}')
    patchMessageById(assistantMessageId, {
      content: data.text || '本次提问已停止。',
      status: 'canceled',
    })
    sendingState.value = 'idle'
    cleanupActiveTask()
    scrollToBottom()
  })

  eventSource.addEventListener('task_failed', (event) => {
    if (locallyCanceledTaskUuids.value.has(taskUuid)) return
    if (activeTaskUuid.value !== taskUuid) return
    const data = JSON.parse(event.data || '{}')
    patchMessageById(assistantMessageId, {
      content: data.error || '生成失败，请重新提问。',
      status: 'failed',
      errorMessage: data.error,
    })
    sendingState.value = 'idle'
    cleanupActiveTask()
    scrollToBottom()
  })

  // SSE onerror 处理（文档 Section 20.7）
  // EventSource.onerror 可能由多种原因触发（用户关闭、正常结束、网络波动），
  // 不能无脑显示"连接已中断"。先检查消息是否已有最终状态。
  eventSource.onerror = () => {
    // 本端已取消的任务：忽略
    if (locallyCanceledTaskUuids.value.has(taskUuid)) return
    // 不是当前活跃任务：忽略
    if (activeTaskUuid.value !== taskUuid) return
    // 正在取消中：忽略
    if (sendingState.value === 'canceling' || sendingState.value === 'canceled') return

    // 检查 assistant 消息是否已有最终状态
    const assistantMsg = messages.value.find((m) => m.id === assistantMessageId)
    if (assistantMsg) {
      // 任务已正常完成：忽略（可能是 EventSource 正常关闭触发的 onerror）
      if (assistantMsg.status === 'completed') return
      // 任务已被取消：忽略
      if (assistantMsg.status === 'canceled') return
    }

    // 确实没收到完成/取消事件且连接断开：显示连接中断
    patchMessageById(assistantMessageId, {
      content: '连接已中断，请重新提问。',
      status: 'failed',
    })
    sendingState.value = 'idle'
    cleanupActiveTask()
  }
}

const continueAsk = () => {
  cleanupActiveTask()
  sendingState.value = 'idle'
  question.value = ''
}

const retryCanceledQuestion = () => {
  cleanupActiveTask()
  question.value = stoppedQuestion.value
  sendingState.value = 'idle'
}

const stopQuestion = async () => {
  if (!activeTaskUuid.value) {
    pendingStopRequested.value = true
    sendingState.value = 'canceling'
    loading.value = false
    return
  }
  sendingState.value = 'canceling'
  const taskUuid = activeTaskUuid.value
  finishCanceledTaskLocally()
  try {
    if (!taskUuid) return

    const latest = await agentTaskAPI.get(taskUuid)
    if (latest.status === 'completed' || latest.status === 'failed' || latest.status === 'canceled') {
      return
    }

    await agentTaskAPI.cancel(taskUuid, { reason: 'user_stop' })
  } catch (e) {
    const detail = e.response?.data?.detail || e.message || ''
    if (detail.includes('任务已结束') || detail.includes('无法取消')) {
      return
    } else {
      ElMessage.error(detail || '停止失败，请稍后重试')
    }
  }
}

const cleanupActiveTask = ({ closeOnly = false, keepLoading = false } = {}) => {
  const eventSource = activeEventSource.value
  activeEventSource.value = null
  if (!closeOnly) {
    activeTaskUuid.value = null
    activeAssistantMessageId.value = null
    pendingStopRequested.value = false
  }
  if (!keepLoading) {
    loading.value = false
  }
  if (eventSource) {
    eventSource.close()
  }
}

const formatFileSize = (bytes) => {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let size = bytes
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024
    i++
  }
  return size.toFixed(i > 0 ? 1 : 0) + ' ' + units[i]
}

const fillExample = (text) => {
  question.value = text
}

const newConversation = () => {
  conversationId.value = null
  messages.value = []
  localStorage.removeItem(getConversationStorageKey())
}

// ── 本地文件修改方法（文档 Section 16.4-16.5） ──────────

const localFileStatusType = (status) => {
  const map = {
    preview_ready: 'warning',
    canceled: 'info',
    writing: 'warning',
    applied: 'success',
    failed: 'danger',
    restored: 'info',
  }
  return map[status] || 'info'
}

const localFileStatusText = (status) => {
  const map = {
    preview_ready: '待确认',
    canceled: '已取消',
    writing: '写入中',
    applied: '已修改',
    failed: '失败',
    restored: '已恢复',
  }
  return map[status] || status
}

const confirmLocalFileEdit = async (msg) => {
  const op = msg.localFileOperation
  if (!op) return
  try {
    await ElMessageBox.confirm(
      `确认把修改写入本地文件《${op.file_name}》吗？系统会先自动备份原文件。`,
      '确认修改本地文件',
      { type: 'warning', confirmButtonText: '确认修改', cancelButtonText: '取消' }
    )

    const res = await agentLocalFileAPI.confirm(op.operation_uuid, {
      expected_original_sha256: op.original_sha256,
    })

    msg.localFileOperation = {
      ...op,
      ...res,
      status: res.status,
    }
    ElMessage.success('文件修改成功，已自动备份原文件')
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') {
      ElMessage.error(e.response?.data?.detail || e.message || '确认修改失败')
    }
  }
}

const cancelLocalFileEdit = async (msg) => {
  const op = msg.localFileOperation
  if (!op) return
  try {
    const res = await agentLocalFileAPI.cancel(op.operation_uuid, {
      reason: 'user_cancel',
    })
    msg.localFileOperation = {
      ...op,
      ...res,
      status: res.status,
    }
    ElMessage.success('已取消，本地文件没有被修改')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || e.message || '取消修改失败')
  }
}

const restoreLocalFileEdit = async (msg) => {
  const op = msg.localFileOperation
  if (!op) return
  try {
    await ElMessageBox.confirm(
      `确认从备份恢复《${op.file_name}》吗？这会撤销上一次的修改。`,
      '恢复备份',
      { type: 'warning', confirmButtonText: '确认恢复', cancelButtonText: '取消' }
    )

    const res = await agentLocalFileAPI.restore(op.operation_uuid)
    msg.localFileOperation = {
      ...op,
      ...res,
      status: res.status,
    }
    ElMessage.success('已从备份恢复')
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') {
      ElMessage.error(e.response?.data?.detail || e.message || '恢复备份失败')
    }
  }
}

// ── 学习目标跳转（对话式目标创建阶段 Section 17.6） ──────────

const goLearningGoal = (goalId, action = null) => {
  router.push({
    path: '/learning-goals',
    query: {
      goalId,
      ...(action ? { action } : {}),
    },
  })
}

// ── 目标循环卡片辅助（文档 Section 24.1） ──────────

const loopStatusType = (status) => {
  const map = {
    running: '', completed: 'success', waiting_user_action: 'warning',
    blocked: 'info', failed: 'danger', budget_exhausted: 'warning',
    goal_completed: 'success', canceled: 'info',
  }
  return map[status] || 'info'
}

const loopStatusLabel = (status) => {
  const map = {
    running: '推进中', completed: '推进完成', waiting_user_action: '等待操作',
    blocked: '阻塞', failed: '失败', budget_exhausted: '已达上限',
    goal_completed: '目标完成', canceled: '已取消',
  }
  return map[status] || status
}

const loopStopReasonLabel = (reason) => {
  const map = {
    user_action_required: '需要操作',
    max_iterations_reached: '达到轮数上限',
    max_seconds_reached: '达到时间上限',
    goal_completed: '目标完成',
    replan_required: '需确认重规划',
    manual_task_required: '需要线下任务',
    failed_final: '步骤失败',
    blocked: '已阻塞',
    no_action_available: '无可执行动作',
    error: '异常',
  }
  return map[reason] || reason
}

const openLoopPractice = (goalLoop) => {
  const sessionId = goalLoop.action_payload?.session_id
  const goalId = goalLoop.goal_id
  if (!sessionId || !goalId) return
  router.push({
    path: '/learning-goals',
    query: { goalId, sessionId },
  })
}

const scrollToBottom = async () => {
  await nextTick()
  if (chatBox.value) {
    chatBox.value.scrollTop = chatBox.value.scrollHeight
  }
}

const formatMessage = (text) => {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\n/g, '<br>')
}

onMounted(() => {
  fetchCourses()
})
</script>

<style scoped>
.qa-chat {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 100px);
  max-width: 960px;
  margin: 0 auto;
}

.chat-header {
  padding: 10px 0;
  border-bottom: 1px solid #e4e7ed;
  margin-bottom: 10px;
  display: flex;
  gap: 12px;
  align-items: center;
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 10px 0;
}

.chat-welcome {
  text-align: center;
  padding: 40px 20px;
  color: #909399;
}

.chat-welcome h3 {
  font-size: 22px;
  margin-bottom: 12px;
  color: #303133;
}

.welcome-examples {
  margin-top: 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.example-item {
  padding: 10px 20px;
  background: #f0f2f5;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  color: #606266;
  transition: all 0.2s;
  max-width: 500px;
}

.example-item:hover {
  background: #e6f0ff;
  color: #409eff;
}

.message {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}

.message.user {
  flex-direction: row-reverse;
}

.message-content {
  max-width: 78%;
}

.message-text {
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
}

.message.user .message-text {
  background: #409eff;
  color: #fff;
}

.message.assistant .message-text {
  background: #f0f2f5;
  color: #303133;
}

.clarification-text {
  display: flex;
  align-items: flex-start;
  background: #fdf6ec !important;
  border: 1px solid #faecd8;
  color: #b88230 !important;
}

/* 文档卡片 */
.document-card {
  background: #fff;
  border: 1px solid #dcdfe6;
  border-radius: 10px;
  padding: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.document-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.document-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}

.document-file {
  font-size: 13px;
  color: #909399;
  margin-bottom: 12px;
  padding-left: 28px;
}

.document-actions {
  display: flex;
  gap: 8px;
  padding-left: 28px;
}

/* Agent 执行过程 */
.agent-trace {
  margin-top: 10px;
  padding: 12px;
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  background: #fff;
}

.agent-trace-title {
  font-weight: 600;
  color: #303133;
}

.agent-trace-title {
  margin-bottom: 8px;
}

/* 练习批改结果卡片 */
.practice-result-card {
  margin-top: 8px;
  padding: 12px 16px;
  background: #fff;
  border: 1px solid #dcdfe6;
  border-radius: 10px;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.05);
}

.practice-result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.correct-badge {
  font-weight: 600;
  color: #67c23a;
  font-size: 14px;
}

.wrong-badge {
  font-weight: 600;
  color: #f56c6c;
  font-size: 14px;
}

.practice-question-no {
  font-size: 13px;
  color: #909399;
}

.practice-result-body {
  font-size: 13px;
  color: #606266;
  line-height: 1.8;
}

.practice-answer-row {
  display: flex;
  gap: 16px;
  margin-bottom: 6px;
}

.practice-feedback {
  color: #303133;
  margin-top: 4px;
  padding-top: 8px;
  border-top: 1px solid #ebeef5;
}

.practice-completed {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid #ebeef5;
  color: #67c23a;
  font-weight: 600;
}

.message-actions {
  margin-top: 8px;
  display: flex;
  gap: 8px;
}

/* 预览弹窗 */
.markdown-preview {
  background: #fafafa;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 24px;
  max-height: 65vh;
  overflow: auto;
  line-height: 1.8;
  font-size: 14px;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: 'Helvetica Neue', Helvetica, 'PingFang SC', 'Microsoft YaHei', Arial, sans-serif;
}

.chat-input {
  padding: 10px 0;
  border-top: 1px solid #e4e7ed;
  background: #fff;
}

.chat-input-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.chat-input-row .el-input {
  flex: 1;
}

/* 附件卡片 */
.attachment-list {
  margin-top: 8px;
}

.attachment-card {
  display: flex;
  align-items: center;
  gap: 12px;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 8px;
}

.attachment-icon {
  font-size: 28px;
}

.attachment-info {
  flex: 1;
}

.attachment-title {
  font-weight: 600;
  color: #303133;
}

.attachment-meta {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}

.attachment-status {
  font-size: 12px;
  color: #67c23a;
  margin-top: 2px;
}

.attachment-actions {
  display: flex;
  gap: 6px;
}

.attachment-remove-btn {
  font-size: 18px;
  font-weight: 700;
}

.attachment-removed-status {
  color: #909399;
}

/* 取消后消息样式 */
.canceled-message {
  margin-top: 8px;
  padding: 12px 16px;
  background: #fef0f0;
  border: 1px solid #fde2e2;
  border-radius: 8px;
}

.canceled-text {
  color: #f56c6c;
  font-weight: 600;
  margin-bottom: 8px;
}

.canceled-actions {
  display: flex;
  gap: 8px;
}

.agent-running {
  background: #f0f2f5;
  border-radius: 12px;
  padding: 12px 16px;
  color: #606266;
}

.typing-indicator {
  display: flex;
  gap: 4px;
  padding-top: 10px;
}

.typing-indicator span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #a0cfff;
  animation: typing 1.4s infinite;
}

.typing-indicator span:nth-child(2) {
  animation-delay: 0.2s;
}

.typing-indicator span:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes typing {
  0%, 60%, 100% {
    transform: translateY(0);
    opacity: 0.4;
  }
  30% {
    transform: translateY(-10px);
    opacity: 1;
  }
}

/* 本地文件修改预览卡片（文档 Section 16.6） */
.local-file-card {
  margin-top: 10px;
  padding: 12px;
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  background: #fff;
}

.local-file-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.local-file-meta {
  color: #606266;
  font-size: 13px;
  line-height: 1.7;
  margin-bottom: 10px;
}

.local-file-diff {
  max-height: 360px;
  overflow: auto;
  padding: 10px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  background: #f7f8fa;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
}

.local-file-actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}

/* 学习目标卡片（对话式目标创建阶段 Section 17.3） */
.learning-goal-card {
  margin-top: 8px;
  padding: 16px;
  background: linear-gradient(135deg, #e6f7ff, #f0f5ff);
  border: 1px solid #91caff;
  border-radius: 10px;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.1);
}

.learning-goal-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.learning-goal-card-header strong {
  font-size: 15px;
  color: #303133;
}

.learning-goal-title {
  font-size: 18px;
  font-weight: 700;
  color: #1a1a2e;
  margin-bottom: 8px;
  padding: 8px 0;
  border-bottom: 1px dashed #91caff;
}

.learning-goal-summary {
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
  margin-bottom: 14px;
  padding: 8px 10px;
  background: rgba(255, 255, 255, 0.7);
  border-radius: 6px;
}

.learning-goal-actions {
  display: flex;
  gap: 10px;
}

/* 目标自主推进循环卡片（文档 Section 24.1） */
.goal-loop-card {
  margin-top: 8px;
  padding: 16px;
  background: linear-gradient(135deg, #f0fdf4, #ecfdf5);
  border: 1px solid #86efac;
  border-radius: 10px;
  box-shadow: 0 2px 8px rgba(34, 197, 94, 0.1);
}

.goal-loop-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.goal-loop-card-header strong {
  font-size: 15px;
  color: #303133;
}

.goal-loop-summary {
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
  margin-bottom: 8px;
  padding: 8px 10px;
  background: rgba(255, 255, 255, 0.7);
  border-radius: 6px;
}

.goal-loop-meta {
  font-size: 12px;
  color: #909399;
  margin-bottom: 14px;
  display: flex;
  align-items: center;
}

.goal-loop-actions {
  display: flex;
  gap: 10px;
}
</style>
