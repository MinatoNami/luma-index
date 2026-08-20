<script setup lang="ts">
/**
 * Modal for renaming and for confirming a destructive action.
 *
 * Focus moves in on open and returns to the trigger on close, and Tab is
 * trapped inside — without that, a keyboard user tabs into the page behind the
 * dialog and cannot tell where they are.
 */
const props = defineProps<{
  title: string
  label?: string
  modelValue?: string
  confirmLabel?: string
  danger?: boolean
  message?: string
  busy?: boolean
}>()
const emit = defineEmits<{ confirm: [string]; cancel: [] }>()

const value = ref(props.modelValue ?? '')
const input = ref<HTMLInputElement | null>(null)
const panel = ref<HTMLElement | null>(null)
let previouslyFocused: HTMLElement | null = null

const FOCUSABLE = 'button:not(:disabled), input, a[href], [tabindex]:not([tabindex="-1"])'

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.stopPropagation()
    emit('cancel')
    return
  }
  if (event.key !== 'Tab' || !panel.value) return

  const items = [...panel.value.querySelectorAll<HTMLElement>(FOCUSABLE)]
  if (!items.length) return
  const first = items[0]
  const last = items[items.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

onMounted(async () => {
  previouslyFocused = document.activeElement as HTMLElement | null
  await nextTick()
  if (input.value) {
    input.value.focus()
    input.value.select()
  } else {
    panel.value?.querySelector<HTMLElement>(FOCUSABLE)?.focus()
  }
})

onBeforeUnmount(() => previouslyFocused?.focus())
</script>

<template>
  <div class="backdrop" @click.self="emit('cancel')" @keydown="onKeydown">
    <div ref="panel" class="dialog panel" role="dialog" aria-modal="true"
         :aria-label="props.title">
      <h2>{{ props.title }}</h2>
      <p v-if="props.message" class="message">{{ props.message }}</p>

      <form v-if="props.label" @submit.prevent="emit('confirm', value)">
        <label for="prompt-value">{{ props.label }}</label>
        <input id="prompt-value" ref="input" v-model="value" type="text" required
               maxlength="255" autocomplete="off" />
        <div class="actions">
          <AppButton variant="ghost" @click="emit('cancel')">Cancel</AppButton>
          <AppButton variant="primary" type="submit" :loading="props.busy">
            {{ props.confirmLabel || 'Save' }}
          </AppButton>
        </div>
      </form>

      <div v-else class="actions">
        <AppButton variant="ghost" @click="emit('cancel')">Cancel</AppButton>
        <AppButton :variant="props.danger ? 'danger' : 'primary'" :loading="props.busy"
                   @click="emit('confirm', '')">
          {{ props.confirmLabel || 'Confirm' }}
        </AppButton>
      </div>
    </div>
  </div>
</template>

<style scoped>
.backdrop {
  position: fixed; inset: 0; z-index: 50;
  display: grid; place-items: center;
  padding: var(--space-5);
  background: rgb(20 19 16 / 55%);
  backdrop-filter: blur(2px);
  animation: fade var(--duration) var(--ease);
}
.dialog {
  width: min(26rem, 100%);
  padding: var(--space-5);
  box-shadow: var(--shadow-lg);
  animation: rise var(--duration) var(--ease);
}
h2 { margin: 0; font-size: var(--text-lg); font-weight: 600; }
.message { margin: var(--space-2) 0 0; color: var(--text-secondary); }
form { margin-top: var(--space-4); }
.actions { display: flex; gap: var(--space-2); justify-content: flex-end;
           margin-top: var(--space-5); }

@keyframes fade { from { opacity: 0; } }
@keyframes rise { from { opacity: 0; transform: translateY(6px) scale(0.99); } }

/* A dialog that fades and rises is exactly the motion someone with vestibular
   sensitivity asks the system to stop. It still appears; it just appears
   without travelling. */
@media (prefers-reduced-motion: reduce) {
  .backdrop, .dialog { animation: none; }
}
</style>