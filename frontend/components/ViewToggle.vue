<script setup lang="ts">
export type ViewMode = 'list' | 'grid' | 'large'

const model = defineModel<ViewMode>({ required: true })

const OPTIONS: { value: ViewMode; icon: string; label: string }[] = [
  { value: 'list', icon: 'list-view', label: 'List' },
  { value: 'grid', icon: 'grid-view', label: 'Grid' },
  { value: 'large', icon: 'large-view', label: 'Large icons' },
]
</script>

<template>
  <div class="toggle" role="group" aria-label="View">
    <button v-for="option in OPTIONS" :key="option.value" type="button"
            :class="{ active: model === option.value }"
            :aria-pressed="model === option.value" :title="option.label"
            @click="model = option.value">
      <AppIcon :name="option.icon" :size="16" />
      <span class="sr-only">{{ option.label }}</span>
    </button>
  </div>
</template>

<style scoped>
.toggle {
  display: inline-flex;
  padding: 2px;
  gap: 2px;
  background: var(--surface-sunken);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}
button {
  display: grid; place-items: center;
  width: 34px; height: 32px;
  background: transparent; color: var(--text-tertiary);
  border: 0; border-radius: 4px; cursor: pointer;
  transition: background-color var(--duration-fast) var(--ease),
              color var(--duration-fast) var(--ease);
}
button:hover { color: var(--text); }
button.active {
  background: var(--surface); color: var(--accent-text); box-shadow: var(--shadow-sm);
}
@media (prefers-reduced-motion: reduce) { button { transition: none; } }
</style>
