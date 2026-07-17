import type { JobStatus } from './adobe'
import request from './request'
import type { BatchImportResult, MessageResult, Page } from './types'

export interface PoolItem {
  id: number
  admin_id: number
  admin_email: string
  email: string
  display_name: string
  member_id: string
  status: string
  credits: number | null
  expires_at: number | null
  registered: boolean
  is_admin: boolean
  is_imported: boolean
  has_token: boolean
  has_cookie: boolean
  has_arp: boolean
  created_at: string
}

export type PoolTypeFilter = '' | 'all' | 'imported' | 'sub' | 'admin'
export type PoolTokenFilter = '' | 'yes' | 'no'
export type PoolCreditFilter = '' | 'unknown' | 'known'
export type PoolCreditValueFilter = number | null
export type PoolStatusFilter = '' | 'failed' | 'registered' | 'pending' | 'needs_authorization'

export interface PoolListParams {
  page?: number
  size?: number
  keyword?: string
  admin_id?: number | null
  registered_only?: boolean
  pool_type?: PoolTypeFilter
  has_token?: PoolTokenFilter
  credit_status?: PoolCreditFilter
  credit_value?: PoolCreditValueFilter
  status_filter?: PoolStatusFilter
}

export function listPool(params: PoolListParams): Promise<Page<PoolItem>> {
  return request.get('/pool', { params })
}

export function batchDeletePool(ids: number[]): Promise<MessageResult> {
  return request.post('/pool/batch-delete', { ids })
}

export function importPool(content: string): Promise<BatchImportResult> {
  return request.post('/pool/import', { content })
}

export interface PoolMoeMailGeneratePayload {
  api_key: string
  count: number
  domain: string
  name_prefix?: string
  expiry_time: number
  password?: string
}

export function generatePoolMoeMail(data: PoolMoeMailGeneratePayload): Promise<BatchImportResult> {
  return request.post('/pool/moemail/generate', data, { timeout: 180000 })
}

export function batchLoginPool(
  ids: number[],
  opts: { autoRetry?: boolean; maxRetries?: number } = {},
): Promise<JobStatus> {
  return request.post('/pool/batch-login', {
    ids,
    auto_retry: opts.autoRetry ?? true,
    max_retries: opts.maxRetries ?? 2,
  })
}

export interface PoolBatchLoginFilter {
  keyword?: string
  admin_id?: number | null
  registered_only?: boolean
  pool_type?: PoolTypeFilter
  has_token?: boolean | null
  credit_status?: PoolCreditFilter
  credit_value?: PoolCreditValueFilter
  status_filter?: PoolStatusFilter
  auto_retry?: boolean
  max_retries?: number
}

export function batchLoginPoolFilter(filter: PoolBatchLoginFilter): Promise<JobStatus> {
  return request.post('/pool/batch-login-filter', {
    keyword: filter.keyword ?? '',
    admin_id: filter.admin_id ?? null,
    registered_only: filter.registered_only ?? false,
    pool_type: filter.pool_type || 'imported',
    has_token: filter.has_token ?? false,
    credit_status: filter.credit_status ?? '',
    credit_value: filter.credit_value ?? null,
    status_filter: filter.status_filter ?? '',
    auto_retry: filter.auto_retry ?? true,
    max_retries: filter.max_retries ?? 2,
  })
}

export function batchRefreshCreditsPool(ids: number[]): Promise<JobStatus> {
  return request.post('/pool/batch-refresh-credits', { ids })
}

export function batchRefreshCreditsPoolFilter(filter: PoolBatchLoginFilter): Promise<JobStatus> {
  return request.post('/pool/batch-refresh-credits-filter', {
    keyword: filter.keyword ?? '',
    admin_id: filter.admin_id ?? null,
    registered_only: filter.registered_only ?? false,
    pool_type: filter.pool_type || 'sub',
    has_token: true,
    credit_status: filter.credit_status ?? '',
    credit_value: filter.credit_value ?? null,
    status_filter: filter.status_filter ?? '',
  })
}

export function batchLoginRetryJob(jobId: number): Promise<JobStatus> {
  return request.post(`/pool/batch-login-retry/${jobId}`)
}

export interface PoolMemberDetail {
  id: number
  admin_id: number
  email: string
  display_name: string
  member_id: string
  status: string
  message: string
  credits: number | null
  expires_at: number | null
  registered: boolean
  access_token: string
  cookie: string
  arp_session_id: string
  refresh_token: string
  client_id: string
}

export type PoolMemberUpdate = Partial<
  Pick<
    PoolMemberDetail,
    | 'display_name'
    | 'status'
    | 'access_token'
    | 'cookie'
    | 'arp_session_id'
    | 'refresh_token'
    | 'client_id'
    | 'credits'
  >
>

export interface TestImageResult {
  success: boolean
  message: string
  image_url: string
  prompt: string
}

export interface RefreshTokenResult {
  success: boolean
  message: string
  credits: number | null
  expires_at: number | null
}

export interface RefreshARPResult {
  success: boolean
  message: string
  arp_session_id: string
  has_access_token: boolean
}

export function getPoolMember(id: number): Promise<PoolMemberDetail> {
  return request.get(`/pool/${id}`)
}

export function updatePoolMember(id: number, data: PoolMemberUpdate): Promise<PoolMemberDetail> {
  return request.put(`/pool/${id}`, data)
}

export function testPoolImage(
  id: number,
  opts: {
    prompt?: string
    aspectRatio?: string
    quality?: string
    width?: number | null
    height?: number | null
  } = {},
): Promise<TestImageResult> {
  return request.post(
    `/pool/${id}/test-image`,
    {
      prompt: opts.prompt,
      aspect_ratio: opts.aspectRatio ?? '1:1',
      quality: opts.quality ?? 'medium',
      width: opts.width ?? null,
      height: opts.height ?? null,
    },
    { timeout: 200000 },
  )
}

export function refreshPoolToken(id: number): Promise<RefreshTokenResult> {
  // 协议登录刷新 AT,OTP 最长约 3 分钟
  return request.post(`/pool/${id}/refresh-token`, {}, { timeout: 220000 })
}

export function refreshPoolARP(
  id: number,
  opts: { prompt?: string; headless?: boolean; timeoutSeconds?: number } = {},
): Promise<RefreshARPResult> {
  return request.post(
    `/pool/${id}/refresh-arp`,
    {
      prompt: opts.prompt ?? 'cartoon watermelon sticker',
      headless: opts.headless ?? true,
      timeout_seconds: opts.timeoutSeconds ?? 120,
    },
    { timeout: (opts.timeoutSeconds ?? 120) * 1000 + 30000 },
  )
}

export function testPoolMail(id: number): Promise<MessageResult> {
  return request.post(`/pool/${id}/test-mail`, {}, { timeout: 60000 })
}

function downloadBlob(blob: Blob, format: 'default' | 'json' | 'cookies' | 'tokens' | 'accounts') {
  const ext = format === 'tokens' ? 'txt' : 'json'
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `pool_${format}_${Date.now()}.${ext}`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  window.URL.revokeObjectURL(url)
}

export async function exportPool(
  format: 'default' | 'json' | 'cookies' | 'tokens' | 'accounts',
  params: Pick<
    PoolListParams,
    | 'keyword'
    | 'admin_id'
    | 'pool_type'
    | 'has_token'
    | 'credit_status'
    | 'credit_value'
    | 'status_filter'
  > & { ids?: string } = {},
): Promise<void> {
  const blob = (await request.get('/pool/export', {
    params: { format, ...params },
    responseType: 'blob',
  })) as unknown as Blob
  downloadBlob(blob, format)
}

export async function exportSelectedPool(
  format: 'default' | 'json' | 'cookies' | 'tokens' | 'accounts',
  ids: number[],
): Promise<void> {
  const blob = (await request.post(
    '/pool/export-selected',
    { ids },
    { params: { format }, responseType: 'blob' },
  )) as unknown as Blob
  downloadBlob(blob, format)
}
