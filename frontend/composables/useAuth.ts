export interface SessionUser {
  id: number
  email: string
  display_name: string
  role: 'user' | 'admin'
  is_staff: boolean
  created_at: string
}

/**
 * Current user, shared across components via useState so SSR and client agree.
 *
 * Note this is presentation state only. Hiding a route here is a convenience,
 * never a control — PRD §29 requires Django to authorize every request on the
 * server, and it does.
 */
export function useAuth() {
  const user = useState<SessionUser | null>('auth:user', () => null)
  const { api, ensureCsrf } = useApi()

  async function refresh(): Promise<SessionUser | null> {
    try {
      // 204 (anonymous) deserializes to null, which is exactly what we want.
      user.value = (await api<SessionUser | null>('/auth/session/')) || null
    } catch {
      user.value = null
    }
    return user.value
  }

  async function login(email: string, password: string): Promise<SessionUser> {
    await ensureCsrf()
    const signedIn = await api<SessionUser>('/auth/login/', {
      method: 'POST',
      body: { email, password },
    })
    user.value = signedIn
    return signedIn
  }

  async function logout(): Promise<void> {
    await ensureCsrf()
    try {
      await api('/auth/logout/', { method: 'POST' })
    } finally {
      user.value = null
      await navigateTo('/login')
    }
  }

  return {
    user,
    isAuthenticated: computed(() => user.value !== null),
    refresh,
    login,
    logout,
  }
}
