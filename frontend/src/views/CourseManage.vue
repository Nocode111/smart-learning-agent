<template>
  <div class="course-manage">
    <h2>📝 教师管理</h2>

    <el-tabs v-model="activeTab" type="border-card">
      <!-- 课程管理 -->
      <el-tab-pane label="课程管理" name="courses">
        <div class="tab-toolbar">
          <el-button type="primary" @click="showCourseDialog = true">创建课程</el-button>
        </div>
        <el-table :data="courses" style="width: 100%">
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column prop="name" label="课程名称" />
          <el-table-column prop="description" label="描述" show-overflow-tooltip />
          <el-table-column prop="created_at" label="创建时间" width="180" />
          <el-table-column label="操作" width="150">
            <template #default="{ row }">
              <el-button size="small" @click="editCourse(row)">编辑</el-button>
              <el-button size="small" type="danger" @click="deleteCourse(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 知识点管理 -->
      <el-tab-pane label="知识点管理" name="knowledgePoints">
        <div class="tab-toolbar">
          <el-select v-model="selectedCourseIdForKP" placeholder="选择课程" @change="fetchKnowledgePoints" style="width: 200px; margin-right: 10px">
            <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
          <el-button type="primary" @click="showKPDialog = true" :disabled="!selectedCourseIdForKP">创建知识点</el-button>
        </div>
        <el-table :data="knowledgePoints" style="width: 100%">
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column prop="name" label="名称" />
          <el-table-column prop="description" label="描述" show-overflow-tooltip />
          <el-table-column prop="difficulty" label="难度" width="80" />
          <el-table-column prop="sort_order" label="排序" width="80" />
          <el-table-column label="操作" width="150">
            <template #default="{ row }">
              <el-button size="small" @click="editKP(row)">编辑</el-button>
              <el-button size="small" type="danger" @click="deleteKP(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 资源管理 -->
      <el-tab-pane label="资源管理" name="resources">
        <div class="tab-toolbar">
          <el-select v-model="selectedCourseIdForRes" placeholder="选择课程" @change="fetchResources" style="width: 200px; margin-right: 10px">
            <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
          <el-button type="primary" @click="showResDialog = true" :disabled="!selectedCourseIdForRes">添加资源</el-button>
        </div>
        <el-table :data="resources" style="width: 100%">
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column prop="title" label="标题" />
          <el-table-column prop="resource_type" label="类型" width="80" />
          <el-table-column label="已索引" width="80">
            <template #default="{ row }">
              <el-tag :type="row.indexed ? 'success' : 'info'" size="small">{{ row.indexed ? '是' : '否' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="200">
            <template #default="{ row }">
              <el-button v-if="!row.indexed" size="small" type="warning" @click="indexResource(row.id)">构建索引</el-button>
              <el-button size="small" type="danger" @click="deleteResource(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 题目管理 -->
      <el-tab-pane label="题目管理" name="questions">
        <div class="tab-toolbar">
          <el-select v-model="selectedCourseIdForQ" placeholder="选择课程" @change="fetchQuestions" style="width: 200px; margin-right: 10px">
            <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
          <el-button type="primary" @click="showQDialog = true" :disabled="!selectedCourseIdForQ">创建题目</el-button>
        </div>
        <el-table :data="questions" style="width: 100%">
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column prop="stem" label="题目" show-overflow-tooltip />
          <el-table-column prop="question_type" label="类型" width="80" />
          <el-table-column prop="answer" label="答案" width="120" show-overflow-tooltip />
          <el-table-column prop="difficulty" label="难度" width="60" />
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- 课程对话框 -->
    <el-dialog v-model="showCourseDialog" :title="editingCourse ? '编辑课程' : '创建课程'" width="500px">
      <el-form :model="courseForm">
        <el-form-item label="课程名称">
          <el-input v-model="courseForm.name" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="courseForm.description" type="textarea" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCourseDialog = false">取消</el-button>
        <el-button type="primary" @click="saveCourse">保存</el-button>
      </template>
    </el-dialog>

    <!-- 知识点对话框 -->
    <el-dialog v-model="showKPDialog" :title="editingKP ? '编辑知识点' : '创建知识点'" width="500px">
      <el-form :model="kpForm">
        <el-form-item label="名称">
          <el-input v-model="kpForm.name" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="kpForm.description" type="textarea" />
        </el-form-item>
        <el-form-item label="难度">
          <el-input-number v-model="kpForm.difficulty" :min="1" :max="5" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="kpForm.sort_order" :min="0" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showKPDialog = false">取消</el-button>
        <el-button type="primary" @click="saveKP">保存</el-button>
      </template>
    </el-dialog>

    <!-- 资源对话框 -->
    <el-dialog v-model="showResDialog" title="添加资源" width="600px">
      <el-form :model="resForm">
        <el-form-item label="标题">
          <el-input v-model="resForm.title" />
        </el-form-item>
        <el-form-item label="关联知识点">
          <el-select v-model="resForm.knowledge_point_id" placeholder="可选" clearable style="width: 100%">
            <el-option v-for="kp in knowledgePoints" :key="kp.id" :label="kp.name" :value="kp.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="resForm.resource_type" style="width: 100%">
            <el-option label="文本" value="text" />
            <el-option label="PDF" value="pdf" />
            <el-option label="链接" value="link" />
          </el-select>
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="resForm.content" type="textarea" :rows="8" placeholder="录入课程资料内容" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showResDialog = false">取消</el-button>
        <el-button type="primary" @click="saveResource">保存</el-button>
      </template>
    </el-dialog>

    <!-- 题目对话框 -->
    <el-dialog v-model="showQDialog" title="创建题目" width="600px">
      <el-form :model="qForm">
        <el-form-item label="关联知识点">
          <el-select v-model="qForm.knowledge_point_id" placeholder="请选择" style="width: 100%">
            <el-option v-for="kp in knowledgePoints" :key="kp.id" :label="kp.name" :value="kp.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="题型">
          <el-select v-model="qForm.question_type" style="width: 100%">
            <el-option label="单选题" value="single" />
            <el-option label="多选题" value="multiple" />
            <el-option label="判断题" value="judge" />
            <el-option label="简答题" value="short" />
          </el-select>
        </el-form-item>
        <el-form-item label="题目">
          <el-input v-model="qForm.stem" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="选项(JSON)">
          <el-input v-model="qForm.options_json_text" type="textarea" :rows="3" placeholder='{"A":"...","B":"..."}' />
        </el-form-item>
        <el-form-item label="答案">
          <el-input v-model="qForm.answer" placeholder="如：B" />
        </el-form-item>
        <el-form-item label="解析">
          <el-input v-model="qForm.explanation" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="难度">
          <el-input-number v-model="qForm.difficulty" :min="1" :max="5" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showQDialog = false">取消</el-button>
        <el-button type="primary" @click="saveQuestion">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { courseAPI, knowledgePointAPI, resourceAPI, questionAPI } from '../api'

const activeTab = ref('courses')

// === 课程 ===
const courses = ref([])
const showCourseDialog = ref(false)
const editingCourse = ref(null)
const courseForm = reactive({ name: '', description: '' })

const fetchCourses = async () => {
  try { courses.value = await courseAPI.list() } catch (e) {}
}

const editCourse = (row) => {
  editingCourse.value = row
  courseForm.name = row.name
  courseForm.description = row.description || ''
  showCourseDialog.value = true
}

const saveCourse = async () => {
  try {
    if (editingCourse.value) {
      await courseAPI.update(editingCourse.value.id, courseForm)
      ElMessage.success('课程已更新')
    } else {
      await courseAPI.create(courseForm)
      ElMessage.success('课程已创建')
    }
    showCourseDialog.value = false
    editingCourse.value = null
    courseForm.name = ''
    courseForm.description = ''
    await fetchCourses()
  } catch (e) {}
}

const deleteCourse = async (id) => {
  try {
    await ElMessageBox.confirm('确定删除该课程？', '警告', { type: 'warning' })
    await courseAPI.delete(id)
    ElMessage.success('已删除')
    await fetchCourses()
  } catch (e) {}
}

// === 知识点 ===
const selectedCourseIdForKP = ref(null)
const knowledgePoints = ref([])
const showKPDialog = ref(false)
const editingKP = ref(null)
const kpForm = reactive({ name: '', description: '', difficulty: 1, sort_order: 0 })

const fetchKnowledgePoints = async () => {
  if (!selectedCourseIdForKP.value) return
  try { knowledgePoints.value = await knowledgePointAPI.list(selectedCourseIdForKP.value) } catch (e) {}
}

const editKP = (row) => {
  editingKP.value = row
  kpForm.name = row.name
  kpForm.description = row.description || ''
  kpForm.difficulty = row.difficulty
  kpForm.sort_order = row.sort_order
  showKPDialog.value = true
}

const saveKP = async () => {
  try {
    if (editingKP.value) {
      await knowledgePointAPI.update(editingKP.value.id, kpForm)
      ElMessage.success('知识点已更新')
    } else {
      await knowledgePointAPI.create({ course_id: selectedCourseIdForKP.value, ...kpForm })
      ElMessage.success('知识点已创建')
    }
    showKPDialog.value = false
    editingKP.value = null
    Object.assign(kpForm, { name: '', description: '', difficulty: 1, sort_order: 0 })
    await fetchKnowledgePoints()
  } catch (e) {}
}

const deleteKP = async (id) => {
  try {
    await ElMessageBox.confirm('确定删除？', '警告', { type: 'warning' })
    await knowledgePointAPI.delete(id)
    ElMessage.success('已删除')
    await fetchKnowledgePoints()
  } catch (e) {}
}

// === 资源 ===
const selectedCourseIdForRes = ref(null)
const resources = ref([])
const showResDialog = ref(false)
const resForm = reactive({ title: '', knowledge_point_id: null, resource_type: 'text', content: '' })

const fetchResources = async () => {
  if (!selectedCourseIdForRes.value) return
  try { resources.value = await resourceAPI.list(selectedCourseIdForRes.value) } catch (e) {}
}

const saveResource = async () => {
  try {
    await resourceAPI.create({
      course_id: selectedCourseIdForRes.value,
      knowledge_point_id: resForm.knowledge_point_id,
      title: resForm.title,
      resource_type: resForm.resource_type,
      content: resForm.content,
    })
    ElMessage.success('资源已创建')
    showResDialog.value = false
    Object.assign(resForm, { title: '', knowledge_point_id: null, resource_type: 'text', content: '' })
    await fetchResources()
  } catch (e) {}
}

const indexResource = async (id) => {
  try {
    await resourceAPI.index(id)
    ElMessage.success('向量索引构建成功')
    await fetchResources()
  } catch (e) {}
}

const deleteResource = async (id) => {
  try {
    await ElMessageBox.confirm('确定删除？', '警告', { type: 'warning' })
    await resourceAPI.delete(id)
    ElMessage.success('已删除')
    await fetchResources()
  } catch (e) {}
}

// === 题目 ===
const selectedCourseIdForQ = ref(null)
const questions = ref([])
const showQDialog = ref(false)
const qForm = reactive({
  knowledge_point_id: null,
  question_type: 'single',
  stem: '',
  options_json_text: '',
  answer: '',
  explanation: '',
  difficulty: 1,
})

const fetchQuestions = async () => {
  if (!selectedCourseIdForQ.value) return
  try { questions.value = await questionAPI.list(selectedCourseIdForQ.value) } catch (e) {}
}

const saveQuestion = async () => {
  try {
    let optionsJson = null
    if (qForm.options_json_text.trim()) {
      try { optionsJson = JSON.parse(qForm.options_json_text) } catch {
        ElMessage.error('选项 JSON 格式错误')
        return
      }
    }
    await questionAPI.create({
      course_id: selectedCourseIdForQ.value,
      knowledge_point_id: qForm.knowledge_point_id,
      question_type: qForm.question_type,
      stem: qForm.stem,
      options_json: optionsJson,
      answer: qForm.answer,
      explanation: qForm.explanation,
      difficulty: qForm.difficulty,
    })
    ElMessage.success('题目已创建')
    showQDialog.value = false
    Object.assign(qForm, {
      knowledge_point_id: null, question_type: 'single', stem: '',
      options_json_text: '', answer: '', explanation: '', difficulty: 1,
    })
    await fetchQuestions()
  } catch (e) {}
}

onMounted(() => {
  fetchCourses()
})
</script>

<style scoped>
.course-manage h2 {
  margin-bottom: 20px;
}

.tab-toolbar {
  margin-bottom: 16px;
  display: flex;
  align-items: center;
}
</style>
