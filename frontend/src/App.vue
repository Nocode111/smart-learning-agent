<template>
  <div id="app">
    <el-container class="layout-container">
      <el-header class="layout-header" v-if="userStore.token">
        <div class="header-left">
          <h2>📚 智慧学习辅助系统</h2>
          <el-menu
            :default-active="activeMenu"
            mode="horizontal"
            router
            class="header-menu"
          >
            <el-menu-item index="/student-home" v-if="userStore.user?.role === 'student'">首页</el-menu-item>
            <el-menu-item index="/qa-chat" v-if="userStore.user?.role === 'student'">智能答疑</el-menu-item>
            <el-menu-item index="/learning-profile" v-if="userStore.user?.role === 'student'">学习画像</el-menu-item>
            <el-menu-item index="/recommendation-plan" v-if="userStore.user?.role === 'student'">推荐方案</el-menu-item>
            <el-menu-item index="/learning-goals" v-if="userStore.user?.role === 'student'">学习目标</el-menu-item>
            <el-menu-item index="/agent-tools">Agent 工具箱</el-menu-item>
            <el-menu-item index="/course-manage" v-if="userStore.user?.role === 'teacher' || userStore.user?.role === 'admin'">课程管理</el-menu-item>
          </el-menu>
        </div>
        <div class="header-right">
          <span class="user-name">{{ userStore.user?.name }}</span>
          <el-tag :type="userStore.user?.role === 'teacher' ? 'warning' : 'success'">
            {{ userStore.user?.role === 'teacher' ? '教师' : '学生' }}
          </el-tag>
          <el-button type="danger" size="small" @click="handleLogout">退出</el-button>
        </div>
      </el-header>
      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from './stores/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const activeMenu = computed(() => route.path)

const handleLogout = () => {
  userStore.logout()
  router.push('/login')
}
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: 'Helvetica Neue', Helvetica, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', Arial, sans-serif;
  background-color: #f5f7fa;
}

.layout-container {
  min-height: 100vh;
}

.layout-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  padding: 0 20px;
  height: 60px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 20px;
}

.header-left h2 {
  font-size: 18px;
  white-space: nowrap;
  color: #409eff;
}

.header-menu {
  border-bottom: none !important;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.user-name {
  font-size: 14px;
  color: #606266;
}

.el-main {
  padding: 20px;
}
</style>
