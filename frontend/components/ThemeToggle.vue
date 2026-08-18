<script setup lang="ts">
import { applyTheme, type Theme } from '~/composables/useSettings'

/**
 * Cycles light → dark → follow-system.
 *
 * Applies immediately and saves to the account in the background, so the choice
 * follows the user to their other devices (PRD §24). A failed save is not worth
 * interrupting anyone over — the setting still applies here.
 */
const { settings, saveSettings } = useSettings()

const theme = computed<Theme>(() => settings.value?.theme ?? 'system')

const LABELS: Record<Theme, string> = {
  system: 'Theme: follows your system',
  light: 'Theme: light',
  dark: 'Theme: dark',
}

async function cycle() {
  const next: Theme = theme.value === 'system' ? 'light' : theme.value === 'light' ? 'dark' : 'system'
  applyTheme(next)
  if (settings.value) settings.value = { ...settings.value, theme: next }
  try {
    await saveSettings({ theme: next })
  } catch {
    // Applied locally regardless.
  }
}
</script>

<template>
  <AppButton variant="ghost" size="sm" icon-only
             :icon="theme === 'dark' ? 'moon' : 'sun'"
             :title="LABELS[theme]" :aria-label="LABELS[theme]" @click="cycle" />
</template>
