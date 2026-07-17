import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/login/index.vue'),
    meta: { title: '登录', requiresAuth: false },
  },
  {
    path: '/',
    component: () => import('@/layouts/AdminLayout.vue'),
    redirect: '/adobe',
    meta: { requiresAuth: true },
    children: [
      {
        path: 'adobe',
        name: 'adobe',
        component: () => import('@/views/adobe/index.vue'),
        meta: { title: '母号管理', requiresAuth: true },
      },
      {
        path: 'pool',
        name: 'pool',
        component: () => import('@/views/pool/index.vue'),
        meta: { title: '号池管理', requiresAuth: true },
      },
      {
        path: 'jobs',
        name: 'jobs',
        component: () => import('@/views/jobs/index.vue'),
        meta: { title: '拉号任务', requiresAuth: true },
      },
      {
        path: 'email',
        name: 'email',
        component: () => import('@/views/email/index.vue'),
        meta: { title: '邮箱管理', requiresAuth: true },
      },
      {
        path: 'logs',
        name: 'logs',
        component: () => import('@/views/logs/index.vue'),
        meta: { title: '日志管理', requiresAuth: true },
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/settings/index.vue'),
        meta: { title: '设置', requiresAuth: true },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/',
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

router.beforeEach((to) => {
  const token = localStorage.getItem('okad_token')

  if (to.meta.requiresAuth && !token) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && token) {
    return { name: 'adobe' }
  }
  return true
})

router.afterEach((to) => {
  const title = to.meta.title as string | undefined
  document.title = title ? `${title} - okad 管理平台` : 'okad 管理平台'
})

export default router
