<script setup lang="ts">
const { api, ensureCsrf } = useApi()

const email = ref('')
const sent = ref(false)
const pending = ref(false)

async function onSubmit() {
  pending.value = true
  try {
    await ensureCsrf()
    await api('/auth/password/reset/', { method: 'POST', body: { email: email.value } })
  } catch {
    // Deliberately ignored. The endpoint answers the same way whether or not
    // the address exists, and the UI must not undo that by showing an error
    // only for unknown addresses.
  } finally {
    pending.value = false
    sent.value = true
  }
}
</script>

<template>
  <main class="wrap">
    <div class="panel card">
      <template v-if="!sent">
        <h1>Reset your password</h1>
        <p class="sub">We'll email you a link if this address has an account.</p>
        <form @submit.prevent="onSubmit">
          <div class="field">
            <label for="email">Email</label>
            <input id="email" v-model="email" type="email" autocomplete="username" required
                   autocapitalize="none" spellcheck="false" />
          </div>
          <AppButton variant="primary" type="submit" :loading="pending" class="submit">
            Send reset link
          </AppButton>
        </form>
      </template>
      <template v-else>
        <h1>Check your email</h1>
        <p class="sub">
          If an account exists for {{ email }}, a reset link is on its way.
          It expires in an hour.
        </p>
      </template>
      <p class="back"><NuxtLink to="/login">Back to sign in</NuxtLink></p>
    </div>
  </main>
</template>

<style scoped>
.wrap { min-height: 100dvh; display: grid; place-items: center; padding: var(--space-5); }
.card { width: min(23rem, 100%); padding: var(--space-6); }
h1 { margin: 0; font-size: var(--text-xl); }
.sub { margin: var(--space-2) 0 var(--space-5); color: var(--text-secondary); }
.field { margin-bottom: var(--space-4); }
.submit { width: 100%; }
.back { margin: var(--space-5) 0 0; font-size: var(--text-sm); text-align: center; }
</style>
