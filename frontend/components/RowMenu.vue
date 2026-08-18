<script setup lang="ts">
export interface RowAction {
  label: string
  icon?: string
  danger?: boolean
  run: () => void
}

const props = defineProps<{ actions: RowAction[]; label?: string }>()

const open = ref(false)
const root = ref<HTMLElement | null>(null)

function close() { open.value = false }

function onDocumentClick(event: MouseEvent) {
  if (root.value && !root.value.contains(event.target as Node)) close()
}

onMounted(() => document.addEventListener('click', onDocumentClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocumentClick))

function choose(action: RowAction) {
  close()
  action.run()
}
</script>

<template>
  <div ref="root" class="menu" @keydown.esc="close">
    <button class="trigger" type="button" :aria-expanded="open" aria-haspopup="menu"
            :aria-label="props.label || 'More actions'" @click.stop.prevent="open = !open">
      <AppIcon name="more" :size="18" />
    </button>
    <ul v-if="open" class="items" role="menu">
      <li v-for="action in props.actions" :key="action.label" role="none">
        <button type="button" role="menuitem" :class="{ danger: action.danger }"
                @click.stop.prevent="choose(action)">
          <AppIcon v-if="action.icon" :name="action.icon" :size="15" />
          {{ action.label }}
        </button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.menu { position: relative; }
.trigger {
  display: grid; place-items: center;
  width: 32px; height: 32px;
  background: transparent; color: var(--text-tertiary);
  border: 0; border-radius: var(--radius-sm); cursor: pointer;
  transition: background-color var(--duration-fast) var(--ease),
              color var(--duration-fast) var(--ease);
}
.trigger:hover, .trigger[aria-expanded="true"] {
  background: var(--surface-hover); color: var(--text);
}
.items {
  position: absolute; right: 0; top: calc(100% + 4px); z-index: 30;
  min-width: 12rem;
  list-style: none; margin: 0; padding: var(--space-1);
  background: var(--surface-raised);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-lg);
  animation: pop var(--duration-fast) var(--ease);
}
.items button {
  display: flex; align-items: center; gap: var(--space-3);
  width: 100%; min-height: 34px;
  padding: 0 var(--space-3);
  background: none; color: var(--text); border: 0;
  border-radius: var(--radius-sm);
  font-size: var(--text-base); text-align: left; cursor: pointer;
}
.items button:hover { background: var(--surface-hover); }
.items button.danger { color: var(--danger-text); }
.items button.danger:hover { background: var(--danger-soft); }

@keyframes pop { from { opacity: 0; transform: translateY(-3px); } }
</style>
