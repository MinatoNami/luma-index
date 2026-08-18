<script setup lang="ts">
const route = useRoute()
const { api, ensureCsrf } = useApi()

const password = ref('')
const confirm = ref('')
const error = ref('')
const done = ref(false)
const pending = ref(false)

async function onSubmit() {
  error.value = ''
  if (password.value !== confirm.value) {
    error.value = 'The two passwords do not match.'
    return
  }
  pending.value = true
  try {
    await ensureCsrf()
    await api('/auth/password/reset/confirm/', {
      method: 'POST',
      body: {
        uid: route.params.uid,
        token: route.params.token,
        new_password: password.value,
      },
    })
    done.value = true
  } catch (err: any) {
    const data = err?.data
    error.value = data?.detail
      || (Array.isArray(data?.new_password) ? data.new_password[0] : null)
      || 'This reset link is invalid or has expired.'
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <main class="wrap">
    <div class="panel">
      <template v-if="!done">
        <h1>Choose a new password</h1>
        <p class="sub">At least 12 characters.</p>
        <form @submit.prevent="onSubmit">
          <div class="field">
            <label for="password">New password</label>
            <input id="password" v-model="password" type="password"
                   autocomplete="new-password" required />
          </div>
          <div class="field">
            <label for="confirm">Confirm new password</label>
            <input id="confirm" v-model="confirm" type="password"
                   autocomplete="new-password" required />
          </div>
          <button type="submit" :disabled="pending">
            {{ pending ? 'Saving…' : 'Set new password' }}
          </button>
          <p v-if="error" class="error" role="alert">{{ error }}</p>
        </form>
      </template>
      <template v-else>
        <h1>Password updated</h1>
        <p class="sub">You can sign in with your new password now.</p>
      </template>
      <p class="back"><NuxtLink to="/login">Back to sign in</NuxtLink></p>
    </div>
  </main>
</template>

<style scoped>
.wrap { min-height: 100dvh; display: grid; place-items: center; padding: 1.5rem; }
.panel { width: min(24rem, 100%); }
h1 { margin: 0; font-size: 1.35rem; }
.sub { margin: 0.25rem 0 1.5rem; color: var(--muted); font-size: 0.9rem; }
.field { margin-bottom: 1rem; }
button { width: 100%; }
.back { margin: 1.25rem 0 0; font-size: 0.875rem; text-align: center; }
</style>
