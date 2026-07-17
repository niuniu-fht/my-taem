<script setup lang="ts">
import {
  NButton,
  NCard,
  NDataTable,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NModal,
  NPopconfirm,
  NSelect,
  NSpace,
  NSwitch,
  NTag,
  NText,
  useDialog,
  type DataTableColumns,
  type FormInst,
} from 'naive-ui'
import { computed, h, onMounted, reactive, ref } from 'vue'

import {
  batchDeleteEmails,
  batchImportEmails,
  batchImportEmailsChecked,
  batchSetEmailsDisabled,
  batchSetEmailsUsed,
  createEmail,
  deleteEmail,
  generateMoeMailEmails,
  listEmails,
  updateEmail,
  type EmailForm,
  type EmailItem,
} from '@/api/email'
import { listAdobeAccounts, type AdobeAccount } from '@/api/adobe'
import BatchImportModal from '@/components/BatchImportModal.vue'
import MailViewerModal from '@/components/MailViewerModal.vue'

const dialog = useDialog()

const mailViewerShow = ref(false)
const mailViewerAccount = ref<EmailItem | null>(null)

function openMailViewer(row: EmailItem) {
  if ((!row.refresh_token || !row.client_id) && !row.mail_url) {
    window.$message?.warning('该邮箱缺少 Refresh Token / Client ID 或取信配置,无法收取邮件')
    return
  }
  mailViewerAccount.value = row
  mailViewerShow.value = true
}

const data = ref<EmailItem[]>([])
const loading = ref(false)
const keyword = ref('')
const statusFilter = ref<'all' | 'unused' | 'used' | 'disabled'>('all')
const remarkFilter = ref('')
const checkedRowKeys = ref<number[]>([])
const pagination = reactive({ page: 1, pageSize: 20, itemCount: 0, pageSizes: [20, 50, 100] })

const importModalRef = ref<InstanceType<typeof BatchImportModal> | null>(null)
const moemailVisible = ref(false)
const moemailGenerating = ref(false)
const moemailForm = reactive({
  api_key: 'mk_biH9iMGVvOvrZETzY-U1GflX5rRKyE9H',
  count: 10,
  domain: 'edu6.site',
  name_prefix: '',
  expiry_time: 0,
  password: '',
  on_duplicate: 'overwrite' as 'skip' | 'overwrite',
})

const statusOptions = [
  { label: '全部状态', value: 'all' },
  { label: '未使用', value: 'unused' },
  { label: '已使用', value: 'used' },
  { label: '已停用', value: 'disabled' },
]
const remarkOptions = ref<{ label: string; value: string }[]>([
  { label: '全部母号', value: '' },
])
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

async function fetchData() {
  loading.value = true
  try {
    const res = await listEmails({
      page: pagination.page,
      size: pagination.pageSize,
      keyword: keyword.value.trim(),
      remark: remarkFilter.value,
      is_used:
        statusFilter.value === 'used' ? true : statusFilter.value === 'unused' ? false : null,
      is_disabled: statusFilter.value === 'disabled' ? true : null,
    })
    const remark = remarkFilter.value
    const items = remark ? res.items.filter((item) => item.remark === remark) : res.items
    data.value = items
    pagination.itemCount = remark && items.length !== res.items.length ? items.length : res.total
  } finally {
    loading.value = false
  }
}

function copyText(text: string) {
  if (!text) return
  navigator.clipboard?.writeText(text).then(
    () => window.$message?.success('已复制'),
    () => window.$message?.error('复制失败'),
  )
}

function ellipsisCopyCell(value: string, max = 18) {
  if (!value) return h(NText, { depth: 3 }, { default: () => '—' })
  const short = value.length > max ? value.slice(0, max) + '…' : value
  return h('span', { title: value, style: 'cursor: pointer; color: #1890ff;', onClick: () => copyText(value) }, short)
}

async function toggleUsed(row: EmailItem, value: boolean) {
  await updateEmail(row.id, { is_used: value })
  row.is_used = value
  window.$message?.success(value ? '已标记为已使用' : '已标记为未使用')
  fetchData()
}

async function toggleDisabled(row: EmailItem, value: boolean) {
  await updateEmail(row.id, { is_disabled: value })
  row.is_disabled = value
  window.$message?.success(value ? '已停用' : '已取消停用')
  fetchData()
}

async function fetchRemarkOptions() {
  const res = await listAdobeAccounts({ page: 1, size: 200 })
  remarkOptions.value = [
    { label: '全部母号', value: '' },
    ...res.items.map((item: AdobeAccount) => ({
      label: item.remark ? `${item.email} (${item.remark})` : item.email,
      value: item.email,
    })),
  ]
}

const columns = computed<DataTableColumns<EmailItem>>(() => [
  { type: 'selection' },
  { title: 'ID', key: 'id', width: 64 },
  { title: '邮箱', key: 'email', width: 240, ellipsis: { tooltip: true } },
  { title: '密码', key: 'password', width: 150, render: (row) => ellipsisCopyCell(row.password, 14) },
  { title: 'Refresh Token', key: 'refresh_token', width: 150, render: (row) => ellipsisCopyCell(row.refresh_token) },
  { title: 'Client ID', key: 'client_id', width: 150, render: (row) => ellipsisCopyCell(row.client_id) },
  { title: '取信配置', key: 'mail_url', width: 150, render: (row) => ellipsisCopyCell(row.mail_url) },
  {
    title: '是否已使用',
    key: 'is_used',
    width: 120,
    render: (row) =>
      h(NSwitch, {
        value: row.is_used,
        'onUpdate:value': (v: boolean) => toggleUsed(row, v),
      }, { checked: () => '已用', unchecked: () => '未用' }),
  },
  {
    title: '状态',
    key: 'status_tag',
    width: 160,
    render: (row) =>
      h(NSpace, { size: 4 }, () => [
        h(NTag, { type: row.is_used ? 'warning' : 'success', size: 'small', round: true }, () => (row.is_used ? '已使用' : '未使用')),
        row.is_disabled
          ? h(NTag, { type: 'error', size: 'small', round: true }, () => '已停用')
          : null,
      ]),
  },
  {
    title: '停用',
    key: 'is_disabled',
    width: 100,
    render: (row) =>
      h(NSwitch, {
        value: row.is_disabled,
        'onUpdate:value': (v: boolean) => toggleDisabled(row, v),
      }, { checked: () => '停用', unchecked: () => '可用' }),
  },
  { title: '备注/所属母号', key: 'remark', width: 220, ellipsis: { tooltip: true } },
  {
    title: '操作',
    key: 'actions',
    width: 180,
    fixed: 'right',
    render: (row) =>
      h(NSpace, { size: 8 }, () => [
        h(NButton, { size: 'small', text: true, type: 'success', onClick: () => openMailViewer(row) }, () => '收取邮件'),
        h(NButton, { size: 'small', text: true, type: 'primary', onClick: () => openEdit(row) }, () => '编辑'),
        h(
          NPopconfirm,
          { onPositiveClick: () => handleDelete(row.id) },
          { trigger: () => h(NButton, { size: 'small', text: true, type: 'error' }, () => '删除'), default: () => '确认删除该邮箱?' },
        ),
      ]),
  },
])

const showFormModal = ref(false)
const editingId = ref<number | null>(null)
const formRef = ref<FormInst | null>(null)
const form = reactive<EmailForm>({ email: '', password: '', refresh_token: '', client_id: '', mail_url: '', remark: '' })

const rules = { email: { required: true, message: '请输入邮箱', trigger: 'blur' } }

function resetForm() {
  form.email = ''
  form.password = ''
  form.refresh_token = ''
  form.client_id = ''
  form.mail_url = ''
  form.remark = ''
}

function openCreate() {
  editingId.value = null
  resetForm()
  showFormModal.value = true
}

function openEdit(row: EmailItem) {
  editingId.value = row.id
  form.email = row.email
  form.password = row.password
  form.refresh_token = row.refresh_token
  form.client_id = row.client_id
  form.mail_url = row.mail_url
  form.remark = row.remark
  showFormModal.value = true
}

const saving = ref(false)
async function handleSave() {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  saving.value = true
  try {
    if (editingId.value === null) {
      await createEmail({ ...form })
      window.$message?.success('新增成功')
    } else {
      await updateEmail(editingId.value, { ...form })
      window.$message?.success('保存成功')
    }
    showFormModal.value = false
    fetchData()
  } finally {
    saving.value = false
  }
}

async function handleDelete(id: number) {
  await deleteEmail(id)
  window.$message?.success('删除成功')
  fetchData()
}

function handleBatchDelete() {
  if (!checkedRowKeys.value.length) {
    window.$message?.warning('请先勾选要删除的邮箱')
    return
  }
  dialog.warning({
    title: '批量删除',
    content: `确认删除选中的 ${checkedRowKeys.value.length} 个邮箱?`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      await batchDeleteEmails(checkedRowKeys.value)
      window.$message?.success('批量删除成功')
      checkedRowKeys.value = []
      fetchData()
    },
  })
}

async function handleBatchSetUsed(isUsed: boolean) {
  if (!checkedRowKeys.value.length) {
    window.$message?.warning('请先勾选邮箱')
    return
  }
  const res = await batchSetEmailsUsed(checkedRowKeys.value, isUsed)
  window.$message?.success(res.message)
  checkedRowKeys.value = []
  fetchData()
}

async function handleBatchSetDisabled(isDisabled: boolean) {
  if (!checkedRowKeys.value.length) {
    window.$message?.warning('请先勾选邮箱')
    return
  }
  const res = await batchSetEmailsDisabled(checkedRowKeys.value, isDisabled)
  window.$message?.success(res.message)
  checkedRowKeys.value = []
  fetchData()
}

function handleSearch() {
  pagination.page = 1
  fetchData()
}

function handleRemarkFilterChange(value: string | null) {
  remarkFilter.value = value || ''
  handleSearch()
}

async function handleGenerateMoeMail() {
  moemailGenerating.value = true
  try {
    const res = await generateMoeMailEmails({ ...moemailForm })
    window.$message?.success(`创建完成:新增 ${res.created},更新 ${res.updated},失败 ${res.failed}`)
    moemailVisible.value = false
    fetchData()
  } finally {
    moemailGenerating.value = false
  }
}

onMounted(() => {
  fetchRemarkOptions()
  fetchData()
})
</script>

<template>
  <div>
    <NCard :bordered="false">
      <NSpace justify="space-between" align="center" style="margin-bottom: 16px">
        <NSpace>
          <NButton type="primary" @click="openCreate">+ 新增邮箱</NButton>
          <NButton type="info" @click="importModalRef?.open()">批量导入</NButton>
          <NButton type="success" @click="moemailVisible = true">一键创建 MoeMail</NButton>
          <NButton type="warning" :disabled="!checkedRowKeys.length" @click="handleBatchSetUsed(true)">
            批量启用
          </NButton>
          <NButton type="success" :disabled="!checkedRowKeys.length" @click="handleBatchSetUsed(false)">
            批量未用
          </NButton>
          <NButton type="error" secondary :disabled="!checkedRowKeys.length" @click="handleBatchSetDisabled(true)">
            批量停用
          </NButton>
          <NButton secondary :disabled="!checkedRowKeys.length" @click="handleBatchSetDisabled(false)">
            取消停用
          </NButton>
          <NButton type="error" :disabled="!checkedRowKeys.length" @click="handleBatchDelete">
            批量删除
          </NButton>
        </NSpace>
        <NSpace>
          <NSelect
            v-model:value="statusFilter"
            :options="statusOptions"
            style="width: 130px"
            @update:value="handleSearch"
          />
          <NSelect
            v-model:value="remarkFilter"
            :options="remarkOptions"
            filterable
            style="width: 240px"
            @update:value="handleRemarkFilterChange"
          />
          <NInput
            v-model:value="keyword"
            placeholder="搜索邮箱 / 备注"
            clearable
            style="width: 220px"
            @keyup.enter="handleSearch"
          />
          <NButton @click="handleSearch">搜索</NButton>
        </NSpace>
      </NSpace>

      <NDataTable
        :columns="columns"
        :data="data"
        :loading="loading"
        :row-key="(row: EmailItem) => row.id"
        v-model:checked-row-keys="checkedRowKeys"
        :scroll-x="1300"
        remote
        :pagination="{
          page: pagination.page,
          pageSize: pagination.pageSize,
          itemCount: pagination.itemCount,
          pageSizes: pagination.pageSizes,
          showSizePicker: true,
          prefix: (info) => `共 ${info.itemCount} 条`,
          onUpdatePage: (p: number) => { pagination.page = p; fetchData() },
          onUpdatePageSize: (s: number) => { pagination.pageSize = s; pagination.page = 1; fetchData() },
        }"
      />
    </NCard>

    <NModal v-model:show="showFormModal">
      <NCard
        :title="editingId === null ? '新增邮箱' : '编辑邮箱'"
        style="width: 520px"
        :bordered="false"
        role="dialog"
      >
        <NForm ref="formRef" :model="form" :rules="rules" label-placement="top">
          <NFormItem label="邮箱" path="email">
            <NInput v-model:value="form.email" placeholder="example@outlook.com" />
          </NFormItem>
          <NFormItem label="密码">
            <NInput v-model:value="form.password" />
          </NFormItem>
          <NFormItem label="Refresh Token">
            <NInput v-model:value="form.refresh_token" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
          </NFormItem>
          <NFormItem label="Client ID">
            <NInput v-model:value="form.client_id" />
          </NFormItem>
          <NFormItem label="取信配置">
            <NInput v-model:value="form.mail_url" placeholder="moemail://edu6.site?api_key=...&email_id=..." />
          </NFormItem>
          <NFormItem label="备注">
            <NInput v-model:value="form.remark" />
          </NFormItem>
        </NForm>
        <template #footer>
          <NSpace justify="end">
            <NButton @click="showFormModal = false">取消</NButton>
            <NButton type="primary" :loading="saving" @click="handleSave">保存</NButton>
          </NSpace>
        </template>
      </NCard>
    </NModal>

    <NModal v-model:show="moemailVisible">
      <NCard
        title="一键创建 MoeMail 邮箱"
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
            <NInput v-model:value="moemailForm.password" placeholder="写入本地备注字段用,不影响 MoeMail" />
          </NFormItem>
          <NFormItem label="重复处理">
            <NSelect
              v-model:value="moemailForm.on_duplicate"
              :options="[
                { label: '覆盖更新', value: 'overwrite' },
                { label: '跳过', value: 'skip' },
              ]"
              style="width: 140px"
            />
          </NFormItem>
        </NForm>
        <template #footer>
          <NSpace justify="end">
            <NButton @click="moemailVisible = false">取消</NButton>
            <NButton type="primary" :loading="moemailGenerating" @click="handleGenerateMoeMail">
              创建
            </NButton>
          </NSpace>
        </template>
      </NCard>
    </NModal>

    <BatchImportModal
      ref="importModalRef"
      title="批量导入微软邮箱"
      format-hint="每行一条,支持两种格式(自动识别):邮箱|密码|RefreshToken|ClientID 或 邮箱----密码----ClientID----RefreshToken"
      placeholder="email@hotmail.com|password|refresh_token|client_id&#10;email2@hotmail.com----password----client_id----refresh_token"
      :import-fn="batchImportEmails"
      :checked-import-fn="batchImportEmailsChecked"
      @success="fetchData"
    />

    <MailViewerModal v-model:show="mailViewerShow" :account="mailViewerAccount" />
  </div>
</template>
