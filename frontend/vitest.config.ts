import { defineVitestConfig } from '@nuxt/test-utils/config'

/**
 * Nuxt's own Vite config, so tests see what the app sees.
 *
 * Without it the composables here fail on `ref is not defined`: auto-imports
 * are a build-time transform, not a runtime global, so a plain Vitest setup
 * cannot load a file that never imported them.
 */
export default defineVitestConfig({
  test: {
    environment: 'nuxt',
    include: ['tests/**/*.test.ts'],
  },
})
