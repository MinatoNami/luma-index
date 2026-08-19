<script setup lang="ts">
import type { Folder } from '~/composables/useLibrary'

/**
 * Choose a destination folder.
 *
 * Browses one level at a time rather than loading the whole tree: a library
 * with hundreds of folders would otherwise be one large request every time
 * someone moves a single file.
 *
 * The folders being moved are excluded from the list so none can be dropped
 * into itself — all of them, not just the first, or a selection of twenty would
 * offer nineteen destinations that are certain to be skipped. Deeper cycles — a
 * folder into its own descendant — are refused by the server, and its message
 * is shown as-is rather than duplicating the rule here.
 */
const props = withDefaults(defineProps<{
  title: string
  /** Folders being moved cannot be their own destination. */
  excludeFolderId?: number | number[] | null
  /** Where the item lives now, so "already here" can be disabled. */
  currentFolderId?: number | null
  busy?: boolean
  error?: string
}>(), { excludeFolderId: null, currentFolderId: null })

const emit = defineEmits<{ choose: [number | null]; cancel: [] }>()

const library = useLibrary()

// One id or many, so a single move and a selection can share this component
// without the caller having to know which shape it wants.
const excluded = computed(() => new Set(
  props.excludeFolderId === null || props.excludeFolderId === undefined
    ? []
    : [props.excludeFolderId].flat(),
))

const parent = ref<number | null>(null)
const trail = ref<Folder[]>([])
const folders = ref<Folder[]>([])
const loading = ref(true)

async function open(folder: Folder | null) {
  loading.value = true
  try {
    parent.value = folder?.id ?? null
    folders.value = await library.listFolders(parent.value)
  } finally {
    loading.value = false
  }
}

async function enter(folder: Folder) {
  trail.value = [...trail.value, folder]
  await open(folder)
}

async function goTo(index: number) {
  trail.value = trail.value.slice(0, index + 1)
  await open(trail.value[index] ?? null)
}

async function goRoot() {
  trail.value = []
  await open(null)
}

onMounted(() => open(null))

const selectable = computed(() =>
  folders.value.filter(f => !excluded.value.has(f.id)))

// Moving something to where it already is would be a no-op request.
const alreadyHere = computed(() => parent.value === props.currentFolderId)
const destinationName = computed(() =>
  trail.value.length ? trail.value[trail.value.length - 1].name : 'My library')
</script>

<template>
  <div class="backdrop" @click.self="emit('cancel')" @keydown.esc="emit('cancel')">
    <div class="dialog panel" role="dialog" aria-modal="true" :aria-label="props.title">
      <h2>{{ props.title }}</h2>

      <nav class="crumbs" aria-label="Folder path">
        <button type="button" class="crumb" @click="goRoot">My library</button>
        <template v-for="(folder, index) in trail" :key="folder.id">
          <AppIcon name="chevron-right" :size="13" class="sep" />
          <button type="button" class="crumb" @click="goTo(index)">{{ folder.name }}</button>
        </template>
      </nav>

      <ul class="list">
        <li v-for="folder in selectable" :key="folder.id">
          <button type="button" @click="enter(folder)">
            <span class="chip"><AppIcon name="folder" :size="15" /></span>
            <span class="name">{{ folder.name }}</span>
            <AppIcon name="chevron-right" :size="14" class="into" />
          </button>
        </li>
        <li v-if="!loading && !selectable.length" class="empty tertiary">
          No folders here — you can still move it into this one.
        </li>
      </ul>

      <p v-if="props.error" class="notice notice-error" role="alert">
        <AppIcon name="warning" :size="16" /> {{ props.error }}
      </p>

      <footer class="actions">
        <AppButton variant="ghost" @click="emit('cancel')">Cancel</AppButton>
        <AppButton variant="primary" :disabled="alreadyHere" :loading="props.busy"
                   @click="emit('choose', parent)">
          {{ alreadyHere ? 'Already here' : `Move to ${destinationName}` }}
        </AppButton>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.backdrop {
  position: fixed; inset: 0; z-index: 50; display: grid; place-items: center;
  padding: var(--space-5); background: rgb(20 19 16 / 55%); backdrop-filter: blur(2px);
}
.dialog { width: min(28rem, 100%); padding: var(--space-5); box-shadow: var(--shadow-lg); }
h2 { margin: 0 0 var(--space-3); font-size: var(--text-lg); font-weight: 600; }
.crumbs { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1);
          margin-bottom: var(--space-2); }
.crumb { background: none; border: 0; padding: var(--space-1) var(--space-2);
         color: var(--accent-text); font-size: var(--text-sm);
         border-radius: var(--radius-sm); cursor: pointer; }
.crumb:hover { background: var(--surface-hover); }
.sep { color: var(--text-tertiary); }
.list { list-style: none; margin: 0; padding: 0; max-height: 15rem; overflow: auto;
        border: 1px solid var(--border); border-radius: var(--radius-sm); }
.list li + li { border-top: 1px solid var(--border); }
.list button {
  display: flex; align-items: center; gap: var(--space-3); width: 100%;
  padding: var(--space-2) var(--space-3); background: none; border: 0;
  color: var(--text); font-size: var(--text-base); text-align: left; cursor: pointer;
}
.list button:hover { background: var(--surface-hover); }
.chip { display: grid; place-items: center; width: 26px; height: 26px; flex: none;
        border-radius: var(--radius-sm); background: var(--accent-soft);
        color: var(--accent-text); }
.name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.into { color: var(--text-tertiary); }
.empty { padding: var(--space-4); text-align: center; font-size: var(--text-sm); }
.notice { margin-top: var(--space-3); }
.actions { display: flex; gap: var(--space-2); justify-content: flex-end;
           margin-top: var(--space-4); }
</style>
