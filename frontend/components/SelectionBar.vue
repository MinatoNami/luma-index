<script setup lang="ts">
/**
 * What you can do with what you have selected.
 *
 * Sits above the listing rather than floating over it: a bar that covers the
 * last row hides exactly the thing someone is about to add to the selection.
 *
 * Actions that only apply to books disappear when a folder is in the
 * selection, rather than staying and failing. A disabled control the user
 * cannot explain is worse than one that is not there.
 */
const props = defineProps<{
  count: number
  folders: number
  books: number
  busy?: boolean
  allSelected?: boolean
}>()

const emit = defineEmits<{
  move: []; trash: []; favourite: []; unfavourite: []; collect: []
  selectAll: []; clear: []
}>()

const booksOnly = computed(() => props.folders === 0 && props.books > 0)

const summary = computed(() => {
  const parts: string[] = []
  if (props.folders) parts.push(`${props.folders} folder${props.folders > 1 ? 's' : ''}`)
  if (props.books) parts.push(`${props.books} book${props.books > 1 ? 's' : ''}`)
  return parts.join(' and ')
})
</script>

<template>
  <div class="selection-bar panel" role="toolbar" :aria-label="`${count} selected`">
    <button class="clear" type="button" title="Clear selection (Esc)" @click="emit('clear')">
      <AppIcon name="close" :size="16" />
    </button>

    <strong class="count">{{ summary }} selected</strong>

    <button v-if="!allSelected" class="link" type="button" @click="emit('selectAll')">
      Select all
    </button>

    <div class="spacer" />

    <AppButton icon="folder" :disabled="busy" @click="emit('move')">Move to…</AppButton>
    <template v-if="booksOnly">
      <AppButton icon="collection" :disabled="busy" @click="emit('collect')">
        Add to collection…
      </AppButton>
      <AppButton icon="star-filled" :disabled="busy" @click="emit('favourite')">
        Favourite
      </AppButton>
      <AppButton icon="star" :disabled="busy" @click="emit('unfavourite')">
        Unfavourite
      </AppButton>
    </template>
    <AppButton icon="trash" variant="danger" :disabled="busy" @click="emit('trash')">
      Move to trash
    </AppButton>
  </div>
</template>

<style scoped>
.selection-bar {
  display: flex; align-items: center; flex-wrap: wrap;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  margin-bottom: var(--space-3);
  /* Tinted, so it is obvious the page is in a different mode. */
  background: var(--accent-soft);
  border-color: var(--accent-border, var(--border));
}

.count { font-size: var(--text-sm); }
.spacer { flex: 1 1 auto; }

.clear {
  display: grid; place-items: center; flex: none;
  width: 28px; height: 28px; padding: 0;
  background: none; border: 0; border-radius: var(--radius-sm);
  color: var(--accent-text); cursor: pointer;
}
.clear:hover { background: var(--surface); }

.link {
  background: none; border: 0; padding: 0;
  color: var(--accent-text); font-size: var(--text-sm);
  text-decoration: underline; cursor: pointer;
}
</style>
