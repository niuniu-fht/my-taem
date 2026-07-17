export interface Page<T> {
  items: T[]
  total: number
  page: number
  size: number
}

export interface BatchImportResult {
  created: number
  updated: number
  skipped: number
  failed: number
  errors: string[]
}

export interface MessageResult {
  success: boolean
  message: string
}
