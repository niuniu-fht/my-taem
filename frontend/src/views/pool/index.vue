<script setup lang="ts">
import {
  NButton,
  NCard,
  NDataTable,
  NEmpty,
  NForm,
  NFormItem,
  NImage,
  NInput,
  NInputNumber,
  NPopconfirm,
  NSelect,
  NSpace,
  NSpin,
  NSwitch,
  NTag,
  NText,
  NTooltip,
  NModal,
  type DataTableColumns,
} from 'naive-ui'
import { computed, h, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { listAdobeAccounts, type AdobeAccount } from '@/api/adobe'
import {
  batchDeletePool,
  batchLoginPool,
  batchLoginPoolFilter,
  batchRefreshCreditsPool,
  batchRefreshCreditsPoolFilter,
  exportPool,
  exportSelectedPool,
  getPoolMember,
  generatePoolMoeMail,
  importPool,
  listPool,
  refreshPoolARP,
  refreshPoolToken,
  testPoolMail,
  testPoolImage,
  updatePoolMember,
  type PoolItem,
  type PoolMemberDetail,
  type PoolCreditFilter,
  type PoolCreditValueFilter,
  type PoolStatusFilter,
  type PoolTokenFilter,
  type PoolTypeFilter,
  type TestImageResult,
} from '@/api/pool'
import BatchImportModal from '@/components/BatchImportModal.vue'

const router = useRouter()
const logging = ref(false)
const refreshingCredits = ref(false)
const autoRetryLogin = ref(true)
const loginMaxRetries = ref(2)
const importModalRef = ref<InstanceType<typeof BatchImportModal> | null>(null)
const importFn = (content: string) => importPool(content)
const moemailVisible = ref(false)
const moemailGenerating = ref(false)
const moemailForm = reactive({
  api_key: 'mk_biH9iMGVvOvrZETzY-U1GflX5rRKyE9H',
  count: 10,
  domain: 'edu6.site',
  name_prefix: '',
  expiry_time: 0,
  password: '',
})

async function handleBatchLogin() {
  if (!checkedRowKeys.value.length) {
    window.$message?.warning('请先勾选要登录的账号')
    return
  }
  logging.value = true
  try {
    const job = await batchLoginPool(checkedRowKeys.value, {
      autoRetry: autoRetryLogin.value,
      maxRetries: loginMaxRetries.value,
    })
    window.$message?.success(`已开始批量协议登录(${checkedRowKeys.value.length} 个),前往拉号任务查看进度`)
    router.push({ name: 'jobs', query: { id: String(job.id) } })
  } finally {
    logging.value = false
  }
}

async function handleBatchLoginFilter() {
  if (!pagination.itemCount) {
    window.$message?.warning('当前筛选没有账号')
    return
  }
  const adminId = selectedAdminId()
  logging.value = true
  try {
    const job = await batchLoginPoolFilter({
      keyword: keyword.value.trim(),
      registered_only: registeredOnly.value,
      admin_id: adminId,
      pool_type: poolTypeFilter.value,
      has_token: tokenFilter.value === 'yes' ? true : tokenFilter.value === 'no' ? false : null,
      credit_status: creditFilter.value,
      credit_value: creditValueFilter.value,
      status_filter: statusFilter.value,
      auto_retry: autoRetryLogin.value,
      max_retries: loginMaxRetries.value,
    })
    window.$message?.success(
      `已开始批量协议登录(当前筛选共 ${pagination.itemCount} 个),前往拉号任务查看进度`,
    )
    router.push({ name: 'jobs', query: { id: String(job.id) } })
  } finally {
    logging.value = false
  }
}

async function handleBatchRefreshCredits() {
  if (!checkedRowKeys.value.length) {
    window.$message?.warning('请先勾选要刷新额度的账号')
    return
  }
  refreshingCredits.value = true
  try {
    const job = await batchRefreshCreditsPool(checkedRowKeys.value)
    window.$message?.success(`已开始刷新选中账号额度(${checkedRowKeys.value.length} 个),前往拉号任务查看进度`)
    router.push({ name: 'jobs', query: { id: String(job.id) } })
  } finally {
    refreshingCredits.value = false
  }
}

async function handleBatchRefreshCreditsFilter() {
  if (!pagination.itemCount) {
    window.$message?.warning('当前筛选没有账号')
    return
  }
  const adminId = selectedAdminId()
  refreshingCredits.value = true
  try {
    const job = await batchRefreshCreditsPoolFilter({
      keyword: keyword.value.trim(),
      registered_only: registeredOnly.value,
      admin_id: adminId,
      pool_type: poolTypeFilter.value,
      has_token: true,
      credit_status: creditFilter.value,
      credit_value: creditValueFilter.value,
      status_filter: statusFilter.value,
    })
    window.$message?.success(`已开始刷新当前筛选额度,前往拉号任务查看进度`)
    router.push({ name: 'jobs', query: { id: String(job.id) } })
  } finally {
    refreshingCredits.value = false
  }
}

const data = ref<PoolItem[]>([])
const loading = ref(false)
const keyword = ref('')
const registeredOnly = ref(true)
const poolTypeFilter = ref<PoolTypeFilter>('sub')
const adminIdFilter = ref<number | 'all' | null>('all')
const tokenFilter = ref<PoolTokenFilter>('yes')
const selectedCreditFilter = ref('')
const creditFilter = ref<PoolCreditFilter>('')
const creditValueFilter = ref<PoolCreditValueFilter>(null)
const statusFilter = ref<PoolStatusFilter>('')
const checkedRowKeys = ref<number[]>([])
const exporting = ref(false)
const pagination = reactive({ page: 1, pageSize: 500, itemCount: 0 })

const typeOptions = [
  { label: '全部', value: 'all' },
  { label: '导入', value: 'imported' },
  { label: '子号', value: 'sub' },
  { label: '母号', value: 'admin' },
]
type AdminSelectOption = {
  label: string
  value: number | 'all'
  email?: string
  remark?: string
}

const adminMenuProps = {
  style: {
    width: '580px',
    maxWidth: 'calc(100vw - 48px)',
  },
}

function renderAdminLabel(option: AdminSelectOption) {
  if (option.value === 'all') return option.label
  return h('div', { style: 'max-width: 540px; padding: 4px 0;' }, [
    h('div', {
      style: 'font-size: 13px; line-height: 18px; white-space: normal; word-break: break-all;',
    }, option.email || option.label),
    option.remark
      ? h('div', {
          style: 'margin-top: 2px; font-size: 12px; line-height: 16px; color: #888; white-space: normal; word-break: break-all;',
        }, option.remark)
      : null,
  ])
}

const adminOptions = ref<any[]>([
  { label: '全部母号', value: 'all' },
])
const tokenOptions = [
  { label: '全部 Token', value: '' },
  { label: '有 Token', value: 'yes' },
  { label: '无 Token', value: 'no' },
]
const creditOptions = [
  { label: '全部额度', value: '' },
  { label: '额度未知', value: 'unknown' },
  { label: '额度正常', value: 'known' },
  { label: '0 额度', value: 'value:0' },
  { label: '10 额度', value: 'value:10' },
  { label: '500 额度', value: 'value:500' },
  { label: '4000 额度', value: 'value:4000' },
]
const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '待审批/低额度', value: 'needs_authorization' },
  { label: '注册失败', value: 'failed' },
  { label: '已拿 Token', value: 'registered' },
  { label: '未拿 Token', value: 'pending' },
]
const moemailDomainOptions = [
  { label: '随机域名', value: 'random' },
  { label: 'edu6.site', value: 'edu6.site' },
  { label: 'edu0.buzz', value: 'edu0.buzz' },
  { label: 'edu1.store', value: 'edu1.store' },
  { label: 'edu8.buzz', value: 'edu8.buzz' },
]
const expiryOptions = [
  { label: '永久', value: 0 },
  { label: '1 小时', value: 3600000 },
  { label: '1 天', value: 86400000 },
  { label: '7 天', value: 604800000 },
]

function selectedAdminId() {
  if (adminIdFilter.value === 'all' || adminIdFilter.value === null) return null
  const id = Number(adminIdFilter.value)
  return Number.isFinite(id) && id > 0 ? id : null
}

async function fetchData() {
  loading.value = true
  try {
    const adminId = selectedAdminId()
    const res = await listPool({
      page: pagination.page,
      size: pagination.pageSize,
      keyword: keyword.value.trim(),
      admin_id: adminId,
      registered_only: registeredOnly.value,
      pool_type: poolTypeFilter.value,
      has_token: tokenFilter.value,
      credit_status: creditFilter.value,
      credit_value: creditValueFilter.value,
      status_filter: statusFilter.value,
    })
    const items = adminId ? res.items.filter((item) => Number(item.admin_id) === adminId) : res.items
    data.value = items
    pagination.itemCount = adminId && items.length !== res.items.length ? items.length : res.total
    checkedRowKeys.value = []
  } finally {
    loading.value = false
  }
}

async function fetchAdminOptions() {
  const res = await listAdobeAccounts({ page: 1, size: 200 })
  adminOptions.value = [
    { label: '全部母号', value: 'all' },
    ...res.items.map((item: AdobeAccount) => {
      const remark = item.remark || ''
      return {
        label: remark ? `${item.email} (${remark})` : item.email,
        value: item.id,
        email: item.email,
        remark,
      }
    }),
  ]
}

function fmtExpires(ts: number | null) {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  const left = ts * 1000 - Date.now()
  const hours = Math.round(left / 3600000)
  return `${d.toLocaleString()}${hours > 0 ? `(剩${hours}h)` : '(已过期)'}`
}

const columns = computed<DataTableColumns<PoolItem>>(() => [
  { type: 'selection' },
  {
    title: '类型',
    key: 'is_admin',
    width: 76,
    render: (row) => {
      if (row.is_admin)
        return h(NTag, { type: 'warning', size: 'small', round: true, bordered: false }, () => '母号')
      if (row.is_imported)
        return h(NTag, { type: 'success', size: 'small', round: true, bordered: false }, () => '导入')
      return h(NTag, { type: 'info', size: 'small', round: true, bordered: false }, () => '子号')
    },
  },
  {
    title: '子号邮箱',
    key: 'email',
    minWidth: 220,
    ellipsis: { tooltip: true },
    render: (row) =>
      h('span', {}, [
        row.email,
        row.is_admin
          ? h(NText, { depth: 3, style: 'font-size:12px;margin-left:6px' }, () => '(母号自身)')
          : null,
      ]),
  },
  {
    title: '名称',
    key: 'display_name',
    width: 130,
    ellipsis: { tooltip: true },
    render: (row) => row.display_name || h(NText, { depth: 3 }, () => '—'),
  },
  {
    title: '所属母号',
    key: 'admin_email',
    minWidth: 200,
    ellipsis: { tooltip: true },
  },
  {
    title: '状态',
    key: 'registered',
    width: 100,
    render: (row) => {
      if (row.status === 'needs_authorization') {
        return h(NTag, { type: 'warning', size: 'small', round: true }, () => '待审批')
      }
      if (row.has_token && (row.credits === null || row.credits === undefined || row.credits < 0)) {
        return h(NTag, { type: 'warning', size: 'small', round: true }, () => '额度未知')
      }
      if (row.has_token) {
        return h(NTag, { type: 'success', size: 'small', round: true }, () => '已拿Token')
      }
      return h(NTag, { type: 'default', size: 'small', round: true }, () => row.status || '—')
    },
  },
  {
    title: '额度',
    key: 'credits',
    width: 80,
    render: (row) =>
      row.credits === null || row.credits === undefined || row.credits < 0
        ? h(NText, { depth: 3 }, () => '—')
        : String(row.credits),
  },
  {
    title: 'newbanana',
    key: 'nb',
    width: 120,
    render: (row) =>
      h(NSpace, { size: 4 }, () => [
        h(
          NTag,
          { type: row.has_cookie ? 'success' : 'default', size: 'small' },
          () => 'cookie',
        ),
        h(
          NTag,
          { type: row.has_token ? 'success' : 'default', size: 'small' },
          () => 'token',
        ),
        h(
          NTag,
          { type: row.has_arp ? 'success' : 'default', size: 'small' },
          () => 'arp',
        ),
      ]),
  },
  {
    title: '过期时间',
    key: 'expires_at',
    width: 200,
    render: (row) =>
      h(NText, { depth: 3, style: 'font-size:12px' }, () => fmtExpires(row.expires_at)),
  },
  {
    title: '入池时间',
    key: 'created_at',
    width: 170,
    render: (row) => new Date(row.created_at).toLocaleString(),
  },
  {
    title: '操作',
    key: 'actions',
    width: 380,
    fixed: 'right',
    render: (row) =>
      h(NSpace, { size: 4 }, () => [
        h(NButton, { size: 'small', secondary: true, onClick: () => openEdit(row) }, () => '编辑'),
        h(
          NButton,
          {
            size: 'small',
            type: 'success',
            secondary: true,
            loading: testingMailId.value === row.id,
            disabled: testingMailId.value !== null,
            onClick: () => handleTestMail(row),
          },
          () => '测试收件',
        ),
        h(
          NButton,
          {
            size: 'small',
            type: 'warning',
            secondary: true,
            loading: refreshingId.value === row.id,
            disabled: refreshingId.value !== null,
            onClick: () => handleRefresh(row),
          },
          () => '刷新AT',
        ),
        h(
          NButton,
          {
            size: 'small',
            type: 'info',
            secondary: true,
            loading: refreshingARPId.value === row.id,
            disabled: refreshingARPId.value !== null || !row.has_cookie,
            onClick: () => handleRefreshARP(row),
          },
          () => '刷新ARP',
        ),
        h(
          NButton,
          {
            size: 'small',
            type: 'primary',
            secondary: true,
            disabled: !row.has_token,
            onClick: () => openTest(row),
          },
          () => '测试出图',
        ),
      ]),
  },
])

// ===== 刷新 AT =====
const refreshingId = ref<number | null>(null)
const refreshingARPId = ref<number | null>(null)
const testingMailId = ref<number | null>(null)

async function handleTestMail(row: PoolItem) {
  testingMailId.value = row.id
  try {
    const res = await testPoolMail(row.id)
    if (res.success) {
      window.$message?.success(res.message)
    } else {
      window.$message?.warning(res.message)
    }
  } finally {
    testingMailId.value = null
  }
}

async function handleRefresh(row: PoolItem) {
  refreshingId.value = row.id
  try {
    const res = await refreshPoolToken(row.id)
    if (res.success) {
      window.$message?.success(`已刷新 AT,额度 ${res.credits ?? '—'}`)
    } else {
      window.$message?.warning(res.message || '刷新失败')
    }
    await fetchData()
  } finally {
    refreshingId.value = null
  }
}

async function handleRefreshARP(row: PoolItem) {
  refreshingARPId.value = row.id
  try {
    const res = await refreshPoolARP(row.id, {
      prompt: 'cartoon watermelon sticker',
      headless: true,
      timeoutSeconds: 120,
    })
    if (res.success) {
      window.$message?.success(`已捕获 ARP${res.has_access_token ? ',并同步 AT' : ''}`)
    } else {
      window.$message?.warning(res.message || '捕获 ARP 失败')
    }
    await fetchData()
  } finally {
    refreshingARPId.value = null
  }
}

// ===== 编辑 =====
const editVisible = ref(false)
const editLoading = ref(false)
const editSaving = ref(false)
const editForm = ref<PoolMemberDetail | null>(null)

async function openEdit(row: PoolItem) {
  editVisible.value = true
  editLoading.value = true
  editForm.value = null
  try {
    editForm.value = await getPoolMember(row.id)
  } finally {
    editLoading.value = false
  }
}

async function saveEdit() {
  if (!editForm.value) return
  editSaving.value = true
  try {
    const f = editForm.value
    await updatePoolMember(f.id, {
      display_name: f.display_name,
      status: f.status,
      access_token: f.access_token,
      cookie: f.cookie,
      arp_session_id: f.arp_session_id,
      refresh_token: f.refresh_token,
      client_id: f.client_id,
      credits: f.credits ?? undefined,
    })
    window.$message?.success('已保存')
    editVisible.value = false
    await fetchData()
  } finally {
    editSaving.value = false
  }
}

// ===== 测试出图 =====
const testVisible = ref(false)
const testLoading = ref(false)
const testTarget = ref<PoolItem | null>(null)
const testPrompt = ref('a cute corgi puppy running on a sunny beach, cinematic')
const testResult = ref<TestImageResult | null>(null)
const testQuality = ref('medium')
const testSize = ref('2048x2048')
const qualityOptions = [
  { label: '低 (low)', value: 'low' },
  { label: '中 (medium)', value: 'medium' },
  { label: '高 (high)', value: 'high' },
]
// value: "WxH" 显式尺寸,或 "auto"
const sizeOptions = [
  { label: '2048 × 2048', value: '2048x2048' },
  { label: '1024 × 1024', value: '1024x1024' },
  { label: '1536 × 1024 (3:2)', value: '1536x1024' },
  { label: '1024 × 1536 (2:3)', value: '1024x1536' },
  { label: '自动 (auto)', value: 'auto' },
]

function openTest(row: PoolItem) {
  testTarget.value = row
  testResult.value = null
  testVisible.value = true
}

async function runTest() {
  if (!testTarget.value) return
  testLoading.value = true
  testResult.value = null
  let width: number | null = null
  let height: number | null = null
  if (testSize.value !== 'auto') {
    const [w, h] = testSize.value.split('x').map((n) => Number(n))
    width = w
    height = h
  }
  try {
    testResult.value = await testPoolImage(testTarget.value.id, {
      prompt: testPrompt.value.trim(),
      quality: testQuality.value,
      width,
      height,
    })
    if (testResult.value.success) {
      window.$message?.success('出图成功')
    } else {
      window.$message?.warning(testResult.value.message || '出图失败')
    }
  } finally {
    testLoading.value = false
  }
}

async function handleExport(format: 'default' | 'json' | 'cookies' | 'tokens' | 'accounts') {
  exporting.value = true
  try {
    const adminId = selectedAdminId()
    if (checkedRowKeys.value.length) {
      await exportSelectedPool(format, checkedRowKeys.value)
      window.$message?.success(`已导出选中的 ${checkedRowKeys.value.length} 个账号`)
    } else {
      await exportPool(format, {
        keyword: keyword.value.trim(),
        admin_id: adminId,
        pool_type: poolTypeFilter.value,
        has_token: tokenFilter.value,
        credit_status: creditFilter.value,
        credit_value: creditValueFilter.value,
        status_filter: statusFilter.value,
      })
      window.$message?.success('已导出当前筛选')
    }
  } catch {
    // 拦截器已提示
  } finally {
    exporting.value = false
  }
}

async function handleBatchDelete() {
  if (!checkedRowKeys.value.length) return
  const res = await batchDeletePool(checkedRowKeys.value)
  window.$message?.success(res.message)
  checkedRowKeys.value = []
  await fetchData()
}

async function handleGenerateMoeMail() {
  moemailGenerating.value = true
  try {
    const res = await generatePoolMoeMail({ ...moemailForm })
    window.$message?.success(`创建完成:新增 ${res.created},更新 ${res.updated},失败 ${res.failed}`)
    moemailVisible.value = false
    fetchData()
  } finally {
    moemailGenerating.value = false
  }
}

function handlePageChange(page: number) {
  pagination.page = page
  fetchData()
}

function handlePageSizeChange(pageSize: number) {
  pagination.pageSize = pageSize
  pagination.page = 1
  fetchData()
}

function search() {
  pagination.page = 1
  fetchData()
}

function handleAdminFilterChange(value: number | 'all' | null) {
  adminIdFilter.value = value ?? 'all'
  search()
}

function handleCreditFilterChange(value: string) {
  if (value.startsWith('value:')) {
    creditFilter.value = ''
    creditValueFilter.value = Number(value.slice('value:'.length))
  } else {
    creditFilter.value = value as PoolCreditFilter
    creditValueFilter.value = null
  }
  search()
}

function handleStatusFilterChange(value: PoolStatusFilter) {
  if (value === 'needs_authorization') {
    registeredOnly.value = false
    poolTypeFilter.value = 'sub'
  }
  search()
}

onMounted(() => {
  fetchAdminOptions()
  fetchData()
})
</script>

<template>
  <NCard :bordered="false">
    <NSpace vertical size="large">
      <NSpace justify="space-between">
        <NSpace>
          <NButton type="primary" ghost @click="importModalRef?.open()">导入邮箱</NButton>
          <NButton type="success" ghost @click="moemailVisible = true">一键创建 MoeMail</NButton>
          <NTooltip>
            <template #trigger>
              <NButton type="primary" :loading="exporting" @click="handleExport('default')">
                导出(按设置)
              </NButton>
            </template>
            按「设置 → 导出默认格式」导出;可在设置里切换 FF-iOS Token / 纯 Cookie
          </NTooltip>
          <NTooltip>
            <template #trigger>
              <NButton :loading="exporting" @click="handleExport('json')">
                导出 newbanana(JSON)
              </NButton>
            </template>
            [{ cookie, name, access_token, device_token, credits, expires_at }] —— 可直接导入 newbanana
          </NTooltip>
          <NButton :loading="exporting" @click="handleExport('cookies')">导出 Cookie</NButton>
          <NButton :loading="exporting" @click="handleExport('tokens')">导出 Token</NButton>
          <NTooltip>
            <template #trigger>
              <NButton type="warning" :loading="exporting" @click="handleExport('accounts')">
                导出账号
              </NButton>
            </template>
            有勾选时只导出勾选账号;未勾选时导出当前筛选。格式:邮箱----Adobe密码
          </NTooltip>
          <NTooltip>
            <template #trigger>
              <NButton
                type="info"
                :loading="logging"
                :disabled="!checkedRowKeys.length"
                @click="handleBatchLogin"
              >
                登录选中 ({{ checkedRowKeys.length }})
              </NButton>
            </template>
            对当前页勾选的账号协议登录,刷新 access_token / cookie / 额度
          </NTooltip>
          <NTooltip>
            <template #trigger>
              <NButton
                type="success"
                ghost
                :loading="refreshingCredits"
                :disabled="!checkedRowKeys.length"
                @click="handleBatchRefreshCredits"
              >
                刷新选中额度 ({{ checkedRowKeys.length }})
              </NButton>
            </template>
            只用已有 Token 查询额度,不会重新登录或收验证码
          </NTooltip>
          <NPopconfirm @positive-click="handleBatchRefreshCreditsFilter">
            <template #trigger>
              <NButton
                type="success"
                :loading="refreshingCredits"
                :disabled="!pagination.itemCount"
              >
                刷新当前筛选额度
              </NButton>
            </template>
            对当前筛选条件下有 Token 的账号批量刷新额度,确认?
          </NPopconfirm>
          <NPopconfirm @positive-click="handleBatchLoginFilter">
            <template #trigger>
              <NButton type="primary" :loading="logging" :disabled="!pagination.itemCount">
                登录当前筛选 ({{ pagination.itemCount }})
              </NButton>
            </template>
            <div style="max-width: 280px">
              <div>对当前筛选条件下的全部 {{ pagination.itemCount }} 个账号开批量协议登录,确认?</div>
              <div style="margin-top: 8px; display: flex; align-items: center; gap: 8px">
                <NSwitch v-model:value="autoRetryLogin" size="small" />
                <NText depth="3" style="font-size: 12px">失败自动重试(最多 {{ loginMaxRetries }} 轮)</NText>
              </div>
            </div>
          </NPopconfirm>
          <NPopconfirm @positive-click="handleBatchDelete">
            <template #trigger>
              <NButton type="error" :disabled="!checkedRowKeys.length">批量删除</NButton>
            </template>
            将从号池移除选中的 {{ checkedRowKeys.length }} 个子号(同时尝试从组织里移除),确认?
          </NPopconfirm>
        </NSpace>
        <NSpace align="center" wrap>
          <NText depth="3" style="font-size: 13px">类型</NText>
          <NSelect
            v-model:value="poolTypeFilter"
            :options="typeOptions"
            style="width: 100px"
            @update:value="search"
          />
          <NText depth="3" style="font-size: 13px">所属母号</NText>
          <NSelect
            v-model:value="adminIdFilter"
            :options="adminOptions"
            :menu-props="adminMenuProps"
            :render-label="renderAdminLabel"
            filterable
            clearable
            style="width: 460px; max-width: calc(100vw - 420px)"
            @update:value="handleAdminFilterChange"
          />
          <NText depth="3" style="font-size: 13px">Token</NText>
          <NSelect
            v-model:value="tokenFilter"
            :options="tokenOptions"
            style="width: 120px"
            @update:value="search"
          />
          <NText depth="3" style="font-size: 13px">额度</NText>
          <NSelect
            v-model:value="selectedCreditFilter"
            :options="creditOptions"
            style="width: 130px"
            @update:value="handleCreditFilterChange"
          />
          <NText depth="3" style="font-size: 13px">状态</NText>
          <NSelect
            v-model:value="statusFilter"
            :options="statusOptions"
            style="width: 120px"
            @update:value="handleStatusFilterChange"
          />
          <NText depth="3" style="font-size: 13px">只看已注册</NText>
          <NSwitch v-model:value="registeredOnly" @update:value="search" />
          <NInput
            v-model:value="keyword"
            placeholder="搜索邮箱"
            clearable
            style="width: 220px"
            @keyup.enter="search"
          />
          <NButton @click="search">搜索</NButton>
        </NSpace>
      </NSpace>

      <NDataTable
        :columns="columns"
        :data="data"
        :loading="loading"
        :row-key="(row: PoolItem) => row.id"
        v-model:checked-row-keys="checkedRowKeys"
        :scroll-x="1600"
        remote
        :pagination="{
          page: pagination.page,
          pageSize: pagination.pageSize,
          itemCount: pagination.itemCount,
          pageSizes: [50, 100, 200, 500],
          showSizePicker: true,
          prefix: (info) => `共 ${info.itemCount} 个号`,
          onUpdatePage: handlePageChange,
          onUpdatePageSize: handlePageSizeChange,
        }"
      >
        <template #empty>
          <NEmpty description="号池为空,去 母号管理里「一键拉号」生成子号" />
        </template>
      </NDataTable>
    </NSpace>

    <!-- 导入邮箱(独立账号) -->
    <NModal v-model:show="moemailVisible">
      <NCard
        title="一键创建 MoeMail 到号池"
        style="width: 560px"
        :bordered="false"
        role="dialog"
      >
        <NForm :model="moemailForm" label-placement="top">
          <NFormItem label="API Key">
            <NInput v-model:value="moemailForm.api_key" type="password" show-password-on="click" />
          </NFormItem>
          <NSpace>
            <NFormItem label="数量">
              <NInputNumber v-model:value="moemailForm.count" :min="1" :max="500" style="width: 120px" />
            </NFormItem>
            <NFormItem label="域名">
              <NSelect v-model:value="moemailForm.domain" :options="moemailDomainOptions" style="width: 140px" />
            </NFormItem>
            <NFormItem label="有效期">
              <NSelect v-model:value="moemailForm.expiry_time" :options="expiryOptions" style="width: 120px" />
            </NFormItem>
          </NSpace>
          <NFormItem label="邮箱前缀(可选)">
            <NInput v-model:value="moemailForm.name_prefix" placeholder="留空则随机生成" />
          </NFormItem>
          <NFormItem label="默认密码(可选)">
            <NInput v-model:value="moemailForm.password" placeholder="仅写入本地字段" />
          </NFormItem>
        </NForm>
        <template #footer>
          <NSpace justify="end">
            <NButton @click="moemailVisible = false">取消</NButton>
            <NButton type="primary" :loading="moemailGenerating" @click="handleGenerateMoeMail">
              创建并导入号池
            </NButton>
          </NSpace>
        </template>
      </NCard>
    </NModal>

    <BatchImportModal
      ref="importModalRef"
      title="导入邮箱到号池(独立账号)"
      format-hint="邮箱----密码----ClientID----RefreshToken(或 邮箱|密码|RefreshToken|ClientID)"
      placeholder="BidezDufficy631@hotmail.com----lvbeczm9527----9e5f94bc-e8a4-4e73-b8be-63364c29d753----M.C512_BAY...."
      :import-fn="importFn"
      @success="fetchData"
    />

    <!-- 编辑 -->
    <NModal
      v-model:show="editVisible"
      preset="card"
      title="编辑子号"
      style="width: 640px; max-width: 92vw"
    >
      <NSpin :show="editLoading">
        <NForm v-if="editForm" label-placement="left" :label-width="100">
          <NFormItem label="子号邮箱">
            <NInput :value="editForm.email" disabled />
          </NFormItem>
          <NFormItem label="名称">
            <NInput v-model:value="editForm.display_name" placeholder="display name" />
          </NFormItem>
          <NFormItem label="状态">
            <NInput v-model:value="editForm.status" placeholder="状态文本" />
          </NFormItem>
          <NFormItem label="额度">
            <NInputNumber v-model:value="editForm.credits" :min="0" style="width: 100%" />
          </NFormItem>
          <NFormItem label="access_token">
            <NInput
              v-model:value="editForm.access_token"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 4 }"
              placeholder="firefly access token"
            />
          </NFormItem>
          <NFormItem label="cookie">
            <NInput
              v-model:value="editForm.cookie"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 4 }"
            />
          </NFormItem>
          <NFormItem label="ARP Session">
            <NInput
              v-model:value="editForm.arp_session_id"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 4 }"
              placeholder="浏览器请求头 x-arp-session-id"
            />
          </NFormItem>
          <NFormItem label="refresh_token">
            <NInput
              v-model:value="editForm.refresh_token"
              type="textarea"
              :autosize="{ minRows: 1, maxRows: 3 }"
            />
          </NFormItem>
          <NFormItem label="client_id">
            <NInput v-model:value="editForm.client_id" />
          </NFormItem>
        </NForm>
      </NSpin>
      <template #footer>
        <NSpace justify="end">
          <NButton @click="editVisible = false">取消</NButton>
          <NButton type="primary" :loading="editSaving" :disabled="!editForm" @click="saveEdit">
            保存
          </NButton>
        </NSpace>
      </template>
    </NModal>

    <!-- 测试出图 -->
    <NModal
      v-model:show="testVisible"
      preset="card"
      title="测试出图"
      style="width: 720px; max-width: 92vw"
    >
      <NSpace vertical size="large">
        <NText depth="3" style="font-size: 13px">
          账号:{{ testTarget?.email }} —— 用该账号的 access_token 调 Firefly 生成图片(GPT Image 2)
        </NText>
        <NSpace align="center">
          <span style="font-size: 13px">质量</span>
          <NSelect v-model:value="testQuality" :options="qualityOptions" style="width: 130px" />
          <span style="font-size: 13px">尺寸</span>
          <NSelect v-model:value="testSize" :options="sizeOptions" style="width: 170px" />
        </NSpace>
        <NSpace align="center">
          <NInput v-model:value="testPrompt" placeholder="提示词 prompt" style="width: 480px" />
          <NButton type="primary" :loading="testLoading" @click="runTest">生成</NButton>
        </NSpace>
        <NSpin :show="testLoading" description="出图中,大概需要 30~120 秒 …">
          <div style="min-height: 80px">
            <template v-if="testResult">
              <NSpace vertical v-if="testResult.success">
                <NTag type="success" round>出图成功</NTag>
                <NImage
                  v-if="testResult.image_url"
                  :src="testResult.image_url"
                  width="320"
                  object-fit="contain"
                />
              </NSpace>
              <NTag v-else type="error" round>{{ testResult.message }}</NTag>
            </template>
            <NText v-else-if="!testLoading" depth="3" style="font-size: 13px">
              点击「生成」开始测试出图
            </NText>
          </div>
        </NSpin>
      </NSpace>
    </NModal>
  </NCard>
</template>
