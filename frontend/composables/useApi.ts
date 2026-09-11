/**
 * Thin wrapper around $fetch that makes Django's session + CSRF scheme work
 * from both the browser and the Nuxt server.
 *
 * Two things routinely go wrong here and are handled explicitly:
 *
 * 1. SSR has no cookies of its own. A server-side fetch is made by the Nuxt
 *    *server*, not the user's browser, so unless we forward the incoming
 *    Cookie header every SSR render looks signed-out — the page flashes the
 *    login screen and then corrects itself on hydration.
 *
 * 2. Django rejects unsafe methods without an `X-CSRFToken` header matching
 *    the CSRF cookie. The cookie is intentionally readable by JS; the session
 *    cookie is not.
 */

export type ApiOptions = Parameters<typeof $fetch>[1]

/**
 * The value of a cookie in a serialised jar — the LAST of that name, not the
 * first.
 *
 * A browser can hold two cookies of one name at different paths, which is what
 * an instance moving under a path prefix leaves behind: the old cookie at "/"
 * and the new one at the prefix, both sent on every request. Django's parser
 * keeps the last occurrence, so the last is the one it will validate against —
 * and echoing the first fails CSRF on every unsafe request, the login that
 * would be the way out included. `document.cookie` is serialised like the
 * Cookie header, so the last here is the last there.
 *
 * The backend expires the stale cookie as soon as it sees the duplicate, so
 * this decides the round trip that does it, and any duplicate after.
 */
export function lastCookie(jar: string, name: string): string | null {
  const matches = [...jar.matchAll(new RegExp(`(?:^|;\\s*)${name}=([^;]*)`, 'g'))]
  const last = matches.at(-1)
  return last ? decodeURIComponent(last[1]) : null
}

function readCookie(name: string): string | null {
  if (!import.meta.client) return null
  return lastCookie(document.cookie, name)
}

/**
 * A browser-reachable URL for an API path.
 *
 * For the URLs the *browser* follows rather than the app fetches: `<img src>`,
 * `window.open`, the one PDF.js is given. Those never pass through `api()`, so
 * they never picked up its base — which is invisible while the app owns the
 * origin and breaks every cover the moment it is served under a path prefix.
 *
 * Always the public base, even during SSR. The server renders the attribute
 * but the browser is what follows it, so `apiInternalBase` — which names a
 * container on the compose network — would be both wrong and unreachable.
 *
 * Paths are given without the `/api` prefix: `/library/books/1/thumbnail`.
 */
export function useApiUrl() {
  const config = useRuntimeConfig()
  return (path: string) => `${config.public.apiBase}${path}`
}

export function useApi() {
  const config = useRuntimeConfig()
  // Captured here, during setup, rather than inside the request function.
  // Nuxt composables need an active instance, and that context is lost after
  // the first `await` in an async handler — so a *second*, sequential request
  // threw "[nuxt] instance unavailable". Parallel calls happened to survive,
  // which is why a page fetching everything at once looked fine while one
  // fetching a detail after a list rendered as empty.
  const incomingHeaders = import.meta.server ? useRequestHeaders(['cookie']) : null

  async function api<T>(path: string, options: ApiOptions = {}): Promise<T> {
    const base = import.meta.server
      ? `${config.apiInternalBase}/api`
      : config.public.apiBase

    const headers: Record<string, string> = {
      ...(options?.headers as Record<string, string> | undefined),
    }

    // Forward the browser's cookies through the SSR request (point 1 above).
    if (import.meta.server && incomingHeaders?.cookie) {
      headers.cookie = incomingHeaders.cookie
    }

    const method = (options?.method ?? 'GET').toString().toUpperCase()
    if (!['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes(method)) {
      const token = readCookie('lumaindex_csrftoken')
      if (token) headers['X-CSRFToken'] = token
    }

    // Cast: adding a server/ route made Nitro generate types for internal
    // paths, so $fetch narrows to TypedInternalResponse and no longer agrees
    // that a generic T is what comes back. Every path here is Django's, which
    // Nitro knows nothing about.
    return await $fetch(path, {
      baseURL: base,
      credentials: 'include',
      ...options,
      headers,
    }) as T
  }

  /** Ask Django to set the CSRF cookie. Call before the first unsafe request. */
  async function ensureCsrf(): Promise<void> {
    if (!import.meta.client) return
    if (readCookie('lumaindex_csrftoken')) return
    await api('/auth/csrf/')
  }

  return { api, ensureCsrf }
}
