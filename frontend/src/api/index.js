import axios from 'axios'
import { ElMessage } from 'element-plus'

const api = axios.create({
  baseURL: '/api',
  timeout: 90000,
})

// 请求拦截器：添加 token
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// 响应拦截器：统一错误处理
api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const message = error.response?.data?.detail || error.message || '请求失败'
    ElMessage.error(message)
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// --- 认证接口 ---
export const authAPI = {
  login: (data) => api.post('/auth/login', data),
  register: (data) => api.post('/auth/register', data),
  me: () => api.get('/auth/me'),
}

// --- 课程接口 ---
export const courseAPI = {
  list: (params = {}) => api.get('/courses', { params }),
  get: (id) => api.get(`/courses/${id}`),
  create: (data) => api.post('/courses', data),
  createStudentCourse: (data) => api.post('/courses/student', data),
  generateOutline: (id, data) => api.post(`/courses/${id}/outline/generate`, data),
  update: (id, data) => api.put(`/courses/${id}`, data),
  delete: (id) => api.delete(`/courses/${id}`),
}

// --- 知识点接口 ---
export const knowledgePointAPI = {
  list: (courseId) => api.get('/knowledge-points', { params: { courseId } }),
  create: (data) => api.post('/knowledge-points', data),
  update: (id, data) => api.put(`/knowledge-points/${id}`, data),
  delete: (id) => api.delete(`/knowledge-points/${id}`),
}

// --- 资源接口 ---
export const resourceAPI = {
  list: (courseId) => api.get('/resources', { params: { courseId } }),
  get: (id) => api.get(`/resources/${id}`),
  create: (data) => api.post('/resources', data),
  upload: (formData) => api.post('/resources/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }),
  index: (id) => api.post(`/resources/${id}/index`),
  delete: (id) => api.delete(`/resources/${id}`),
}

// --- 题目接口 ---
export const questionAPI = {
  list: (courseId, knowledgePointId) =>
    api.get('/questions', { params: { courseId, knowledgePointId } }),
  create: (data) => api.post('/questions', data),
  submit: (id, data) => api.post(`/questions/${id}/submit`, data),
}

// --- 答疑接口 ---
export const qaAPI = {
  ask: (data) => api.post('/qa/ask', data),
  history: (courseId) =>
    api.get('/qa/history', { params: { courseId } }),
  feedback: (qaId, data) => api.post(`/qa/${qaId}/feedback`, data),
}

// --- 行为接口 ---
export const behaviorAPI = {
  list: (limit = 50) =>
    api.get('/behaviors', { params: { limit } }),
  create: (data) => api.post('/behaviors', data),
}

// --- 画像接口 ---
export const profileAPI = {
  get: (courseId) =>
    api.get('/profiles', { params: { courseId } }),
  refresh: (courseId) =>
    api.post('/profiles/refresh', null, { params: { courseId } }),
  weakPoints: (courseId) =>
    api.get('/profiles/weak-points', { params: { courseId } }),
}

// --- 练习题生成接口 ---
export const exerciseGenerationAPI = {
  generate: (data) => api.post('/exercise-generation/generate', data),
  list: (courseId) => api.get('/exercise-generation/documents', { params: { courseId } }),
  get: (id) => api.get(`/exercise-generation/documents/${id}`),
  downloadUrl: (id) => `/api/exercise-generation/${id}/download`,
}

// --- 统一 Agent 入口接口 ---
export const agentAPI = {
  chat: (data) => api.post('/agent/chat', data),
  recentConversation: (courseId) => api.get('/agent/conversations/recent', { params: { courseId } }),
  messages: (conversationId) => api.get(`/agent/conversations/${conversationId}/messages`),
}

// --- Agent 对话附件接口 ---
export const agentAttachmentAPI = {
  upload: (formData) => api.post('/agent/attachments/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }),
  list: (conversationId) =>
    api.get('/agent/attachments', { params: { conversationId } }),
  preview: (id) => api.get(`/agent/attachments/${id}/preview`),
  downloadUrl: (id) => `/api/agent/attachments/${id}/download`,
  delete: (id) => api.delete(`/agent/attachments/${id}`),
  remove: (id, data = {}) => api.post(`/agent/attachments/${id}/remove`, data),
  reindex: (id) => api.post(`/agent/attachments/${id}/reindex`),
}

// --- Agent 提问任务接口（二期） ---
export const agentTaskAPI = {
  create: (data) => api.post('/agent/chat-tasks', data),
  get: (taskUuid) => api.get(`/agent/chat-tasks/${taskUuid}`),
  cancel: (taskUuid, data = {}) => api.post(`/agent/chat-tasks/${taskUuid}/cancel`, data),
  eventsUrl: (taskUuid) => `/api/agent/chat-tasks/${taskUuid}/events`,
}

// --- Agent 长期记忆接口（三期） ---
export const agentMemoryAPI = {
  list: (params = {}) => api.get('/agent/memories', { params }),
  create: (data) => api.post('/agent/memories', data),
  get: (id) => api.get(`/agent/memories/${id}`),
  update: (id, data) => api.put(`/agent/memories/${id}`, data),
  disable: (id) => api.post(`/agent/memories/${id}/disable`),
  delete: (id) => api.delete(`/agent/memories/${id}`),
  context: (params = {}) => api.get('/agent/memories/context', { params }),
  events: (params = {}) => api.get('/agent/memories/events', { params }),
  feedback: (id, data) => api.post(`/agent/memories/${id}/feedback`, data),
  createSummary: (data) => api.post('/agent/memories/summaries', data),
}

// --- 推荐方案接口 ---
export const recommendationAPI = {
  list: (courseId) =>
    api.get('/recommendations', { params: { courseId } }),
  generate: (data) => api.post('/recommendations/generate', data),
  completeTask: (planId, taskId) =>
    api.post(`/recommendations/${planId}/tasks/${taskId}/complete`),
}

// --- 本地文件修改 Agent 接口（文档 Section 16.1） ---
export const agentLocalFileAPI = {
  config: () => api.get('/agent/local-files/config'),
  getOperation: (operationUuid) =>
    api.get(`/agent/local-files/operations/${operationUuid}`),
  confirm: (operationUuid, data) =>
    api.post(`/agent/local-files/operations/${operationUuid}/confirm`, data),
  cancel: (operationUuid, data = {}) =>
    api.post(`/agent/local-files/operations/${operationUuid}/cancel`, data),
  restore: (operationUuid, data = {}) =>
    api.post(`/agent/local-files/operations/${operationUuid}/restore`, data),
}

// --- 长期目标 Agent 接口（文档 Section 13.2 + 执行闭环增强 Section 11.1） ---
export const agentGoalAPI = {
  // 基础 CRUD
  list: (params = {}) => api.get('/agent/goals', { params }),
  create: (data) => api.post('/agent/goals', data),
  get: (id) => api.get(`/agent/goals/${id}`),
  plan: (id) => api.post(`/agent/goals/${id}/plan`),
  runNext: (id) => api.post(`/agent/goals/${id}/run-next`),
  completeStep: (goalId, stepId, data) =>
    api.post(`/agent/goals/${goalId}/steps/${stepId}/complete`, data),
  pause: (id) => api.post(`/agent/goals/${id}/pause`),
  resume: (id) => api.post(`/agent/goals/${id}/resume`),
  cancel: (id) => api.post(`/agent/goals/${id}/cancel`),
  complete: (id) => api.post(`/agent/goals/${id}/complete`),

  // 执行闭环增强
  stepRuns: (goalId, stepId) =>
    api.get(`/agent/goals/${goalId}/steps/${stepId}/runs`),
  runDetail: (goalId, runId) =>
    api.get(`/agent/goals/${goalId}/runs/${runId}`),
  refreshReflection: (goalId, stepId, data = {}) =>
    api.post(`/agent/goals/${goalId}/steps/${stepId}/refresh-reflection`, data),
  replan: (goalId, data = {}) =>
    api.post(`/agent/goals/${goalId}/replan`, data),
  insertRemedialStep: (goalId, data) =>
    api.post(`/agent/goals/${goalId}/steps/remedial`, data),
  practiceDetail: (goalId, sessionId) =>
    api.get(`/agent/goals/${goalId}/practice-sessions/${sessionId}`),
  submitPracticeAnswer: (goalId, sessionId, data) =>
    api.post(`/agent/goals/${goalId}/practice-sessions/${sessionId}/answer`, data),

  // 目标推进闭环（文档 Section 14.1）
  advance: (goalId, data = {}) =>
    api.post(`/agent/goals/${goalId}/advance`, data),
  advanceCycles: (goalId, params = {}) =>
    api.get(`/agent/goals/${goalId}/advance-cycles`, { params }),
  advanceCycleDetail: (goalId, cycleId) =>
    api.get(`/agent/goals/${goalId}/advance-cycles/${cycleId}`),

  // 多轮自主推进循环（文档 Section 15）
  runLoop: (goalId, data = {}) =>
    api.post(`/agent/goals/${goalId}/run-loop`, data),
  loopRuns: (goalId, params = {}) =>
    api.get(`/agent/goals/${goalId}/loop-runs`, { params }),
  loopRunDetail: (goalId, loopRunId) =>
    api.get(`/agent/goals/${goalId}/loop-runs/${loopRunId}`),

  // 用户动作门控（文档 Section 16）
  startUserAction: (goalId, stepId, data) =>
    api.post(`/agent/goals/${goalId}/steps/${stepId}/user-actions/start`, data),
  heartbeatUserAction: (goalId, stepId, data) =>
    api.post(`/agent/goals/${goalId}/steps/${stepId}/user-actions/heartbeat`, data),
  completeUserAction: (goalId, stepId, data) =>
    api.post(`/agent/goals/${goalId}/steps/${stepId}/user-actions/complete`, data),
  latestUserAction: (goalId, stepId) =>
    api.get(`/agent/goals/${goalId}/steps/${stepId}/user-actions/latest`),

  // 目标守护（文档 Section 13）
  guardianConfig: (goalId) =>
    api.get(`/agent/goals/${goalId}/guardian/config`),
  updateGuardianConfig: (goalId, data) =>
    api.put(`/agent/goals/${goalId}/guardian/config`, data),
  runGuardian: (goalId) =>
    api.post(`/agent/goals/${goalId}/guardian/run`),
  guardianRuns: (goalId, params = {}) =>
    api.get(`/agent/goals/${goalId}/guardian/runs`, { params }),
  guardianEvents: (goalId, params = {}) =>
    api.get(`/agent/goals/${goalId}/guardian/events`, { params }),
  readGuardianEvent: (goalId, eventId) =>
    api.post(`/agent/goals/${goalId}/guardian/events/${eventId}/read`),
  dismissGuardianEvent: (goalId, eventId) =>
    api.post(`/agent/goals/${goalId}/guardian/events/${eventId}/dismiss`),
}
