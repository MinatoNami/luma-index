<script setup lang="ts">
import type { Book } from '~/composables/useLibrary'
import { matchPlaces, PLACES, step, type Place } from '~/composables/useQuickOpen'

/**
 * Jump to any book, or any part of the app, from the keyboard.
 *
 * Linear, Notion, Obsidian and Raycast all put one box behind ⌘K, because
 * the fastest way to a thing you can name is to type its name. Here the
 * library is folders, and the book you want is often three clicks deep in one
 * — this makes it one shortcut and a few letters.
 *
 * A combobox in the ARIA sense: focus stays in the input, the arrow keys move
 * a highlight through the options, and the input says which option is active,
 * so a screen reader follows along without focus ever leaving the field.
 */
const emit = defineEmits<{ close: [] }>()
const { api } = useApi()
const library = useLibrary()

interface Option {
  key: string
  kind: 'book' | 'place' | 'action'
  label: string
  detail?: string
  icon?: string
  book?: Book
  to: string
}

// Offered before anything is typed. The rest are a word away.
const PLACES_SHOWN: Place[] = PLACES.filter(p =>
  ['/library', '/notebook', '/collections', '/settings'].includes(p.to))

const query = ref('')
const input = ref<HTMLInputElement | null>(null)
const books = ref<Book[]>([])
const reading = ref<Book[]>([])
const loading = ref(false)
const active = ref(0)
let previouslyFocused: HTMLElement | null = null

const options = computed<Option[]>(() => {
  const q = query.value.trim()
  const bookOption = (book: Book, detail?: string): Option => ({
    key: `book-${book.id}`, kind: 'book', label: book.title, book,
    detail, to: `/books/${book.id}`,
  })

  if (!q) {
    // Nothing typed: where you were, then everywhere you can go.
    return [
      ...reading.value.slice(0, 5).map(b =>
        bookOption(b, b.progress ? `${Math.round(b.progress.percentage)}% read` : undefined)),
      ...PLACES_SHOWN.map(placeOption),
    ]
  }

  return [
    ...books.value.map(b => bookOption(b, folderOf(b))),
    ...matchPlaces(q).map(placeOption),
    { key: 'inside', kind: 'action', icon: 'search', label: `Search inside books for “${q}”`,
      to: `/library?q=${encodeURIComponent(q)}` },
    { key: 'notes', kind: 'action', icon: 'notebook', label: `Search your notebook for “${q}”`,
      to: `/notebook?q=${encodeURIComponent(q)}` },
  ]
})

function placeOption(place: Place): Option {
  return { key: `place-${place.to}`, kind: 'place', icon: place.icon, label: place.label,
           detail: 'Go to', to: place.to }
}

function folderOf(book: Book): string | undefined {
  const parts = book.path?.split('/') ?? []
  return parts.length > 1 ? parts.slice(0, -1).join(' / ') : undefined
}

let generation = 0
let timer: ReturnType<typeof setTimeout> | null = null

watch(query, (value) => {
  active.value = 0
  if (timer) clearTimeout(timer)
  const q = value.trim()
  if (!q) { books.value = []; loading.value = false; return }
  loading.value = true
  // Short, because this is a title filter on an indexed column and the point
  // of the box is speed.
  timer = setTimeout(async () => {
    const mine = ++generation
    try {
      const body = await api<{ results: Book[] }>('/library/books/', {
        params: { search: q, limit: 8, sort: 'name' },
      })
      if (mine === generation) books.value = body.results ?? []
    } catch {
      if (mine === generation) books.value = []
    } finally {
      if (mine === generation) loading.value = false
    }
  }, 120)
})

function choose(option: Option | undefined) {
  if (!option) return
  emit('close')
  navigateTo(option.to)
}

function onKeydown(event: KeyboardEvent) {
  const count = options.value.length
  switch (event.key) {
    case 'ArrowDown':
      event.preventDefault()
      active.value = step(active.value, 1, count)
      break
    case 'ArrowUp':
      event.preventDefault()
      active.value = step(active.value, -1, count)
      break
    case 'Enter':
      event.preventDefault()
      choose(options.value[active.value])
      break
    case 'Escape':
      event.preventDefault()
      event.stopPropagation()
      emit('close')
      break
    case 'Tab':
      // There is one control in here; Tab leaving it would put focus on the
      // page behind a modal.
      event.preventDefault()
      break
  }
}

// Keep the active option in view as the arrows move it past the fold.
watch(active, async (index) => {
  await nextTick()
  document.getElementById(`quick-option-${index}`)?.scrollIntoView({ block: 'nearest' })
})

onMounted(async () => {
  previouslyFocused = document.activeElement as HTMLElement | null
  await nextTick()
  input.value?.focus()
  try {
    reading.value = await library.continueReading()
  } catch {
    reading.value = []
  }
})

onBeforeUnmount(() => {
  if (timer) clearTimeout(timer)
  previouslyFocused?.focus()
})

const activeId = computed(() =>
  options.value.length ? `quick-option-${active.value}` : undefined)
</script>

<template>
  <div class="backdrop" @click.self="emit('close')">
    <div class="dialog panel" role="dialog" aria-modal="true" aria-label="Quick open">
      <div class="field">
        <AppIcon name="search" :size="18" class="field-icon" />
        <input ref="input" v-model="query" type="text" role="combobox"
               aria-label="Find a book or a page" aria-autocomplete="list"
               aria-controls="quick-options" :aria-expanded="options.length > 0"
               :aria-activedescendant="activeId" autocomplete="off" spellcheck="false"
               placeholder="Find a book, or go somewhere…" @keydown="onKeydown" />
        <kbd class="esc">Esc</kbd>
      </div>

      <ul id="quick-options" class="options" role="listbox" aria-label="Results">
        <li v-if="!query.trim() && reading.length" class="group" role="presentation">
          Continue reading
        </li>
        <li v-for="(option, i) in options" :id="`quick-option-${i}`" :key="option.key"
            role="option" :aria-selected="i === active"
            :class="['option', option.kind, { active: i === active }]"
            @mousemove="active = i" @click="choose(option)">
          <span v-if="option.book" class="cover"><BookCover :book="option.book" size="sm" /></span>
          <span v-else class="glyph"><AppIcon :name="option.icon || 'file'" :size="16" /></span>
          <span class="text">
            <span class="label">{{ option.label }}</span>
            <span v-if="option.detail" class="detail">{{ option.detail }}</span>
          </span>
          <AppIcon v-if="i === active" name="chevron-right" :size="15" class="enter" />
        </li>
        <li v-if="query.trim() && !loading && !books.length" class="none" role="presentation">
          No titles match. Try searching inside the books.
        </li>
      </ul>

      <footer class="keys" aria-hidden="true">
        <span><kbd>↑</kbd><kbd>↓</kbd> move</span>
        <span><kbd>↵</kbd> open</span>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.backdrop {
  position: fixed; inset: 0; z-index: 60;
  display: flex; justify-content: center; align-items: flex-start;
  padding: max(10vh, var(--space-6)) var(--space-4) var(--space-4);
  background: rgb(20 19 16 / 45%);
  animation: fade var(--duration) var(--ease);
}
.dialog {
  width: min(36rem, 100%); max-height: min(32rem, 80vh);
  display: flex; flex-direction: column; overflow: hidden;
  box-shadow: var(--shadow-lg);
  animation: rise var(--duration) var(--ease);
}

.field { position: relative; display: flex; align-items: center; border-bottom: 1px solid var(--border); }
.field-icon { position: absolute; left: var(--space-4); color: var(--text-tertiary); pointer-events: none; }
.field input {
  flex: 1; min-height: 52px; padding: 0 var(--space-3) 0 calc(var(--space-4) + 28px);
  border: 0; background: transparent; color: var(--text); font-size: var(--text-md);
}
.field input:focus-visible { outline: none; box-shadow: none; }
.esc { margin-right: var(--space-3); }

kbd {
  display: inline-grid; place-items: center; min-width: 22px; height: 22px; padding: 0 var(--space-1);
  border: 1px solid var(--border); border-bottom-width: 2px; border-radius: 5px;
  background: var(--surface-sunken); color: var(--text-tertiary);
  font-family: var(--font-sans); font-size: 0.6875rem;
}

.options { list-style: none; margin: 0; padding: var(--space-2); overflow-y: auto; flex: 1; }
.group, .none {
  padding: var(--space-2) var(--space-3) var(--space-1);
  font-size: var(--text-xs); color: var(--text-tertiary);
}
.group { font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; }
.none { padding: var(--space-3); font-size: var(--text-sm); }

.option {
  display: flex; align-items: center; gap: var(--space-3);
  min-height: 44px; padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-sm); cursor: pointer;
}
.option.active { background: var(--accent-soft); }
.cover { width: 26px; flex: none; }
.glyph {
  display: grid; place-items: center; width: 26px; height: 26px; flex: none;
  border-radius: var(--radius-sm); background: var(--surface-sunken); color: var(--text-secondary);
}
.option.active .glyph { background: var(--surface); color: var(--accent-text); }
.text { min-width: 0; flex: 1; display: flex; flex-direction: column; }
.label {
  font-size: var(--text-base); color: var(--text);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.detail {
  font-size: var(--text-xs); color: var(--text-tertiary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.enter { color: var(--accent-text); }

.keys {
  display: flex; gap: var(--space-4); padding: var(--space-2) var(--space-4);
  border-top: 1px solid var(--border); font-size: var(--text-xs); color: var(--text-tertiary);
}
.keys span { display: inline-flex; align-items: center; gap: var(--space-1); }

@keyframes fade { from { opacity: 0; } }
@keyframes rise { from { opacity: 0; transform: translateY(-6px) scale(0.99); } }
@media (prefers-reduced-motion: reduce) {
  .backdrop, .dialog { animation: none; }
}
@media (max-width: 40rem) {
  .backdrop { padding-top: calc(env(safe-area-inset-top) + var(--space-4)); }
  .keys { display: none; }
}
</style>
