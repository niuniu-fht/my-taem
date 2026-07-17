import { defineStore } from 'pinia'
import { ref } from 'vue'

import { getMeApi, loginApi, type LoginParams, type UserInfo } from '@/api/auth'

const TOKEN_KEY = 'okad_token'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(localStorage.getItem(TOKEN_KEY) || '')
  const userInfo = ref<UserInfo | null>(null)

  function setToken(value: string) {
    token.value = value
    localStorage.setItem(TOKEN_KEY, value)
  }

  function clear() {
    token.value = ''
    userInfo.value = null
    localStorage.removeItem(TOKEN_KEY)
  }

  async function login(params: LoginParams) {
    const result = await loginApi(params)
    setToken(result.token.access_token)
    userInfo.value = result.user
    return result
  }

  async function fetchUserInfo() {
    userInfo.value = await getMeApi()
    return userInfo.value
  }

  return { token, userInfo, setToken, clear, login, fetchUserInfo }
})
