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

/**
 * Icons and the manifest, pointed at wherever this instance is served from.
 *
 * Nuxt rewrites build assets from app.baseURL but not head links, so these
 * would stay root-absolute — and behind a path prefix that means the manifest
 * 404s, no install prompt appears, and the favicon comes from whatever else
 * owns the root of the origin.
 */
const base = (useRuntimeConfig().app.baseURL || '/').replace(/\/$/, '')

useHead({
  link: [
    // SVG first for anything modern; the PNGs cover Safari's touch icon and
    // the contexts that still ask for a raster favicon.
    { rel: 'icon', type: 'image/svg+xml', href: `${base}/icon.svg` },
    { rel: 'icon', type: 'image/png', sizes: '32x32', href: `${base}/favicon-32.png` },
    { rel: 'apple-touch-icon', href: `${base}/apple-touch-icon.png` },
    { rel: 'manifest', href: `${base}/manifest.webmanifest` },
  ],
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
