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
    const detail = err?.data?.detail
    error.value = Array.isArray(detail) ? detail[0] : detail || 'Unable to sign in.'
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <main class="wrap">
    <form class="panel card" @submit.prevent="onSubmit">
      <div class="brand">
        <AppLogo :size="24" />
        <h1>LumaIndex</h1>
      </div>
      <p class="sub">Your PDF library.</p>

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

      <AppButton variant="primary" type="submit" :loading="pending" class="submit">
        {{ pending ? 'Signing in…' : 'Sign in' }}
      </AppButton>

      <p v-if="error" class="notice notice-error" role="alert">
        <AppIcon name="warning" :size="17" /> {{ error }}
      </p>

      <p class="forgot"><NuxtLink to="/forgot-password">Forgot your password?</NuxtLink></p>
    </form>
    <ThemeToggle class="theme" />
  </main>
</template>

<style scoped>
.wrap { min-height: 100dvh; display: grid; place-items: center; padding: var(--space-5);
        position: relative; }
.card { width: min(23rem, 100%); padding: var(--space-6); }
.brand { display: flex; align-items: center; gap: var(--space-3); }
h1 { margin: 0; font-size: var(--text-xl); }
.sub { margin: var(--space-2) 0 var(--space-5); color: var(--text-secondary); }
.field { margin-bottom: var(--space-4); }
.submit { width: 100%; }
.notice { margin-top: var(--space-4); }
.forgot { margin: var(--space-5) 0 0; text-align: center; font-size: var(--text-sm); }
.theme { position: absolute; top: var(--space-4); right: var(--space-4); }
</style>
