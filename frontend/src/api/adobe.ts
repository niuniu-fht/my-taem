import request from './request'
import type { BatchImportResult, MessageResult, Page } from './types'

export interface AdobeAccount {
  id: number
  email: string
  hotmail_password: string
  adobe_password: string
  refresh_token: string
  client_id: string
  remark: string
  is_valid: boolean | null
  check_message: string
  last_checked_at: string | null
  has_org: boolean | null
  org_id: string
  product_name: string
  member_count: number
  last_login_at: string | null
  mail_ok: boolean | null
  mail_message: string
  mail_checked_at: string | null
  created_at: string
  updated_at: string
}

export interface AdminActionResult {
  success: boolean
  message: string
  has_org: boolean | null
  org_id: string
  product_name: string
  org_count: number
  product_count: number
  logs: string[]
}

export interface QuickAddAdobeAccountResult extends AdminActionResult {
  account_id: number
  email: string
  account_created: boolean
  email_created: boolean
  email_synced: boolean
  login_attempted: boolean
}

export interface ManualLoginStartResult {
  success: boolean
  message: string
  session_id: string
  logs: string[]
}

export interface AdobeMember {
  id: number
  admin_id: number
  email: string
  member_id: string
  status: string
  message: string
  display_name: string
  credits: number | null
  expires_at: number | null
  registered: boolean
  email_disabled: boolean
  created_at: string
  updated_at: string
}

export interface JobTeam {
  admin_id: number
  email: string
  target: number
  success: number
  fail: number
  status: string
  message: string
}

export interface JobStatus {
  id: number
  type: string
  status: 'running' | 'done' | 'error' | 'cancelled'
  target: number
  success: number
  fail: number
  result: Record<string, unknown> | null
  error: string
  created_at: number | null
  finished_at: number | null
  log_total: number
  logs: string[]
  extra: { teams?: JobTeam[] } | null
}

export interface GrantItemResult {
  email: string
  ok: boolean
  message: string
}

export interface BatchGrantResult {
  total: number
  granted: number
  failed: number
  items: GrantItemResult[]
}

export type AdobeAccountForm = Pick<
  AdobeAccount,
  'email' | 'hotmail_password' | 'adobe_password' | 'refresh_token' | 'client_id' | 'remark'
>

export interface TestEmailResult {
  success: boolean
  message: string
  inbox_total: number | null
  latest_subject: string | null
  latest_from: string | null
}

export interface ListParams {
  page?: number
  size?: number
  keyword?: string
}

export function listAdobeAccounts(params: ListParams): Promise<Page<AdobeAccount>> {
  return request.get('/adobe-accounts', { params })
}

export function createAdobeAccount(data: AdobeAccountForm): Promise<AdobeAccount> {
  return request.post('/adobe-accounts', data)
}

export function updateAdobeAccount(
  id: number,
  data: Partial<AdobeAccountForm>,
): Promise<AdobeAccount> {
  return request.put(`/adobe-accounts/${id}`, data)
}

export function deleteAdobeAccount(id: number): Promise<MessageResult> {
  return request.delete(`/adobe-accounts/${id}`)
}

export function batchDeleteAdobeAccounts(ids: number[]): Promise<MessageResult> {
  return request.post('/adobe-accounts/batch-delete', { ids })
}

export function batchImportAdobeAccounts(
  content: string,
  onDuplicate: 'skip' | 'overwrite',
): Promise<BatchImportResult> {
  return request.post('/adobe-accounts/batch-import', {
    content,
    on_duplicate: onDuplicate,
  })
}

export function quickAddAdobeAccount(
  content: string,
  remark = '母号',
): Promise<QuickAddAdobeAccountResult> {
  return request.post(
    '/adobe-accounts/quick-add',
    { content, remark, login: true },
    { timeout: 240000 },
  )
}

export function testAdobeEmail(id: number): Promise<TestEmailResult> {
  return request.post(`/adobe-accounts/${id}/test-email`)
}

export function loginAdobeAdmin(id: number): Promise<AdminActionResult> {
  return request.post(`/adobe-accounts/${id}/login`)
}

export function startManualAdobeLogin(id: number): Promise<ManualLoginStartResult> {
  return request.post(`/adobe-accounts/${id}/login/manual/start`, {}, { timeout: 60000 })
}

export function verifyManualAdobeLogin(
  id: number,
  data: { session_id: string; code: string },
): Promise<AdminActionResult> {
  return request.post(`/adobe-accounts/${id}/login/manual/verify`, data, { timeout: 120000 })
}

export function checkAdobeAdmin(id: number): Promise<AdminActionResult> {
  return request.post(`/adobe-accounts/${id}/check`)
}

export function syncAdobeMembers(id: number): Promise<MessageResult> {
  return request.post(`/adobe-accounts/${id}/members/sync-remote`, {}, { timeout: 120000 })
}

export function listAdobeMembers(
  id: number,
  params: { page?: number; size?: number; keyword?: string },
): Promise<Page<AdobeMember>> {
  return request.get(`/adobe-accounts/${id}/members`, { params })
}

export function batchGrantMembers(
  id: number,
  data: { count?: number; emails?: string[] },
): Promise<BatchGrantResult> {
  return request.post(`/adobe-accounts/${id}/members/batch-grant`, data)
}

export function batchDeleteMembers(id: number, ids: number[]): Promise<MessageResult> {
  return request.post(`/adobe-accounts/${id}/members/batch-delete`, { ids })
}

export function batchDisableMemberEmails(id: number, ids: number[]): Promise<MessageResult> {
  return request.post(`/adobe-accounts/${id}/members/batch-disable-emails`, { ids })
}

export function batchAuthorizeLoginMembers(
  id: number,
  ids: number[],
): Promise<BatchGrantResult> {
  return request.post(
    `/adobe-accounts/${id}/members/batch-authorize-login`,
    { ids },
    { timeout: 300000 },
  )
}

export type BuildTeamMode = 'fill' | 'one_by_one'

export function buildTeam(id: number, count = 9, mode: BuildTeamMode = 'fill'): Promise<JobStatus> {
  return request.post(`/adobe-accounts/${id}/members/build-team`, { count, mode })
}

export function getJob(jobId: number, logOffset = 0): Promise<JobStatus> {
  return request.get(`/adobe-accounts/jobs/${jobId}`, {
    params: { log_offset: logOffset },
  })
}

export function buildTeamBatch(adminIds: number[], count = 9): Promise<JobStatus> {
  return request.post('/adobe-accounts/build-team-batch', {
    admin_ids: adminIds,
    count,
  })
}

export function batchReloginAdobeAccounts(ids: number[]): Promise<JobStatus> {
  return request.post('/adobe-accounts/batch-relogin', {
    ids,
    only_invalid: true,
  })
}

export function listJobs(limit = 30): Promise<JobStatus[]> {
  return request.get('/adobe-accounts/jobs', { params: { limit } })
}

export function batchDeleteJobs(ids: number[]): Promise<MessageResult> {
  return request.post('/adobe-accounts/jobs/batch-delete', { ids })
}

export function cancelJob(jobId: number): Promise<MessageResult> {
  return request.post(`/adobe-accounts/jobs/${jobId}/cancel`)
}

export function clearJobLogs(jobId: number): Promise<MessageResult> {
  return request.post(`/adobe-accounts/jobs/${jobId}/clear-logs`)
}
