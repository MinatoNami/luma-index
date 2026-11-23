<script setup lang="ts">
import { citation, relativeDay, type NotebookEntry } from '~/composables/useNotebook'

/**
 * One highlight or page note, as the notebook shows it.
 *
 * The card is the way back to the passage: the whole surface opens the book at
 * that page, the way a result does anywhere else, rather than a 13px link in
 * its corner. Everything else you would want to do with a note — copy it, say
 * something about it, get rid of it — is in its menu, so a note no longer has
 * to be found again inside the reader to be changed.
 *
 * The passage is set in the book face and your note in the app's: whose words
 * are whose should not need reading to tell.
 */
const props = defineProps<{ entry: NotebookEntry; showBook?: boolean }>()
const emit = defineEmits<{
  saved: [NotebookEntry]
  remove: [NotebookEntry]
  book: [number]
}>()

const notebook = useNotebook()

const editing = ref(false)
const draft = ref('')
const saving = ref(false)
const error = ref('')
const copied = ref(false)
const field = ref<HTMLTextAreaElement | null>(null)

const isHighlight = computed(() => props.entry.kind === 'highlight')
const href = computed(() => `/books/${props.entry.book.id}?page=${props.entry.page + 1}`)

// For a highlight the editable text is its note; for a page note, the note itself.
const editable = computed(() => (isHighlight.value ? props.entry.note : props.entry.text))

const actions = computed(() => [
  { label: 'Open at this page', icon: 'chevron-right', run: () => navigateTo(href.value) },
  ...(isHighlight.value && props.entry.text
    ? [{ label: 'Copy passage', icon: 'quote', run: copy }] : []),
  { label: isHighlight.value ? (props.entry.note ? 'Edit note' : 'Add a note') : 'Edit note',
    icon: 'pencil', run: startEditing },
  { label: isHighlight.value ? 'Delete highlight' : 'Delete note', icon: 'trash', danger: true,
    run: () => emit('remove', props.entry) },
])

// Only ever shown while editing, which only happens in the browser.
const saveHint = computed(() =>
  /mac|iphone|ipad/i.test(navigator.platform || navigator.userAgent)
    ? '⌘↵ to save' : 'Ctrl+Enter to save')

async function startEditing() {
  draft.value = editable.value
  error.value = ''
  editing.value = true
  await nextTick()
  field.value?.focus()
  field.value?.setSelectionRange(draft.value.length, draft.value.length)
}

async function save() {
  const text = draft.value.trim()
  // A page note is nothing but its text; emptying it is deleting it, which
  // has its own, confirmed, way in.
  if (!isHighlight.value && !text) {
    error.value = 'A page note needs some text. Delete it instead?'
    return
  }
  saving.value = true
  error.value = ''
  try {
    emit('saved', await notebook.edit(props.entry, text))
    editing.value = false
  } catch {
    error.value = 'That could not be saved.'
  } finally {
    saving.value = false
  }
}

function onEditorKey(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.stopPropagation(); editing.value = false }
  if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); save() }
}

async function copy() {
  try {
    await navigator.clipboard.writeText(citation(props.entry))
    copied.value = true
    setTimeout(() => { copied.value = false }, 1800)
  } catch {
    error.value = 'Copying is not allowed here.'
  }
}

</script>

<template>
  <article :class="['entry', 'panel', `is-${entry.kind}`, { editing }]">
    <span v-if="isHighlight" :class="['pen', entry.colour]" aria-hidden="true" />

    <div class="body">
      <p v-if="!isHighlight" class="kind">
        <AppIcon name="pencil" :size="13" /> Page note
      </p>

      <!-- Inline on purpose: `white-space: pre-line` keeps the passage's own
           line breaks, and would keep the template's indentation too. -->
      <blockquote v-if="isHighlight" class="passage">{{ entry.text
        || 'A highlighted area with no text under it' }}</blockquote>
      <p v-else-if="!editing" class="page-note">{{ entry.text }}</p>

      <p v-if="isHighlight && entry.note && !editing" class="your-note">{{ entry.note }}</p>

      <form v-if="editing" class="editor" @submit.prevent="save">
        <label :for="`edit-${entry.kind}-${entry.id}`" class="sr-only">
          {{ isHighlight ? 'Your note on this passage' : 'Page note' }}
        </label>
        <textarea :id="`edit-${entry.kind}-${entry.id}`" ref="field" v-model="draft" rows="3"
                  :placeholder="isHighlight ? 'What did you make of it?' : 'Your note on this page'"
                  @keydown="onEditorKey" />
        <div class="editor-actions">
          <span class="tertiary hint">{{ saveHint }}</span>
          <AppButton size="sm" variant="ghost" @click="editing = false">Cancel</AppButton>
          <AppButton size="sm" variant="primary" type="submit" :loading="saving">Save</AppButton>
        </div>
      </form>

      <p v-if="error" class="error" role="alert">{{ error }}</p>

      <footer class="meta">
        <button v-if="showBook" type="button" class="book" :title="`Only ${entry.book.title}`"
                @click="emit('book', entry.book.id)">
          {{ entry.book.title }}
        </button>
        <!-- The card's own link: stretched over the whole card, so anywhere on
             it opens the passage. Everything else sits above it. -->
        <NuxtLink class="open" :to="href">
          Page {{ entry.page + 1 }}
          <span class="sr-only"> of {{ entry.book.title }}</span>
        </NuxtLink>
        <span class="when">{{ relativeDay(entry.created_at) }}</span>
        <span v-if="copied" class="copied" role="status">
          <AppIcon name="check" :size="13" /> Copied
        </span>
      </footer>
    </div>

    <RowMenu class="actions" :actions="actions"
             :label="`Actions for this ${isHighlight ? 'highlight' : 'page note'}`" />
  </article>
</template>

<style scoped>
.entry {
  position: relative; display: flex; gap: var(--space-2);
  padding: var(--space-4) var(--space-2) var(--space-3) var(--space-5);
  transition: border-color var(--duration-fast) var(--ease),
              box-shadow var(--duration-fast) var(--ease);
}
.entry:not(.editing):hover { border-color: var(--border-strong); box-shadow: var(--shadow-md); }
.entry:focus-within { border-color: var(--border-strong); }

/* The pen it was marked with, down the edge. Colour carries which pen; the
   text beside it stays in text colours. Page notes keep the same gutter, so
   every entry's text starts on one line. */
.pen {
  position: absolute; left: 0; top: 0; bottom: 0; width: 4px;
  border-radius: var(--radius-lg) 0 0 var(--radius-lg);
}
.pen.yellow { background: var(--hl-yellow); }
.pen.green { background: var(--hl-green); }
.pen.blue { background: var(--hl-blue); }
.pen.pink { background: var(--hl-pink); }

.body { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: var(--space-2); }

.kind {
  display: flex; align-items: center; gap: var(--space-1); margin: 0;
  font-size: var(--text-xs); font-weight: 600; letter-spacing: 0.04em;
  text-transform: uppercase; color: var(--text-tertiary);
}

.passage {
  margin: 0;
  font-family: var(--font-serif); font-size: 1.0625rem; line-height: 1.6;
  color: var(--text); white-space: pre-line; overflow-wrap: anywhere;
}
.page-note, .your-note {
  margin: 0; font-size: var(--text-base); line-height: 1.55;
  white-space: pre-line; overflow-wrap: anywhere;
}
.your-note {
  padding-left: var(--space-3); border-left: 2px solid var(--border);
  color: var(--text-secondary);
}

.editor { position: relative; z-index: 1; display: grid; gap: var(--space-2); }
.editor textarea {
  width: 100%; min-height: 5.5rem; resize: vertical;
  padding: var(--space-2) var(--space-3);
  background: var(--surface); color: var(--text);
  border: 1px solid var(--border-strong); border-radius: var(--radius-sm);
  font: inherit; line-height: 1.5;
}
.editor textarea:focus-visible { outline: none; border-color: var(--focus); box-shadow: var(--shadow-focus); }
.editor-actions { display: flex; align-items: center; justify-content: flex-end; gap: var(--space-2); }
.hint { margin-right: auto; font-size: var(--text-xs); }

.error { margin: 0; font-size: var(--text-sm); color: var(--danger-text); }

.meta {
  display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1) var(--space-3);
  font-size: var(--text-sm); color: var(--text-tertiary);
}
.book {
  position: relative; z-index: 1;
  min-height: 28px; max-width: 100%; padding: 0;
  background: none; border: 0; cursor: pointer;
  color: var(--text-secondary); font-weight: 500; text-align: left;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.book:hover { color: var(--text); text-decoration: underline; }
.open {
  display: inline-flex; align-items: center; min-height: 28px;
  color: var(--accent-text); text-decoration: none; font-weight: 500;
}
.open::after { content: ""; position: absolute; inset: 0; border-radius: inherit; }
.entry.editing .open::after { display: none; }
.open:focus-visible { outline: none; }
.open:focus-visible::after { outline: 2px solid var(--focus); outline-offset: 2px;
                             border-radius: var(--radius-lg); }
.when { font-size: var(--text-xs); }
.copied {
  display: inline-flex; align-items: center; gap: 2px;
  color: var(--success); font-size: var(--text-xs); font-weight: 500;
}

.actions { position: relative; z-index: 2; align-self: flex-start; margin-top: -6px; }
/* Quiet until wanted, but never hidden from touch or the keyboard. */
@media (hover: hover) {
  .entry .actions :deep(.trigger) { opacity: 0; }
  .entry:hover .actions :deep(.trigger),
  .entry:focus-within .actions :deep(.trigger),
  .actions :deep(.trigger[aria-expanded="true"]) { opacity: 1; }
}
</style>
