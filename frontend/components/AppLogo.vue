<script setup lang="ts">
/**
 * The LumaIndex mark.
 *
 * Inlined rather than an <img> so it renders in the first paint with no extra
 * request, and because the tile carries its own background — it needs no
 * per-theme variant.
 */
const props = withDefaults(defineProps<{ size?: number }>(), { size: 24 })
</script>

<template>
  <svg class="logo" :width="props.size" :height="props.size" viewBox="0 0 64 64"
       role="img" aria-label="LumaIndex">
    <defs>
      <linearGradient :id="`lt-${props.size}`" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#5F5EE0" />
        <stop offset="1" stop-color="#3B3AAF" />
      </linearGradient>
      <linearGradient :id="`lp-${props.size}`" x1="0.5" y1="0" x2="0.5" y2="1">
        <stop offset="0" stop-color="#FFFDF7" />
        <stop offset="0.55" stop-color="#FFFFFF" />
        <stop offset="1" stop-color="#E9E7FB" />
      </linearGradient>
    </defs>
    <rect width="64" height="64" rx="15" :fill="`url(#lt-${props.size})`" />
    <rect x="15" y="11" width="34" height="42" rx="4.5" :fill="`url(#lp-${props.size})`" />
    <path d="M15 15.5A4.5 4.5 0 0 1 19.5 11h2.5v42h-2.5A4.5 4.5 0 0 1 15 48.5Z"
          fill="#2E2D96" />
    <path d="M33 11h9v21.5a1 1 0 0 1-1.6.8L37.5 31l-2.9 2.3a1 1 0 0 1-1.6-.8Z"
          fill="#F5A623" />
  </svg>
</template>

<style scoped>
.logo { display: block; flex: none; border-radius: 23.4%; }
</style>
