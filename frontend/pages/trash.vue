<script setup lang="ts">
import type { Book, Folder } from '~/composables/useLibrary'

const library = useLibrary()

const folders = ref<Folder[]>([])
const books = ref<Book[]>([])
const busy = ref(false)
const error = ref('')
const confirming = ref<{ kind: 'folder' | 'book'; id: number; name: string } | null>(null)

async function load() {
  busy.value = true
  try {
    const trash = await library.listTrash()
    folders.value = trash.folders
    books.value = trash.books
  } finally {
    busy.value = false
  }
}
onMounted(load)

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
    </p>

    <div v-if="!isEmpty" class="listing panel">
      <div v-for="folder in folders" :key="`f${folder.id}`" class="row">
        <span class="chip"><AppIcon name="folder" :size="16" /></span>
        <span class="path">{{ folder.path }}</span>
        <div class="actions">
          <AppButton size="sm" icon="restore" :disabled="busy"
                     @click="act(() => library.restoreFolder(folder.id))">Restore</AppButton>
          <AppButton size="sm" variant="ghost" :disabled="busy" class="danger-link"
                     @click="confirming = { kind: 'folder', id: folder.id, name: folder.name }">
            Delete forever
          </AppButton>
        </div>
      </div>
      <div v-for="book in books" :key="`b${book.id}`" class="row">
        <span class="chip"><AppIcon name="file" :size="16" /></span>
        <span class="path">{{ book.path }}</span>
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
.listing { overflow: hidden; }
.row { display: flex; align-items: center; gap: var(--space-3);
       padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--border); }
.row:last-child { border-bottom: 0; }
.row:hover { background: var(--surface-hover); }
.chip { display: grid; place-items: center; width: 28px; height: 28px; flex: none;
        border-radius: var(--radius-sm); background: var(--surface-sunken);
        color: var(--text-tertiary); }
.path { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis;
        white-space: nowrap; color: var(--text-secondary); }
.actions { display: flex; gap: var(--space-2); flex: none; }
.danger-link { color: var(--danger-text); }
</style>
