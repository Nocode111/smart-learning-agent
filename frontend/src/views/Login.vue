<template>
  <div class="login-container">
    <div class="login-card">
      <h1>📚 智慧学习辅助系统</h1>
      <p class="subtitle">基于 AI Agent 的个性化学习平台</p>
      <el-tabs v-model="activeTab" class="login-tabs">
        <el-tab-pane label="登录" name="login">
          <el-form :model="loginForm" :rules="rules" ref="loginFormRef">
            <el-form-item prop="username">
              <el-input v-model="loginForm.username" placeholder="用户名" prefix-icon="User" size="large" />
            </el-form-item>
            <el-form-item prop="password">
              <el-input v-model="loginForm.password" type="password" placeholder="密码" prefix-icon="Lock" size="large" show-password />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" size="large" style="width: 100%" @click="handleLogin" :loading="loading">登 录</el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="注册" name="register">
          <el-form :model="registerForm" :rules="registerRules" ref="registerFormRef">
            <el-form-item prop="username">
              <el-input v-model="registerForm.username" placeholder="用户名" size="large" />
            </el-form-item>
            <el-form-item prop="password">
              <el-input v-model="registerForm.password" type="password" placeholder="密码" size="large" show-password />
            </el-form-item>
            <el-form-item prop="name">
              <el-input v-model="registerForm.name" placeholder="姓名" size="large" />
            </el-form-item>
            <el-form-item prop="role">
              <el-radio-group v-model="registerForm.role">
                <el-radio value="student">学生</el-radio>
                <el-radio value="teacher">教师</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item>
              <el-button type="success" size="large" style="width: 100%" @click="handleRegister" :loading="loading">注 册</el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '../stores/user'

const router = useRouter()
const userStore = useUserStore()
const activeTab = ref('login')
const loading = ref(false)

const loginForm = reactive({ username: '', password: '' })
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

const registerForm = reactive({ username: '', password: '', name: '', role: 'student' })
const registerRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
  name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
}

const handleLogin = async () => {
  loading.value = true
  try {
    await userStore.login(loginForm.username, loginForm.password)
    ElMessage.success('登录成功')
    const role = userStore.user?.role
    router.push(role === 'teacher' || role === 'admin' ? '/course-manage' : '/student-home')
  } catch (e) {
    // 错误已在拦截器中处理
  } finally {
    loading.value = false
  }
}

const handleRegister = async () => {
  loading.value = true
  try {
    await userStore.register(registerForm)
    ElMessage.success('注册成功')
    const role = userStore.user?.role
    router.push(role === 'teacher' || role === 'admin' ? '/course-manage' : '/student-home')
  } catch (e) {
    // 错误已在拦截器中处理
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.login-card {
  background: #fff;
  border-radius: 12px;
  padding: 40px;
  width: 420px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.15);
}

.login-card h1 {
  text-align: center;
  font-size: 24px;
  color: #303133;
  margin-bottom: 8px;
}

.subtitle {
  text-align: center;
  color: #909399;
  font-size: 14px;
  margin-bottom: 24px;
}

.login-tabs {
  margin-top: 10px;
}
</style>
