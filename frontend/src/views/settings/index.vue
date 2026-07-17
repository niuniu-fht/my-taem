<script setup lang="ts">
import {
  NButton,
  NCard,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NSelect,
  NSpace,
  NSwitch,
  NTag,
  NText,
  type FormInst,
  type FormRules,
} from 'naive-ui'
import { onMounted, reactive, ref } from 'vue'

import {
  changePassword,
  getSettings,
  testProxy,
  updateSettings,
  type ProxyTestItem,
  type SystemSettings,
} from '@/api/settings'

const settings = reactive<SystemSettings>({
  proxy_enabled: false,
  proxy_url: '',
  concurrency: 5,
  request_timeout: 30,
  register_country: 'SG',
  register_locale: 'en_US',
  export_format: 'token',
})

// 号池默认导出格式:token=FF-iOS 全量(cookie+access_token+device_token),cookie=纯 CK。
const exportFormatOptions = [
  { label: 'FF-iOS Token(保留 access_token + device_token)', value: 'token' },
  { label: '纯 Cookie(CK 格式)', value: 'cookie' },
]

const savingSettings = ref(false)
const testingProxy = ref(false)
const proxyResults = ref<ProxyTestItem[]>([])

// 注册账号所用的国家。US 区会被 Adobe geoip/第三方模型地区灰度挡掉,默认用 SG。
const countryOptions = [
  { label: '新加坡 SG(推荐)', value: 'SG' },
  { label: '中国香港 HK', value: 'HK' },
  { label: '日本 JP', value: 'JP' },
  { label: '英国 GB', value: 'GB' },
  { label: '加拿大 CA', value: 'CA' },
  { label: '澳大利亚 AU', value: 'AU' },
  { label: '德国 DE', value: 'DE' },
  { label: '美国 US(不推荐)', value: 'US' },
]

async function loadSettings() {
  const data = await getSettings()
  Object.assign(settings, data)
}

async function handleTestProxy() {
  if (!settings.proxy_url.trim()) {
    window.$message?.warning('请先填写代理地址')
    return
  }
  testingProxy.value = true
  proxyResults.value = []
  try {
    const res = await testProxy(settings.proxy_url)
    proxyResults.value = res.items
    if (res.ok_count === res.total) {
      window.$message?.success(`全部可用:${res.ok_count}/${res.total}`)
    } else {
      window.$message?.warning(`可用 ${res.ok_count}/${res.total},有代理不通`)
    }
  } finally {
    testingProxy.value = false
  }
}

async function handleSaveSettings() {
  savingSettings.value = true
  try {
    const data = await updateSettings({ ...settings })
    Object.assign(settings, data)
    window.$message?.success('设置已保存')
  } finally {
    savingSettings.value = false
  }
}

// 修改密码
const pwdFormRef = ref<FormInst | null>(null)
const pwdForm = reactive({ old_password: '', new_password: '', confirm_password: '' })
const savingPwd = ref(false)

const pwdRules: FormRules = {
  old_password: { required: true, message: '请输入原密码', trigger: 'blur' },
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' },
  ],
  confirm_password: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_rule, value: string) => value === pwdForm.new_password,
      message: '两次输入的密码不一致',
      trigger: ['blur', 'input'],
    },
  ],
}

async function handleChangePassword() {
  try {
    await pwdFormRef.value?.validate()
  } catch {
    return
  }
  savingPwd.value = true
  try {
    await changePassword(pwdForm.old_password, pwdForm.new_password)
    window.$message?.success('密码修改成功')
    pwdForm.old_password = ''
    pwdForm.new_password = ''
    pwdForm.confirm_password = ''
  } finally {
    savingPwd.value = false
  }
}

onMounted(loadSettings)
</script>

<template>
  <NSpace vertical :size="20">
    <NCard title="运行设置" :bordered="false">
      <NForm label-placement="left" :label-width="120" style="max-width: 860px">
        <NFormItem label="启用代理">
          <NSwitch v-model:value="settings.proxy_enabled" />
        </NFormItem>
        <NFormItem label="代理地址">
          <NSpace vertical style="width: 100%">
            <NInput
              v-model:value="settings.proxy_url"
              type="textarea"
              :autosize="{ minRows: 4, maxRows: 14 }"
              placeholder="一行一个代理,支持:&#10;user:pass@host:port(默认 http)&#10;http://user:pass@host:port&#10;socks5://host:port"
              :disabled="!settings.proxy_enabled"
              style="width: 100%; font-family: monospace"
            />
            <NSpace align="center">
              <NButton
                size="small"
                :loading="testingProxy"
                :disabled="!settings.proxy_url.trim()"
                @click="handleTestProxy"
              >
                测试代理
              </NButton>
              <NText depth="3" style="font-size: 12px">
                一行一个,外呼时按行轮换出口 IP;并发拉号会自动分散到不同代理。留空则不使用代理。
              </NText>
            </NSpace>
            <NSpace v-if="proxyResults.length" vertical size="small">
              <div
                v-for="(r, i) in proxyResults"
                :key="i"
                style="display: flex; align-items: center; gap: 8px; font-size: 12px"
              >
                <NTag :type="r.ok ? 'success' : 'error'" size="small" round>
                  {{ r.ok ? '可用' : '失败' }}
                </NTag>
                <span style="font-family: monospace; color: #4e5969">{{ r.proxy }}</span>
                <span v-if="r.ok" style="color: #18a058">→ {{ r.ip }} · {{ r.latency_ms }}ms</span>
                <span v-else style="color: #d03050">{{ r.message }}</span>
              </div>
            </NSpace>
          </NSpace>
        </NFormItem>
        <NFormItem label="并发线程数">
          <NInputNumber v-model:value="settings.concurrency" :min="1" :max="1000" style="width: 200px" />
        </NFormItem>
        <NFormItem label="请求超时(秒)">
          <NInputNumber v-model:value="settings.request_timeout" :min="1" :max="600" style="width: 200px" />
        </NFormItem>
        <NFormItem label="注册地区">
          <NSpace vertical style="width: 100%">
            <NSelect
              v-model:value="settings.register_country"
              :options="countryOptions"
              tag
              filterable
              style="width: 300px"
            />
            <NText depth="3" style="font-size: 12px">
              注册/补全账号时使用的国家代码(两位大写)。美国 US 会被 Adobe geoip 及第三方模型地区灰度拦截,推荐用新加坡 SG。
            </NText>
          </NSpace>
        </NFormItem>
        <NFormItem label="注册语言 locale">
          <NInput v-model:value="settings.register_locale" placeholder="en_US" style="width: 200px" />
        </NFormItem>
        <NFormItem label="导出默认格式">
          <NSpace vertical style="width: 100%">
            <NSelect
              v-model:value="settings.export_format"
              :options="exportFormatOptions"
              style="width: 360px"
            />
            <NText depth="3" style="font-size: 12px">
              号池页「导出(按设置)」按钮使用此格式。Token 格式为 newbanana 全量 JSON,保留
              cookie + access_token + device_token;Cookie 格式仅导出纯 CK([{ cookie, name }])。
            </NText>
          </NSpace>
        </NFormItem>
        <NFormItem label=" ">
          <NButton type="primary" :loading="savingSettings" @click="handleSaveSettings">
            保存设置
          </NButton>
        </NFormItem>
      </NForm>
    </NCard>

    <NCard title="修改管理员密码" :bordered="false">
      <NForm
        ref="pwdFormRef"
        :model="pwdForm"
        :rules="pwdRules"
        label-placement="left"
        :label-width="120"
        style="max-width: 480px"
      >
        <NFormItem label="原密码" path="old_password">
          <NInput v-model:value="pwdForm.old_password" type="password" show-password-on="click" />
        </NFormItem>
        <NFormItem label="新密码" path="new_password">
          <NInput v-model:value="pwdForm.new_password" type="password" show-password-on="click" />
        </NFormItem>
        <NFormItem label="确认新密码" path="confirm_password">
          <NInput v-model:value="pwdForm.confirm_password" type="password" show-password-on="click" />
        </NFormItem>
        <NFormItem label=" ">
          <NButton type="primary" :loading="savingPwd" @click="handleChangePassword">
            修改密码
          </NButton>
        </NFormItem>
      </NForm>
    </NCard>
  </NSpace>
</template>
