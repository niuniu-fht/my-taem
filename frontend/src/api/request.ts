import axios, { type AxiosInstance, type AxiosResponse } from 'axios'

import { useAuthStore } from '@/stores/auth'
import router from '@/router'

const request: AxiosInstance = axios.create({
  baseURL: '/team/api',
  timeout: 15000,
})

// 请求拦截:自动携带 token
request.interceptors.request.use((config) => {
  const authStore = useAuthStore()
  if (authStore.token) {
    config.headers.Authorization = `Bearer ${authStore.token}`
  }
  return config
})

// 响应拦截:统一错误提示与 401 处理
request.interceptors.response.use(
  (response: AxiosResponse) => response.data,
  (error) => {
    const status = error.response?.status
    const detail = error.response?.data?.detail
    const msg = typeof detail === 'string' ? detail : '请求失败,请稍后重试'

    if (status === 401) {
      const authStore = useAuthStore()
      authStore.clear()
      if (router.currentRoute.value.name !== 'login') {
        window.$message?.error('登录已过期,请重新登录')
        router.push({ name: 'login' })
      } else {
        window.$message?.error(msg)
      }
    } else {
      window.$message?.error(msg)
    }
    return Promise.reject(error)
  },
)

export default request
