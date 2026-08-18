<script setup lang="ts">
/**
 * Inline SVG icons.
 *
 * Replaces the emoji the listing used to draw with. Emoji render differently
 * on every platform, cannot inherit colour, and sit on the text baseline
 * rather than aligning to the row — all of which showed.
 */
const props = withDefaults(defineProps<{ name: string; size?: number | string }>(), {
  size: 18,
})

const PATHS: Record<string, string> = {
  folder: 'M3 6.5A2.5 2.5 0 0 1 5.5 4h3.2a2 2 0 0 1 1.5.7l1 1.2a1 1 0 0 0 .8.4h5.5A2.5 2.5 0 0 1 20 8.8v8.7a2.5 2.5 0 0 1-2.5 2.5h-12A2.5 2.5 0 0 1 3 17.5Z',
  file: 'M6 3.5A1.5 1.5 0 0 1 7.5 2h5.6a1.5 1.5 0 0 1 1.06.44l4.4 4.4A1.5 1.5 0 0 1 19 7.9v12.6a1.5 1.5 0 0 1-1.5 1.5h-10A1.5 1.5 0 0 1 6 20.5Z M13 2.5V7a1 1 0 0 0 1 1h4.5',
  upload: 'M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M4 15v3.5A2.5 2.5 0 0 0 6.5 21h11a2.5 2.5 0 0 0 2.5-2.5V15',
  'folder-plus': 'M3 6.5A2.5 2.5 0 0 1 5.5 4h3.2a2 2 0 0 1 1.5.7l1 1.2a1 1 0 0 0 .8.4h5.5A2.5 2.5 0 0 1 20 8.8v8.7a2.5 2.5 0 0 1-2.5 2.5h-12A2.5 2.5 0 0 1 3 17.5Z M11.5 11.5v5M9 14h5',
  search: 'M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14ZM20 20l-4-4',
  trash: 'M4 7h16M10 4h4a1 1 0 0 1 1 1v2H9V5a1 1 0 0 1 1-1ZM6 7l.8 12.1A2 2 0 0 0 8.8 21h6.4a2 2 0 0 0 2-1.9L18 7M10 11v6M14 11v6',
  restore: 'M4 12a8 8 0 1 0 2.5-5.8M4 4v4h4',
  download: 'M12 4v12m0 0 4.5-4.5M12 16l-4.5-4.5M4 17v1.5A2.5 2.5 0 0 0 6.5 21h11a2.5 2.5 0 0 0 2.5-2.5V17',
  pencil: 'M4 20h4L19 9a2.1 2.1 0 0 0-3-3L5 17Zm11-13 3 3',
  'arrow-up': 'M12 20V5m0 0-6 6m6-6 6 6',
  'chevron-right': 'M9 6l6 6-6 6',
  'list-view': 'M4 6h16M4 12h16M4 18h16',
  'grid-view': 'M4 5h6v6H4Zm10 0h6v6h-6ZM4 13h6v6H4Zm10 0h6v6h-6Z',
  'large-view': 'M4 4h7v7H4Zm9 0h7v7h-7ZM4 13h7v7H4Zm9 0h7v7h-7Z',
  sun: 'M12 5V3m0 18v-2m7-7h2M3 12h2m12.1-5.1 1.4-1.4M5.5 18.5l1.4-1.4m10.2 0 1.4 1.4M5.5 5.5l1.4 1.4M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z',
  moon: 'M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z',
  more: 'M12 6.5h.01M12 12h.01M12 17.5h.01',
  check: 'M5 12.5 10 17.5 19 7',
  close: 'M6 6l12 12M18 6 6 18',
  warning: 'M12 8.5v4.5m0 3h.01M10.3 3.9 2.6 17.4A2 2 0 0 0 4.3 20.4h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z',
  inbox: 'M4 13h4l1.5 3h5L16 13h4M4 13 6.8 5.7A2 2 0 0 1 8.7 4.4h6.6a2 2 0 0 1 1.9 1.3L20 13v5.5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z',
}

const segments = computed(() => (PATHS[props.name] ?? '').split(' M').map((d, i) => (i ? `M${d}` : d)))
</script>

<template>
  <svg class="icon" :width="props.size" :height="props.size" viewBox="0 0 24 24"
       fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"
       stroke-linejoin="round" aria-hidden="true" focusable="false">
    <path v-for="(d, i) in segments" :key="i" :d="d" />
  </svg>
</template>

<style scoped>
.icon { display: block; flex: none; }
</style>
