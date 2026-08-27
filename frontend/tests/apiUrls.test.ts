import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * No root-absolute API URL may be written by hand.
 *
 * The app can be served under a path prefix (LUMA_BASE_PATH), and everything
 * that goes through `useApi` picks that up. What does not go through it are the
 * URLs the *browser* follows rather than the app fetches — `<img src>`,
 * `window.open`, the one PDF.js is handed. Those were written as `/api/...`
 * literals, which is invisible while the app owns the origin and breaks every
 * cover, every download and the reader itself the moment it is behind a prefix.
 *
 * This is a lint rather than a behaviour test on purpose: the failure has no
 * symptom in a unit test, only in a deployment nobody has yet.
 */

// process.cwd(), not import.meta.url: Vite rewrites the latter to a /@fs/…
// path that readdirSync cannot open, so the scan silently found nothing and
// the guard passed while the bug it guards against was in the tree.
const ROOT = process.cwd()
const SEARCH = ['components', 'pages', 'composables', 'layouts']

// useApi.ts is where the base actually lives, and the e2e suite runs against an
// instance with no prefix, in page context, where a relative path is correct.
const ALLOWED = ['composables/useApi.ts']

function sourceFiles(dir: string): string[] {
  const here = join(ROOT, dir)
  let entries: string[]
  try {
    entries = readdirSync(here)
  } catch {
    return []
  }
  return entries.flatMap((name) => {
    const full = join(here, name)
    if (statSync(full).isDirectory()) return sourceFiles(join(dir, name))
    return /\.(vue|ts)$/.test(name) ? [join(dir, name)] : []
  })
}

describe('API URLs', () => {
  it('are never written as root-absolute literals', () => {
    const offenders: string[] = []

    for (const file of SEARCH.flatMap(sourceFiles)) {
      if (ALLOWED.includes(file)) continue
      const text = readFileSync(join(ROOT, file), 'utf8')
      text.split('\n').forEach((line, index) => {
        // `"/api/…` or `` `/api/… `` — a literal that ignores the base.
        if (/["'`]\/api\//.test(line)) {
          offenders.push(`${file}:${index + 1}  ${line.trim().slice(0, 72)}`)
        }
      })
    }

    expect(offenders, [
      'These build an API URL that ignores LUMA_BASE_PATH.',
      'Use useApiUrl() — it returns a browser-reachable URL for a path',
      'given without the /api prefix.',
      '',
      ...offenders,
    ].join('\n')).toEqual([])
  })

  it('finds the files it is meant to be scanning', () => {
    // A guard whose glob quietly matches nothing passes forever.
    const files = SEARCH.flatMap(sourceFiles)
    expect(files.length).toBeGreaterThan(15)
    expect(files).toContain('components/BookCover.vue')
  })
})
