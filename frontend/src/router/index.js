import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    redirect: '/login',
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/Login.vue'),
  },
  {
    path: '/student-home',
    name: 'StudentHome',
    component: () => import('../views/StudentHome.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/qa-chat',
    name: 'QaChat',
    component: () => import('../views/QaChat.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/learning-profile',
    name: 'LearningProfile',
    component: () => import('../views/LearningProfile.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/recommendation-plan',
    name: 'RecommendationPlan',
    component: () => import('../views/RecommendationPlan.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/my-courses',
    name: 'MyCourses',
    component: () => import('../views/MyCourses.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/course-manage',
    name: 'CourseManage',
    component: () => import('../views/CourseManage.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/agent-tools',
    name: 'AgentTools',
    component: () => import('../views/AgentTools.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/learning-goals',
    name: 'LearningGoals',
    component: () => import('../views/LearningGoals.vue'),
    meta: { requiresAuth: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫
router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('token')
  if (to.meta.requiresAuth && !token) {
    next('/login')
  } else {
    next()
  }
})

export default router
