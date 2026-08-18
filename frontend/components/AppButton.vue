<script setup lang="ts">
const props = withDefaults(defineProps<{
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md'
  icon?: string
  iconOnly?: boolean
  loading?: boolean
  disabled?: boolean
  type?: 'button' | 'submit'
}>(), {
  variant: 'secondary',
  size: 'md',
  type: 'button',
})
</script>

<template>
  <button :type="props.type" :class="[props.variant, props.size, { 'icon-only': props.iconOnly }]"
          :disabled="props.disabled || props.loading" :data-loading="props.loading || undefined">
    <AppIcon v-if="props.icon && !props.loading" :name="props.icon"
             :size="props.size === 'sm' ? 15 : 17" />
    <span v-if="props.loading" class="spinner" aria-hidden="true" />
    <span v-if="!props.iconOnly" class="label"><slot /></span>
  </button>
</template>

<style scoped>
button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  font: inherit;
  font-size: var(--text-base);
  font-weight: 500;
  line-height: 1;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  cursor: pointer;
  white-space: nowrap;
  transition: background-color var(--duration-fast) var(--ease),
              border-color var(--duration-fast) var(--ease),
              color var(--duration-fast) var(--ease);
}

.md { min-height: var(--tap-target); padding: 0 var(--space-4); }
.sm { min-height: 32px; padding: 0 var(--space-3); font-size: var(--text-sm); }
.icon-only.md { width: var(--tap-target); padding: 0; }
.icon-only.sm { width: 32px; padding: 0; }

.primary { background: var(--accent); color: var(--on-accent); }
.primary:hover:not(:disabled) { background: var(--accent-hover); }

.secondary {
  background: var(--surface);
  color: var(--text);
  border-color: var(--border);
  box-shadow: var(--shadow-sm);
}
.secondary:hover:not(:disabled) { background: var(--surface-hover); }

.ghost { background: transparent; color: var(--text-secondary); }
.ghost:hover:not(:disabled) { background: var(--surface-hover); color: var(--text); }

.danger { background: var(--danger); color: var(--on-danger); }
.danger:hover:not(:disabled) { background: var(--danger-hover); }

button:disabled { opacity: 0.5; cursor: not-allowed; }

.spinner {
  width: 14px; height: 14px; border-radius: 50%;
  border: 2px solid currentColor; border-top-color: transparent;
  animation: spin 620ms linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

@media (prefers-reduced-motion: reduce) {
  .spinner { animation-duration: 2s; }
  button { transition: none; }
}
</style>
