<script setup lang="ts">
import { applyTheme, nextTheme, type Theme } from '~/composables/useSettings'

/**
 * Switches between light and dark, based on what is currently on screen.
 *
 * It used to cycle light → dark → system, which meant one press in three did
 * nothing you could see: with the setting on `system` and the machine set to
 * light, the app already looked light, so choosing `light` changed the stored
 * value and not a single pixel. Pressing it twice appeared to be necessary.
 *
 * So it toggles against the *resolved* appearance instead, and every press
 * changes something. `system` is still a choice — it lives in Settings, where
 * picking it is deliberate rather than something you land on mid-cycle.
 *
 * Applies immediately and saves in the background, so the choice follows the
 * reader to their other devices (PRD §24). A failed save is not worth
 * interrupting anyone over; the setting still applies here.
 */
const { settings, saveSettings } = useSettings()

// Only consulted when the setting is `system`. Starts false so the server and
// the first client render agree; a machine set to dark corrects it on mount.
const systemPrefersDark = ref(false)
let media: MediaQueryList | null = null
const onSystemChange = (event: MediaQueryListEvent) => {
  systemPrefersDark.value = event.matches
}

onMounted(() => {
  media = window.matchMedia('(prefers-color-scheme: dark)')
  systemPrefersDark.value = media.matches
  media.addEventListener('change', onSystemChange)
})
onBeforeUnmount(() => media?.removeEventListener('change', onSystemChange))

// The decision itself lives in useSettings as a pure function, where it can be
// tested without mounting anything.
const target = computed<Theme>(() =>
  nextTheme(settings.value?.theme ?? 'system', systemPrefersDark.value))
const label = computed(() =>
  target.value === 'light' ? 'Switch to the light theme' : 'Switch to the dark theme')

async function toggle() {
  const next = target.value
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
  <!-- The icon is what you will get, not what you have: it is the thing being
       offered, and it is how this control is usually read. -->
  <AppButton variant="ghost" size="sm" icon-only
             :icon="target === 'light' ? 'sun' : 'moon'"
             :title="label" :aria-label="label" @click="toggle" />
</template>
