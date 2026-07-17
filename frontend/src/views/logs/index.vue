<script setup lang="ts">
import {
  NButton,
  NCard,
  NDataTable,
  NEmpty,
  NInput,
  NModal,
  NPopconfirm,
  NSelect,
  NSpace,
  NSwitch,
  NTag,
  NText,
  type DataTableColumns,
} from 'naive-ui'
import { computed, h, onMounted, onUnmounted, ref } from 'vue'

import { clearLogs, listLogs, type LogItem } from '@/api/logs'

const data = ref<LogItem[]>([])
const loading = ref(false)
const level = ref('')
const keyword = ref('')
const autoRefresh = ref(false)
const detail = ref<LogItem | null>(null)
const detailVisible = computed({
  get: () => detail.value !== null,
  set: (v) => {
    if (!v) detail.value = null
  },
})
let timer: number | null = null

const levelOptions = [
  { label: '全部级别', value: '' },
  { label: '错误 ERROR', value: 'ERROR' },
  { label: '告警 WARNING', value: 'WARNING' },
  { label: '信息 INFO', value: 'INFO' },
]

async function fetchData() {
  loading.value = true
  try {
    const res = await listLogs({
      level: level.value,
      keyword: keyword.value.trim(),
      limit: 500,
    })
    data.value = res.items
  } finally {
    loading.value = false
  }
}

function levelTagType(lv: string): 'error' | 'warning' | 'info' | 'default' {
  if (lv === 'ERROR') return 'error'
  if (lv === 'WARNING') return 'warning'
  if (lv === 'INFO') return 'info'
  return 'default'
}

const columns = computed<DataTableColumns<LogItem>>(() => [
  { title: '时间', key: 'time', width: 170 },
  {
    title: '级别',
    key: 'level',
    width: 110,
    render: (row) =>
      h(NTag, { type: levelTagType(row.level), size: 'small', round: true }, () => row.level),
  },
  { title: '来源', key: 'source', width: 120, ellipsis: { tooltip: true } },
  {
    title: '内容',
    key: 'message',
    minWidth: 360,
    ellipsis: { tooltip: true },
  },
  {
    title: '操作',
    key: 'actions',
    width: 90,
    render: (row) =>
      h(
        NButton,
        { size: 'tiny', tertiary: true, onClick: () => (detail.value = row) },
        () => '详情',
      ),
  },
])

async function handleClear() {
  const res = await clearLogs()
  window.$message?.success(res.message)
  await fetchData()
}

function toggleAuto(v: boolean) {
  if (v) {
    timer = window.setInterval(fetchData, 3000)
  } else if (timer !== null) {
    window.clearInterval(timer)
    timer = null
  }
}

onMounted(fetchData)
onUnmounted(() => {
  if (timer !== null) window.clearInterval(timer)
})
</script>

<template>
  <NCard :bordered="false">
    <NSpace vertical size="large">
      <NSpace justify="space-between">
        <NSpace align="center">
          <NSelect
            v-model:value="level"
            :options="levelOptions"
            style="width: 150px"
            @update:value="fetchData"
          />
          <NInput
            v-model:value="keyword"
            placeholder="搜索内容 / 来源"
            clearable
            style="width: 260px"
            @keyup.enter="fetchData"
          />
          <NButton @click="fetchData">刷新</NButton>
          <NText depth="3" style="font-size: 13px">自动刷新</NText>
          <NSwitch v-model:value="autoRefresh" @update:value="toggleAuto" />
        </NSpace>
        <NPopconfirm @positive-click="handleClear">
          <template #trigger>
            <NButton type="error" tertiary>清空日志</NButton>
          </template>
          确认清空所有日志缓冲?
        </NPopconfirm>
      </NSpace>

      <NDataTable
        :columns="columns"
        :data="data"
        :loading="loading"
        :row-key="(row: LogItem) => row.id"
        :scroll-x="900"
        :max-height="560"
        :pagination="{ pageSize: 50 }"
      >
        <template #empty>
          <NEmpty description="暂无日志。出现错误后这里会记录请求路径、状态码和异常堆栈" />
        </template>
      </NDataTable>
    </NSpace>
  </NCard>

  <NModal v-model:show="detailVisible" preset="card" title="日志详情" style="width: 800px">
    <NSpace v-if="detail" vertical size="small">
      <NText
        ><b>时间:</b>{{ detail.time }} ·
        <NTag :type="levelTagType(detail.level)" size="small" round>{{ detail.level }}</NTag> ·
        <b>来源:</b>{{ detail.source }}</NText
      >
      <NText><b>内容:</b></NText>
      <pre class="log-pre">{{ detail.message }}</pre>
      <template v-if="detail.traceback">
        <NText><b>堆栈:</b></NText>
        <pre class="log-pre">{{ detail.traceback }}</pre>
      </template>
    </NSpace>
  </NModal>
</template>

<style scoped>
.log-pre {
  white-space: pre-wrap;
  word-break: break-all;
  background: #f6f7f9;
  border: 1px solid #eee;
  border-radius: 6px;
  padding: 10px;
  margin: 0;
  font-size: 12px;
  max-height: 320px;
  overflow: auto;
}
</style>
