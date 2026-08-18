<script setup lang="ts">
const { login } = useAuth()
const route = useRoute()

const email = ref('')
const password = ref('')
const error = ref('')
const pending = ref(false)

async function onSubmit() {
  error.value = ''
  pending.value = true
  try {
    await login(email.value, password.value)
    await navigateTo((route.query.next as string) || '/')
  } catch (err: any) {
    // Django returns {"detail": [...]} for a failed credential check.
    const detail = err?.data?.detail
    error.value = Array.isArray(detail) ? detail[0] : detail || 'Unable to sign in.'
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <main class="wrap">
    <form class="panel" @submit.prevent="onSubmit">
      <h1>LumaIndex</h1>
      <p class="sub">Sign in to your library.</p>

      <div class="field">
        <label for="email">Email</label>
        <input id="email" v-model="email" type="email" autocomplete="username" required
               autocapitalize="none" spellcheck="false" />
      </div>

      <div class="field">
        <label for="password">Password</label>
        <input id="password" v-model="password" type="password"
               autocomplete="current-password" required />
      </div>

      <button type="submit" :disabled="pending">
        {{ pending ? 'Signing in…' : 'Sign in' }}
      </button>

      <p v-if="error" class="error" role="alert">{{ error }}</p>

      <p class="forgot"><NuxtLink to="/forgot-password">Forgot your password?</NuxtLink></p>
    </form>
  </main>
</template>

<style scoped>
.wrap {
  min-height: 100dvh;
  display: grid;
  place-items: center;
  padding: 1.5rem;
}
form { width: min(24rem, 100%); }
h1 { margin: 0; font-size: 1.5rem; }
.sub { margin: 0.25rem 0 1.5rem; color: var(--muted); font-size: 0.9rem; }
.field { margin-bottom: 1rem; }
button { width: 100%; }
.forgot { margin: 1.25rem 0 0; font-size: 0.875rem; text-align: center; }
</style>
