<script setup lang="ts">
import {
  NConfigProvider,
  NDialogProvider,
  NMessageProvider,
  zhCN,
  dateZhCN,
  type GlobalThemeOverrides,
} from 'naive-ui'
import NaiveProviderContent from '@/components/NaiveProviderContent'

const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#1890ff',
    primaryColorHover: '#46a6ff',
    primaryColorPressed: '#0e80e6',
    borderRadius: '6px',
  },
}
</script>

<template>
  <NConfigProvider :locale="zhCN" :date-locale="dateZhCN" :theme-overrides="themeOverrides">
    <NMessageProvider>
      <NDialogProvider>
        <NaiveProviderContent />
        <RouterView />
      </NDialogProvider>
    </NMessageProvider>
  </NConfigProvider>
</template>
