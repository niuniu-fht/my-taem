import request from './request'
import type { MessageResult } from './types'

export type ExportFormat = 'token' | 'cookie'

export interface SystemSettings {
  proxy_enabled: boolean
  proxy_url: string
  concurrency: number
  request_timeout: number
  register_country: string
  register_locale: string
  export_format: ExportFormat
}

export function getSettings(): Promise<SystemSettings> {
  return request.get('/settings')
}

export function updateSettings(data: Partial<SystemSettings>): Promise<SystemSettings> {
  return request.put('/settings', data)
}

export function changePassword(
  oldPassword: string,
  newPassword: string,
): Promise<MessageResult> {
  return request.post('/settings/change-password', {
    old_password: oldPassword,
    new_password: newPassword,
  })
}

export interface ProxyTestItem {
  proxy: string
  ok: boolean
  ip: string
  latency_ms: number
  message: string
}

export interface ProxyTestResult {
  total: number
  ok_count: number
  items: ProxyTestItem[]
}

export function testProxy(proxyUrl: string): Promise<ProxyTestResult> {
  return request.post('/settings/test-proxy', { proxy_url: proxyUrl })
}
