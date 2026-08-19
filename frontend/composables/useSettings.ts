export interface Profile {
  id: number
  email: string
  display_name: string
  role: 'user' | 'admin'
  is_staff: boolean
  created_at: string
}

export type Theme = 'system' | 'light' | 'dark'
export type LibraryView = 'list' | 'grid' | 'large'

export interface UserSettings {
  theme: Theme
  library_view: LibraryView
  reader_mode: 'continuous' | 'single'
  reader_zoom: string
  sidebar_open: boolean
}

export function useSettings() {
  const { api, ensureCsrf } = useApi()

  const settings = useState<UserSettings | null>('user-settings', () => null)

  async function loadProfile() {
    return await api<Profile>('/auth/profile/')
  }

  async function saveProfile(changes: Partial<Pick<Profile, 'display_name'>>) {
    await ensureCsrf()
    return await api<Profile>('/auth/profile/', { method: 'PATCH', body: changes })
  }

  async function loadSettings() {
    settings.value = await api<UserSettings>('/auth/settings/')
    return settings.value
  }

  async function saveSettings(changes: Partial<UserSettings>) {
    await ensureCsrf()
    settings.value = await api<UserSettings>('/auth/settings/', {
      method: 'PATCH',
      body: changes,
    })
    return settings.value
  }

  async function changePassword(currentPassword: string, newPassword: string) {
    await ensureCsrf()
    await api('/auth/password/change/', {
      method: 'POST',
      body: { current_password: currentPassword, new_password: newPassword },
    })
  }

  async function deleteAccount(password: string, confirm: string) {
    await ensureCsrf()
    await api('/auth/account/delete/', { method: 'POST', body: { password, confirm } })
  }

  async function storage() {
    return await api<{
      free_bytes: number
      max_upload_bytes: number
      min_free_disk_bytes: number
      book_count: number
      /** This account's allowance in bytes. 0 means unlimited. */
      quota_bytes: number
      used_bytes: number
    }>('/library/storage/')
  }

  return {
    settings, loadProfile, saveProfile, loadSettings, saveSettings,
    changePassword, deleteAccount, storage,
  }
}

/** Apply a stored theme to the document. Shared by the toggle and the page. */
export function applyTheme(value: Theme) {
  if (!import.meta.client) return
  const root = document.documentElement
  if (value === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', value)
}
