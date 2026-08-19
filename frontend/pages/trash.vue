<script setup lang="ts">
import type { Book, Folder } from '~/composables/useLibrary'
import type { SortKey } from '~/components/SortMenu.vue'

const library = useLibrary()

const folders = ref<Folder[]>([])
const books = ref<Book[]>([])
const retentionDays = ref<number | null>(null)

// Most recently deleted first: what you came to the trash for is almost always
// the thing you just deleted by mistake.
const sortKey = ref<SortKey>('trashed')
const sortDesc = ref(true)

const apiSort = computed(() => {
  if (sortKey.value === 'type') return 'name'
  return sortDesc.value ? `-${sortKey.value}` : sortKey.value
})
const filesFirst = computed(() => sortKey.value === 'type' && sortDesc.value)
const busy = ref(false)
const error = ref('')
const confirming = ref<{ kind: 'folder' | 'book'; id: number; name: string } | null>(null)

async function load() {
  busy.value = true
  try {
    const trash = await library.listTrash({ sort: apiSort.value })
    folders.value = trash.folders
    books.value = trash.books
    retentionDays.value = trash.retention_days
  } finally {
    busy.value = false
  }
}
onMounted(load)
watch(apiSort, () => load())

/** "in 12 days", or "today" once it is close enough not to bother counting. */
/** Where it was, without repeating the name that is already the label. */
function parentOf(path: string): string {
  const cut = path.lastIndexOf('/')
  return cut === -1 ? '' : path.slice(0, cut)
}

function countdown(iso: string | null): string {
  if (!iso) return ''
  const days = Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000)
  if (days <= 0) return 'due to be deleted'
  if (days === 1) return 'deleted tomorrow'
  return `deleted in ${days} days`
}

async function act(work: () => Promise<unknown>) {
  busy.value = true
  error.value = ''
  try {
    await work()
    await load()
  } catch (err: any) {
    error.value = err?.data?.detail || 'That did not work.'
  } finally {
    busy.value = false
    confirming.value = null
  }
}

const isEmpty = computed(() => !busy.value && !folders.value.length && !books.value.length)
</script>

<template>
  <main class="wrap">
    <header>
      <h1>Trash</h1>
      <NuxtLink class="quiet-link" to="/">Back to library</NuxtLink>
    </header>

    <p v-if="error" class="notice notice-error" role="alert">
      <AppIcon name="warning" :size="17" /> {{ error }}
    </p>

    <p v-if="!isEmpty" class="muted">
      Restoring a folder brings back everything that was trashed with it.
      Deleting permanently cannot be undone.
      <template v-if="retentionDays">
        Anything left here is deleted automatically {{ retentionDays }} days after
        it was trashed.
      </template>
      Items in the trash still count towards your storage.
    </p>

    <div v-if="!isEmpty" class="toolbar">
      <SortMenu v-model="sortKey" v-model:descending="sortDesc" allow-trashed />
    </div>

    <div v-if="!isEmpty" class="listing panel">
      <div v-for="folder in folders" :key="`f${folder.id}`" class="row"
           :style="{ order: filesFirst ? 2 : 1 }">
        <span class="chip"><AppIcon name="folder" :size="16" /></span>
        <span class="named">
          <span class="label">{{ folder.name }}</span>
          <span v-if="parentOf(folder.path)" class="where tertiary">
            {{ parentOf(folder.path) }}
          </span>
        </span>
        <span v-if="folder.expires_at" class="expiry tertiary">
          {{ countdown(folder.expires_at) }}
        </span>
        <div class="actions">
          <AppButton size="sm" icon="restore" :disabled="busy"
                     @click="act(() => library.restoreFolder(folder.id))">Restore</AppButton>
          <AppButton size="sm" variant="ghost" :disabled="busy" class="danger-link"
                     @click="confirming = { kind: 'folder', id: folder.id, name: folder.name }">
            Delete forever
          </AppButton>
        </div>
      </div>
      <div v-for="book in books" :key="`b${book.id}`" class="row"
           :style="{ order: filesFirst ? 1 : 2 }">
        <span class="chip"><AppIcon name="file" :size="16" /></span>
        <span class="named">
          <span class="label">{{ book.title }}</span>
          <span v-if="parentOf(book.path)" class="where tertiary">
            {{ parentOf(book.path) }}
          </span>
        </span>
        <span v-if="book.expires_at" class="expiry tertiary">
          {{ countdown(book.expires_at) }}
        </span>
        <div class="actions">
          <AppButton size="sm" icon="restore" :disabled="busy"
                     @click="act(() => library.restoreBook(book.id))">Restore</AppButton>
          <AppButton size="sm" variant="ghost" :disabled="busy" class="danger-link"
                     @click="confirming = { kind: 'book', id: book.id, name: book.title }">
            Delete forever
          </AppButton>
        </div>
      </div>
    </div>

    <EmptyState v-if="isEmpty" icon="trash" title="The trash is empty"
                description="Anything you delete lands here first, so nothing goes missing by accident." />

    <PromptDialog v-if="confirming" :title="`Delete &quot;${confirming.name}&quot; forever?`"
                  message="This removes the file from disk. It cannot be undone."
                  confirm-label="Delete forever" danger
                  @cancel="confirming = null"
                  @confirm="act(() => library.deleteForever(confirming!.kind, confirming!.id))" />
  </main>
</template>

<style scoped>
.wrap { max-width: 62rem; margin: 0 auto; padding: var(--space-5);
        display: grid; gap: var(--space-4); align-content: start; }
header { display: flex; align-items: center; justify-content: space-between; }
h1 { font-size: var(--text-xl); margin: 0; }
.quiet-link { color: var(--text-secondary); text-decoration: none; }
.quiet-link:hover { color: var(--text); }
.muted { color: var(--text-secondary); }
.toolbar { display: flex; justify-content: flex-end; }
/* Flex, so the "files first" sort can flip the two blocks with `order`. */
.listing { display: flex; flex-direction: column; overflow: hidden; }
.expiry { flex: none; font-size: var(--text-xs); }
.row { display: flex; align-items: center; gap: var(--space-3);
       padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--border); }
.row:last-child { border-bottom: 0; }
.row:hover { background: var(--surface-hover); }
.chip { display: grid; place-items: center; width: 28px; height: 28px; flex: none;
        border-radius: var(--radius-sm); background: var(--surface-sunken);
        color: var(--text-tertiary); }
/* The name leads and the old location follows: the listing sorts by name, and
   showing only the full path made an alphabetical sort look broken — three
   items called Architecture, Architecture, Books read as no order at all. */
.named { flex: 1; min-width: 0; display: grid; gap: 1px; }
.named > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.where { font-size: var(--text-xs); }
.actions { display: flex; gap: var(--space-2); flex: none; }
.danger-link { color: var(--danger-text); }
</style>
