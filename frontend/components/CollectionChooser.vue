<script setup lang="ts">
import type { Collection } from '~/composables/useCollections'

/**
 * Pick one collection to add a selection of books to.
 *
 * Deliberately not CollectionPicker: that one shows and toggles what a single
 * book already belongs to, and membership across many books is a tri-state
 * nobody wants to reason about mid-gesture. This only adds, which is the
 * action the selection bar offers.
 */
defineProps<{ count: number }>()
const emit = defineEmits<{ choose: [number]; cancel: [] }>()

const collections = useCollections()

const all = ref<Collection[]>([])
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const newName = ref('')

onMounted(async () => {
  try {
    all.value = await collections.list()
  } catch (err: any) {
    error.value = err?.data?.detail || 'Could not load your collections.'
  } finally {
    loading.value = false
  }
})

async function createAndChoose() {
  const name = newName.value.trim()
  if (!name) return
  busy.value = true
  error.value = ''
  try {
    const created = await collections.create(name)
    emit('choose', created.id)
  } catch (err: any) {
    error.value = err?.data?.detail || 'Could not create that collection.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="backdrop" @click.self="emit('cancel')">
    <div class="sheet panel" role="dialog" aria-modal="true" aria-labelledby="cc-title">
      <h2 id="cc-title">Add {{ count }} book{{ count > 1 ? 's' : '' }} to…</h2>

      <p v-if="loading" class="muted">Loading…</p>
      <p v-else-if="!all.length" class="muted">
        You have no collections yet. Make one below.
      </p>
      <ul v-else class="list">
        <li v-for="c in all" :key="c.id">
          <button type="button" :disabled="busy" @click="emit('choose', c.id)">
            <AppIcon name="collection" :size="16" />
            <span>{{ c.name }}</span>
          </button>
        </li>
      </ul>

      <form class="new" @submit.prevent="createAndChoose">
        <label class="sr-only" for="cc-new">New collection name</label>
        <input id="cc-new" v-model="newName" placeholder="New collection…" :disabled="busy" />
        <AppButton type="submit" :disabled="busy || !newName.trim()">Create and add</AppButton>
      </form>

      <p v-if="error" class="inline-error">{{ error }}</p>

      <footer>
        <AppButton variant="ghost" :disabled="busy" @click="emit('cancel')">Cancel</AppButton>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.backdrop {
  position: fixed; inset: 0; z-index: 50;
  display: grid; place-items: center;
  padding: var(--space-4);
  background: rgb(0 0 0 / 45%);
}
.sheet {
  width: min(420px, 100%);
  max-height: min(80vh, 640px);
  display: flex; flex-direction: column; gap: var(--space-3);
  padding: var(--space-4);
}
h2 { font-size: var(--text-lg); }

.list { list-style: none; margin: 0; padding: 0; overflow-y: auto; }
.list button {
  display: flex; align-items: center; gap: var(--space-2);
  width: 100%; padding: var(--space-2);
  background: none; border: 0; border-radius: var(--radius-sm);
  color: inherit; text-align: left; cursor: pointer;
}
.list button:hover { background: var(--surface-hover); }

.new { display: flex; gap: var(--space-2); }
.new input { flex: 1 1 auto; }

footer { display: flex; justify-content: flex-end; }
</style>
