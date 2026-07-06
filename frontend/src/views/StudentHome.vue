<template>
  <div class="student-home">
    <h2>欢迎，{{ userStore.user?.name }} 👋</h2>
    <el-row :gutter="20" class="home-row">
      <!-- 课程选择（分组显示） -->
      <el-col :span="24">
        <el-card class="course-select-card">
          <template #header>
            <span>📖 当前课程</span>
          </template>
          <el-select v-model="selectedCourseId" placeholder="请选择课程" @change="onCourseChange" style="width: 260px">
            <el-option-group v-if="teacherCourses.length > 0" label="教师课程">
              <el-option v-for="c in teacherCourses" :key="c.id" :label="c.name" :value="c.id" />
            </el-option-group>
            <el-option-group v-if="studentCourses.length > 0" label="我的课程">
              <el-option v-for="c in studentCourses" :key="c.id" :label="c.name" :value="c.id" />
            </el-option-group>
          </el-select>
        </el-card>
      </el-col>

      <!-- 今日推荐任务 -->
      <el-col :span="12">
        <el-card>
          <template #header><span>🎯 推荐学习方案</span></template>
          <div v-if="plans.length === 0" class="empty-tip">暂无推荐方案，去答疑或做题吧！</div>
          <div v-for="plan in plans.slice(0, 2)" :key="plan.id" class="plan-item">
            <el-tag :type="plan.status === 'completed' ? 'success' : 'warning'" size="small">{{ plan.status === 'completed' ? '已完成' : '进行中' }}</el-tag>
            <span class="plan-title">{{ plan.title }}</span>
          </div>
        </el-card>
      </el-col>

      <!-- 薄弱知识点 -->
      <el-col :span="12">
        <el-card>
          <template #header><span>⚠️ 薄弱知识点</span></template>
          <div v-if="weakPoints.length === 0" class="empty-tip">暂无薄弱知识点，继续保持！</div>
          <el-tag v-for="wp in weakPoints" :key="wp.knowledge_point_id" type="danger" style="margin: 4px">
            {{ wp.name }} ({{ wp.mastery_score }}分)
          </el-tag>
        </el-card>
      </el-col>

      <!-- 最近答疑记录 -->
      <el-col :span="24">
        <el-card>
          <template #header><span>💬 最近答疑</span></template>
          <el-table :data="qaHistory" style="width: 100%" max-height="300" size="small">
            <el-table-column prop="question" label="问题" show-overflow-tooltip />
            <el-table-column prop="answer" label="回答" show-overflow-tooltip width="300" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="row.resolved === 1 ? 'success' : row.resolved === 0 ? 'danger' : 'info'" size="small">
                  {{ row.resolved === 1 ? '已解决' : row.resolved === 0 ? '未解决' : '未反馈' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="时间" width="180" />
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '../stores/user'
import { courseAPI, qaAPI, profileAPI, recommendationAPI } from '../api'

const userStore = useUserStore()
const courses = ref([])
const selectedCourseId = ref(null)
const plans = ref([])
const weakPoints = ref([])
const qaHistory = ref([])

// 课程分组（文档 Section 18.2）
const teacherCourses = computed(() => courses.value.filter(c => c.course_type === 'teacher'))
const studentCourses = computed(() => courses.value.filter(c => c.course_type === 'student'))

const fetchCourses = async () => {
  try {
    courses.value = await courseAPI.list()
    if (courses.value.length > 0) {
      selectedCourseId.value = courses.value[0].id
      await onCourseChange(selectedCourseId.value)
    }
  } catch (e) {}
}

const onCourseChange = async (courseId) => {
  await Promise.all([fetchPlans(courseId), fetchWeakPoints(courseId), fetchQAHistory(courseId)])
}

const fetchPlans = async (courseId) => {
  try {
    plans.value = await recommendationAPI.list(courseId)
  } catch (e) {}
}

const fetchWeakPoints = async (courseId) => {
  try {
    weakPoints.value = await profileAPI.weakPoints(courseId)
  } catch (e) {}
}

const fetchQAHistory = async (courseId) => {
  try {
    qaHistory.value = await qaAPI.history(courseId)
  } catch (e) {}
}

onMounted(() => {
  fetchCourses()
})
</script>

<style scoped>
.student-home h2 {
  margin-bottom: 20px;
  color: #303133;
}

.home-row .el-col {
  margin-bottom: 20px;
}

.empty-tip {
  color: #909399;
  font-size: 14px;
  text-align: center;
  padding: 20px 0;
}

.plan-item {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.plan-title {
  font-size: 14px;
  color: #606266;
}
</style>
