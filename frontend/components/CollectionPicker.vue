<script setup lang="ts">
import type { Collection } from '~/composables/useCollections'

/**
 * Put a book in a collection.
 *
 * A book can be in several at once, so this shows what it is already in rather
 * than asking you to pick exactly one — and lets a new collection be made
 * without leaving the dialog, which is when you usually realise you want one.
 */
const props = defineProps<{ bookTitle: string; bookId: number }>()
const emit = defineEmits<{ done: []; cancel: [] }>()

const collections = useCollections()

const all = ref<Collection[]>([])
const member = ref<Set<number>>(new Set())
const newName = ref('')
const busy = ref(false)
const error = ref('')

async function load() {
  all.value = await collections.list()
  // Which ones already contain this book.
  const { api } = useApi()
  const containing = await Promise.all(all.value.map(async (c) => {
    const books = await api<{ id: number }[]>('/library/books/', {
      params: { collection: String(c.id) },
    }).catch(() => [])
    return books.some(b => b.id === props.bookId) ? c.id : null
  }))
  member.value = new Set(containing.filter((id): id is number => id !== null))
}

onMounted(load)

async function toggle(collection: Collection) {
  busy.value = true
  error.value = ''
  try {
    if (member.value.has(collection.id)) {
      await collections.removeBook(collection.id, props.bookId)
      member.value.delete(collection.id)
    } else {
      await collections.addBook(collection.id, props.bookId)
      member.value.add(collection.id)
    }
    member.value = new Set(member.value)
  } catch (err: any) {
    error.value = err?.data?.detail || 'That did not work.'
  } finally {
    busy.value = false
  }
}

async function createAndAdd() {
  const name = newName.value.trim()
  if (!name) return
  busy.value = true
  error.value = ''
  try {
    const created = await collections.create(name)
    await collections.addBook(created.id, props.bookId)
    newName.value = ''
    await load()
  } catch (err: any) {
    error.value = err?.data?.detail || 'Could not create that collection.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="backdrop" @click.self="emit('cancel')" @keydown.esc="emit('cancel')">
    <div class="dialog panel" role="dialog" aria-modal="true" aria-label="Add to collection">
      <h2>Collections</h2>
      <p class="sub tertiary">{{ props.bookTitle }}</p>

      <ul v-if="all.length" class="list">
        <li v-for="collection in all" :key="collection.id">
          <button type="button" :disabled="busy" @click="toggle(collection)">
            <AppIcon :name="member.has(collection.id) ? 'check' : 'collection'" :size="16"
                     :class="{ on: member.has(collection.id) }" />
            <span class="name">{{ collection.path }}</span>
            <span class="tertiary count">{{ collection.book_count }}</span>
          </button>
        </li>
      </ul>
      <p v-else class="tertiary empty">No collections yet — make one below.</p>

      <form class="create" @submit.prevent="createAndAdd">
        <input v-model="newName" type="text" placeholder="New collection…"
               aria-label="New collection name" maxlength="255" />
        <AppButton type="submit" :disabled="!newName.trim() || busy">Create</AppButton>
      </form>

      <p v-if="error" class="notice notice-error" role="alert">
        <AppIcon name="warning" :size="16" /> {{ error }}
      </p>

      <footer class="actions">
        <AppButton variant="primary" @click="emit('done')">Done</AppButton>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.backdrop { position: fixed; inset: 0; z-index: 50; display: grid; place-items: center;
            padding: var(--space-5); background: rgb(20 19 16 / 55%); backdrop-filter: blur(2px); }
.dialog { width: min(26rem, 100%); padding: var(--space-5); box-shadow: var(--shadow-lg); }
h2 { margin: 0; font-size: var(--text-lg); font-weight: 600; }
.sub { margin: var(--space-1) 0 var(--space-3); font-size: var(--text-sm);
       overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.list { list-style: none; margin: 0 0 var(--space-3); padding: 0;
        max-height: 14rem; overflow: auto;
        border: 1px solid var(--border); border-radius: var(--radius-sm); }
.list li + li { border-top: 1px solid var(--border); }
.list button { display: flex; align-items: center; gap: var(--space-3); width: 100%;
               padding: var(--space-2) var(--space-3); background: none; border: 0;
               color: var(--text); font-size: var(--text-base); text-align: left;
               cursor: pointer; }
.list button:hover { background: var(--surface-hover); }
.list .on { color: var(--accent-text); }
.name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.count { font-size: var(--text-xs); }
.empty { font-size: var(--text-sm); margin: 0 0 var(--space-3); }
.create { display: flex; gap: var(--space-2); }
.create input { flex: 1; }
.notice { margin-top: var(--space-3); }
.actions { display: flex; justify-content: flex-end; margin-top: var(--space-4); }
</style>
