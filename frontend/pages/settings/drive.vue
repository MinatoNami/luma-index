<script setup lang="ts">
import type { DriveFolder } from '~/composables/useDrive'

const route = useRoute()
const drive = useDrive()

const { data: status, refresh } = await useAsyncData('drive-status', () => drive.refresh())

const busy = ref(false)
const error = ref('')
const folders = ref<DriveFolder[]>([])
const browsing = ref(false)
const confirmingDisconnect = ref(false)
const deleteLibraryOnDisconnect = ref(false)

// The OAuth callback redirects back here with a result in the query string.
const callbackError = computed(() => (route.query.error as string) || '')
const justConnected = computed(() => route.query.connected === '1')

const CALLBACK_MESSAGES: Record<string, string> = {
  access_denied: 'You cancelled the Google authorization.',
  invalid_state: 'That authorization link expired or did not match this session. Try again.',
  no_refresh_token: 'Google did not return a refresh token. Remove LumaIndex from your '
    + 'Google account permissions and connect again.',
  exchange_failed: 'Google rejected the authorization. Try again.',
  no_identity: 'Google did not return an account identity.',
}

async function run(action: () => Promise<unknown>) {
  busy.value = true
  error.value = ''
  try {
    await action()
    await refresh()
  } catch (err: any) {
    error.value = err?.data?.detail || 'Something went wrong. Try again.'
  } finally {
    busy.value = false
  }
}

async function browse() {
  browsing.value = true
  await run(async () => { folders.value = await drive.listFolders() })
}

const connection = computed(() => status.value?.connection ?? null)
</script>

<template>
  <main class="wrap">
    <header>
      <h1>Google Drive</h1>
      <NuxtLink to="/">Back to library</NuxtLink>
    </header>

    <p v-if="justConnected" class="notice ok" role="status">Google Drive connected.</p>
    <p v-if="callbackError" class="notice bad" role="alert">
      {{ CALLBACK_MESSAGES[callbackError] || `Authorization failed (${callbackError}).` }}
    </p>
    <p v-if="error" class="notice bad" role="alert">{{ error }}</p>

    <!-- Not configured on this instance -->
    <section v-if="!status?.configured" class="panel">
      <h2>Not configured</h2>
      <p>
        This instance has no Google OAuth credentials. Set
        <code>GOOGLE_OAUTH_CLIENT_ID</code> and <code>GOOGLE_OAUTH_CLIENT_SECRET</code>
        in <code>.env</code>, then redeploy.
      </p>
      <p class="muted">
        Read <code>docs/google-oauth.md</code> first — the scope you choose has
        consequences that are awkward to reverse.
      </p>
    </section>

    <!-- Not connected -->
    <section v-else-if="!connection" class="panel">
      <h2>Connect your Drive</h2>
      <p>
        LumaIndex will read PDFs from folders you choose. Your files stay in Drive;
        nothing is moved, renamed, or shared.
      </p>
      <button type="button" :disabled="busy" @click="run(drive.connect)">
        Connect Google Drive
      </button>
    </section>

    <!-- Connected -->
    <template v-else>
      <section class="panel">
        <div class="row">
          <div>
            <h2>{{ connection.provider_email || 'Google Drive' }}</h2>
            <p class="muted">
              <span :class="['badge', connection.status]">{{ connection.status }}</span>
              <span v-if="connection.last_synced_at">
                last synced {{ new Date(connection.last_synced_at).toLocaleString() }}
              </span>
              <span v-else>never synced</span>
            </p>
          </div>
          <button class="secondary" type="button" @click="confirmingDisconnect = true">
            Disconnect
          </button>
        </div>

        <p v-if="connection.needs_reauthorization" class="notice bad">
          Authorization has expired, so syncing has stopped. Your books, reading
          progress, and notes are untouched — reconnect to resume.
          <button type="button" :disabled="busy" @click="run(drive.connect)">Reconnect</button>
        </p>
      </section>

      <section class="panel">
        <div class="row">
          <h2>Folders</h2>
          <button class="secondary" type="button" :disabled="busy" @click="browse">
            Add a folder
          </button>
        </div>

        <p v-if="!connection.roots.length" class="muted">
          No folders selected yet. LumaIndex imports PDFs recursively from the
          folders you add here.
        </p>
        <ul v-else class="roots">
          <li v-for="root in connection.roots" :key="root.id">
            <span>{{ root.name }}</span>
            <button class="link" type="button" :disabled="busy"
                    @click="run(() => drive.removeRoot(root.id))">Remove</button>
          </li>
        </ul>

        <div v-if="browsing" class="picker">
          <h3>Pick a folder</h3>
          <ul>
            <li v-for="folder in folders" :key="folder.id">
              <span>{{ folder.name }}</span>
              <button class="link" type="button" :disabled="busy"
                      @click="run(() => drive.addRoot(folder))">Add</button>
            </li>
            <li v-if="!folders.length" class="muted">No folders found in your Drive root.</li>
          </ul>
          <button class="secondary" type="button" @click="browsing = false">Close</button>
        </div>
      </section>

      <section class="panel">
        <div class="row">
          <h2>Sync</h2>
          <button type="button"
                  :disabled="busy || connection.needs_reauthorization || !connection.roots.length"
                  @click="run(drive.requestSync)">
            Sync now
          </button>
        </div>

        <p v-if="connection.sync_requested_at" class="muted">
          Queued. The sync worker picks this up within a minute.
        </p>

        <dl v-if="connection.latest_sync">
          <dt>Last run</dt>
          <dd>{{ connection.latest_sync.status }}</dd>
          <template v-for="(value, key) in connection.latest_sync.counts" :key="key">
            <dt>{{ key }}</dt>
            <dd>{{ value }}</dd>
          </template>
        </dl>
        <p v-if="connection.latest_sync?.error_summary" class="notice bad">
          {{ connection.latest_sync.error_summary }}
        </p>
      </section>
    </template>

    <!-- Disconnect confirmation -->
    <div v-if="confirmingDisconnect" class="panel confirm">
      <h2>Disconnect Google Drive?</h2>
      <p>Syncing stops. Nothing in your Google Drive is changed.</p>
      <label class="check">
        <input v-model="deleteLibraryOnDisconnect" type="checkbox" />
        Also delete the imported books from LumaIndex
      </label>
      <p class="muted">
        Leave this unchecked to keep your library, reading progress, bookmarks,
        and notes. You can reconnect later and they will still be there.
      </p>
      <div class="row">
        <button class="secondary" type="button" @click="confirmingDisconnect = false">
          Cancel
        </button>
        <button type="button" :disabled="busy"
                @click="run(async () => { await drive.disconnect(deleteLibraryOnDisconnect);
                                          confirmingDisconnect = false })">
          Disconnect
        </button>
      </div>
    </div>
  </main>
</template>

<style scoped>
.wrap { max-width: 46rem; margin: 0 auto; padding: 1.5rem; display: grid; gap: 1rem; }
header { display: flex; align-items: center; justify-content: space-between; }
h1 { font-size: 1.35rem; margin: 0; }
h2 { font-size: 1rem; margin: 0 0 0.5rem; }
h3 { font-size: 0.9rem; margin: 1rem 0 0.5rem; }
.row { display: flex; flex-wrap: wrap; gap: 1rem; align-items: center;
       justify-content: space-between; }
.muted { color: var(--muted); font-size: 0.9rem; }
.notice { border-radius: 8px; padding: 0.75rem 1rem; font-size: 0.9rem; margin: 0; }
.notice.ok { background: color-mix(in srgb, var(--accent) 12%, transparent); }
.notice.bad { background: color-mix(in srgb, var(--danger) 14%, transparent);
              color: var(--danger); }
.badge { text-transform: capitalize; margin-right: 0.5rem; }
.badge.expired, .badge.revoked, .badge.error { color: var(--danger); }
ul { list-style: none; margin: 0; padding: 0; }
.roots li, .picker li { display: flex; justify-content: space-between; align-items: center;
                        padding: 0.5rem 0; border-bottom: 1px solid var(--border); }
.link { background: none; color: var(--accent); padding: 0.25rem 0; min-height: 0; }
.picker { margin-top: 1rem; }
dl { display: grid; grid-template-columns: auto 1fr; gap: 0.3rem 1rem; font-size: 0.9rem;
     margin: 1rem 0 0; }
dt { color: var(--muted); text-transform: capitalize; }
dd { margin: 0; }
.confirm { border-color: var(--danger); }
.check { display: flex; gap: 0.5rem; align-items: center; color: var(--text); margin: 1rem 0; }
code { font-size: 0.85em; background: var(--bg); padding: 0.1em 0.35em; border-radius: 4px; }
</style>
