<template>
  <div class="recommendation-plan">
    <h2>推荐学习方案</h2>

    <div class="plan-header">
      <el-select v-model="courseId" placeholder="选择课程" @change="fetchPlans" style="width: 220px">
        <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
      </el-select>
    </div>

    <div v-if="plans.length === 0" class="empty-tip">暂无推荐方案。完成一次答疑反馈或练习后，系统会生成专项计划。</div>

    <div v-for="plan in plans" :key="plan.id" class="plan-card">
      <el-card>
        <template #header>
          <div class="plan-card-header">
            <span>{{ plan.title }}</span>
            <el-tag :type="plan.status === 'completed' ? 'success' : 'warning'">
              {{ plan.status === 'completed' ? '已完成' : '进行中' }}
            </el-tag>
          </div>
        </template>

        <div class="plan-reason" v-if="plan.reason">{{ plan.reason }}</div>

        <el-timeline>
          <el-timeline-item
            v-for="task in plan.tasks"
            :key="task.id"
            :timestamp="task.estimated_minutes ? `预计 ${task.estimated_minutes} 分钟` : ''"
            :type="task.status === 'completed' ? 'success' : 'primary'"
          >
            <div class="task-item">
              <div class="task-info">
                <el-tag :type="taskTypeMap[task.task_type]?.color" size="small" style="margin-right: 8px">
                  {{ taskTypeMap[task.task_type]?.label || task.task_type }}
                </el-tag>
                <span :class="{ 'task-done': task.status === 'completed' }">{{ task.title }}</span>
              </div>

              <div class="task-actions">
                <el-button
                  v-if="task.task_type === 'resource'"
                  size="small"
                  type="primary"
                  @click="openResourceTask(plan, task)"
                >
                  阅读
                </el-button>
                <el-button
                  v-else-if="task.task_type === 'practice'"
                  size="small"
                  type="warning"
                  @click="openPracticeTask(plan, task)"
                >
                  练习
                </el-button>
                <el-button
                  v-else-if="task.task_type === 'qa'"
                  size="small"
                  type="success"
                  @click="goQaTask(task)"
                >
                  去答疑
                </el-button>

                <el-button
                  v-if="task.status === 'pending'"
                  size="small"
                  @click="completeTask(plan.id, task.id)"
                >
                  标记完成
                </el-button>
                <el-tag v-else type="info" size="small">已完成</el-tag>
              </div>
            </div>
          </el-timeline-item>
        </el-timeline>
      </el-card>
    </div>

    <el-dialog v-model="resourceDialogVisible" title="阅读资源" width="720px">
      <h3>{{ activeResource?.title }}</h3>
      <div class="resource-meta" v-if="activeResource">类型：{{ activeResource.resource_type }}</div>
      <div class="resource-content">{{ activeResource?.content || '暂无资源内容' }}</div>
      <template #footer>
        <el-button @click="resourceDialogVisible = false">稍后再看</el-button>
        <el-button type="primary" @click="finishResourceTask">已阅读并完成</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="practiceDialogVisible" title="专项练习" width="760px">
      <div v-if="practiceQuestions.length === 0" class="empty-tip compact">这个知识点还没有题目，请先让教师添加练习题。</div>
      <div v-else>
        <div class="question-counter">第 {{ currentQuestionIndex + 1 }} / {{ practiceQuestions.length }} 题</div>
        <h3>{{ currentQuestion?.stem }}</h3>
        <el-radio-group v-if="currentOptions.length" v-model="practiceAnswer" class="option-list">
          <el-radio v-for="option in currentOptions" :key="option.key" :value="option.key">
            {{ option.key }}. {{ option.value }}
          </el-radio>
        </el-radio-group>
        <el-input v-else v-model="practiceAnswer" placeholder="输入你的答案" />

        <el-alert
          v-if="practiceResult"
          :type="practiceResult.is_correct ? 'success' : 'error'"
          :title="practiceResult.is_correct ? '回答正确' : `回答错误，正确答案：${practiceResult.correct_answer}`"
          :description="practiceResult.explanation || ''"
          show-icon
          style="margin-top: 16px"
        />
      </div>
      <template #footer>
        <el-button @click="practiceDialogVisible = false">关闭</el-button>
        <el-button v-if="practiceResult && currentQuestionIndex < practiceQuestions.length - 1" @click="nextQuestion">下一题</el-button>
        <el-button v-if="practiceResult && currentQuestionIndex === practiceQuestions.length - 1" type="primary" @click="finishPracticeTask">完成练习</el-button>
        <el-button v-if="!practiceResult && practiceQuestions.length" type="primary" @click="submitPracticeAnswer">提交答案</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '../stores/user'
import { behaviorAPI, courseAPI, questionAPI, recommendationAPI, resourceAPI } from '../api'

const router = useRouter()
const userStore = useUserStore()
const courses = ref([])
const courseId = ref(null)
const plans = ref([])

const resourceDialogVisible = ref(false)
const activePlan = ref(null)
const activeTask = ref(null)
const activeResource = ref(null)

const practiceDialogVisible = ref(false)
const practiceQuestions = ref([])
const currentQuestionIndex = ref(0)
const practiceAnswer = ref('')
const practiceResult = ref(null)

const taskTypeMap = {
  resource: { label: '资源', color: 'primary' },
  practice: { label: '练习', color: 'warning' },
  qa: { label: '答疑', color: 'success' },
  review: { label: '复习', color: 'info' },
}

const currentQuestion = computed(() => practiceQuestions.value[currentQuestionIndex.value])
const currentOptions = computed(() => {
  const options = currentQuestion.value?.options_json
  if (!options) return []
  return Object.entries(options).map(([key, value]) => ({ key, value }))
})

const fetchCourses = async () => {
  try {
    courses.value = await courseAPI.list()
    if (courses.value.length > 0) {
      courseId.value = courses.value[0].id
      await fetchPlans()
    }
  } catch (e) {}
}

const fetchPlans = async () => {
  if (!courseId.value) return
  try {
    plans.value = await recommendationAPI.list(courseId.value)
  } catch (e) {}
}

const completeTask = async (planId, taskId) => {
  try {
    await recommendationAPI.completeTask(planId, taskId)
    ElMessage.success('任务已完成，学习画像已更新')
    await fetchPlans()
  } catch (e) {}
}

const openResourceTask = async (plan, task) => {
  try {
    activePlan.value = plan
    activeTask.value = task
    activeResource.value = await resourceAPI.get(task.target_id)
    resourceDialogVisible.value = true

    await behaviorAPI.create({
      course_id: activeResource.value.course_id,
      knowledge_point_id: activeResource.value.knowledge_point_id,
      behavior_type: 'view_resource',
      content: activeResource.value.title,
      result: 'viewed',
      source: 'recommendation_page',
    })
  } catch (e) {}
}

const finishResourceTask = async () => {
  if (!activePlan.value || !activeTask.value) return
  await completeTask(activePlan.value.id, activeTask.value.id)
  resourceDialogVisible.value = false
}

const openPracticeTask = async (plan, task) => {
  try {
    activePlan.value = plan
    activeTask.value = task
    practiceQuestions.value = await questionAPI.list(plan.course_id, task.target_id)
    currentQuestionIndex.value = 0
    practiceAnswer.value = ''
    practiceResult.value = null
    practiceDialogVisible.value = true
  } catch (e) {}
}

const submitPracticeAnswer = async () => {
  if (!currentQuestion.value || !practiceAnswer.value.trim()) {
    ElMessage.warning('请先填写答案')
    return
  }
  try {
    practiceResult.value = await questionAPI.submit(currentQuestion.value.id, {
      answer: practiceAnswer.value,
    })
  } catch (e) {}
}

const nextQuestion = () => {
  currentQuestionIndex.value += 1
  practiceAnswer.value = ''
  practiceResult.value = null
}

const finishPracticeTask = async () => {
  if (!activePlan.value || !activeTask.value) return
  await completeTask(activePlan.value.id, activeTask.value.id)
  practiceDialogVisible.value = false
}

const goQaTask = (task) => {
  router.push({
    path: '/qa-chat',
    query: {
      courseId: courseId.value,
      prompt: `请帮我复习这个推荐任务：${task.title}`,
    },
  })
}

onMounted(() => {
  fetchCourses()
})
</script>

<style scoped>
.recommendation-plan h2 {
  margin-bottom: 20px;
}

.plan-header {
  margin-bottom: 20px;
}

.empty-tip {
  color: #909399;
  text-align: center;
  padding: 60px;
  font-size: 16px;
}

.empty-tip.compact {
  padding: 20px;
}

.plan-card {
  margin-bottom: 20px;
}

.plan-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.plan-reason {
  color: #606266;
  font-size: 14px;
  margin-bottom: 16px;
  line-height: 1.6;
}

.task-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.task-info {
  display: flex;
  align-items: center;
  min-width: 0;
}

.task-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-shrink: 0;
}

.task-done {
  text-decoration: line-through;
  color: #909399;
}

.resource-meta {
  color: #909399;
  margin-bottom: 12px;
}

.resource-content {
  white-space: pre-wrap;
  line-height: 1.8;
  color: #303133;
  background: #f7f8fa;
  border: 1px solid #ebeef5;
  padding: 16px;
  max-height: 420px;
  overflow: auto;
}

.question-counter {
  color: #909399;
  margin-bottom: 10px;
}

.option-list {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
  margin-top: 12px;
}
</style>
