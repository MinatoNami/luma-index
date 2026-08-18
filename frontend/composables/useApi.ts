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

function readCookie(name: string): string | null {
  if (!import.meta.client) return null
  const match = document.cookie.match(new RegExp(`(^|;\\s*)${name}=([^;]*)`))
  return match ? decodeURIComponent(match[2]) : null
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

    return await $fetch<T>(path, {
      baseURL: base,
      credentials: 'include',
      ...options,
      headers,
    })
  }

  /** Ask Django to set the CSRF cookie. Call before the first unsafe request. */
  async function ensureCsrf(): Promise<void> {
    if (!import.meta.client) return
    if (readCookie('lumaindex_csrftoken')) return
    await api('/auth/csrf/')
  }

  return { api, ensureCsrf }
}
