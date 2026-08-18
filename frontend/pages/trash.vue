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
      <NuxtLink to="/">Back to library</NuxtLink>
    </header>

    <p v-if="error" class="notice bad" role="alert">{{ error }}</p>

    <p v-if="!isEmpty" class="muted">
      Restoring a folder brings back everything that was trashed with it.
      Deleting permanently cannot be undone.
    </p>

    <table v-if="!isEmpty" class="listing">
      <tbody>
        <tr v-for="folder in folders" :key="`f${folder.id}`">
          <td><span aria-hidden="true">📁</span> {{ folder.path }}</td>
          <td class="actions">
            <button class="secondary" type="button" :disabled="busy"
                    @click="act(() => library.restoreFolder(folder.id))">Restore</button>
            <button class="link danger" type="button" :disabled="busy"
                    @click="confirming = { kind: 'folder', id: folder.id, name: folder.name }">
              Delete forever
            </button>
          </td>
        </tr>
        <tr v-for="book in books" :key="`b${book.id}`">
          <td><span aria-hidden="true">📄</span> {{ book.path }}</td>
          <td class="actions">
            <button class="secondary" type="button" :disabled="busy"
                    @click="act(() => library.restoreBook(book.id))">Restore</button>
            <button class="link danger" type="button" :disabled="busy"
                    @click="confirming = { kind: 'book', id: book.id, name: book.title }">
              Delete forever
            </button>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="isEmpty" class="empty panel">
      <h2>The trash is empty</h2>
    </div>

    <PromptDialog v-if="confirming" :title="`Delete &quot;${confirming.name}&quot; forever?`"
                  message="This removes the file from disk. It cannot be undone."
                  confirm-label="Delete forever" danger
                  @cancel="confirming = null"
                  @confirm="act(() => library.deleteForever(confirming!.kind, confirming!.id))" />
  </main>
</template>

<style scoped>
.wrap { max-width: 62rem; margin: 0 auto; padding: 1.5rem; }
header { display: flex; align-items: center; justify-content: space-between;
         margin-bottom: 1rem; }
h1 { font-size: 1.35rem; margin: 0; }
.muted { color: var(--muted); font-size: 0.9rem; }
.notice.bad { background: color-mix(in srgb, var(--danger) 14%, transparent);
              color: var(--danger); border-radius: 8px; padding: 0.7rem 1rem; }
.listing { width: 100%; border-collapse: collapse; margin-top: 1rem; }
.listing td { padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border); }
.actions { text-align: right; white-space: nowrap; display: flex; gap: 0.5rem;
           justify-content: flex-end; }
.link { background: none; color: var(--accent); padding: 0.4rem 0.5rem; }
.link.danger { color: var(--danger); }
.empty { text-align: center; padding: 3rem 1.5rem; }
.empty h2 { font-size: 1rem; margin: 0; }
</style>
