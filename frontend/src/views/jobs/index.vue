<script setup lang="ts">
import {
  NButton,
  NCard,
  NDataTable,
  NEmpty,
  NGrid,
  NGridItem,
  NInput,
  NPopconfirm,
  NProgress,
  NScrollbar,
  NSpace,
  NSwitch,
  NTag,
  NText,
  type DataTableColumns,
} from 'naive-ui'
import { computed, h, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import {
  batchDeleteJobs,
  cancelJob,
  clearJobLogs,
  getJob,
  listJobs,
  type JobStatus,
  type JobTeam,
} from '@/api/adobe'
import { batchLoginRetryJob } from '@/api/pool'

const route = useRoute()

const jobs = ref<JobStatus[]>([])
const selectedId = ref<number | null>(null)
const detail = ref<JobStatus | null>(null)
const autoRefresh = ref(true)
const retrying = ref(false)
const deleting = ref(false)
const clearingLogs = ref(false)
const checkedRowKeys = ref<number[]>([])
const cancellingIds = ref<Set<number>>(new Set())
let timer: number | undefined

const TYPE_LABEL: Record<string, string> = {
  build_team: '单主号拉号',
  build_team_batch: '批量拉号',
  replace_member: '移除并安全补号',
  admin_relogin_batch: '母号检测重登',
  pool_login: '号池批量登录',
}

const CANCELLABLE_TYPES = new Set(['build_team', 'build_team_batch', 'replace_member'])

function statusTag(status: string) {
  if (status === 'running')
    return h(NTag, { type: 'info', size: 'small', round: true }, () => '进行中')
  if (status === 'done')
    return h(NTag, { type: 'success', size: 'small', round: true }, () => '已完成')
  if (status === 'error')
    return h(NTag, { type: 'error', size: 'small', round: true }, () => '出错')
  if (status === 'cancelled')
    return h(NTag, { type: 'warning', size: 'small', round: true }, () => '已停止')
  return h(NTag, { size: 'small', round: true }, () => status)
}

function teamStatusTag(status: string) {
  const map: Record<string, { type: 'default' | 'info' | 'success' | 'warning' | 'error'; text: string }> = {
    pending: { type: 'default', text: '等待' },
    running: { type: 'info', text: '处理中' },
    done: { type: 'success', text: '已完成' },
    partial: { type: 'warning', text: '部分完成' },
    cancelled: { type: 'warning', text: '已停止' },
    error: { type: 'error', text: '失败' },
  }
  const it = map[status] || { type: 'default', text: status }
  return h(NTag, { type: it.type, size: 'small', round: true }, () => it.text)
}

function fmtTime(ts: number | null) {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString()
}

function isCancellableJob(row: JobStatus | null | undefined) {
  return !!row && row.status === 'running' && CANCELLABLE_TYPES.has(row.type)
}

function setCancelling(id: number, value: boolean) {
  const next = new Set(cancellingIds.value)
  if (value) next.add(id)
  else next.delete(id)
  cancellingIds.value = next
}

const jobColumns = computed<DataTableColumns<JobStatus>>(() => [
  { type: 'selection' },
  { title: 'ID', key: 'id', width: 56 },
  {
    title: '类型',
    key: 'type',
    width: 100,
    render: (row) => TYPE_LABEL[row.type] || row.type,
  },
  { title: '状态', key: 'status', width: 90, render: (row) => statusTag(row.status) },
  {
    title: '进度',
    key: 'progress',
    width: 110,
    render: (row) => `${row.success}/${row.target}${row.fail ? ` (失败${row.fail})` : ''}`,
  },
  {
    title: '时间',
    key: 'created_at',
    minWidth: 160,
    render: (row) => fmtTime(row.created_at),
  },
  {
    title: '',
    key: 'op',
    width: 120,
    render: (row) =>
      h(NSpace, { size: 6, wrap: false }, () => [
        h(
          NButton,
          { size: 'small', type: 'primary', text: true, onClick: () => selectJob(row.id) },
          () => '查看',
        ),
        isCancellableJob(row)
          ? h(
              NButton,
              {
                size: 'small',
                type: 'error',
                secondary: true,
                loading: cancellingIds.value.has(row.id),
                onClick: () => handleCancelJob(row.id),
              },
              () => '停止',
            )
          : null,
      ]),
  },
])

const teamColumns: DataTableColumns<JobTeam> = [
  { title: '主号', key: 'email', minWidth: 220, ellipsis: { tooltip: true } },
  {
    title: '进度',
    key: 'progress',
    width: 150,
    render: (row) =>
      h('div', { style: 'display:flex;align-items:center;gap:8px' }, [
        h(NProgress, {
          type: 'line',
          percentage: row.target ? Math.min(100, Math.round((row.success / row.target) * 100)) : 0,
          style: 'width:80px',
          height: 8,
          showIndicator: false,
          status: row.status === 'error' ? 'error' : row.status === 'done' ? 'success' : row.status === 'cancelled' ? 'warning' : 'default',
        }),
        h(NText, { depth: 2 }, () => `${row.success}/${row.target}`),
      ]),
  },
  { title: '失败', key: 'fail', width: 64 },
  { title: '状态', key: 'status', width: 100, render: (row) => teamStatusTag(row.status) },
  { title: '备注', key: 'message', minWidth: 160, ellipsis: { tooltip: true } },
]

const teams = computed<JobTeam[]>(() => detail.value?.extra?.teams || [])
const detailWarning = computed(() => {
  const messages = teams.value.map((team) => team.message).filter(Boolean)
  return messages.find((message) => /429|暂停|等待|停止|保护邮箱池/.test(message)) || ''
})
const cancellableDetailId = computed(() => {
  const current = detail.value
  if (!current || current.status !== 'running' || !CANCELLABLE_TYPES.has(current.type)) return null
  return current.id
})
const overallPercent = computed(() => {
  const d = detail.value
  if (!d || !d.target) return 0
  return Math.min(100, Math.round((d.success / d.target) * 100))
})

const detailCookie = computed(() => {
  const result = detail.value?.result as
    | { replacement?: { cookie?: string } }
    | null
    | undefined
  return result?.replacement?.cookie || ''
})

async function copyDetailCookie() {
  const cookie = detailCookie.value
  if (!cookie) return
  try {
    await navigator.clipboard.writeText(cookie)
  } catch {
    const textarea = document.createElement('textarea')
    textarea.value = cookie
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.focus()
    textarea.select()
    document.execCommand('copy')
    textarea.remove()
  }
  window.$message?.success('Cookie 已复制')
}

async function loadList() {
  jobs.value = await listJobs(30)
  checkedRowKeys.value = checkedRowKeys.value.filter((id) =>
    jobs.value.some((j) => j.id === id),
  )
  if (selectedId.value !== null && !jobs.value.some((j) => j.id === selectedId.value)) {
    selectedId.value = null
    detail.value = null
  }
  if (selectedId.value === null && jobs.value.length) {
    selectJob(jobs.value[0].id)
  }
}

async function loadDetail() {
  if (selectedId.value === null) return
  try {
    detail.value = await getJob(selectedId.value)
  } catch {
    // 任务可能已不存在
  }
}

function selectJob(id: number) {
  selectedId.value = id
  detail.value = null
  loadDetail()
}

async function handleRetryFailed() {
  if (!detail.value || detail.value.type !== 'pool_login') return
  retrying.value = true
  try {
    const job = await batchLoginRetryJob(detail.value.id)
    window.$message?.success(`已开始重试仍无 token 的账号,新任务 #${job.id}`)
    selectedId.value = job.id
    detail.value = job
    await loadList()
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : '重试失败'
    window.$message?.error(msg)
  } finally {
    retrying.value = false
  }
}

const canRetryFailed = computed(() => {
  const d = detail.value
  if (!d || d.type !== 'pool_login') return false
  if (d.status === 'running') return false
  const still = Number(d.result?.still_no_token ?? 0)
  return still > 0 || d.fail > 0
})

const selectedRunningCount = computed(
  () =>
    checkedRowKeys.value.filter((id) => jobs.value.find((j) => j.id === id)?.status === 'running')
      .length,
)

async function handleBatchDelete() {
  if (!checkedRowKeys.value.length) return
  deleting.value = true
  try {
    const res = await batchDeleteJobs(checkedRowKeys.value)
    window.$message?.success(res.message)
    checkedRowKeys.value = []
    await loadList()
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : '删除失败'
    window.$message?.error(msg)
  } finally {
    deleting.value = false
  }
}

async function handleCancelJob(jobId: number) {
  setCancelling(jobId, true)
  try {
    const res = await cancelJob(jobId)
    window.$message?.warning(res.message || '已请求停止拉号')
    await loadList()
    if (selectedId.value === jobId) await loadDetail()
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : '停止失败'
    window.$message?.error(msg)
  } finally {
    setCancelling(jobId, false)
  }
}

async function handleClearLogs() {
  if (!detail.value) return
  clearingLogs.value = true
  try {
    const res = await clearJobLogs(detail.value.id)
    window.$message?.success(res.message)
    await loadDetail()
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : '清空失败'
    window.$message?.error(msg)
  } finally {
    clearingLogs.value = false
  }
}

async function tick() {
  await loadList()
  if (selectedId.value !== null && detail.value?.status === 'running') {
    await loadDetail()
  } else if (selectedId.value !== null && !detail.value) {
    await loadDetail()
  }
}

function setupTimer() {
  if (timer) window.clearInterval(timer)
  if (autoRefresh.value) {
    timer = window.setInterval(tick, 2000)
  }
}

onMounted(async () => {
  const qid = route.query.id ? Number(route.query.id) : null
  if (qid) selectedId.value = qid
  await loadList()
  if (qid) await loadDetail()
  setupTimer()
})

onUnmounted(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<template>
  <NGrid :cols="24" :x-gap="16" responsive="screen">
    <NGridItem :span="9">
      <NCard :bordered="false" title="任务列表" size="small">
        <template #header-extra>
          <NSpace align="center" :size="8">
            <NPopconfirm @positive-click="handleBatchDelete">
              <template #trigger>
                <NButton
                  type="error"
                  size="small"
                  tertiary
                  :loading="deleting"
                  :disabled="!checkedRowKeys.length"
                >
                  删除选中 ({{ checkedRowKeys.length }})
                </NButton>
              </template>
              <div style="max-width: 260px">
                确认删除选中的 {{ checkedRowKeys.length }} 个任务?
                <NText v-if="selectedRunningCount" type="warning" style="display: block; margin-top: 6px; font-size: 12px">
                  其中 {{ selectedRunningCount }} 个进行中,将自动跳过
                </NText>
              </div>
            </NPopconfirm>
            <NText depth="3" style="font-size: 12px">自动刷新</NText>
            <NSwitch v-model:value="autoRefresh" size="small" @update:value="setupTimer" />
          </NSpace>
        </template>
        <NDataTable
          v-model:checked-row-keys="checkedRowKeys"
          :columns="jobColumns"
          :data="jobs"
          :row-key="(row: JobStatus) => row.id"
          :row-props="(row: JobStatus) => ({ style: row.id === selectedId ? 'background:#f0f7ff' : '' })"
          size="small"
          :max-height="640"
        />
      </NCard>
    </NGridItem>

    <NGridItem :span="15">
      <NCard :bordered="false" size="small">
        <template #header>
          <NSpace align="center" justify="space-between" style="width: 100%">
            <NSpace align="center" :size="10">
              <NText strong>任务详情</NText>
              <template v-if="detail">
                <component :is="statusTag(detail.status)" />
                <NText depth="3">{{ TYPE_LABEL[detail.type] || detail.type }} · #{{ detail.id }}</NText>
              </template>
            </NSpace>
            <NSpace :size="8">
              <NButton
                v-if="cancellableDetailId !== null"
                type="error"
                size="small"
                secondary
                :loading="cancellableDetailId !== null && cancellingIds.has(cancellableDetailId)"
                @click="cancellableDetailId !== null && handleCancelJob(cancellableDetailId)"
              >
                停止拉号
              </NButton>
              <NButton
                v-if="canRetryFailed"
                type="warning"
                size="small"
                :loading="retrying"
                @click="handleRetryFailed"
              >
                重试失败
              </NButton>
            </NSpace>
          </NSpace>
        </template>

        <NEmpty v-if="!detail" description="请选择左侧任务查看进度" style="padding: 40px 0" />

        <NSpace v-else vertical size="large">
          <div>
            <NSpace align="center" justify="space-between" style="margin-bottom: 6px">
              <NText
                >总进度 {{ detail.success }}/{{ detail.target }}
                <NText v-if="detail.fail" type="error">· 失败 {{ detail.fail }}</NText></NText
              >
              <NText depth="3" style="font-size: 12px">{{ fmtTime(detail.created_at) }}</NText>
            </NSpace>
            <NProgress
              type="line"
              :percentage="overallPercent"
              :status="detail.status === 'error' ? 'error' : detail.status === 'done' ? 'success' : detail.status === 'cancelled' ? 'warning' : 'default'"
            />
          </div>

          <NText v-if="detail.error" type="error">{{ detail.error }}</NText>
          <NText v-if="detailWarning" type="warning">{{ detailWarning }}</NText>

          <NDataTable
            v-if="teams.length"
            :columns="teamColumns"
            :data="teams"
            :row-key="(row: JobTeam) => row.admin_id"
            size="small"
            :max-height="240"
          />

          <NSpace v-if="detailCookie" vertical size="small">
            <NSpace align="center" justify="space-between">
              <NText strong>新补子号 Cookie</NText>
              <NButton type="primary" secondary size="small" @click="copyDetailCookie">
                复制 Cookie
              </NButton>
            </NSpace>
            <NInput
              :value="detailCookie"
              type="textarea"
              readonly
              :autosize="{ minRows: 3, maxRows: 8 }"
            />
          </NSpace>

          <div>
            <NSpace align="center" justify="space-between" style="margin-bottom: 6px">
              <NText depth="3" style="font-size: 12px">实时日志(共 {{ detail.log_total }} 条)</NText>
              <NPopconfirm @positive-click="handleClearLogs">
                <template #trigger>
                  <NButton size="tiny" tertiary :loading="clearingLogs" :disabled="!detail.log_total">
                    清空日志
                  </NButton>
                </template>
                确认清空当前任务的日志?
              </NPopconfirm>
            </NSpace>
            <NScrollbar style="max-height: 280px">
              <pre class="logbox">{{ (detail.logs || []).join('\n') || '暂无日志' }}</pre>
            </NScrollbar>
          </div>
        </NSpace>
      </NCard>
    </NGridItem>
  </NGrid>
</template>

<style scoped>
.logbox {
  margin: 0;
  padding: 10px 12px;
  background: #1e1e1e;
  color: #d4d4d4;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: 'Cascadia Code', Consolas, Monaco, monospace;
}
</style>
