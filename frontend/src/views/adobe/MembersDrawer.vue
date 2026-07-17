<script setup lang="ts">
import {
  NButton,
  NDataTable,
  NDrawer,
  NDrawerContent,
  NEmpty,
  NInput,
  NInputNumber,
  NLog,
  NModal,
  NProgress,
  NRadio,
  NRadioGroup,
  NSpace,
  NTag,
  NText,
  NTooltip,
  type DataTableColumns,
} from 'naive-ui'
import { computed, h, onUnmounted, reactive, ref, watch } from 'vue'

import {
  batchAuthorizeLoginMembers,
  batchDeleteMembers,
  batchGrantMembers,
  buildTeam,
  cancelJob,
  getJob,
  listAdobeMembers,
  type AdobeAccount,
  type AdobeMember,
  type BuildTeamMode,
  type JobStatus,
} from '@/api/adobe'

const props = defineProps<{ show: boolean; account: AdobeAccount | null }>()
const emit = defineEmits<{ 'update:show': [boolean]; refresh: [] }>()

const visible = computed({
  get: () => props.show,
  set: (v) => emit('update:show', v),
})

const data = ref<AdobeMember[]>([])
const loading = ref(false)
const keyword = ref('')
const checkedRowKeys = ref<number[]>([])
const authorizingMembers = ref(false)
const pagination = reactive({ page: 1, pageSize: 50, itemCount: 0 })

async function fetchData() {
  if (!props.account) return
  loading.value = true
  try {
    const res = await listAdobeMembers(props.account.id, {
      page: pagination.page,
      size: pagination.pageSize,
      keyword: keyword.value.trim(),
    })
    data.value = res.items
    pagination.itemCount = res.total
  } finally {
    loading.value = false
  }
}

watch(
  () => props.show,
  (v) => {
    if (v) {
      pagination.page = 1
      keyword.value = ''
      checkedRowKeys.value = []
      fetchData()
    }
  },
)

function renderStatus(row: AdobeMember) {
  const map: Record<string, { type: 'success' | 'error' | 'warning' | 'default'; label: string }> = {
    registered: { type: 'success', label: '已注册' },
    needs_authorization: { type: 'warning', label: '待审批' },
    granted: { type: 'warning', label: '已授权' },
    member: { type: 'success', label: '已是成员' },
    failed: { type: 'error', label: '失败' },
    removed_failed: { type: 'warning', label: '移除失败' },
  }
  const cfg = map[row.status] || { type: 'default', label: row.status || '—' }
  const tag = h(NTag, { type: cfg.type, size: 'small', round: true }, () => cfg.label)
  const statusNode = row.email_disabled
    ? h(NSpace, { size: 4, wrap: false }, () => [
        tag,
        h(NTag, { type: 'warning', size: 'small', round: true }, () => '已停用'),
      ])
    : tag
  if (!row.message) return statusNode
  return h(NTooltip, null, {
    trigger: () => statusNode,
    default: () => h('div', { style: 'max-width:360px;word-break:break-all;' }, row.message),
  })
}

async function handleAuthorizeSelected() {
  if (!props.account || !checkedRowKeys.value.length) {
    window.$message?.warning('请先选择子号')
    return
  }
  authorizingMembers.value = true
  try {
    const res = await batchAuthorizeLoginMembers(props.account.id, checkedRowKeys.value)
    if (res.failed === 0) {
      window.$message?.success(`授权并刷新完成:可用 ${res.granted} 个`)
    } else {
      const firstErr = res.items.find((item) => !item.ok)
      window.$message?.warning(
        `完成:可用 ${res.granted} 个,待处理 ${res.failed} 个${
          firstErr ? `(示例:${firstErr.email} ${firstErr.message})` : ''
        }`,
      )
    }
    checkedRowKeys.value = []
    await fetchData()
    emit('refresh')
  } finally {
    authorizingMembers.value = false
  }
}

function rowClassName(row: AdobeMember) {
  return row.email_disabled ? 'member-email-disabled-row' : ''
}

const columns = computed<DataTableColumns<AdobeMember>>(() => [
  { type: 'selection' },
  { title: '邮箱', key: 'email', minWidth: 220, ellipsis: { tooltip: true } },
  {
    title: '状态',
    key: 'status',
    width: 100,
    render: (row) => renderStatus(row),
  },
  {
    title: '额度',
    key: 'credits',
    width: 80,
    render: (row) =>
      row.credits === null || row.credits === undefined
        ? h(NText, { depth: 3 }, () => '—')
        : String(row.credits),
  },
  {
    title: 'newbanana',
    key: 'nb',
    width: 90,
    render: (row) =>
      row.registered
        ? h(NTag, { type: 'success', size: 'small', round: true }, () => '可导出')
        : h(NText, { depth: 3 }, () => '—'),
  },
  {
    title: '时间',
    key: 'updated_at',
    width: 170,
    render: (row) => new Date(row.updated_at).toLocaleString(),
  },
])

// ---- 批量加号授权 ----
const grantModal = ref(false)
const granting = ref(false)
const grantForm = reactive<{ mode: 'pool' | 'paste'; count: number; emails: string }>({
  mode: 'pool',
  count: 10,
  emails: '',
})

function openGrant() {
  grantForm.mode = 'pool'
  grantForm.count = 10
  grantForm.emails = ''
  grantModal.value = true
}

async function submitGrant() {
  if (!props.account) return
  const payload: { count?: number; emails?: string[] } = {}
  if (grantForm.mode === 'pool') {
    if (!grantForm.count || grantForm.count < 1) {
      window.$message?.warning('请输入要授权的数量')
      return
    }
    payload.count = grantForm.count
  } else {
    const emails = grantForm.emails
      .split(/[\s,;]+/)
      .map((e) => e.trim())
      .filter((e) => e.includes('@'))
    if (!emails.length) {
      window.$message?.warning('请粘贴至少一个邮箱')
      return
    }
    payload.emails = emails
  }
  granting.value = true
  try {
    const res = await batchGrantMembers(props.account.id, payload)
    if (res.failed === 0) {
      window.$message?.success(`授权完成:成功 ${res.granted} 个`)
    } else {
      const firstErr = res.items.find((i) => !i.ok)
      window.$message?.warning(
        `完成:成功 ${res.granted} 个,失败 ${res.failed} 个${
          firstErr ? `(示例:${firstErr.email} ${firstErr.message}）` : ''
        }`,
      )
    }
    grantModal.value = false
    pagination.page = 1
    await fetchData()
    emit('refresh')
  } catch (e) {
    // 拦截器已提示
  } finally {
    granting.value = false
  }
}

// ---- 一键拉号(凑满 N 个已注册子号)----
const buildModal = ref(false)
const buildMode = ref<BuildTeamMode>('one_by_one')
const buildCount = ref(9)
const job = ref<JobStatus | null>(null)
const starting = ref(false)
const stopping = ref(false)
let pollTimer: number | null = null

const logText = computed(() => (job.value?.logs ?? []).join('\n'))
const jobRunning = computed(() => job.value?.status === 'running')
const jobPercent = computed(() => {
  const t = job.value?.target || 0
  if (!t) return 0
  return Math.min(100, Math.round(((job.value?.success || 0) / t) * 100))
})
const jobMessage = computed(() => job.value?.extra?.teams?.[0]?.message || '')

function stopPoll() {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

function startPoll() {
  stopPoll()
  pollTimer = window.setInterval(async () => {
    const id = job.value?.id
    if (!id) return
    try {
      job.value = await getJob(id)
      if (job.value.status !== 'running') {
        stopping.value = false
        stopPoll()
        await fetchData()
        emit('refresh')
      }
    } catch {
      stopping.value = false
      stopPoll()
    }
  }, 2000)
}

function openBuild() {
  buildMode.value = 'one_by_one'
  buildCount.value = 9
  job.value = null
  stopping.value = false
  buildModal.value = true
}

async function startBuild() {
  if (!props.account) return
  starting.value = true
  stopping.value = false
  try {
    job.value = await buildTeam(props.account.id, buildCount.value, buildMode.value)
    if (job.value.status === 'running') {
      startPoll()
    } else {
      await fetchData()
      emit('refresh')
    }
  } catch {
    // 拦截器已提示
  } finally {
    starting.value = false
  }
}

async function stopBuild() {
  const id = job.value?.id
  if (!id || !jobRunning.value) return
  stopping.value = true
  try {
    const res = await cancelJob(id)
    window.$message?.warning(res.message || '已请求停止拉号')
    job.value = await getJob(id)
    if (job.value.status === 'running') {
      startPoll()
    } else {
      stopping.value = false
      await fetchData()
      emit('refresh')
    }
  } catch {
    stopping.value = false
  }
}

watch(
  () => props.show,
  (v) => {
    if (!v) {
      stopPoll()
      stopping.value = false
      buildModal.value = false
    }
  },
)

onUnmounted(stopPoll)

async function handleBatchRemove() {
  if (!props.account || !checkedRowKeys.value.length) {
    window.$message?.warning('请先勾选要移除的成员')
    return
  }
  const res = await batchDeleteMembers(props.account.id, checkedRowKeys.value)
  window.$message?.success(res.message)
  checkedRowKeys.value = []
  await fetchData()
  emit('refresh')
}

function handlePageChange(page: number) {
  pagination.page = page
  fetchData()
}
</script>

<template>
  <NDrawer v-model:show="visible" :width="720" placement="right">
    <NDrawerContent :title="`子账号管理 · ${account?.email ?? ''}`" closable>
      <NSpace vertical size="large">
        <NText depth="3" style="font-size: 13px">
          组织:{{ account?.org_id || '—' }} ·
          授权产品:{{ account?.product_name || '—' }}
        </NText>

        <NSpace justify="space-between">
          <NSpace>
            <NButton type="primary" :disabled="!account?.has_org" @click="openBuild">
              安全补号
            </NButton>
            <NButton :disabled="!account?.has_org" @click="openGrant">
              仅授权(不注册)
            </NButton>
            <NButton
              type="success"
              :disabled="!checkedRowKeys.length || !account?.has_org"
              :loading="authorizingMembers"
              @click="handleAuthorizeSelected"
            >
              授权并刷新
            </NButton>
            <NButton type="error" :disabled="!checkedRowKeys.length" @click="handleBatchRemove">
              批量移除
            </NButton>
          </NSpace>
          <NSpace>
            <NInput
              v-model:value="keyword"
              placeholder="搜索邮箱"
              clearable
              style="width: 200px"
              @keyup.enter="((pagination.page = 1), fetchData())"
            />
            <NButton @click="((pagination.page = 1), fetchData())">搜索</NButton>
          </NSpace>
        </NSpace>

        <NDataTable
          :columns="columns"
          :data="data"
          :loading="loading"
          :row-key="(row: AdobeMember) => row.id"
          :row-class-name="rowClassName"
          v-model:checked-row-keys="checkedRowKeys"
          :scroll-x="760"
          remote
          :pagination="{
            page: pagination.page,
            pageSize: pagination.pageSize,
            itemCount: pagination.itemCount,
            prefix: (info) => `共 ${info.itemCount} 个成员`,
            onUpdatePage: handlePageChange,
          }"
        >
          <template #empty>
            <NEmpty description="还没有子账号,点击「批量加号授权」开始" />
          </template>
        </NDataTable>
      </NSpace>
    </NDrawerContent>
  </NDrawer>

  <!-- 批量加号授权弹窗 -->
  <NModal v-model:show="grantModal" preset="card" title="批量加子账号并授权" style="width: 560px">
    <NSpace vertical size="large">
      <NRadioGroup v-model:value="grantForm.mode">
        <NSpace>
          <NRadio value="pool">从邮箱池取号</NRadio>
          <NRadio value="paste">手动粘贴邮箱</NRadio>
        </NSpace>
      </NRadioGroup>

      <template v-if="grantForm.mode === 'pool'">
        <NSpace align="center">
          <NText>取未使用邮箱数量:</NText>
          <NInputNumber v-model:value="grantForm.count" :min="1" :max="500" style="width: 160px" />
        </NSpace>
        <NText depth="3" style="font-size: 12px">
          将从「邮箱管理」池里取未使用的邮箱作为子账号,授权成功后自动标记为已使用。
        </NText>
      </template>
      <template v-else>
        <NInput
          v-model:value="grantForm.emails"
          type="textarea"
          :autosize="{ minRows: 5, maxRows: 12 }"
          placeholder="每行一个邮箱,或用空格/逗号分隔"
        />
      </template>
    </NSpace>
    <template #footer>
      <NSpace justify="end">
        <NButton @click="grantModal = false">取消</NButton>
        <NButton type="primary" :loading="granting" @click="submitGrant">开始授权</NButton>
      </NSpace>
    </template>
  </NModal>

  <!-- 一键拉号 进度弹窗 -->
  <NModal
    v-model:show="buildModal"
    preset="card"
    title="安全补号 / 一键拉满"
    style="width: 680px"
    :mask-closable="!jobRunning"
    :closable="!jobRunning"
  >
    <NSpace vertical size="large">
      <template v-if="!job">
        <NRadioGroup v-model:value="buildMode">
          <NSpace>
            <NRadio value="one_by_one">安全补一个</NRadio>
            <NRadio value="fill">凑满目标</NRadio>
          </NSpace>
        </NRadioGroup>
        <NSpace align="center">
          <NText>{{ buildMode === 'one_by_one' ? '最多补到:' : '目标已注册子号数量:' }}</NText>
          <NInputNumber v-model:value="buildCount" :min="1" :max="50" style="width: 160px" />
        </NSpace>
        <NText depth="3" style="font-size: 12px">
          安全补一个会先校准当前成功子号数,然后本轮只补 1 个成功号;失败邮箱会自动停用并换号。
          全程单并发:邀请 → 分配产品 → 子号登录收验证码 → 切企业资料 → 获取积分。
          可以随时点「停止拉号」,停止后不会再取新邮箱。只要检测到真实 Adobe 429,会立即自动停止并提示隔夜或至少等待 12-24 小时后再继续。
        </NText>
      </template>

      <template v-else>
        <NSpace vertical>
          <NText
            >进度:成功 {{ job.success }} / 目标 {{ job.target }} · 失败 {{ job.fail }}
            <NTag
              v-if="job.status === 'done'"
              type="success"
              size="small"
              round
              style="margin-left: 8px"
              >已完成</NTag
            >
            <NTag
              v-else-if="job.status === 'error'"
              type="error"
              size="small"
              round
              style="margin-left: 8px"
              >出错</NTag
            >
            <NTag
              v-else-if="job.status === 'cancelled'"
              type="warning"
              size="small"
              round
              style="margin-left: 8px"
              >已停止</NTag
            >
            <NTag v-else type="info" size="small" round style="margin-left: 8px">进行中</NTag>
          </NText>
          <NProgress
            type="line"
            :percentage="jobPercent"
            :status="job.status === 'error' ? 'error' : job.status === 'done' ? 'success' : job.status === 'cancelled' ? 'warning' : 'default'"
          />
          <NText v-if="job.error" type="error" style="font-size: 12px">{{ job.error }}</NText>
          <NText v-if="jobMessage" type="warning" style="font-size: 12px">{{ jobMessage }}</NText>
          <NLog :log="logText" :rows="14" trim style="border: 1px solid #eee; border-radius: 6px" />
        </NSpace>
      </template>
    </NSpace>
    <template #footer>
      <NSpace justify="end">
        <NButton :disabled="jobRunning" @click="buildModal = false">关闭</NButton>
        <NButton
          v-if="jobRunning"
          type="error"
          secondary
          :loading="stopping"
          @click="stopBuild"
        >
          停止拉号
        </NButton>
        <NButton
          v-if="!job"
          type="primary"
          :loading="starting"
          @click="startBuild"
        >
          {{ buildMode === 'one_by_one' ? '安全补一个' : '开始拉满' }}
        </NButton>
        <NButton
          v-else-if="!jobRunning"
          type="primary"
          @click="((job = null))"
        >
          再拉一批
        </NButton>
      </NSpace>
    </template>
  </NModal>
</template>

<style scoped>
:deep(.member-email-disabled-row td) {
  background-color: #fff7ed !important;
}

:deep(.member-email-disabled-row:hover td) {
  background-color: #ffedd5 !important;
}
</style>
