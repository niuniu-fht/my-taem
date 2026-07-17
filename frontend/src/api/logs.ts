import request from './request'
import type { MessageResult } from './types'

export interface LogItem {
  id: number
  time: string
  ts: number
  level: string
  source: string
  message: string
  traceback: string
}

export interface LogListResult {
  items: LogItem[]
  total: number
}

export function listLogs(params: {
  level?: string
  keyword?: string
  limit?: number
}): Promise<LogListResult> {
  return request.get('/logs', { params })
}

export function clearLogs(): Promise<MessageResult> {
  return request.post('/logs/clear')
}
