<script setup lang="ts">
/** A small modal for renaming and for confirming a destructive action. */
const props = defineProps<{
  title: string
  label?: string
  modelValue?: string
  confirmLabel?: string
  danger?: boolean
  message?: string
}>()
const emit = defineEmits<{ confirm: [string]; cancel: [] }>()

const value = ref(props.modelValue ?? '')
const input = ref<HTMLInputElement | null>(null)

onMounted(async () => {
  await nextTick()
  input.value?.focus()
  input.value?.select()
})
</script>

<template>
  <div class="backdrop" @click.self="emit('cancel')" @keydown.esc="emit('cancel')">
    <div class="dialog" role="dialog" aria-modal="true" :aria-label="props.title">
      <h2>{{ props.title }}</h2>
      <p v-if="props.message" class="message">{{ props.message }}</p>
      <form v-if="props.label" @submit.prevent="emit('confirm', value)">
        <label for="prompt-value">{{ props.label }}</label>
        <input id="prompt-value" ref="input" v-model="value" type="text" required />
        <div class="actions">
          <button class="secondary" type="button" @click="emit('cancel')">Cancel</button>
          <button type="submit">{{ props.confirmLabel || 'Save' }}</button>
        </div>
      </form>
      <div v-else class="actions">
        <button class="secondary" type="button" @click="emit('cancel')">Cancel</button>
        <button :class="{ danger: props.danger }" type="button" @click="emit('confirm', '')">
          {{ props.confirmLabel || 'Confirm' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.backdrop {
  position: fixed; inset: 0; z-index: 50; display: grid; place-items: center;
  background: rgb(0 0 0 / 45%); padding: 1.5rem;
}
.dialog {
  width: min(26rem, 100%); background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 1.5rem;
}
h2 { margin: 0 0 0.5rem; font-size: 1.05rem; }
.message { color: var(--muted); font-size: 0.9rem; margin: 0 0 1rem; }
label { margin-top: 0.5rem; }
.actions { display: flex; gap: 0.75rem; justify-content: flex-end; margin-top: 1.25rem; }
button.danger { background: var(--danger); }
</style>
