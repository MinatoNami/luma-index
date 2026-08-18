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
})
