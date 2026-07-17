import request from './request'
import type { BatchImportResult, MessageResult, Page } from './types'

export interface EmailItem {
  id: number
  email: string
  password: string
  refresh_token: string
  client_id: string
  mail_url: string
  is_used: boolean
  is_disabled: boolean
  used_at: string | null
  remark: string
  created_at: string
}

export type EmailForm = Pick<
  EmailItem,
  'email' | 'password' | 'refresh_token' | 'client_id' | 'mail_url' | 'remark'
>

export interface CheckedEmailImportItem {
  line_no: number
  email: string
  success: boolean
  message: string
  source: string
}

export interface CheckedEmailImportResult extends BatchImportResult {
  checked: number
  passed: number
  rejected: number
  checks: CheckedEmailImportItem[]
}

export interface ListEmailParams {
  page?: number
  size?: number
  keyword?: string
  remark?: string
  is_used?: boolean | null
  is_disabled?: boolean | null
}

export function listEmails(params: ListEmailParams): Promise<Page<EmailItem>> {
  return request.get('/emails', { params })
}

export function createEmail(data: EmailForm): Promise<EmailItem> {
  return request.post('/emails', data)
}

export function updateEmail(
  id: number,
  data: Partial<EmailForm> & { is_used?: boolean; is_disabled?: boolean },
): Promise<EmailItem> {
  return request.put(`/emails/${id}`, data)
}

export function deleteEmail(id: number): Promise<MessageResult> {
  return request.delete(`/emails/${id}`)
}

export function batchDeleteEmails(ids: number[]): Promise<MessageResult> {
  return request.post('/emails/batch-delete', { ids })
}

export function batchSetEmailsUsed(ids: number[], isUsed: boolean): Promise<MessageResult> {
  return request.post('/emails/batch-used', { ids, is_used: isUsed })
}

export function batchSetEmailsDisabled(
  ids: number[],
  isDisabled: boolean,
): Promise<MessageResult> {
  return request.post('/emails/batch-disabled', { ids, is_disabled: isDisabled })
}

export function batchImportEmails(
  content: string,
  onDuplicate: 'skip' | 'overwrite',
): Promise<BatchImportResult> {
  return request.post('/emails/batch-import', { content, on_duplicate: onDuplicate })
}

export function batchImportEmailsChecked(
  content: string,
  onDuplicate: 'skip' | 'overwrite',
  checkMail = true,
): Promise<CheckedEmailImportResult> {
  return request.post(
    '/emails/batch-import-checked',
    { content, on_duplicate: onDuplicate, check_mail: checkMail },
    { timeout: 600000 },
  )
}

export interface MoeMailGeneratePayload {
  api_key: string
  count: number
  domain: string
  name_prefix?: string
  expiry_time: number
  password?: string
  on_duplicate?: 'skip' | 'overwrite'
}

export function generateMoeMailEmails(data: MoeMailGeneratePayload): Promise<BatchImportResult> {
  return request.post('/emails/moemail/generate', data, { timeout: 180000 })
}

export interface MailSummary {
  id: string
  subject: string
  from_addr: string
  date: string
  folder: string
  preview: string
  is_read: boolean | null
  source: string
}

export interface MailListResult {
  success: boolean
  message: string
  source: string
  messages: MailSummary[]
}

export interface MailDetailResult {
  success: boolean
  message: string
  subject: string
  from_addr: string
  to_addr: string
  date: string
  body_html: string
  body_text: string
}

export function fetchMailMessages(emailId: number, top = 20): Promise<MailListResult> {
  return request.get(`/emails/${emailId}/messages`, { params: { top } })
}

export function fetchMailDetail(
  emailId: number,
  messageId: string,
  source: string,
): Promise<MailDetailResult> {
  return request.get(`/emails/${emailId}/message`, {
    params: { message_id: messageId, source },
  })
}
