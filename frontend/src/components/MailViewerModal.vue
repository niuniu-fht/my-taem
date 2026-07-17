<script setup lang="ts">
import {
  NButton,
  NEmpty,
  NModal,
  NScrollbar,
  NSpace,
  NSpin,
  NTag,
  NText,
} from 'naive-ui'
import { ref, watch } from 'vue'

import {
  fetchMailDetail,
  fetchMailMessages,
  type EmailItem,
  type MailDetailResult,
  type MailSummary,
} from '@/api/email'

const props = defineProps<{
  show: boolean
  account: EmailItem | null
}>()
const emit = defineEmits<{ 'update:show': [boolean] }>()

const listLoading = ref(false)
const listMessage = ref('')
const source = ref('')
const messages = ref<MailSummary[]>([])

const selectedId = ref<string | null>(null)
const detailLoading = ref(false)
const detail = ref<MailDetailResult | null>(null)

function close() {
  emit('update:show', false)
}

async function loadList() {
  if (!props.account) return
  listLoading.value = true
  detail.value = null
  selectedId.value = null
  messages.value = []
  try {
    const res = await fetchMailMessages(props.account.id, 20)
    listMessage.value = res.message
    source.value = res.source
    messages.value = res.messages
    if (!res.success) {
      window.$message?.error(`收取失败:${res.message}`)
    } else if (res.messages.length) {
      openDetail(res.messages[0])
    }
  } catch {
    listMessage.value = '收取失败'
  } finally {
    listLoading.value = false
  }
}

async function openDetail(msg: MailSummary) {
  if (!props.account) return
  selectedId.value = msg.id
  detailLoading.value = true
  detail.value = null
  try {
    const res = await fetchMailDetail(props.account.id, msg.id, msg.source || source.value)
    detail.value = res
    if (!res.success) window.$message?.error(`读取详情失败:${res.message}`)
  } catch {
    detail.value = { success: false, message: '读取失败', subject: '', from_addr: '', to_addr: '', date: '', body_html: '', body_text: '' }
  } finally {
    detailLoading.value = false
  }
}

function fmtDate(d: string) {
  if (!d) return ''
  const t = new Date(d)
  return Number.isNaN(t.getTime()) ? d : t.toLocaleString()
}

function folderLabel(folder: string) {
  const f = (folder || '').toLowerCase()
  if (!f) return ''
  if (f === 'inbox') return '收件箱'
  if (f.includes('junk')) return '垃圾箱'
  return folder
}

watch(
  () => props.show,
  (v) => {
    if (v) loadList()
  },
)
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    :title="`收取邮件 — ${account?.email || ''}`"
    style="width: 980px; max-width: 94vw"
    @update:show="(v: boolean) => emit('update:show', v)"
  >
    <template #header-extra>
      <NSpace align="center" :size="8">
        <NTag v-if="source" size="small" :type="source === 'graph' ? 'success' : 'info'">
          {{ source === 'graph' ? 'Graph' : 'IMAP' }}
        </NTag>
        <NButton size="small" :loading="listLoading" @click="loadList">刷新收件箱</NButton>
      </NSpace>
    </template>

    <div class="mail-body">
      <!-- 列表 -->
      <div class="mail-list">
        <NSpin :show="listLoading">
          <NEmpty
            v-if="!messages.length && !listLoading"
            :description="listMessage || '暂无邮件'"
            style="padding: 30px 0"
          />
          <NScrollbar v-else style="max-height: 520px">
            <div
              v-for="m in messages"
              :key="m.id"
              class="mail-item"
              :class="{ active: m.id === selectedId }"
              @click="openDetail(m)"
            >
              <div class="mail-item-top">
                <span class="mail-subject" :class="{ unread: m.is_read === false }">
                  {{ m.subject }}
                </span>
                <NTag v-if="m.folder" size="tiny" :type="folderLabel(m.folder) === '垃圾箱' ? 'warning' : 'default'">
                  {{ folderLabel(m.folder) }}
                </NTag>
                <span v-else-if="m.is_read === false" class="dot" />
              </div>
              <div class="mail-from">{{ m.from_addr }}</div>
              <div class="mail-meta">{{ fmtDate(m.date) }}</div>
              <div v-if="m.preview" class="mail-preview">{{ m.preview }}</div>
            </div>
          </NScrollbar>
        </NSpin>
      </div>

      <!-- 详情 -->
      <div class="mail-detail">
        <NSpin :show="detailLoading">
          <NEmpty
            v-if="!detail && !detailLoading"
            description="选择左侧邮件查看详情"
            style="padding: 60px 0"
          />
          <template v-else-if="detail">
            <div class="detail-head">
              <div class="detail-subject">{{ detail.subject }}</div>
              <div class="detail-line"><NText depth="3">发件人:</NText>{{ detail.from_addr }}</div>
              <div v-if="detail.to_addr" class="detail-line">
                <NText depth="3">收件人:</NText>{{ detail.to_addr }}
              </div>
              <div class="detail-line"><NText depth="3">时间:</NText>{{ fmtDate(detail.date) }}</div>
            </div>
            <iframe
              v-if="detail.body_html"
              class="detail-frame"
              sandbox=""
              :srcdoc="detail.body_html"
            />
            <NScrollbar v-else style="max-height: 430px">
              <pre class="detail-text">{{ detail.body_text || '(无正文)' }}</pre>
            </NScrollbar>
          </template>
        </NSpin>
      </div>
    </div>

    <template #footer>
      <NSpace justify="end">
        <NButton @click="close">关闭</NButton>
      </NSpace>
    </template>
  </NModal>
</template>

<style scoped>
.mail-body {
  display: flex;
  gap: 14px;
  min-height: 540px;
}
.mail-list {
  width: 320px;
  flex-shrink: 0;
  border-right: 1px solid #efeff5;
  padding-right: 10px;
}
.mail-item {
  padding: 10px 10px;
  border-radius: 8px;
  cursor: pointer;
  border: 1px solid transparent;
  transition: background 0.15s;
}
.mail-item:hover {
  background: #f5f7fa;
}
.mail-item.active {
  background: #eaf3ff;
  border-color: #c5dcff;
}
.mail-item-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.mail-subject {
  font-size: 13px;
  font-weight: 500;
  color: #1f2329;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mail-subject.unread {
  font-weight: 700;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #1890ff;
  flex-shrink: 0;
}
.mail-from {
  font-size: 12px;
  color: #4e5969;
  margin-top: 3px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mail-meta {
  font-size: 11px;
  color: #909399;
  margin-top: 2px;
}
.mail-preview {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.mail-detail {
  flex: 1;
  min-width: 0;
}
.detail-head {
  border-bottom: 1px solid #efeff5;
  padding-bottom: 10px;
  margin-bottom: 10px;
}
.detail-subject {
  font-size: 16px;
  font-weight: 600;
  color: #1f2329;
  margin-bottom: 8px;
  word-break: break-word;
}
.detail-line {
  font-size: 13px;
  color: #1f2329;
  margin-top: 2px;
}
.detail-frame {
  width: 100%;
  height: 430px;
  border: 0;
  background: #fff;
}
.detail-text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.6;
  font-family: inherit;
  color: #1f2329;
}
</style>
