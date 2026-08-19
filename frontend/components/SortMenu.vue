<script setup lang="ts">
/**
 * How a listing is ordered.
 *
 * A select and a direction button rather than a popover: there are five
 * choices, the control is used rarely, and a native select brings keyboard
 * handling and a sensible mobile picker for free.
 *
 * "Type" is here alongside real columns because that is how people describe
 * it, but it is not a database order — folders and books come back as separate
 * lists, so it only decides which block is drawn first.
 */
/** `trashed` is only offered where `allowTrashed` is set — the trash. */
export type SortKey = 'name' | 'added' | 'modified' | 'size' | 'type' | 'trashed'

const props = defineProps<{
  modelValue: SortKey
  descending: boolean
  /** The trash orders by when things were deleted, which nowhere else can. */
  allowTrashed?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [SortKey]
  'update:descending': [boolean]
}>()

type Option = { value: SortKey; label: string }

const OPTIONS: Option[] = [
  { value: 'name', label: 'Name' },
  { value: 'added', label: 'Date added' },
  { value: 'modified', label: 'Last modified' },
  { value: 'size', label: 'Size' },
  { value: 'type', label: 'Type' },
]

// The direction means different things per column, and "A to Z / Z to A" on a
// date column is the kind of label that makes people pick the wrong one.
const DIRECTION: Record<SortKey, [string, string]> = {
  name: ['A to Z', 'Z to A'],
  added: ['Oldest first', 'Newest first'],
  modified: ['Oldest first', 'Newest first'],
  size: ['Smallest first', 'Largest first'],
  type: ['Folders first', 'Files first'],
  trashed: ['Longest ago', 'Most recent'],
}

const TRASHED: Option = { value: 'trashed', label: 'Date deleted' }

const options = computed<Option[]>(() =>
  props.allowTrashed ? [TRASHED, ...OPTIONS] : OPTIONS)

// The arrow shows which way the order runs. Naming only that state on a button
// that changes it reads as an instruction — "A to Z" on the control that
// switches to Z-to-A — so the accessible name is the action, with the state
// after it. Bolting "Sort" onto the state strings instead produced
// "Sort longest ago".
const stateLabel = computed(() =>
  DIRECTION[props.modelValue][props.descending ? 1 : 0])
const directionLabel = computed(() =>
  `Reverse sort order (currently ${stateLabel.value})`)
</script>

<template>
  <div class="sort">
    <label class="sr-only" for="sort-key">Sort by</label>
    <select id="sort-key" :value="modelValue"
            @change="emit('update:modelValue', ($event.target as HTMLSelectElement).value as SortKey)">
      <option v-for="o in options" :key="o.value" :value="o.value">{{ o.label }}</option>
    </select>
    <button type="button" class="direction" :title="stateLabel" :aria-label="directionLabel"
            :aria-pressed="descending"
            @click="emit('update:descending', !descending)">
      <AppIcon :name="descending ? 'arrow-down' : 'arrow-up'" :size="16" />
    </button>
  </div>
</template>

<style scoped>
.sort { display: flex; align-items: stretch; gap: var(--space-1); }

select {
  height: 36px;
  padding: 0 var(--space-2);
  font-size: var(--text-sm);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
}

.direction {
  display: grid; place-items: center;
  width: 36px; height: 36px; flex: none;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-secondary);
  cursor: pointer;
}
.direction:hover { background: var(--surface-hover); color: var(--text); }
</style>
