/**
 * The logic behind quick open (⌘K), kept out of the component so it can be
 * tested without a DOM.
 */

export interface Place {
  label: string
  icon: string
  to: string
  /** Other words someone might type for it. */
  aliases?: string[]
}

export const PLACES: Place[] = [
  { label: 'Reading now', icon: 'clock', to: '/', aliases: ['home', 'continue'] },
  { label: 'Library', icon: 'folder', to: '/library', aliases: ['books', 'files', 'folders'] },
  { label: 'Notebook', icon: 'notebook', to: '/notebook',
    aliases: ['highlights', 'notes', 'annotations', 'quotes'] },
  { label: 'Favourites', icon: 'star', to: '/library?view=favourites', aliases: ['starred'] },
  { label: 'Recently added', icon: 'inbox', to: '/library?view=recent', aliases: ['new'] },
  { label: 'Unsorted', icon: 'file', to: '/library?view=unsorted' },
  { label: 'Collections', icon: 'collection', to: '/collections' },
  { label: 'Shared with me', icon: 'inbox', to: '/shared' },
  { label: 'Trash', icon: 'trash', to: '/trash', aliases: ['deleted', 'bin'] },
  { label: 'Settings', icon: 'settings', to: '/settings',
    aliases: ['preferences', 'goal', 'theme', 'password', 'account'] },
]

/**
 * Places that match what was typed, best first.
 *
 * A word that starts the label beats one found inside it, and the label beats
 * an alias: typing "no" should offer Notebook before it offers Reading now
 * because of "now". Nothing typed means nothing to match, not everything.
 */
export function matchPlaces(query: string, places: Place[] = PLACES): Place[] {
  const q = query.trim().toLowerCase()
  if (!q) return []
  const score = (place: Place): number => {
    const label = place.label.toLowerCase()
    if (label.startsWith(q)) return 3
    if (label.split(/\s+/).some(word => word.startsWith(q))) return 2
    if (place.aliases?.some(alias => alias.startsWith(q))) return 1
    return 0
  }
  return places
    .map(place => ({ place, score: score(place) }))
    .filter(entry => entry.score > 0)
    .sort((a, b) => b.score - a.score)
    .map(entry => entry.place)
}

/** Move a highlight through a list with the arrow keys, wrapping at the ends. */
export function step(index: number, delta: number, length: number): number {
  if (length <= 0) return -1
  if (index < 0) return delta > 0 ? 0 : length - 1
  return (index + delta + length) % length
}

/** The shortcut as this machine spells it. */
export function shortcutLabel(platform: string): string {
  return /mac|iphone|ipad/i.test(platform) ? '⌘K' : 'Ctrl K'
}

/** Whether a key event is the quick-open shortcut. */
export function isQuickOpen(event: Pick<KeyboardEvent, 'key' | 'metaKey' | 'ctrlKey'
  | 'altKey' | 'shiftKey'>): boolean {
  return (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey
    && event.key.toLowerCase() === 'k'
}
