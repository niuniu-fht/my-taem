<script setup lang="ts">
import {
  NButton,
  NCard,
  NDataTable,
  NDropdown,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NModal,
  NSpace,
  NTag,
  NText,
  NTooltip,
  useDialog,
  type DataTableColumns,
  type FormInst,
} from 'naive-ui'
import { computed, h, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  batchDeleteAdobeAccounts,
  batchImportAdobeAccounts,
  batchReloginAdobeAccounts,
  buildTeamBatch,
  checkAdobeAdmin,
  createAdobeAccount,
  deleteAdobeAccount,
  listAdobeAccounts,
  loginAdobeAdmin,
  quickAddAdobeAccount,
  startManualAdobeLogin,
  syncAdobeMembers,
  testAdobeEmail,
  updateAdobeAccount,
  verifyManualAdobeLogin,
  type AdobeAccount,
  type AdobeAccountForm,
} from '@/api/adobe'
import BatchImportModal from '@/components/BatchImportModal.vue'
import MembersDrawer from './MembersDrawer.vue'

const dialog = useDialog()
const router = useRouter()

// 批量拉号
const batchModal = ref(false)
const batchCount = ref(9)
const batchStarting = ref(false)
const reloginStarting = ref(false)

function openBatchBuild() {
  if (!checkedRowKeys.value.length) {
    window.$message?.warning('请先勾选要拉号的主号')
    return
  }
  batchCount.value = 9
  batchModal.value = true
}

async function startBatchBuild() {
  batchStarting.value = true
  try {
    const job = await buildTeamBatch(checkedRowKeys.value, batchCount.value)
    batchModal.value = false
    window.$message?.success(`已开始批量拉号(${checkedRowKeys.value.length} 个主号),前往拉号任务查看进度`)
    router.push({ name: 'jobs', query: { id: String(job.id) } })
  } finally {
    batchStarting.value = false
  }
}

async function startBatchRelogin() {
  if (!checkedRowKeys.value.length) {
    window.$message?.warning('请先勾选要检测重登的母号')
    return
  }
  reloginStarting.value = true
  try {
    const job = await batchReloginAdobeAccounts(checkedRowKeys.value)
    window.$message?.success(`已开始检测并重登(${checkedRowKeys.value.length} 个母号),前往拉号任务查看进度`)
    router.push({ name: 'jobs', query: { id: String(job.id) } })
  } finally {
    reloginStarting.value = false
  }
}

const data = ref<AdobeAccount[]>([])
const loading = ref(false)
const keyword = ref('')
const checkedRowKeys = ref<number[]>([])
const pagination = reactive({ page: 1, pageSize: 20, itemCount: 0, pageSizes: [20, 50, 100], showSizePicker: true })

const importModalRef = ref<InstanceType<typeof BatchImportModal> | null>(null)
const testingIds = ref<Set<number>>(new Set())
const loginIds = ref<Set<number>>(new Set())
const checkingIds = ref<Set<number>>(new Set())
const manualLoginIds = ref<Set<number>>(new Set())
const syncingIds = ref<Set<number>>(new Set())

// 快速增加母号
const quickAddModal = ref(false)
const quickAddContent = ref('')
const quickAddLogs = ref<string[]>([])
const quickAddSaving = ref(false)

function openQuickAdd() {
  quickAddContent.value = ''
  quickAddLogs.value = []
  quickAddModal.value = true
}

async function submitQuickAdd() {
  const content = quickAddContent.value.trim()
  if (!content) {
    window.$message?.warning('请先粘贴母号账号')
    return
  }
  quickAddSaving.value = true
  quickAddLogs.value = []
  try {
    const res = await quickAddAdobeAccount(content)
    quickAddLogs.value = res.logs || []
    if (res.success) {
      window.$message?.success(`${res.email} 快速增加并登录成功`)
      quickAddModal.value = false
    } else {
      window.$message?.error(`${res.email} ${res.message}`)
    }
    await fetchData()
  } finally {
    quickAddSaving.value = false
  }
}

// 成员管理抽屉
const drawerShow = ref(false)
const drawerAccount = ref<AdobeAccount | null>(null)

function openMembers(row: AdobeAccount) {
  drawerAccount.value = row
  drawerShow.value = true
}

function toggleId(set: typeof testingIds, id: number, on: boolean) {
  const next = new Set(set.value)
  if (on) next.add(id)
  else next.delete(id)
  set.value = next
}

async function fetchData() {
  loading.value = true
  try {
    const res = await listAdobeAccounts({
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

function renderValidTag(row: AdobeAccount) {
  const tag =
    row.is_valid === true
      ? h(NTag, { type: 'success', size: 'small', round: true }, () => '有效')
      : row.is_valid === false
        ? h(NTag, { type: 'error', size: 'small', round: true }, () => '无效')
        : h(NTag, { type: 'default', size: 'small', round: true }, () => '未检测')

  if (!row.check_message) return tag
  return h(NTooltip, null, {
    trigger: () => tag,
    default: () =>
      h('div', { style: 'max-width: 320px; word-break: break-all;' }, [
        h('div', row.check_message),
        row.last_checked_at
          ? h('div', { style: 'margin-top:4px; opacity:0.7; font-size:12px;' }, '检测时间:' + new Date(row.last_checked_at).toLocaleString())
          : null,
      ]),
  })
}

function renderOrgTag(row: AdobeAccount) {
  if (row.has_org === true)
    return h(NTag, { type: 'success', size: 'small' }, () => '有组织')
  if (row.has_org === false)
    return h(NTag, { type: 'warning', size: 'small' }, () => '无组织')
  return h(NText, { depth: 3 }, () => '—')
}

function renderMailTag(row: AdobeAccount) {
  const tag =
    row.mail_ok === true
      ? h(NTag, { type: 'success', size: 'tiny', round: true }, () => '收件正常')
      : row.mail_ok === false
        ? h(NTag, { type: 'error', size: 'tiny', round: true }, () => '收件异常')
        : h(NText, { depth: 3 }, () => '—')
  if (!row.mail_message) return tag
  return h(NTooltip, null, {
    trigger: () => tag,
    default: () => h('div', { style: 'max-width:320px;word-break:break-all;' }, row.mail_message),
  })
}

const rowActions = [
  { label: '测试收邮件', key: 'test' },
  { label: '编辑', key: 'edit' },
  { label: '删除', key: 'delete' },
]

function handleAction(key: string, row: AdobeAccount) {
  if (key === 'test') handleTestEmail(row)
  else if (key === 'edit') openEdit(row)
  else if (key === 'delete') confirmDelete(row)
}

const columns = computed<DataTableColumns<AdobeAccount>>(() => [
  { type: 'selection' },
  { title: 'ID', key: 'id', width: 56 },
  { title: '邮箱', key: 'email', minWidth: 220, ellipsis: { tooltip: true } },
  {
    title: '是否有效',
    key: 'is_valid',
    width: 96,
    render: (row) => renderValidTag(row),
  },
  {
    title: '组织',
    key: 'has_org',
    width: 84,
    render: (row) => renderOrgTag(row),
  },
  {
    title: '授权产品',
    key: 'product_name',
    minWidth: 150,
    ellipsis: { tooltip: true },
    render: (row) => row.product_name || h(NText, { depth: 3 }, () => '—'),
  },
  {
    title: '成员数',
    key: 'member_count',
    width: 80,
    render: (row) => row.member_count ?? 0,
  },
  {
    title: '收件',
    key: 'mail_ok',
    width: 96,
    render: (row) => renderMailTag(row),
  },
  { title: '备注', key: 'remark', minWidth: 100, ellipsis: { tooltip: true } },
  {
    title: '操作',
    key: 'actions',
    width: 460,
    fixed: 'right',
    render: (row) =>
      h(NSpace, { size: 6, wrap: false }, () => [
        h(
          NButton,
          {
            size: 'small',
            type: 'primary',
            secondary: true,
            loading: loginIds.value.has(row.id),
            onClick: () => handleLogin(row),
          },
          () => '登录',
        ),
        h(
          NButton,
          {
            size: 'small',
            type: 'info',
            secondary: true,
            loading: checkingIds.value.has(row.id),
            onClick: () => handleCheck(row),
          },
          () => '检测',
        ),
        h(
          NButton,
          {
            size: 'small',
            type: 'success',
            secondary: true,
            loading: syncingIds.value.has(row.id),
            onClick: () => handleSyncMembers(row),
          },
          () => '同步成员',
        ),
        h(
          NButton,
          {
            size: 'small',
            type: 'warning',
            secondary: true,
            loading: manualLoginIds.value.has(row.id),
            onClick: () => openManualLogin(row),
          },
          () => '验证码登录',
        ),
        h(
          NButton,
          { size: 'small', type: 'success', secondary: true, onClick: () => openMembers(row) },
          () => '成员',
        ),
        h(
          NDropdown,
          {
            trigger: 'click',
            options: rowActions,
            onSelect: (key: string) => handleAction(key, row),
          },
          { default: () => h(NButton, { size: 'small', text: true }, () => '更多') },
        ),
      ]),
  },
])

async function handleLogin(row: AdobeAccount) {
  if (!row.refresh_token || !row.client_id) {
    window.$message?.warning('该账号缺少 Refresh Token / Client ID,无法自动收验证码登录')
    return
  }
  toggleId(loginIds, row.id, true)
  try {
    const res = await loginAdobeAdmin(row.id)
    if (res.success) {
      window.$message?.success(`${row.email} 登录成功:${res.message}`)
    } else {
      window.$message?.error(`${row.email} 登录失败:${res.message}`)
    }
  } finally {
    toggleId(loginIds, row.id, false)
    fetchData()
  }
}

const manualLoginModal = ref(false)
const manualLoginTarget = ref<AdobeAccount | null>(null)
const manualLoginSessionId = ref('')
const manualLoginCode = ref('')
const manualLoginLogs = ref<string[]>([])
const manualLoginSending = ref(false)
const manualLoginVerifying = ref(false)

async function openManualLogin(row: AdobeAccount) {
  manualLoginTarget.value = row
  manualLoginSessionId.value = ''
  manualLoginCode.value = ''
  manualLoginLogs.value = []
  manualLoginModal.value = true
  toggleId(manualLoginIds, row.id, true)
  manualLoginSending.value = true
  try {
    const res = await startManualAdobeLogin(row.id)
    manualLoginLogs.value = res.logs || []
    if (res.success && res.session_id) {
      manualLoginSessionId.value = res.session_id
      window.$message?.success(`${row.email} 验证码已发送,请查看邮箱`)
    } else {
      window.$message?.error(`${row.email} 发送验证码失败:${res.message}`)
    }
  } finally {
    manualLoginSending.value = false
    toggleId(manualLoginIds, row.id, false)
  }
}

async function submitManualLoginCode() {
  const row = manualLoginTarget.value
  const code = manualLoginCode.value.trim()
  if (!row || !manualLoginSessionId.value) {
    window.$message?.warning('请先发送验证码')
    return
  }
  if (!code) {
    window.$message?.warning('请输入邮箱验证码')
    return
  }
  manualLoginVerifying.value = true
  try {
    const res = await verifyManualAdobeLogin(row.id, {
      session_id: manualLoginSessionId.value,
      code,
    })
    manualLoginLogs.value = [...manualLoginLogs.value, ...(res.logs || [])]
    if (res.success) {
      window.$message?.success(`${row.email} 登录成功:${res.message}`)
      manualLoginModal.value = false
      await fetchData()
    } else {
      window.$message?.error(`${row.email} 登录失败:${res.message}`)
    }
  } finally {
    manualLoginVerifying.value = false
  }
}

async function handleCheck(row: AdobeAccount) {
  toggleId(checkingIds, row.id, true)
  try {
    const res = await checkAdobeAdmin(row.id)
    if (res.success) window.$message?.success(`${row.email} ${res.message}`)
    else window.$message?.warning(`${row.email} ${res.message}`)
  } finally {
    toggleId(checkingIds, row.id, false)
    fetchData()
  }
}

async function handleSyncMembers(row: AdobeAccount) {
  toggleId(syncingIds, row.id, true)
  try {
    const res = await syncAdobeMembers(row.id)
    window.$message?.success(`${row.email} ${res.message}`)
    if (drawerAccount.value?.id === row.id) {
      drawerAccount.value = { ...row, member_count: row.member_count }
    }
  } finally {
    toggleId(syncingIds, row.id, false)
    fetchData()
  }
}

function confirmDelete(row: AdobeAccount) {
  dialog.warning({
    title: '删除账号',
    content: `确认删除 ${row.email}?`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: () => handleDelete(row.id),
  })
}

async function handleTestEmail(row: AdobeAccount) {
  if (!row.refresh_token || !row.client_id) {
    window.$message?.warning('该账号缺少 Refresh Token 或 Client ID,无法测试')
    return
  }
  testingIds.value = new Set(testingIds.value).add(row.id)
  try {
    const res = await testAdobeEmail(row.id)
    if (res.success) {
      const extra = res.latest_subject ? `,最新邮件:${res.latest_subject}` : ''
      window.$message?.success(`${row.email} ${res.message}${extra}`)
    } else {
      window.$message?.error(`${row.email} 测试失败:${res.message}`)
    }
  } finally {
    const next = new Set(testingIds.value)
    next.delete(row.id)
    testingIds.value = next
    fetchData()
  }
}

// 新增 / 编辑
const showFormModal = ref(false)
const editingId = ref<number | null>(null)
const formRef = ref<FormInst | null>(null)
const form = reactive<AdobeAccountForm>({
  email: '',
  hotmail_password: '',
  adobe_password: '',
  refresh_token: '',
  client_id: '',
  remark: '',
})

const rules = {
  email: { required: true, message: '请输入邮箱', trigger: 'blur' },
}

function resetForm() {
  form.email = ''
  form.hotmail_password = ''
  form.adobe_password = ''
  form.refresh_token = ''
  form.client_id = ''
  form.remark = ''
}

function openCreate() {
  editingId.value = null
  resetForm()
  showFormModal.value = true
}

function openEdit(row: AdobeAccount) {
  editingId.value = row.id
  form.email = row.email
  form.hotmail_password = row.hotmail_password
  form.adobe_password = row.adobe_password
  form.refresh_token = row.refresh_token
  form.client_id = row.client_id
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
      await createAdobeAccount({ ...form })
      window.$message?.success('新增成功')
    } else {
      await updateAdobeAccount(editingId.value, { ...form })
      window.$message?.success('保存成功')
    }
    showFormModal.value = false
    fetchData()
  } finally {
    saving.value = false
  }
}

async function handleDelete(id: number) {
  await deleteAdobeAccount(id)
  window.$message?.success('删除成功')
  fetchData()
}

function handleBatchDelete() {
  if (!checkedRowKeys.value.length) {
    window.$message?.warning('请先勾选要删除的账号')
    return
  }
  dialog.warning({
    title: '批量删除',
    content: `确认删除选中的 ${checkedRowKeys.value.length} 个账号?`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      await batchDeleteAdobeAccounts(checkedRowKeys.value)
      window.$message?.success('批量删除成功')
      checkedRowKeys.value = []
      fetchData()
    },
  })
}

function handlePageChange(page: number) {
  pagination.page = page
  fetchData()
}

function handlePageSizeChange(size: number) {
  pagination.pageSize = size
  pagination.page = 1
  fetchData()
}

function handleSearch() {
  pagination.page = 1
  fetchData()
}

onMounted(fetchData)
</script>

<template>
  <div>
    <NCard :bordered="false">
      <NSpace justify="space-between" align="center" style="margin-bottom: 16px">
        <NSpace>
          <NButton type="primary" @click="openCreate">+ 新增账号</NButton>
          <NButton type="success" @click="openQuickAdd">快速增加母号</NButton>
          <NButton type="info" @click="importModalRef?.open()">批量导入</NButton>
          <NButton
            type="warning"
            :disabled="!checkedRowKeys.length"
            @click="openBatchBuild"
          >
            批量拉号 ({{ checkedRowKeys.length }})
          </NButton>
          <NButton
            type="info"
            :disabled="!checkedRowKeys.length"
            :loading="reloginStarting"
            @click="startBatchRelogin"
          >
            检测重登 ({{ checkedRowKeys.length }})
          </NButton>
          <NButton type="error" :disabled="!checkedRowKeys.length" @click="handleBatchDelete">
            批量删除
          </NButton>
        </NSpace>
        <NSpace>
          <NInput
            v-model:value="keyword"
            placeholder="搜索邮箱 / Client ID / 备注"
            clearable
            style="width: 260px"
            @keyup.enter="handleSearch"
          />
          <NButton @click="handleSearch">搜索</NButton>
        </NSpace>
      </NSpace>

      <NDataTable
        :columns="columns"
        :data="data"
        :loading="loading"
        :row-key="(row: AdobeAccount) => row.id"
        v-model:checked-row-keys="checkedRowKeys"
        :scroll-x="1240"
        remote
        :pagination="{
          page: pagination.page,
          pageSize: pagination.pageSize,
          itemCount: pagination.itemCount,
          pageSizes: pagination.pageSizes,
          showSizePicker: true,
          prefix: (info) => `共 ${info.itemCount} 条`,
          onUpdatePage: handlePageChange,
          onUpdatePageSize: handlePageSizeChange,
        }"
      />
    </NCard>

    <!-- 新增 / 编辑弹窗 -->
    <NModal v-model:show="showFormModal">
      <NCard
        :title="editingId === null ? '新增账号' : '编辑账号'"
        style="width: 560px"
        :bordered="false"
        role="dialog"
      >
        <NForm ref="formRef" :model="form" :rules="rules" label-placement="top">
          <NFormItem label="邮箱" path="email">
            <NInput v-model:value="form.email" placeholder="example@hotmail.com" />
          </NFormItem>
          <NFormItem label="Hotmail 密码">
            <NInput v-model:value="form.hotmail_password" />
          </NFormItem>
          <NFormItem label="母号密码">
            <NInput v-model:value="form.adobe_password" />
          </NFormItem>
          <NFormItem label="Refresh Token">
            <NInput v-model:value="form.refresh_token" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
          </NFormItem>
          <NFormItem label="Client ID">
            <NInput v-model:value="form.client_id" />
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

    <!-- 快速增加母号 -->
    <NModal
      v-model:show="quickAddModal"
      preset="card"
      title="快速增加母号"
      style="width: 640px"
      :mask-closable="!quickAddSaving"
      :closable="!quickAddSaving"
    >
      <NSpace vertical size="large">
        <NText depth="3">
          粘贴一行账号后,系统会自动加入母号管理和邮箱管理,并立即登录母号。
        </NText>
        <NInput
          v-model:value="quickAddContent"
          type="textarea"
          placeholder="邮箱|Hotmail密码|母号密码|Refresh Token|Client ID"
          :autosize="{ minRows: 5, maxRows: 8 }"
        />
        <NInput
          v-if="quickAddLogs.length"
          :value="quickAddLogs.join('\n')"
          type="textarea"
          readonly
          :autosize="{ minRows: 5, maxRows: 10 }"
          placeholder="登录日志"
        />
      </NSpace>
      <template #footer>
        <NSpace justify="end">
          <NButton :disabled="quickAddSaving" @click="quickAddModal = false">取消</NButton>
          <NButton type="primary" :loading="quickAddSaving" @click="submitQuickAdd">
            增加并登录
          </NButton>
        </NSpace>
      </template>
    </NModal>

    <!-- 批量导入弹窗 -->
    <BatchImportModal
      ref="importModalRef"
      title="批量导入母号"
      format-hint="邮箱 | Hotmail密码 | 母号密码 | Refresh Token | Client ID"
      placeholder="BoychukBialy58@hotmail.com|Boychukayho2109#|vwpPvHVW$R0X|M.C537_SN1...|9e5f94bc-e8a4-4e73-b8be-63364c29d753"
      :import-fn="batchImportAdobeAccounts"
      @success="fetchData"
    />

    <!-- 批量拉号弹窗 -->
    <NModal v-model:show="batchModal" preset="card" title="批量拉号" style="width: 520px">
      <NSpace vertical size="large">
        <NText
          >已选 {{ checkedRowKeys.length }} 个主号。每个主号将凑满下方数量的"已注册可用"子号:
          邀请 → 分配产品 → 子号登录拿 cookie/token。未登录的主号会自动登录。</NText
        >
        <NSpace align="center">
          <NText>每个主号目标数量:</NText>
          <NInputNumber v-model:value="batchCount" :min="1" :max="50" style="width: 160px" />
        </NSpace>
        <NText depth="3" style="font-size: 12px">
          按主号顺序处理,每个主号内子号并发(并发数见「设置」)。进度可在「拉号任务」页查看。
        </NText>
      </NSpace>
      <template #footer>
        <NSpace justify="end">
          <NButton @click="batchModal = false">取消</NButton>
          <NButton type="primary" :loading="batchStarting" @click="startBatchBuild">
            开始批量拉号
          </NButton>
        </NSpace>
      </template>
    </NModal>

    <!-- 手动验证码登录 -->
    <NModal
      v-model:show="manualLoginModal"
      preset="card"
      title="手动验证码登录母号"
      style="width: 560px"
      :mask-closable="!manualLoginVerifying"
      :closable="!manualLoginVerifying"
    >
      <NSpace vertical size="large">
        <NText>
          母号: {{ manualLoginTarget?.email || '—' }}
        </NText>
        <NText v-if="manualLoginSending" depth="3">
          正在请求 Adobe 发送验证码邮件 …
        </NText>
        <NText v-else-if="manualLoginSessionId" depth="3">
          验证码已发送到邮箱,请把收到的验证码填到下面。
        </NText>
        <NInput
          v-model:value="manualLoginCode"
          placeholder="输入邮箱验证码"
          maxlength="12"
          clearable
          @keyup.enter="submitManualLoginCode"
        />
        <NInput
          :value="manualLoginLogs.join('\n')"
          type="textarea"
          readonly
          :autosize="{ minRows: 5, maxRows: 10 }"
          placeholder="登录日志"
        />
      </NSpace>
      <template #footer>
        <NSpace justify="end">
          <NButton :disabled="manualLoginVerifying" @click="manualLoginModal = false">
            关闭
          </NButton>
          <NButton
            type="primary"
            :loading="manualLoginSending || manualLoginVerifying"
            :disabled="!manualLoginSessionId"
            @click="submitManualLoginCode"
          >
            提交验证码登录
          </NButton>
        </NSpace>
      </template>
    </NModal>

    <!-- 子账号(成员)管理抽屉 -->
    <MembersDrawer v-model:show="drawerShow" :account="drawerAccount" @refresh="fetchData" />
  </div>
</template>
