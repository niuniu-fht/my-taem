<script setup lang="ts">
import { NAlert, NButton, NCard, NModal, NRadio, NRadioGroup, NInput, NSpace, NSwitch, NText } from 'naive-ui'
import { ref } from 'vue'

import type { BatchImportResult } from '@/api/types'

type ImportResult = BatchImportResult & {
  checked?: number
  passed?: number
  rejected?: number
  checks?: Array<{ line_no: number; email: string; success: boolean; message: string; source: string }>
}

const props = defineProps<{
  title: string
  formatHint: string
  placeholder: string
  importFn: (content: string, onDuplicate: 'skip' | 'overwrite') => Promise<BatchImportResult>
  checkedImportFn?: (content: string, onDuplicate: 'skip' | 'overwrite', checkMail: boolean) => Promise<ImportResult>
}>()

const emit = defineEmits<{ success: [] }>()

const show = defineModel<boolean>('show', { default: false })

const content = ref('')
const onDuplicate = ref<'skip' | 'overwrite'>('skip')
const loading = ref(false)
const checkBeforeImport = ref(true)
const result = ref<ImportResult | null>(null)

function open() {
  content.value = ''
  result.value = null
  onDuplicate.value = 'skip'
  checkBeforeImport.value = true
  show.value = true
}

defineExpose({ open })

async function handleImport() {
  if (!content.value.trim()) {
    window.$message?.warning('请粘贴要导入的数据')
    return
  }
  loading.value = true
  try {
    result.value = props.checkedImportFn
      ? await props.checkedImportFn(content.value, onDuplicate.value, checkBeforeImport.value)
      : await props.importFn(content.value, onDuplicate.value)
    const r = result.value
    window.$message?.success(
      `导入完成:新增 ${r.created}、更新 ${r.updated}、跳过 ${r.skipped}、失败 ${r.failed}`,
    )
    emit('success')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <NModal v-model:show="show">
    <NCard :title="title" style="width: 680px" :bordered="false" role="dialog">
      <NSpace vertical :size="14">
        <NAlert type="info" :show-icon="false">
          <div class="hint">格式(每行一条,用竖线 <b>|</b> 分隔):</div>
          <code class="format">{{ formatHint }}</code>
        </NAlert>

        <NInput
          v-model:value="content"
          type="textarea"
          :placeholder="placeholder"
          :rows="10"
          :autosize="{ minRows: 8, maxRows: 16 }"
        />

        <NSpace align="center">
          <span>重复邮箱处理:</span>
          <NRadioGroup v-model:value="onDuplicate">
            <NRadio value="skip">跳过</NRadio>
            <NRadio value="overwrite">覆盖更新</NRadio>
          </NRadioGroup>
        </NSpace>

        <NSpace v-if="checkedImportFn" align="center">
          <span>导入前检测收件:</span>
          <NSwitch v-model:value="checkBeforeImport" />
          <NText depth="3" style="font-size: 12px">只导入检测通过的邮箱</NText>
        </NSpace>

        <NAlert v-if="result" :type="result.failed > 0 ? 'warning' : 'success'">
          新增 {{ result.created }} · 更新 {{ result.updated }} · 跳过
          {{ result.skipped }} · 失败 {{ result.failed }}
          <div v-if="result.checked !== undefined" class="check-summary">
            检测 {{ result.checked }} · 通过 {{ result.passed }} · 拒绝 {{ result.rejected }}
          </div>
          <ul v-if="result.errors.length" class="errors">
            <li v-for="(err, i) in result.errors.slice(0, 8)" :key="i">{{ err }}</li>
          </ul>
          <ul v-if="result.checks?.length" class="errors">
            <li v-for="item in result.checks.filter((x) => !x.success).slice(0, 8)" :key="item.line_no">
              第 {{ item.line_no }} 行 {{ item.email || '' }}: {{ item.message }}
            </li>
          </ul>
        </NAlert>
      </NSpace>

      <template #footer>
        <NSpace justify="end">
          <NButton @click="show = false">关闭</NButton>
          <NButton type="primary" :loading="loading" @click="handleImport">开始导入</NButton>
        </NSpace>
      </template>
    </NCard>
  </NModal>
</template>

<style scoped>
.hint {
  margin-bottom: 6px;
  font-size: 13px;
}

.format {
  display: block;
  font-size: 12px;
  color: #1890ff;
  word-break: break-all;
}

.check-summary {
  margin-top: 6px;
  font-size: 12px;
}

.errors {
  margin: 8px 0 0 18px;
  font-size: 12px;
}
</style>
