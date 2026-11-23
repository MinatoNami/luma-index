<script setup lang="ts">
/**
 * The application shell.
 *
 * Before this, five pages each drew their own top bar and a sixth drew none,
 * so where you were and how to leave depended on which page you had reached.
 * The chrome lives here now, once.
 *
 * It moves as well as consolidates: navigation used to sit above the content
 * as a row of chips that wrapped to two lines on a phone, so a 390px screen
 * spent about half its height on controls before the first cover. On a wide
 * screen it is a rail down the side; on a narrow one, a tab bar along the
 * bottom, where a thumb can reach it.
 */
import { isQuickOpen, shortcutLabel } from '~/composables/useQuickOpen'

const route = useRoute()
const { user, logout } = useAuth()
const library = useLibrary()

const quota = ref<{ used: number; limit: number } | null>(null)

onMounted(async () => {
  try {
    const status = await library.storage()
    // 0 means unlimited, which is the default: a meter with no ceiling would
    // be a bar that never moves.
    if (status.quota_bytes > 0) {
      quota.value = { used: status.used_bytes, limit: status.quota_bytes }
    }
  } catch {
    // A missing meter is not worth an error banner over the whole app.
  }
})

const percentUsed = computed(() =>
  quota.value ? Math.min(100, (quota.value.used / quota.value.limit) * 100) : 0)

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1 }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`
}

interface Section {
  label: string
  icon: string
  to: string
  /** Shown in the bottom tab bar as well as the rail. */
  tab?: boolean
  /** The tab bar's label, where the rail's would not fit a sixth of a phone. */
  short?: string
}

const sections: Section[] = [
  { label: 'Reading now', short: 'Reading', icon: 'clock', to: '/', tab: true },
  { label: 'Library', icon: 'folder', to: '/library', tab: true },
  { label: 'Favourites', icon: 'star', to: '/library?view=favourites', tab: true },
  { label: 'Recent', icon: 'inbox', to: '/library?view=recent' },
  { label: 'Unsorted', icon: 'file', to: '/library?view=unsorted' },
  { label: 'Collections', icon: 'collection', to: '/collections', tab: true },
  { label: 'Notebook', icon: 'notebook', to: '/notebook', tab: true },
  { label: 'Shared', icon: 'inbox', to: '/shared' },
  { label: 'Trash', icon: 'trash', to: '/trash' },
]

const tabs = computed(() => [
  ...sections.filter(s => s.tab),
  { label: 'Settings', icon: 'settings', to: '/settings' },
])

/**
 * Quick open, behind ⌘K / Ctrl K on every page that has this shell.
 *
 * The shortcut is taken even from inside a text field — that is where people
 * press it, and no field here has a use of its own for it — but never while
 * another dialog is open, which owns the keyboard until it closes.
 */
const quickOpen = ref(false)
const shortcut = ref('⌘K')

function onShortcut(event: KeyboardEvent) {
  if (!isQuickOpen(event)) return
  if (!quickOpen.value && document.querySelector('[aria-modal="true"]')) return
  event.preventDefault()
  quickOpen.value = !quickOpen.value
}

onMounted(() => {
  shortcut.value = shortcutLabel(navigator.platform || navigator.userAgent)
  window.addEventListener('keydown', onShortcut)
})
onBeforeUnmount(() => window.removeEventListener('keydown', onShortcut))

// Following a result navigates; the dialog should not survive the trip.
watch(() => route.fullPath, () => { quickOpen.value = false })

/**
 * Whether a section is the one being looked at.
 *
 * Path alone is not enough: Library, Favourites and Recent are all "/", told
 * apart by ?view=. Matching on path would light all three at once.
 */
function isCurrent(to: string): boolean {
  const [path, query] = to.split('?')
  if (route.path !== path) return false
  const view = new URLSearchParams(query ?? '').get('view')
  const current = typeof route.query.view === 'string' ? route.query.view : null
  // A collection is its own place, not the plain library listing.
  if (path === '/library' && !view) return !current && !route.query.collection
  return current === view
}
</script>

<template>
  <div class="app">
    <nav class="rail" aria-label="Sections">
      <NuxtLink class="brand" to="/">
        <AppLogo :size="24" />
        <strong>LumaIndex</strong>
      </NuxtLink>

      <button type="button" class="find" @click="quickOpen = true">
        <AppIcon name="search" :size="16" />
        <span>Find</span>
        <kbd aria-hidden="true">{{ shortcut }}</kbd>
        <span class="sr-only">(shortcut {{ shortcut }})</span>
      </button>

      <div class="links">
        <NuxtLink v-for="section in sections" :key="section.to" :to="section.to"
                  :class="['link', { current: isCurrent(section.to) }]"
                  :aria-current="isCurrent(section.to) ? 'page' : undefined">
          <AppIcon :name="section.icon" :size="17" />
          <span>{{ section.label }}</span>
        </NuxtLink>
      </div>

      <div class="foot">
        <div v-if="quota" class="quota">
          <div class="quota-row">
            <span>Storage</span>
            <span>{{ formatBytes(quota.used) }} of {{ formatBytes(quota.limit) }}</span>
          </div>
          <div class="meter">
            <div class="fill" :style="{ width: `${percentUsed}%` }" />
          </div>
        </div>

        <div class="account">
          <ThemeToggle />
          <NuxtLink class="link compact" to="/settings">
            <AppIcon name="settings" :size="17" />
            <span>Settings</span>
          </NuxtLink>
        </div>

        <div class="who">
          <span class="name tertiary">{{ user?.display_name || user?.email }}</span>
          <AppButton variant="ghost" size="sm" icon="sign-out" icon-only
                     title="Sign out" @click="logout" />
        </div>
      </div>
    </nav>

    <div class="content">
      <slot />
    </div>

    <QuickOpen v-if="quickOpen" @close="quickOpen = false" />

    <!-- Narrow screens only: within thumb reach, not stacked above the content. -->
    <nav class="tabs" aria-label="Sections">
      <NuxtLink v-for="tab in tabs" :key="tab.to" :to="tab.to"
                :class="['tab', { current: isCurrent(tab.to) }]"
                :aria-current="isCurrent(tab.to) ? 'page' : undefined">
        <AppIcon :name="tab.icon" :size="21" />
        <span>{{ 'short' in tab && tab.short ? tab.short : tab.label }}</span>
      </NuxtLink>
    </nav>
  </div>
</template>

<style scoped>
/**
 * Everything is held out of the corners here, at every width.
 *
 * These insets used to live on .rail — which is display:none below 60rem, so on
 * a phone nothing carried them at all and the top of every page sat under the
 * Dynamic Island. The reader looked right only because it is layout:false and
 * has its own. viewport-fit=cover means the web view is the whole screen, and
 * the one element that is always there has to be the one that holds the content
 * off the camera.
 *
 * Not padding-bottom: the tab bar takes that, so it can paint its own surface
 * behind the home indicator instead of leaving a strip of --bg under it.
 */
.app {
  min-height: 100dvh;
  display: flex;
  background: var(--bg);
  padding-top: env(safe-area-inset-top);
  padding-left: env(safe-area-inset-left);
  padding-right: env(safe-area-inset-right);
}

/* -- the rail ------------------------------------------------------------- */

.rail {
  width: 232px;
  flex: none;
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border-right: 1px solid var(--border);
}

.brand {
  display: flex; align-items: center; gap: var(--space-2);
  padding: var(--space-5) var(--space-5) var(--space-4);
  color: var(--text); text-decoration: none;
}
.brand strong { font-size: var(--text-md); letter-spacing: -0.01em; }

.links { display: flex; flex-direction: column; gap: 2px; padding: 0 var(--space-3); }

.find {
  display: flex; align-items: center; gap: var(--space-2);
  margin: 0 var(--space-3) var(--space-3);
  min-height: 36px; padding: 0 var(--space-2) 0 var(--space-3);
  background: var(--bg); color: var(--text-tertiary);
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  font-size: var(--text-base); text-align: left; cursor: pointer;
}
.find:hover { color: var(--text-secondary); border-color: var(--border-strong); }
.find span:not(.sr-only) { flex: 1; }
.find kbd {
  padding: 1px var(--space-1);
  border: 1px solid var(--border); border-radius: 4px;
  background: var(--surface); font-family: var(--font-sans); font-size: 0.6875rem;
}

.link {
  display: flex; align-items: center; gap: var(--space-2);
  min-height: 36px; padding: 0 var(--space-3);
  border-radius: var(--radius-sm);
  color: var(--text-secondary); text-decoration: none;
  font-size: var(--text-base);
}
.link:hover { background: var(--surface-hover); color: var(--text); }
.link.current {
  background: var(--accent-soft); color: var(--accent-text); font-weight: 500;
}

.foot { margin-top: auto; padding: var(--space-4) var(--space-3) var(--space-5); }

.quota { padding: 0 var(--space-3) var(--space-4); }
.quota-row {
  display: flex; justify-content: space-between; gap: var(--space-2);
  font-size: var(--text-xs); color: var(--text-tertiary);
  margin-bottom: var(--space-2);
}
.meter {
  height: 4px; border-radius: var(--radius-full);
  background: var(--surface-sunken); overflow: hidden;
}
.fill { height: 100%; background: var(--accent); border-radius: var(--radius-full); }

.account { display: flex; align-items: center; gap: var(--space-1); }
.account .compact { flex: 1; }

.who {
  display: flex; align-items: center; gap: var(--space-2);
  margin-top: var(--space-2); padding: 0 var(--space-3);
}
.name {
  flex: 1; min-width: 0;
  font-size: var(--text-xs);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

.content { flex: 1; min-width: 0; display: flex; flex-direction: column; }

/* -- the tab bar ---------------------------------------------------------- */

.tabs { display: none; }

@media (max-width: 60rem) {
  .app { flex-direction: column; }

  .rail { display: none; }

  .tabs {
    position: sticky; bottom: 0; z-index: 20;
    display: grid; grid-auto-flow: column; grid-auto-columns: 1fr;
    background: var(--surface);
    border-top: 1px solid var(--border);
    /* The home indicator sits below this on a modern phone. */
    padding-bottom: env(safe-area-inset-bottom);
  }

  .tab {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: var(--space-1);
    /* Comfortably past the 44px this has to be hit with a thumb. */
    min-height: 52px;
    color: var(--text-tertiary); text-decoration: none;
    font-size: var(--text-xs);
    /* Six tabs since the notebook joined: about 62px each on a 375px phone,
       so a label may not wrap or push its neighbour. */
    min-width: 0;
  }
  .tab span {
    max-width: 100%; padding: 0 1px;
    font-size: 0.6875rem; letter-spacing: -0.01em;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .tab.current { color: var(--accent-text); font-weight: 500; }
}

@media (prefers-reduced-motion: reduce) {
  .fill { transition: none; }
}
</style>
