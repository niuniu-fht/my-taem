<script setup lang="ts">
import {
  NAvatar,
  NDropdown,
  NIcon,
  NLayout,
  NLayoutContent,
  NLayoutHeader,
  NLayoutSider,
  NMenu,
  type MenuOption,
} from 'naive-ui'
import { computed, h, onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const collapsed = ref(false)

function renderIcon(path: string) {
  return () =>
    h(NIcon, null, {
      default: () =>
        h('svg', { viewBox: '0 0 24 24', width: 18, height: 18 }, [
          h('path', { fill: 'currentColor', d: path }),
        ]),
    })
}

const menuOptions = computed<MenuOption[]>(() => [
  {
    label: () => h(RouterLink, { to: '/adobe' }, { default: () => '母号管理' }),
    key: 'adobe',
    icon: renderIcon(
      'M9 22V10h3.2c3.6 0 5.8 2.3 5.8 6s-2.2 6-5.8 6H9zm3-2.6h.2c1.9 0 3-1.2 3-3.4s-1.1-3.4-3-3.4H12v6.8z',
    ),
  },
  {
    label: () => h(RouterLink, { to: '/pool' }, { default: () => '号池管理' }),
    key: 'pool',
    icon: renderIcon(
      'M12 2 2 7l10 5 10-5-10-5zm0 7.2L4.5 7 12 4.3 19.5 7 12 9.2zM2 12l10 5 10-5-2.2-1.1L12 14.5 4.2 10.9 2 12zm0 5 10 5 10-5-2.2-1.1L12 19.5 4.2 15.9 2 17z',
    ),
  },
  {
    label: () => h(RouterLink, { to: '/jobs' }, { default: () => '拉号任务' }),
    key: 'jobs',
    icon: renderIcon(
      'M13 2.05v2.02c3.95.49 7 3.85 7 7.93 0 4.42-3.58 8-8 8s-8-3.58-8-8c0-2.05.77-3.92 2.04-5.34L7.5 8.07A5.96 5.96 0 0 0 6 12c0 3.31 2.69 6 6 6s6-2.69 6-6a6 6 0 0 0-5-5.91V8l4-4-4-4v2.05zM11 7h2v6h-2V7z',
    ),
  },
  {
    label: () => h(RouterLink, { to: '/email' }, { default: () => '邮箱管理' }),
    key: 'email',
    icon: renderIcon(
      'M20 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z',
    ),
  },
  {
    label: () => h(RouterLink, { to: '/logs' }, { default: () => '日志管理' }),
    key: 'logs',
    icon: renderIcon(
      'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm-1 7V3.5L18.5 9H13zM8 13h8v2H8v-2zm0 4h8v2H8v-2z',
    ),
  },
  {
    label: () => h(RouterLink, { to: '/settings' }, { default: () => '设置' }),
    key: 'settings',
    icon: renderIcon(
      'M19.4 13a7.8 7.8 0 0 0 0-2l2-1.6-2-3.4-2.4 1a7.6 7.6 0 0 0-1.7-1l-.4-2.6H10.1l-.4 2.6a7.6 7.6 0 0 0-1.7 1l-2.4-1-2 3.4L3.6 11a7.8 7.8 0 0 0 0 2l-2 1.6 2 3.4 2.4-1c.5.4 1.1.7 1.7 1l.4 2.6h3.8l.4-2.6c.6-.3 1.2-.6 1.7-1l2.4 1 2-3.4-2-1.6zM12 15.5A3.5 3.5 0 1 1 12 8.5a3.5 3.5 0 0 1 0 7z',
    ),
  },
])

const activeKey = computed(() => route.name as string)

const userOptions = [
  { label: '退出登录', key: 'logout' },
]

function handleUserSelect(key: string) {
  if (key === 'logout') {
    authStore.clear()
    window.$message?.success('已退出登录')
    router.push({ name: 'login' })
  }
}

onMounted(async () => {
  if (!authStore.userInfo) {
    try {
      await authStore.fetchUserInfo()
    } catch {
      // 拦截器处理 401
    }
  }
})
</script>

<template>
  <NLayout has-sider style="height: 100vh">
    <NLayoutSider
      bordered
      collapse-mode="width"
      :collapsed-width="64"
      :width="220"
      :collapsed="collapsed"
      show-trigger
      @collapse="collapsed = true"
      @expand="collapsed = false"
    >
      <div class="logo">
        <svg viewBox="0 0 32 32" width="28" height="28">
          <rect width="32" height="32" rx="7" fill="#1890ff" />
          <path
            d="M9 22V10h3.2c3.6 0 5.8 2.3 5.8 6s-2.2 6-5.8 6H9zm3-2.6h.2c1.9 0 3-1.2 3-3.4s-1.1-3.4-3-3.4H12v6.8zM20 22V10h2.8v12H20z"
            fill="#fff"
          />
        </svg>
        <span v-show="!collapsed" class="logo-text">okad 管理平台</span>
      </div>
      <NMenu
        :value="activeKey"
        :collapsed="collapsed"
        :collapsed-width="64"
        :options="menuOptions"
      />
    </NLayoutSider>

    <NLayout>
      <NLayoutHeader bordered class="header">
        <div class="header-title">{{ route.meta.title }}</div>
        <NDropdown :options="userOptions" @select="handleUserSelect">
          <div class="user-info">
            <NAvatar round size="small" :style="{ background: '#1890ff' }">
              {{ authStore.userInfo?.nickname?.charAt(0) || 'U' }}
            </NAvatar>
            <span class="username">{{ authStore.userInfo?.nickname || '管理员' }}</span>
          </div>
        </NDropdown>
      </NLayoutHeader>

      <NLayoutContent class="content">
        <RouterView />
      </NLayoutContent>
    </NLayout>
  </NLayout>
</template>

<style scoped>
.logo {
  height: 60px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 18px;
  overflow: hidden;
  white-space: nowrap;
  border-bottom: 1px solid #f0f0f0;
}

.logo-text {
  font-size: 16px;
  font-weight: 600;
  color: #1f2329;
}

.header {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  background: #fff;
}

.header-title {
  font-size: 18px;
  font-weight: 600;
  color: #1f2329;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
  transition: background 0.2s;
}

.user-info:hover {
  background: #f0f2f5;
}

.username {
  font-size: 14px;
  color: #4e5969;
}

.content {
  padding: 20px;
  background: #f0f2f5;
  overflow: auto;
}
</style>
