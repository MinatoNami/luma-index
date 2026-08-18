export interface DriveRoot {
  id: number
  provider_folder_id: string
  name: string
  original_path: string
  sync_enabled: boolean
  last_synced_at: string | null
}

export interface SyncRun {
  id: number
  status: 'running' | 'ok' | 'partial' | 'failed'
  started_at: string
  finished_at: string | null
  counts: Record<string, number>
  error_summary: string
}

export interface DriveConnection {
  id: number
  provider_email: string
  status: 'active' | 'expired' | 'revoked' | 'error'
  status_detail: string
  needs_reauthorization: boolean
  last_synced_at: string | null
  sync_requested_at: string | null
  roots: DriveRoot[]
  latest_sync: SyncRun | null
}

export interface DriveStatus {
  configured: boolean
  connection: DriveConnection | null
}

export interface DriveFolder {
  id: string
  name: string
}

export function useDrive() {
  const { api, ensureCsrf } = useApi()

  const status = useState<DriveStatus | null>('drive:status', () => null)

  async function refresh() {
    status.value = await api<DriveStatus>('/drive/status/')
    return status.value
  }

  async function connect() {
    await ensureCsrf()
    const { authorization_url } = await api<{ authorization_url: string }>(
      '/drive/connect/', { method: 'POST' },
    )
    // Full navigation, not a popup: Google's consent screen refuses to render
    // in a frame, and a popup would be blocked as often as not.
    window.location.href = authorization_url
  }

  async function disconnect(deleteLibrary: boolean) {
    await ensureCsrf()
    await api('/drive/disconnect/', {
      method: 'POST',
      body: { delete_library: deleteLibrary },
    })
    await refresh()
  }

  async function listFolders(parent?: string) {
    return await api<DriveFolder[]>('/drive/folders/', {
      params: parent ? { parent } : undefined,
    })
  }

  async function addRoot(folder: DriveFolder) {
    await ensureCsrf()
    await api('/drive/roots/', {
      method: 'POST',
      body: { provider_folder_id: folder.id, name: folder.name },
    })
    await refresh()
  }

  async function removeRoot(id: number) {
    await ensureCsrf()
    await api(`/drive/roots/${id}/`, { method: 'DELETE' })
    await refresh()
  }

  async function requestSync() {
    await ensureCsrf()
    await api('/drive/sync/', { method: 'POST' })
    await refresh()
  }

  async function syncHistory() {
    return await api<{ runs: SyncRun[] }>('/drive/sync/')
  }

  return {
    status,
    refresh,
    connect,
    disconnect,
    listFolders,
    addRoot,
    removeRoot,
    requestSync,
    syncHistory,
  }
}
