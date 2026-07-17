<script setup lang="ts">
import { NButton, NCheckbox, NForm, NFormItem, NIcon, NInput, type FormInst, type FormRules } from 'naive-ui'
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const formRef = ref<FormInst | null>(null)
const loading = ref(false)
const rememberMe = ref(true)

const model = reactive({
  username: 'admin',
  password: 'admin123',
})

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function handleLogin() {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }

  loading.value = true
  try {
    await authStore.login({ username: model.username, password: model.password })
    window.$message?.success('登录成功')
    const redirect = (route.query.redirect as string) || '/'
    router.push(redirect)
  } catch {
    // 错误提示已在 axios 拦截器统一处理
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <!-- 左侧品牌展示区 -->
    <div class="login-banner">
      <div class="banner-content">
        <div class="logo">
          <svg viewBox="0 0 32 32" width="44" height="44">
            <rect width="32" height="32" rx="8" fill="#fff" />
            <path
              d="M9 22V10h3.2c3.6 0 5.8 2.3 5.8 6s-2.2 6-5.8 6H9zm3-2.6h.2c1.9 0 3-1.2 3-3.4s-1.1-3.4-3-3.4H12v6.8zM20 22V10h2.8v12H20z"
              fill="#1890ff"
            />
          </svg>
          <span class="logo-text">okad 管理平台</span>
        </div>
        <h1 class="banner-title">高效、现代的<br />一站式后台管理系统</h1>
        <p class="banner-desc">
          基于 Vue3 + FastAPI 构建,开箱即用的权限、用户与数据管理能力,助你专注业务本身。
        </p>
        <ul class="banner-features">
          <li>⚡ 高性能异步后端</li>
          <li>🎨 现代化精致 UI</li>
          <li>🔐 安全的 JWT 鉴权</li>
        </ul>
      </div>
      <div class="blob blob-1" />
      <div class="blob blob-2" />
    </div>

    <!-- 右侧登录表单区 -->
    <div class="login-form-wrapper">
      <div class="login-card">
        <div class="login-header">
          <h2>欢迎回来 👋</h2>
          <p>请输入您的账号信息登录系统</p>
        </div>

        <NForm ref="formRef" :model="model" :rules="rules" size="large" :show-label="false">
          <NFormItem path="username">
            <NInput v-model:value="model.username" placeholder="请输入用户名" clearable>
              <template #prefix>
                <NIcon>
                  <svg viewBox="0 0 24 24" width="18" height="18">
                    <path
                      fill="currentColor"
                      d="M12 12a5 5 0 1 0 0-10 5 5 0 0 0 0 10zm0 2c-5.33 0-8 2.67-8 6v2h16v-2c0-3.33-2.67-6-8-6z"
                    />
                  </svg>
                </NIcon>
              </template>
            </NInput>
          </NFormItem>

          <NFormItem path="password">
            <NInput
              v-model:value="model.password"
              type="password"
              show-password-on="click"
              placeholder="请输入密码"
              clearable
              @keyup.enter="handleLogin"
            >
              <template #prefix>
                <NIcon>
                  <svg viewBox="0 0 24 24" width="18" height="18">
                    <path
                      fill="currentColor"
                      d="M12 1a5 5 0 0 0-5 5v3H6a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-9a2 2 0 0 0-2-2h-1V6a5 5 0 0 0-5-5zm3 8H9V6a3 3 0 0 1 6 0v3z"
                    />
                  </svg>
                </NIcon>
              </template>
            </NInput>
          </NFormItem>

          <div class="login-options">
            <NCheckbox v-model:checked="rememberMe">记住我</NCheckbox>
            <a class="forgot-link">忘记密码?</a>
          </div>

          <NButton
            type="primary"
            size="large"
            block
            :loading="loading"
            class="login-button"
            @click="handleLogin"
          >
            登 录
          </NButton>
        </NForm>

        <div class="login-tip">
          默认账号:<b>admin</b> / 密码:<b>admin123</b>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  display: flex;
  height: 100vh;
  width: 100vw;
  overflow: hidden;
  background: #f0f2f5;
}

/* 左侧品牌区 */
.login-banner {
  position: relative;
  flex: 1.2;
  display: flex;
  align-items: center;
  padding: 0 8%;
  overflow: hidden;
  background: linear-gradient(135deg, #1890ff 0%, #0e63d6 60%, #0c4ba8 100%);
  color: #fff;
}

.banner-content {
  position: relative;
  z-index: 2;
  max-width: 480px;
}

.logo {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 48px;
}

.logo-text {
  font-size: 22px;
  font-weight: 600;
}

.banner-title {
  font-size: 38px;
  line-height: 1.3;
  font-weight: 700;
  margin-bottom: 20px;
}

.banner-desc {
  font-size: 15px;
  line-height: 1.8;
  opacity: 0.9;
  margin-bottom: 32px;
}

.banner-features {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.banner-features li {
  font-size: 15px;
  opacity: 0.95;
}

.blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(2px);
  opacity: 0.18;
  background: #fff;
}

.blob-1 {
  width: 340px;
  height: 340px;
  top: -120px;
  right: -80px;
}

.blob-2 {
  width: 220px;
  height: 220px;
  bottom: -70px;
  left: 10%;
  opacity: 0.12;
}

/* 右侧表单区 */
.login-form-wrapper {
  width: 480px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fff;
  padding: 40px;
}

.login-card {
  width: 100%;
  max-width: 360px;
}

.login-header {
  margin-bottom: 32px;
}

.login-header h2 {
  font-size: 28px;
  font-weight: 700;
  color: #1f2329;
  margin-bottom: 10px;
}

.login-header p {
  font-size: 14px;
  color: #8a919f;
}

.login-options {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 4px 0 22px;
}

.forgot-link {
  font-size: 14px;
  color: #1890ff;
  cursor: pointer;
}

.forgot-link:hover {
  opacity: 0.8;
}

.login-button {
  font-size: 16px;
  letter-spacing: 4px;
  font-weight: 500;
}

.login-tip {
  margin-top: 24px;
  text-align: center;
  font-size: 13px;
  color: #98a0ab;
}

.login-tip b {
  color: #1890ff;
}

/* 响应式:窄屏隐藏左侧 banner */
@media (max-width: 900px) {
  .login-banner {
    display: none;
  }
  .login-form-wrapper {
    width: 100%;
  }
}
</style>
