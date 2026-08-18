<script setup lang="ts">
/**
 * Light / dark / follow-system.
 *
 * Persisted in localStorage for now. PRD §24 wants this on UserSettings so it
 * follows a reader between devices; that arrives with the reader preferences.
 */
type Theme = 'light' | 'dark' | 'system'

const theme = useState<Theme>('theme', () => 'system')

function apply(value: Theme) {
  if (!import.meta.client) return
  const root = document.documentElement
  if (value === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', value)
  localStorage.setItem('lumaindex-theme', value)
}

onMounted(() => {
  const stored = localStorage.getItem('lumaindex-theme') as Theme | null
  if (stored) theme.value = stored
  apply(theme.value)
})

function cycle() {
  theme.value = theme.value === 'system' ? 'light' : theme.value === 'light' ? 'dark' : 'system'
  apply(theme.value)
}

const label = computed(() => ({
  system: 'Theme: follows your system',
  light: 'Theme: light',
  dark: 'Theme: dark',
}[theme.value]))
</script>

<template>
  <AppButton variant="ghost" size="sm" icon-only :icon="theme === 'dark' ? 'moon' : 'sun'"
             :title="label" :aria-label="label" @click="cycle" />
</template>
