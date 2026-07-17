import { defineComponent, h } from 'vue'
import { useDialog, useMessage } from 'naive-ui'

// 将 Naive UI 的 message / dialog 实例挂到 window,
// 方便在 Vue 组件之外(如 axios 拦截器)调用。
export default defineComponent({
  name: 'NaiveProviderContent',
  setup() {
    window.$message = useMessage()
    window.$dialog = useDialog()
    return () => h('div', { style: { display: 'none' } })
  },
})
