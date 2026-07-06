<template>
  <div class="my-courses">
    <div class="page-header">
      <h2>📚 我的课程</h2>
      <el-button type="primary" @click="showCreateDialog = true">+ 创建课程</el-button>
    </div>

    <el-row :gutter="20" v-loading="loading">
      <!-- 左侧：课程列表 -->
      <el-col :span="6">
        <el-card class="course-list-card">
          <template #header><span>课程列表</span></template>
          <div v-if="myCourses.length === 0" class="empty-tip">还没有创建课程</div>
          <div
            v-for="course in myCourses"
            :key="course.id"
            :class="['course-item', { active: selectedCourseId === course.id }]"
            @click="selectCourse(course)"
          >
            <div class="course-name">{{ course.name }}</div>
            <div class="course-meta">
              <span>📖 {{ course.knowledgeCount || 0 }} 知识点</span>
              <span>📄 {{ course.resourceCount || 0 }} 资料</span>
            </div>
            <div class="course-time">{{ formatDate(course.created_at) }}</div>
          </div>
        </el-card>
      </el-col>

      <!-- 右侧：课程详情 -->
      <el-col :span="18" v-if="selectedCourse">
        <el-card>
          <el-tabs v-model="activeTab">
            <!-- Tab 1: 知识点大纲 -->
            <el-tab-pane label="知识点大纲" name="outline">
              <div class="tab-header">
                <el-button type="primary" size="small" @click="generateOutline" :loading="generating">
                  🤖 AI 生成大纲
                </el-button>
                <el-button size="small" @click="showAddPointDialog = true">+ 新增知识点</el-button>
              </div>
              <el-table :data="knowledgePoints" style="width: 100%; margin-top: 12px;" size="small">
                <el-table-column prop="name" label="知识点名称" />
                <el-table-column prop="description" label="说明" show-overflow-tooltip />
                <el-table-column prop="difficulty" label="难度" width="80">
                  <template #default="{ row }">
                    <el-tag :type="['', 'success', 'warning', 'warning', 'danger', 'danger'][row.difficulty]" size="small">
                      {{ row.difficulty }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="source" label="来源" width="80">
                  <template #default="{ row }">
                    <el-tag :type="row.source === 'ai' ? 'success' : 'info'" size="small">
                      {{ row.source === 'ai' ? 'AI' : '手动' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="120">
                  <template #default="{ row }">
                    <el-button size="small" text type="danger" @click="deletePoint(row.id)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
              <div v-if="knowledgePoints.length === 0" class="empty-tip tab-empty">
                还没有知识点。你可以让 AI 生成知识点大纲，或者直接提问。
              </div>
            </el-tab-pane>

            <!-- Tab 2: 学习资料 -->
            <el-tab-pane label="学习资料" name="resources">
              <div class="tab-header">
                <el-button size="small" @click="showAddResourceDialog = true">✏️ 录入文本</el-button>
                <el-upload
                  :action="uploadUrl"
                  :headers="uploadHeaders"
                  :data="uploadData"
                  :show-file-list="false"
                  :on-success="onUploadSuccess"
                  :on-error="onUploadError"
                  :before-upload="beforeUpload"
                  accept=".txt,.md,.pdf"
                  style="display: inline-block; margin-left: 8px;"
                >
                  <el-button size="small" type="primary">📤 上传文件</el-button>
                </el-upload>
              </div>
              <el-table :data="resources" style="width: 100%; margin-top: 12px;" size="small">
                <el-table-column prop="title" label="标题" show-overflow-tooltip />
                <el-table-column prop="resource_type" label="类型" width="80" />
                <el-table-column label="索引状态" width="100">
                  <template #default="{ row }">
                    <el-tag
                      :type="row.index_status === 'indexed' ? 'success' : row.index_status === 'failed' ? 'danger' : row.index_status === 'pending' ? 'warning' : 'info'"
                      size="small"
                    >
                      {{ { none: '未索引', pending: '索引中', indexed: '已索引', failed: '失败' }[row.index_status] || row.index_status }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="160">
                  <template #default="{ row }">
                    <el-button size="small" text @click="reindexResource(row.id)" :disabled="!row.content">
                      {{ row.index_status === 'indexed' ? '重建索引' : '索引' }}
                    </el-button>
                    <el-button size="small" text type="danger" @click="deleteResource(row.id)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
              <div v-if="resources.length === 0" class="empty-tip tab-empty">
                当前课程还没有上传资料。AI 会基于通用知识回答，上传资料后回答会更贴近你的学习内容。
              </div>
            </el-tab-pane>

            <!-- Tab 3: 课程设置 -->
            <el-tab-pane label="课程设置" name="settings">
              <el-form :model="editForm" label-width="100px" style="max-width: 480px;">
                <el-form-item label="课程名称">
                  <el-input v-model="editForm.name" />
                </el-form-item>
                <el-form-item label="课程描述">
                  <el-input v-model="editForm.description" type="textarea" :rows="3" />
                </el-form-item>
                <el-form-item>
                  <el-button type="primary" @click="updateCourse" :loading="updating">保存</el-button>
                  <el-button type="danger" @click="confirmDelete" style="margin-left: 16px;">删除课程</el-button>
                </el-form-item>
              </el-form>
              <div class="delete-hint">
                删除后该课程不会再出现在你的课程列表中，历史答疑和学习记录仍会保留。
              </div>
            </el-tab-pane>
          </el-tabs>
        </el-card>
      </el-col>

      <!-- 未选择课程 -->
      <el-col :span="18" v-else>
        <el-card>
          <div class="empty-tip" style="padding: 60px 0;">选择左侧课程查看详情，或创建一个新课程</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 创建课程弹窗 -->
    <el-dialog v-model="showCreateDialog" title="创建课程" width="480px" top="10vh">
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
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="createCourse" :loading="creating">创建</el-button>
      </template>
    </el-dialog>

    <!-- 新增知识点弹窗 -->
    <el-dialog v-model="showAddPointDialog" title="新增知识点" width="400px" top="15vh">
      <el-form :model="pointForm" label-width="80px">
        <el-form-item label="名称" required>
          <el-input v-model="pointForm.name" placeholder="知识点名称" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="pointForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="难度">
          <el-select v-model="pointForm.difficulty">
            <el-option :value="1" label="1 - 基础" />
            <el-option :value="2" label="2 - 简单" />
            <el-option :value="3" label="3 - 中等" />
            <el-option :value="4" label="4 - 较难" />
            <el-option :value="5" label="5 - 困难" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddPointDialog = false">取消</el-button>
        <el-button type="primary" @click="addPoint" :loading="addingPoint">确定</el-button>
      </template>
    </el-dialog>

    <!-- 新增资料弹窗（录入文本） -->
    <el-dialog v-model="showAddResourceDialog" title="录入文本资料" width="500px" top="10vh">
      <el-form :model="resourceForm" label-width="80px">
        <el-form-item label="标题" required>
          <el-input v-model="resourceForm.title" placeholder="资料标题" />
        </el-form-item>
        <el-form-item label="关联知识点">
          <el-select v-model="resourceForm.knowledge_point_id" placeholder="可选" clearable>
            <el-option v-for="p in knowledgePoints" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="内容" required>
          <el-input v-model="resourceForm.content" type="textarea" :rows="6" placeholder="粘贴或输入学习资料内容" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddResourceDialog = false">取消</el-button>
        <el-button type="primary" @click="addResource" :loading="addingResource">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '../stores/user'
import { courseAPI, knowledgePointAPI, resourceAPI } from '../api'

const userStore = useUserStore()
const loading = ref(false)
const myCourses = ref([])
const selectedCourseId = ref(null)
const selectedCourse = ref(null)
const activeTab = ref('outline')
const knowledgePoints = ref([])
const resources = ref([])

// 创建课程
const showCreateDialog = ref(false)
const creating = ref(false)
const createForm = ref({ name: '', description: '', learning_goal: '', auto_generate_outline: true })

// 编辑课程
const updating = ref(false)
const editForm = ref({ name: '', description: '' })

// 知识点
const showAddPointDialog = ref(false)
const addingPoint = ref(false)
const pointForm = ref({ name: '', description: '', difficulty: 1 })
const generating = ref(false)

// 资源
const showAddResourceDialog = ref(false)
const addingResource = ref(false)
const resourceForm = ref({ title: '', content: '', knowledge_point_id: null })

// 上传
const uploadUrl = '/api/resources/upload'
const uploadHeaders = computed(() => ({
  Authorization: `Bearer ${localStorage.getItem('token')}`,
}))
const uploadData = computed(() => ({
  course_id: selectedCourseId.value,
  auto_index: true,
  title: '',
}))

const fetchMyCourses = async () => {
  loading.value = true
  try {
    myCourses.value = await courseAPI.list({ scope: 'mine' })
    if (myCourses.value.length > 0 && !selectedCourseId.value) {
      selectCourse(myCourses.value[0])
    }
  } catch (e) {} finally {
    loading.value = false
  }
}

const selectCourse = (course) => {
  selectedCourseId.value = course.id
  selectedCourse.value = course
  editForm.value = { name: course.name, description: course.description || '' }
  fetchKnowledgePoints()
  fetchResources()
}

const createCourse = async () => {
  if (!createForm.value.name.trim()) {
    ElMessage.warning('请输入课程名称')
    return
  }
  creating.value = true
  try {
    const course = await courseAPI.createStudentCourse({
      name: createForm.value.name.trim(),
      description: createForm.value.description || null,
      learning_goal: createForm.value.learning_goal || null,
      auto_generate_outline: createForm.value.auto_generate_outline,
    })
    ElMessage.success('课程创建成功')
    showCreateDialog.value = false
    createForm.value = { name: '', description: '', learning_goal: '', auto_generate_outline: true }
    await fetchMyCourses()
    selectedCourseId.value = course.id
    selectedCourse.value = course
    editForm.value = { name: course.name, description: course.description || '' }
    fetchKnowledgePoints()
    fetchResources()
  } catch (e) {} finally {
    creating.value = false
  }
}

const updateCourse = async () => {
  if (!editForm.value.name.trim()) {
    ElMessage.warning('课程名称不能为空')
    return
  }
  updating.value = true
  try {
    await courseAPI.update(selectedCourseId.value, {
      name: editForm.value.name.trim(),
      description: editForm.value.description || null,
    })
    ElMessage.success('课程已更新')
    await fetchMyCourses()
  } catch (e) {} finally {
    updating.value = false
  }
}

const confirmDelete = async () => {
  try {
    await ElMessageBox.confirm(
      '删除后该课程不会再出现在你的课程列表中，历史答疑和学习记录仍会保留。确定要删除吗？',
      '确认删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
    await courseAPI.delete(selectedCourseId.value)
    ElMessage.success('课程已删除')
    selectedCourseId.value = null
    selectedCourse.value = null
    knowledgePoints.value = []
    resources.value = []
    await fetchMyCourses()
  } catch (e) {
    if (e === 'cancel') return
  }
}

// 知识点
const fetchKnowledgePoints = async () => {
  try {
    knowledgePoints.value = await knowledgePointAPI.list(selectedCourseId.value)
  } catch (e) { knowledgePoints.value = [] }
}

const generateOutline = async () => {
  generating.value = true
  try {
    await courseAPI.generateOutline(selectedCourseId.value, { course_id: selectedCourseId.value, overwrite_existing: false })
    ElMessage.success('知识点大纲已生成')
    fetchKnowledgePoints()
  } catch (e) {} finally {
    generating.value = false
  }
}

const addPoint = async () => {
  if (!pointForm.value.name.trim()) {
    ElMessage.warning('请输入知识点名称')
    return
  }
  addingPoint.value = true
  try {
    await knowledgePointAPI.create({
      course_id: selectedCourseId.value,
      name: pointForm.value.name.trim(),
      description: pointForm.value.description || null,
      difficulty: pointForm.value.difficulty,
    })
    ElMessage.success('知识点已添加')
    showAddPointDialog.value = false
    pointForm.value = { name: '', description: '', difficulty: 1 }
    fetchKnowledgePoints()
  } catch (e) {} finally {
    addingPoint.value = false
  }
}

const deletePoint = async (id) => {
  try {
    await ElMessageBox.confirm('确定删除该知识点？', '确认', { type: 'warning' })
    await knowledgePointAPI.delete(id)
    ElMessage.success('已删除')
    fetchKnowledgePoints()
  } catch (e) {
    if (e === 'cancel') return
  }
}

// 资源
const fetchResources = async () => {
  try {
    resources.value = await resourceAPI.list(selectedCourseId.value)
  } catch (e) { resources.value = [] }
}

const addResource = async () => {
  if (!resourceForm.value.title.trim() || !resourceForm.value.content.trim()) {
    ElMessage.warning('请输入标题和内容')
    return
  }
  addingResource.value = true
  try {
    await resourceAPI.create({
      course_id: selectedCourseId.value,
      knowledge_point_id: resourceForm.value.knowledge_point_id,
      title: resourceForm.value.title.trim(),
      resource_type: 'text',
      content: resourceForm.value.content.trim(),
    })
    ElMessage.success('资料已添加')
    showAddResourceDialog.value = false
    resourceForm.value = { title: '', content: '', knowledge_point_id: null }
    fetchResources()
  } catch (e) {} finally {
    addingResource.value = false
  }
}

const reindexResource = async (id) => {
  try {
    await resourceAPI.index(id)
    ElMessage.success('索引完成')
    fetchResources()
  } catch (e) {}
}

const deleteResource = async (id) => {
  try {
    await ElMessageBox.confirm('确定删除该资料？', '确认', { type: 'warning' })
    await resourceAPI.delete(id)
    ElMessage.success('已删除')
    fetchResources()
  } catch (e) {
    if (e === 'cancel') return
  }
}

const beforeUpload = (file) => {
  const allowedTypes = ['.txt', '.md', '.pdf']
  const suffix = '.' + file.name.split('.').pop().toLowerCase()
  if (!allowedTypes.includes(suffix)) {
    ElMessage.error(`不支持的文件类型。允许：${allowedTypes.join(', ')}`)
    return false
  }
  if (file.size > 20 * 1024 * 1024) {
    ElMessage.error('文件大小不能超过 20MB')
    return false
  }
  // 动态设置 title
  uploadData.value.title = file.name.replace(/\.[^.]+$/, '')
  return true
}

const onUploadSuccess = () => {
  ElMessage.success('文件上传成功')
  fetchResources()
}

const onUploadError = (e) => {
  ElMessage.error('上传失败: ' + (e?.message || '网络错误'))
}

const formatDate = (d) => {
  if (!d) return ''
  return new Date(d).toLocaleDateString('zh-CN')
}

onMounted(() => {
  fetchMyCourses()
})
</script>

<style scoped>
.my-courses {
  padding: 0 20px 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.page-header h2 {
  margin: 0;
  color: #303133;
}

.course-list-card {
  min-height: 400px;
}

.course-item {
  padding: 12px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 8px;
  transition: background 0.2s;
  border: 1px solid transparent;
}

.course-item:hover {
  background: #f5f7fa;
}

.course-item.active {
  background: #ecf5ff;
  border-color: #409eff;
}

.course-name {
  font-weight: 600;
  color: #303133;
  font-size: 14px;
  margin-bottom: 4px;
}

.course-meta {
  display: flex;
  gap: 12px;
  font-size: 12px;
  color: #909399;
}

.course-time {
  font-size: 11px;
  color: #c0c4cc;
  margin-top: 4px;
}

.tab-header {
  margin-bottom: 4px;
  display: flex;
  gap: 8px;
}

.tab-empty {
  padding: 40px 0 !important;
  text-align: center;
}

.empty-tip {
  color: #909399;
  font-size: 14px;
  text-align: center;
  padding: 20px 0;
}

.delete-hint {
  color: #909399;
  font-size: 13px;
  margin-top: 12px;
  padding: 10px;
  background: #fdf6ec;
  border-radius: 6px;
}
</style>
