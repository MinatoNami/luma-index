<script setup lang="ts">
import type { Collection } from '~/composables/useCollections'

const collections = useCollections()
const { logout } = useAuth()

const { data: list, refresh } = await useAsyncData('collections',
  () => collections.list().catch(() => [] as Collection[]))

const busy = ref(false)
const error = ref('')
const dialog = ref<{ title: string; label?: string; value?: string; confirmLabel?: string
                     danger?: boolean; message?: string
                     run: (value: string) => Promise<void> } | null>(null)

async function act(work: () => Promise<unknown>) {
  busy.value = true
  error.value = ''
  try {
    await work()
    await refresh()
  } catch (err: any) {
    error.value = err?.data?.detail || 'That did not work.'
  } finally {
    busy.value = false
    dialog.value = null
  }
}

function createCollection() {
  dialog.value = {
    title: 'New collection', label: 'Name', value: '', confirmLabel: 'Create',
    run: async name => { await collections.create(name) },
  }
}

function renameCollection(collection: Collection) {
  dialog.value = {
    title: 'Rename collection', label: 'Name', value: collection.name,
    confirmLabel: 'Rename',
    run: async name => { await collections.rename(collection.id, name) },
  }
}

function deleteCollection(collection: Collection) {
  dialog.value = {
    title: `Delete “${collection.name}”?`,
    message: collection.book_count
      ? `The ${collection.book_count} book(s) in it stay in your library — only the grouping goes.`
      : 'Only the grouping goes; nothing is removed from your library.',
    confirmLabel: 'Delete', danger: true,
    run: async () => { await collections.remove(collection.id) },
  }
}
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand"><AppLogo :size="24" /><strong>LumaIndex</strong></div>
      <div class="account">
        <NuxtLink class="quiet-link" to="/">My library</NuxtLink>
        <AppButton variant="ghost" size="sm" @click="logout">Sign out</AppButton>
      </div>
    </header>

    <main class="wrap">
      <div class="head">
        <div>
          <h1>Collections</h1>
          <p class="muted">
            A book can be in as many as you like. Collections group books without
            moving the files — a book stays in whatever folder it lives in.
          </p>
        </div>
        <AppButton variant="primary" icon="collection" :disabled="busy"
                   @click="createCollection">New collection</AppButton>
      </div>

      <p v-if="error" class="notice notice-error" role="alert">
        <AppIcon name="warning" :size="17" /> {{ error }}
      </p>

      <div v-if="list?.length" class="listing panel">
        <div v-for="collection in list" :key="collection.id" class="row">
          <NuxtLink class="name" :to="`/?collection=${collection.id}`">
            <span class="chip"><AppIcon name="collection" :size="16" /></span>
            <span class="label">{{ collection.path }}</span>
          </NuxtLink>
          <span class="tertiary count">
            {{ collection.book_count }} book{{ collection.book_count === 1 ? '' : 's' }}
          </span>
          <RowMenu :label="`Actions for ${collection.name}`" :actions="[
            { label: 'Rename', icon: 'pencil', run: () => renameCollection(collection) },
            { label: 'Delete', icon: 'trash', danger: true,
              run: () => deleteCollection(collection) },
          ]" />
        </div>
      </div>

      <EmptyState v-else icon="collection" title="No collections yet"
                  description="Group books by whatever matters to you — a subject, a reading list, a course — without moving them out of their folders.">
        <AppButton variant="primary" @click="createCollection">New collection</AppButton>
      </EmptyState>
    </main>

    <PromptDialog v-if="dialog" :title="dialog.title" :label="dialog.label"
                  :model-value="dialog.value" :confirm-label="dialog.confirmLabel"
                  :danger="dialog.danger" :message="dialog.message" :busy="busy"
                  @cancel="dialog = null"
                  @confirm="value => act(() => dialog!.run(value))" />
  </div>
</template>

<style scoped>
.shell { min-height: 100dvh; }
.topbar { display: flex; align-items: center; justify-content: space-between;
          /* max(), not the bare space: the viewport is declared viewport-fit=cover, so
     on a notched phone — and in particular once this is on the Home Screen and
     runs without Safari's chrome — the bar is drawn under the status bar.
     Written here rather than in main.css because a scoped rule carries an
     attribute selector and outranks a global `.topbar`, and this shorthand
     would reset padding-top even if it did not. */
  padding: max(var(--space-3), env(safe-area-inset-top))
           max(var(--space-5), env(safe-area-inset-right))
           var(--space-3)
           max(var(--space-5), env(safe-area-inset-left));
          background: var(--surface); border-bottom: 1px solid var(--border); }
.brand { display: flex; align-items: center; gap: var(--space-3); font-size: var(--text-md); }
.account { display: flex; align-items: center; gap: var(--space-3); }
.quiet-link { color: var(--text-secondary); text-decoration: none; }
.quiet-link:hover { color: var(--text); }
.wrap { max-width: 56rem; margin: 0 auto; padding: var(--space-5);
        display: grid; gap: var(--space-4); align-content: start; }
.head { display: flex; flex-wrap: wrap; gap: var(--space-4);
        align-items: flex-start; justify-content: space-between; }
h1 { font-size: var(--text-xl); margin: 0; }
.muted { color: var(--text-secondary); margin: var(--space-1) 0 0; max-width: 40rem; }
.listing { overflow: hidden; }
.row { display: grid; grid-template-columns: minmax(0, 1fr) auto 40px;
       align-items: center; gap: var(--space-3);
       padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--border); }
.row:last-child { border-bottom: 0; }
.row:hover { background: var(--surface-hover); }
.name { display: flex; align-items: center; gap: var(--space-3); min-width: 0;
        color: var(--text); text-decoration: none; }
.name:hover .label { color: var(--accent-text); }
.chip { display: grid; place-items: center; width: 28px; height: 28px; flex: none;
        border-radius: var(--radius-sm); background: var(--accent-soft);
        color: var(--accent-text); }
.label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.count { font-size: var(--text-sm); white-space: nowrap; }
</style>
