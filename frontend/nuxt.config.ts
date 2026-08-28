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
        // Not black-translucent, which this used to be. That value hands the
        // status bar area to the page and draws the clock and battery in white
        // over whatever is underneath — which on a phone, where the layout has
        // no top chrome at all, is --bg. In light mode that is #F7F6F3, so the
        // status bar was white on near-white. `default` gives the strip back to
        // iOS, which paints it and picks a readable colour for both themes, and
        // makes it impossible for content to reach the camera in the first
        // place. The safe-area insets in the layout stay as the guard for the
        // cases iOS does hand the space over, landscape among them.
        { name: 'apple-mobile-web-app-status-bar-style', content: 'default' },
        { name: 'apple-mobile-web-app-title', content: 'LumaIndex' },
      ],
      // The icon and manifest links are NOT here: their hrefs have to carry
      // the base the app is served under, and that arrives at runtime. Nuxt
      // rewrites build assets from app.baseURL but not head links, so these
      // are set in app.vue where the runtime config can be read.

    },
  },

  vite: {
    server: {
      /**
       * Hostnames the dev server will answer to, beyond the defaults.
       *
       * Vite refuses a request whose Host header it does not recognise, and the
       * e2e suite reaches the app as `caddy:8080` — a service name, not an
       * address, so it is refused. It survived until now only because a
       * freshly-booted container had not applied the check yet; editing this
       * file restarts Nuxt in place, the check comes into force, and every
       * browser test starts failing on a page that says so in tiny text. The
       * value comes from the environment because the name belongs to the
       * compose file, not to the app.
       */
      allowedHosts: process.env.NUXT_DEV_ALLOWED_HOSTS?.split(',') ?? [],
    },
  },

  typescript: { strict: true },
})
