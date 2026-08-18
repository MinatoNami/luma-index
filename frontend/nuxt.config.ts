// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  compatibilityDate: '2024-11-01',
  devtools: { enabled: false },

  css: ['~/assets/css/main.css'],

  runtimeConfig: {
    // Server-side only. During SSR the Nuxt container talks to Django directly
    // over the compose network, bypassing Caddy — one less hop, and it works
    // even before TLS is configured.
    apiInternalBase: process.env.NUXT_API_INTERNAL_BASE || 'http://backend:8000',

    public: {
      // Browser-side. Relative on purpose: same-origin requests need no CORS
      // and the session cookie is sent automatically.
      apiBase: process.env.NUXT_PUBLIC_API_BASE || '/api',
    },
  },

  nitro: {
    // Nuxt is served by Caddy, which handles compression and TLS.
    compressPublicAssets: false,
  },

  app: {
    head: {
      title: 'LumaIndex',
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1, viewport-fit=cover' },
        { name: 'color-scheme', content: 'light dark' },
        { name: 'theme-color', content: '#4B4ACF' },
      ],
      link: [
        // SVG first for anything modern; the PNGs cover Safari's touch icon and
        // the contexts that still ask for a raster favicon.
        { rel: 'icon', type: 'image/svg+xml', href: '/icon.svg' },
        { rel: 'icon', type: 'image/png', sizes: '32x32', href: '/favicon-32.png' },
        { rel: 'apple-touch-icon', href: '/apple-touch-icon.png' },
      ],
    },
  },

  typescript: { strict: true },
})
