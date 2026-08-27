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
      // Every page was missing this. A screen reader needs it to choose a
      // voice, and a browser to choose hyphenation and quote marks.
      htmlAttrs: { lang: 'en' },
      title: 'LumaIndex',
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1, viewport-fit=cover' },
        { name: 'color-scheme', content: 'light dark' },
        { name: 'theme-color', content: '#4B4ACF' },
        // Added to the Home Screen, iOS runs this without Safari's chrome.
        // The manifest's `display` covers iOS 16.4 and up; this is the older
        // switch, and harmless where the manifest is understood.
        { name: 'apple-mobile-web-app-capable', content: 'yes' },
        { name: 'mobile-web-app-capable', content: 'yes' },
        // Translucent, so the status bar takes the page's own background
        // rather than a black band above it.
        { name: 'apple-mobile-web-app-status-bar-style', content: 'black-translucent' },
        { name: 'apple-mobile-web-app-title', content: 'LumaIndex' },
      ],
      // The icon and manifest links are NOT here: their hrefs have to carry
      // the base the app is served under, and that arrives at runtime. Nuxt
      // rewrites build assets from app.baseURL but not head links, so these
      // are set in app.vue where the runtime config can be read.

    },
  },

  typescript: { strict: true },
})
