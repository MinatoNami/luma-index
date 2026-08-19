<script setup lang="ts">
import { formatBytes } from '~/composables/useLibrary'
import { applyTheme, type LibraryView, type Profile, type Theme } from '~/composables/useSettings'

const account = useSettings()
const { user, refresh: refreshSession, logout } = useAuth()

const profile = ref<Profile | null>(null)
const displayName = ref('')
const theme = ref<Theme>('system')
const libraryView = ref<LibraryView>('list')
const usage = ref<{
  free_bytes: number; max_upload_bytes: number; book_count: number
  quota_bytes: number; used_bytes: number
} | null>(null)

// 0 is the API's way of saying "no limit", which is a different thing from a
// limit of nothing — so a bar is only meaningful when there is one.
const quota = computed(() => {
  const u = usage.value
  if (!u || !u.quota_bytes) return null
  const fraction = Math.min(1, u.used_bytes / u.quota_bytes)
  return {
    used: u.used_bytes,
    limit: u.quota_bytes,
    percent: Math.round(fraction * 100),
    // Rounding hides the two states that matter most, so they are decided on
    // the real numbers: 99.6% must not render as a full bar, and being over
    // must not render as merely nearly full.
    full: u.used_bytes >= u.quota_bytes,
    nearly: fraction >= 0.9 && u.used_bytes < u.quota_bytes,
  }
})

const saving = ref('')
const errors = ref<Record<string, string>>({})
const saved = ref<Record<string, boolean>>({})

// Password
const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')

// Deletion
const deleting = ref(false)
const deletePassword = ref('')
const deleteConfirm = ref('')

const THEMES: { value: Theme; label: string }[] = [
  { value: 'system', label: 'Follow my system' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
]
const VIEWS: { value: LibraryView; label: string }[] = [
  { value: 'list', label: 'List' },
  { value: 'grid', label: 'Grid' },
  { value: 'large', label: 'Large icons' },
]

onMounted(async () => {
  const [p, s, u] = await Promise.all([
    account.loadProfile(),
    account.loadSettings(),
    account.storage().catch(() => null),
  ])
  profile.value = p
  displayName.value = p.display_name
  theme.value = s!.theme
  libraryView.value = s!.library_view
  usage.value = u
})

function flash(key: string) {
  saved.value = { ...saved.value, [key]: true }
  setTimeout(() => { saved.value = { ...saved.value, [key]: false } }, 2200)
}

async function run(key: string, work: () => Promise<unknown>) {
  saving.value = key
  errors.value = { ...errors.value, [key]: '' }
  try {
    await work()
    flash(key)
  } catch (err: any) {
    const data = err?.data
    const first = data && typeof data === 'object'
      ? Object.values(data).flat()[0] as string
      : null
    errors.value = { ...errors.value, [key]: first || 'That did not work.' }
  } finally {
    saving.value = ''
  }
}

const saveName = () => run('profile', async () => {
  profile.value = await account.saveProfile({ display_name: displayName.value })
  await refreshSession()
})

// Applied immediately as well as saved: a preference that needs a reload to
// take effect does not feel like a preference.
const saveAppearance = () => run('appearance', async () => {
  await account.saveSettings({ theme: theme.value, library_view: libraryView.value })
  applyTheme(theme.value)
  localStorage.setItem('lumaindex-view', libraryView.value)
})

const savePassword = () => run('password', async () => {
  if (newPassword.value !== confirmPassword.value) {
    throw { data: { detail: 'The two new passwords do not match.' } }
  }
  await account.changePassword(currentPassword.value, newPassword.value)
  currentPassword.value = newPassword.value = confirmPassword.value = ''
})

const removeAccount = () => run('delete', async () => {
  await account.deleteAccount(deletePassword.value, deleteConfirm.value)
  await navigateTo('/login')
})
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand"><AppLogo :size="24" /><strong>LumaIndex</strong></div>
      <div class="account">
        <NuxtLink class="quiet-link" to="/">Back to library</NuxtLink>
        <AppButton variant="ghost" size="sm" @click="logout">Sign out</AppButton>
      </div>
    </header>

    <main class="wrap">
      <h1>Settings</h1>

      <!-- Profile -->
      <section class="panel card">
        <div class="card-head">
          <h2>Profile</h2>
          <p class="muted">How you appear in LumaIndex.</p>
        </div>
        <div class="card-body">
          <div class="field">
            <label for="display-name">Display name</label>
            <input id="display-name" v-model="displayName" type="text" maxlength="150"
                   placeholder="Your name" />
          </div>
          <div class="field">
            <label for="email">Email</label>
            <input id="email" :value="profile?.email" type="email" disabled />
            <p class="hint">
              Your sign-in address. Changing it needs verification of the new
              address, which isn't built yet.
            </p>
          </div>
          <dl class="facts">
            <dt>Role</dt><dd>{{ profile?.role === 'admin' ? 'Admin' : 'User' }}</dd>
            <dt>Member since</dt>
            <dd>{{ profile ? new Date(profile.created_at).toLocaleDateString() : '—' }}</dd>
          </dl>
        </div>
        <footer class="card-foot">
          <p v-if="errors.profile" class="inline-error">{{ errors.profile }}</p>
          <p v-else-if="saved.profile" class="inline-ok">
            <AppIcon name="check" :size="15" /> Saved
          </p>
          <span v-else />
          <AppButton variant="primary" :loading="saving === 'profile'" @click="saveName">
            Save profile
          </AppButton>
        </footer>
      </section>

      <!-- Appearance -->
      <section class="panel card">
        <div class="card-head">
          <h2>Appearance</h2>
          <p class="muted">Saved to your account, so it follows you between devices.</p>
        </div>
        <div class="card-body">
          <div class="field">
            <label for="theme">Theme</label>
            <select id="theme" v-model="theme">
              <option v-for="option in THEMES" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
          </div>
          <div class="field">
            <label for="view">Default library view</label>
            <select id="view" v-model="libraryView">
              <option v-for="option in VIEWS" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
          </div>
        </div>
        <footer class="card-foot">
          <p v-if="errors.appearance" class="inline-error">{{ errors.appearance }}</p>
          <p v-else-if="saved.appearance" class="inline-ok">
            <AppIcon name="check" :size="15" /> Saved
          </p>
          <span v-else />
          <AppButton variant="primary" :loading="saving === 'appearance'"
                     @click="saveAppearance">Save appearance</AppButton>
        </footer>
      </section>

      <!-- Password -->
      <section class="panel card">
        <div class="card-head">
          <h2>Password</h2>
          <p class="muted">
            Changing it signs you out on every other device. At least 12 characters.
          </p>
        </div>
        <form class="card-body" @submit.prevent="savePassword">
          <div class="field">
            <label for="current">Current password</label>
            <input id="current" v-model="currentPassword" type="password"
                   autocomplete="current-password" required />
          </div>
          <div class="field">
            <label for="new">New password</label>
            <input id="new" v-model="newPassword" type="password"
                   autocomplete="new-password" required minlength="12" />
          </div>
          <div class="field">
            <label for="confirm">Confirm new password</label>
            <input id="confirm" v-model="confirmPassword" type="password"
                   autocomplete="new-password" required minlength="12" />
          </div>
          <footer class="card-foot inset">
            <p v-if="errors.password" class="inline-error">{{ errors.password }}</p>
            <p v-else-if="saved.password" class="inline-ok">
              <AppIcon name="check" :size="15" /> Password changed
            </p>
            <span v-else />
            <AppButton variant="primary" type="submit" :loading="saving === 'password'">
              Change password
            </AppButton>
          </footer>
        </form>
      </section>

      <!-- Storage -->
      <section v-if="usage" class="panel card">
        <div class="card-head">
          <h2>Storage</h2>
          <p class="muted">Uploaded files live on this server.</p>
        </div>
        <div class="card-body">
          <div v-if="quota" class="quota">
            <div class="quota-head">
              <strong>{{ formatBytes(quota.used) }} of {{ formatBytes(quota.limit) }}</strong>
              <span class="tertiary">{{ quota.percent }}%</span>
            </div>
            <div class="meter" role="progressbar" :aria-valuenow="quota.percent"
                 aria-valuemin="0" aria-valuemax="100"
                 :aria-label="`Storage used: ${quota.percent} per cent`">
              <span class="fill" :class="{ nearly: quota.nearly, full: quota.full }"
                    :style="{ width: `${Math.max(quota.percent, 2)}%` }" />
            </div>
            <p v-if="quota.full" class="inline-error">
              You are at your limit. Delete something, or empty your trash, to upload again.
            </p>
            <p v-else class="muted">
              Books in your trash still count. Files stored more than once count once.
            </p>
          </div>
          <dl class="facts">
            <dt>Books</dt><dd>{{ usage.book_count }}</dd>
            <dt v-if="!quota">Library size</dt><dd v-if="!quota">{{ formatBytes(usage.used_bytes) }}</dd>
            <dt>Disk free</dt><dd>{{ formatBytes(usage.free_bytes) }}</dd>
            <dt>Largest upload</dt><dd>{{ formatBytes(usage.max_upload_bytes) }}</dd>
          </dl>
        </div>
      </section>

      <!-- Danger zone -->
      <section class="panel card danger-card">
        <div class="card-head">
          <h2>Delete account</h2>
          <p class="muted">
            Removes your account, every folder and book, and the uploaded files
            themselves. If a PDF exists only here, it is gone. This cannot be
            undone and does not go through the trash.
          </p>
        </div>
        <div class="card-body">
          <AppButton v-if="!deleting" variant="danger" icon="trash" @click="deleting = true">
            Delete my account
          </AppButton>
          <template v-else>
            <div class="field">
              <label for="del-password">Your password</label>
              <input id="del-password" v-model="deletePassword" type="password"
                     autocomplete="current-password" />
            </div>
            <div class="field">
              <label for="del-confirm">Type <code>delete</code> to confirm</label>
              <input id="del-confirm" v-model="deleteConfirm" type="text"
                     autocomplete="off" spellcheck="false" />
            </div>
            <p v-if="errors.delete" class="inline-error">{{ errors.delete }}</p>
            <div class="row-actions">
              <AppButton variant="ghost" @click="deleting = false; deletePassword = ''; deleteConfirm = ''">
                Cancel
              </AppButton>
              <AppButton variant="danger" :loading="saving === 'delete'"
                         :disabled="!deletePassword || deleteConfirm.trim().toLowerCase() !== 'delete'"
                         @click="removeAccount">
                Permanently delete
              </AppButton>
            </div>
          </template>
        </div>
      </section>
    </main>
  </div>
</template>

<style scoped>
.shell { min-height: 100dvh; }
.topbar {
  display: flex; align-items: center; justify-content: space-between; gap: var(--space-4);
  padding: var(--space-3) var(--space-5);
  background: var(--surface); border-bottom: 1px solid var(--border);
}
.brand { display: flex; align-items: center; gap: var(--space-3); font-size: var(--text-md); }
.account { display: flex; align-items: center; gap: var(--space-3); }
.quiet-link { color: var(--text-secondary); text-decoration: none; }
.quiet-link:hover { color: var(--text); }

.wrap { max-width: 44rem; margin: 0 auto; padding: var(--space-5);
        display: grid; gap: var(--space-4); align-content: start; }
h1 { font-size: var(--text-xl); margin: 0 0 var(--space-1); }

.card { overflow: hidden; }
.card-head { padding: var(--space-4) var(--space-5) 0; }
.card-head h2 { margin: 0; font-size: var(--text-md); font-weight: 600; }
.card-head p { margin: var(--space-1) 0 0; font-size: var(--text-sm); }
.card-body { padding: var(--space-4) var(--space-5); display: grid; gap: var(--space-4); }
.card-foot {
  display: flex; align-items: center; justify-content: space-between; gap: var(--space-3);
  padding: var(--space-3) var(--space-5);
  background: var(--surface-sunken); border-top: 1px solid var(--border);
}
.card-foot.inset { margin: 0 calc(var(--space-5) * -1) calc(var(--space-4) * -1);
                   padding-inline: var(--space-5); }

.field { display: grid; }
.hint { margin: var(--space-2) 0 0; font-size: var(--text-xs); color: var(--text-tertiary); }
input:disabled { background: var(--surface-sunken); color: var(--text-tertiary);
                 cursor: not-allowed; }

select {
  min-height: var(--tap-target); padding: 0 var(--space-3);
  background: var(--surface); color: var(--text);
  border: 1px solid var(--border-strong); border-radius: var(--radius-sm);
}
select:focus-visible { outline: none; border-color: var(--focus); box-shadow: var(--shadow-focus); }

.facts { display: grid; grid-template-columns: auto 1fr; gap: var(--space-2) var(--space-5);
         margin: 0; font-size: var(--text-base); }
.facts dt { color: var(--text-secondary); }
.facts dd { margin: 0; }

.inline-error { margin: 0; color: var(--danger-text); font-size: var(--text-sm); }
.inline-ok { margin: 0; display: flex; align-items: center; gap: var(--space-2);
             color: var(--success); font-size: var(--text-sm); }

.danger-card { border-color: color-mix(in srgb, var(--danger) 40%, var(--border)); }
.row-actions { display: flex; gap: var(--space-2); justify-content: flex-end; }
code { font-family: var(--font-mono); font-size: 0.9em; padding: 1px 5px;
       background: var(--surface-sunken); border-radius: 4px; }

/* -- storage quota ------------------------------------------------------- */
.quota { display: grid; gap: var(--space-2); margin-bottom: var(--space-4); }
.quota-head { display: flex; justify-content: space-between; align-items: baseline; }

.meter {
  height: 8px; border-radius: var(--radius-full);
  background: var(--surface-sunken); overflow: hidden;
}
.fill {
  display: block; height: 100%;
  background: var(--accent); border-radius: var(--radius-full);
  transition: width var(--duration) var(--ease);
}
.fill.nearly { background: var(--warning); }
.fill.full { background: var(--danger); }

@media (prefers-reduced-motion: reduce) { .fill { transition: none; } }
</style>