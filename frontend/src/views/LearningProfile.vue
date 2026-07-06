<template>
  <div class="learning-profile">
    <div class="profile-header">
      <h2>学习画像</h2>
      <div>
        <el-select v-model="courseId" placeholder="选择课程" @change="fetchProfile" style="width: 220px; margin-right: 10px">
          <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
        <el-button type="primary" @click="refreshProfile" :loading="refreshing">刷新画像</el-button>
      </div>
    </div>

    <el-row :gutter="20">
      <el-col :span="8">
        <el-card>
          <template #header><span>总体水平</span></template>
          <div class="level-display">
            <el-progress
              type="dashboard"
              :percentage="overallPercentage"
              :color="levelColor"
              :stroke-width="12"
            >
              <template #default>
                <span class="level-label">{{ profile.overall_level || '暂无数据' }}</span>
              </template>
            </el-progress>
          </div>
        </el-card>
      </el-col>

      <el-col :span="8">
        <el-card>
          <template #header><span>薄弱知识点</span></template>
          <div v-if="weakPoints.length === 0" class="empty-tip">暂无薄弱点</div>
          <div v-for="wp in weakPoints" :key="wp.knowledge_point_id" class="weak-item">
            <span class="weak-name">{{ wp.name }}</span>
            <el-progress :percentage="wp.mastery_score" :color="wp.mastery_score < 40 ? '#f56c6c' : '#e6a23c'" :stroke-width="8" />
          </div>
        </el-card>
      </el-col>

      <el-col :span="8">
        <el-card>
          <template #header><span>最近行为</span></template>
          <div class="behavior-summary" ref="behaviorChart" style="height: 200px"></div>
        </el-card>
      </el-col>
    </el-row>

    <el-card style="margin-top: 20px">
      <template #header><span>知识点掌握度对比</span></template>
      <div ref="masteryChart" style="height: 350px"></div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { useUserStore } from '../stores/user'
import { behaviorAPI, courseAPI, profileAPI } from '../api'

const userStore = useUserStore()
const courses = ref([])
const courseId = ref(null)
const profile = ref({ overall_level: '暂无数据', knowledge_mastery: [], weak_points: [] })
const weakPoints = ref([])
const behaviors = ref([])
const refreshing = ref(false)
const masteryChart = ref(null)
const behaviorChart = ref(null)

const overallPercentage = ref(0)
const levelColor = ref('#909399')

const fetchCourses = async () => {
  try {
    courses.value = await courseAPI.list()
    if (courses.value.length > 0) {
      courseId.value = courses.value[0].id
      await fetchProfile()
    }
  } catch (e) {}
}

const fetchProfile = async () => {
  if (!courseId.value) return
  try {
    profile.value = await profileAPI.get(courseId.value)
    behaviors.value = await behaviorAPI.list(100)
    weakPoints.value = profile.value.weak_points || []

    const mastery = profile.value.knowledge_mastery || []
    if (mastery.length > 0) {
      const avg = mastery.reduce((sum, m) => sum + Number(m.mastery_score || 0), 0) / mastery.length
      overallPercentage.value = Math.round(avg)
    } else {
      overallPercentage.value = 0
    }

    if (overallPercentage.value >= 80) levelColor.value = '#67c23a'
    else if (overallPercentage.value >= 60) levelColor.value = '#e6a23c'
    else levelColor.value = '#f56c6c'

    await nextTick()
    renderMasteryChart()
    renderBehaviorChart()
  } catch (e) {}
}

const refreshProfile = async () => {
  refreshing.value = true
  try {
    profile.value = await profileAPI.refresh(courseId.value)
    behaviors.value = await behaviorAPI.list(100)
    weakPoints.value = profile.value.weak_points || []
    await nextTick()
    renderMasteryChart()
    renderBehaviorChart()
  } catch (e) {}
  refreshing.value = false
}

const renderMasteryChart = () => {
  if (!masteryChart.value) return
  const chart = echarts.init(masteryChart.value)
  const mastery = profile.value.knowledge_mastery || []
  chart.setOption({
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: mastery.map((m) => m.name),
      axisLabel: { rotate: 30 },
    },
    yAxis: { type: 'value', max: 100, name: '掌握度' },
    series: [
      {
        type: 'bar',
        data: mastery.map((m) => ({
          value: m.mastery_score,
          itemStyle: {
            color: m.mastery_score >= 80 ? '#67c23a' : m.mastery_score >= 60 ? '#e6a23c' : '#f56c6c',
          },
        })),
        barWidth: '50%',
      },
    ],
    grid: { bottom: 100 },
  })
  window.addEventListener('resize', () => chart.resize())
}

const renderBehaviorChart = () => {
  if (!behaviorChart.value) return
  const chart = echarts.init(behaviorChart.value)
  const currentCourseBehaviors = behaviors.value.filter((b) => b.course_id === courseId.value)
  const labels = {
    ask_question: '提问',
    qa_feedback: '答疑反馈',
    answer_question: '答题',
    view_resource: '阅读资源',
    complete_task: '完成任务',
    generate_exercise: '生成练习',
  }
  const counts = currentCourseBehaviors.reduce((acc, item) => {
    const key = item.behavior_type || 'other'
    acc[key] = (acc[key] || 0) + 1
    return acc
  }, {})
  const data = Object.entries(counts).map(([key, value]) => ({
    value,
    name: labels[key] || key,
  }))

  chart.setOption({
    tooltip: { trigger: 'item' },
    graphic: data.length
      ? []
      : [
          {
            type: 'text',
            left: 'center',
            top: 'middle',
            style: {
              text: '暂无行为数据',
              fill: '#909399',
              fontSize: 14,
            },
          },
        ],
    series: [
      {
        type: 'pie',
        radius: ['40%', '70%'],
        data,
      },
    ],
  })
}

onMounted(() => {
  fetchCourses()
})
</script>

<style scoped>
.learning-profile h2 {
  margin-bottom: 10px;
}

.profile-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.level-display {
  text-align: center;
  padding: 10px 0;
}

.level-label {
  font-size: 14px;
  color: #606266;
}

.empty-tip {
  color: #909399;
  text-align: center;
  padding: 20px;
}

.weak-item {
  margin-bottom: 12px;
}

.weak-name {
  font-size: 13px;
  color: #606266;
  display: block;
  margin-bottom: 4px;
}

.el-row .el-col {
  margin-bottom: 0;
}
</style>


