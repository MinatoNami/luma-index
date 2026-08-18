<script setup lang="ts">
const props = withDefaults(defineProps<{
  icon?: string
  title: string
  description?: string
}>(), { icon: 'inbox' })
</script>

<template>
  <div class="empty">
    <div class="glyph"><AppIcon :name="props.icon" :size="26" /></div>
    <h2>{{ props.title }}</h2>
    <p v-if="props.description">{{ props.description }}</p>
    <div class="actions"><slot /></div>
  </div>
</template>

<style scoped>
.empty {
  display: flex; flex-direction: column; align-items: center; text-align: center;
  padding: var(--space-7) var(--space-5);
  border: 1px dashed var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
}
.glyph {
  display: grid; place-items: center;
  width: 52px; height: 52px; margin-bottom: var(--space-4);
  border-radius: var(--radius-full);
  background: var(--surface-sunken); color: var(--text-tertiary);
}
h2 { margin: 0; font-size: var(--text-md); font-weight: 600; }
p { margin: var(--space-2) 0 0; max-width: 30rem;
    color: var(--text-secondary); font-size: var(--text-base); }
.actions:not(:empty) { margin-top: var(--space-5); display: flex; gap: var(--space-3); }
</style>
