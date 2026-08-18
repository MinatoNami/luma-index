const PUBLIC_EXACT = new Set(['/login', '/forgot-password'])
const PUBLIC_PREFIXES = ['/reset/']

function isPublic(path: string): boolean {
  return PUBLIC_EXACT.has(path) || PUBLIC_PREFIXES.some(prefix => path.startsWith(prefix))
}

export default defineNuxtRouteMiddleware(async (to) => {
  const { user, refresh } = useAuth()

  // Resolve the session once per navigation cycle rather than per route.
  if (user.value === null) await refresh()

  if (!user.value && !isPublic(to.path)) {
    return navigateTo({ path: '/login', query: { next: to.fullPath } })
  }
  // A signed-in user landing on /login goes home, but a reset link must still
  // work — following one is how you recover an account you are already using.
  if (user.value && PUBLIC_EXACT.has(to.path)) {
    return navigateTo('/')
  }

  // Preferences live on the account (PRD §24) and are fetched here so app.vue
  // can stamp the theme into the server-rendered HTML. Applying it only after
  // hydration would flash a white screen at a dark-mode reader on every load.
  if (user.value) {
    const { settings, loadSettings } = useSettings()
    if (settings.value === null) {
      try {
        await loadSettings()
      } catch {
        // Never block navigation on a preference fetch.
      }
    }
    if (settings.value && import.meta.client) {
      // Seed the library's view state from the saved default.
      useState<string>('library-view').value = settings.value.library_view
      localStorage.setItem('lumaindex-view', settings.value.library_view)
    }
  }
})
