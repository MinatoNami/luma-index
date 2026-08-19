<script setup lang="ts">
/**
 * Stamps the saved theme onto <html> during SSR.
 *
 * The global middleware has already awaited the account's preferences by the
 * time this runs, so the attribute is present in the server-rendered HTML. That
 * matters: applying it after hydration means a dark-mode reader on a
 * light-mode system gets a white flash on every cold load.
 *
 * 'system' deliberately sets nothing, leaving prefers-color-scheme in charge —
 * which is the third state the tokens are written for.
 */
const { settings } = useSettings()

useHead({
  htmlAttrs: {
    // A getter rather than a computed wrapping the whole object: unhead
    // resolves per-value functions, and typing a ComputedRef as the attrs bag
    // itself does not satisfy the tag's own property type.
    'data-theme': () => {
      const theme = settings.value?.theme
      return theme === 'light' || theme === 'dark' ? theme : undefined
    },
  },
})
</script>

<template>
  <NuxtLayout>
    <NuxtPage />
  </NuxtLayout>
</template>
