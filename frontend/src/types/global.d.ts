import type { DialogApi, MessageApi } from 'naive-ui'

declare global {
  interface Window {
    $message: MessageApi
    $dialog: DialogApi
  }
}

export {}
