<script setup lang="ts">
const { user, logout } = useAuth()
const { api } = useApi()

// Proves the authenticated, same-origin API path works end to end.
const { data: health } = await useAsyncData('health', () =>
  api<{ status: string; checks: Record<string, string> }>('/health/ready/'),
)
</script>

<template>
  <main class="wrap">
    <header>
      <h1>LumaIndex</h1>
      <div class="who">
        <span>{{ user?.display_name || user?.email }}</span>
        <button class="secondary" type="button" @click="logout">Sign out</button>
      </div>
    </header>

    <section class="panel">
      <h2>Phase 1 — platform foundation</h2>
      <p>
        Authentication, the API, the database, and Google Drive import are wired
        up. The library views and the reader arrive in phases 3–4.
      </p>
      <dl>
        <dt>Backend</dt>
        <dd>{{ health?.status ?? 'unknown' }}</dd>
        <template v-for="(value, key) in health?.checks || {}" :key="key">
          <dt>{{ key }}</dt>
          <dd>{{ value }}</dd>
        </template>
      </dl>
      <p class="links">
        <NuxtLink to="/settings/drive">Google Drive</NuxtLink>
        <a href="/api/docs/">API documentation</a>
        <a v-if="user?.is_staff" href="/admin/">Django Admin</a>
      </p>
    </section>
  </main>
</template>

<style scoped>
.wrap { max-width: 60rem; margin: 0 auto; padding: 1.5rem; }
header { display: flex; flex-wrap: wrap; gap: 1rem; align-items: center;
         justify-content: space-between; margin-bottom: 1.5rem; }
h1 { font-size: 1.35rem; margin: 0; }
h2 { font-size: 1rem; margin: 0 0 0.5rem; }
.who { display: flex; align-items: center; gap: 0.75rem; color: var(--muted); font-size: 0.9rem; }
dl { display: grid; grid-template-columns: auto 1fr; gap: 0.35rem 1rem;
     font-size: 0.9rem; margin: 1.25rem 0 0; }
dt { color: var(--muted); }
dd { margin: 0; }
.links { display: flex; gap: 1rem; margin: 1.5rem 0 0; font-size: 0.9rem; }
</style>
