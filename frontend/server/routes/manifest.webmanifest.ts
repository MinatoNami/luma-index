/**
 * The web app manifest, generated rather than served as a static file.
 *
 * Every path in it has to carry the base the app is actually served under, and
 * a file in public/ cannot: it is written at build time, while the base arrives
 * at runtime through NUXT_APP_BASE_URL. Served behind a path prefix, the static
 * version told the browser `start_url: "/"` — so installing to a Home Screen
 * produced an icon that opened whatever else lives at the root of that origin.
 */
export default defineEventHandler((event) => {
  const base = useRuntimeConfig().app.baseURL || '/'
  // baseURL always has a trailing slash; joining without stripping it gives
  // "//icon.svg", which resolves as a protocol-relative URL to another host.
  const at = (path: string) => `${base.replace(/\/$/, '')}/${path}`

  setHeader(event, 'content-type', 'application/manifest+json')
  // Short, because it changes with the deployment rather than with the build.
  setHeader(event, 'cache-control', 'public, max-age=300')

  return {
    name: 'LumaIndex',
    short_name: 'LumaIndex',
    description: 'Your PDF library.',
    start_url: base,
    scope: base,
    display: 'standalone',
    orientation: 'any',
    background_color: '#151417',
    theme_color: '#4B4ACF',
    icons: [
      { src: at('icon-192.png'), sizes: '192x192', type: 'image/png' },
      { src: at('icon-512.png'), sizes: '512x512', type: 'image/png' },
      { src: at('icon.svg'), sizes: 'any', type: 'image/svg+xml' },
    ],
  }
})
