<script setup lang="ts">
/**
 * The kebab menu on a row — rename, move, delete — the way a file manager
 * offers them.
 *
 * Closes on outside click and on Escape, and the trigger keeps focus so
 * keyboard users can reach every action (PRD §40).
 */
const props = defineProps<{ actions: { label: string; danger?: boolean; run: () => void }[] }>()

const open = ref(false)
const root = ref<HTMLElement | null>(null)

function close() {
  open.value = false
}

function onDocumentClick(event: MouseEvent) {
  if (root.value && !root.value.contains(event.target as Node)) close()
}

onMounted(() => document.addEventListener('click', onDocumentClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocumentClick))

function choose(action: { run: () => void }) {
  close()
  action.run()
}
</script>

<template>
  <div ref="root" class="menu" @keydown.esc="close">
    <button class="trigger" type="button" :aria-expanded="open" aria-haspopup="menu"
            aria-label="More actions" @click.stop="open = !open">
      ⋮
    </button>
    <ul v-if="open" class="items" role="menu">
      <li v-for="action in props.actions" :key="action.label" role="none">
        <button type="button" role="menuitem" :class="{ danger: action.danger }"
                @click.stop="choose(action)">
          {{ action.label }}
        </button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.menu { position: relative; }
.trigger {
  background: none; color: var(--muted); border: 0; padding: 0 0.5rem;
  font-size: 1.1rem; line-height: 1; min-height: 32px; border-radius: 6px;
}
.trigger:hover { background: var(--bg); color: var(--text); }
.items {
  position: absolute; right: 0; top: 100%; z-index: 20; min-width: 11rem;
  list-style: none; margin: 0.25rem 0 0; padding: 0.25rem;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; box-shadow: 0 8px 24px rgb(0 0 0 / 25%);
}
.items button {
  display: block; width: 100%; text-align: left; background: none; color: var(--text);
  border: 0; padding: 0.5rem 0.75rem; border-radius: 6px; font-size: 0.9rem; min-height: 36px;
}
.items button:hover { background: var(--bg); }
.items button.danger { color: var(--danger); }
</style>
