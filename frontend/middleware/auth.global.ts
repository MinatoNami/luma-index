const PUBLIC_ROUTES = new Set(['/login'])

export default defineNuxtRouteMiddleware(async (to) => {
  const { user, refresh } = useAuth()

  // Resolve the session once per navigation cycle rather than per route.
  if (user.value === null) await refresh()

  if (!user.value && !PUBLIC_ROUTES.has(to.path)) {
    return navigateTo({ path: '/login', query: { next: to.fullPath } })
  }
  if (user.value && to.path === '/login') {
    return navigateTo('/')
  }
})
