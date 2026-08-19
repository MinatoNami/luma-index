import type { Ref } from 'vue'

export type SelectionKind = 'folder' | 'book'
export interface SelectableItem { kind: SelectionKind; id: number }

const keyOf = (kind: SelectionKind, id: number) => `${kind[0]}${id}`

/**
 * Which rows are selected, and what a click means.
 *
 * `items` must be in the order they are drawn — folders then books — because
 * shift-click selects a *visual* range, and a range that follows some other
 * order would pick up rows the user cannot see between the two they clicked.
 *
 * Selection is dropped when the underlying list changes rather than filtered
 * down to survivors: after navigating into another folder, a still-ticked id
 * from the folder you left is a selection you cannot see, and the toolbar
 * would then act on it.
 */
export function useSelection(items: Ref<SelectableItem[]>) {
  const selected = ref(new Set<string>())
  // Where a shift-click measures from. Null until something is clicked.
  const anchor = ref<string | null>(null)

  const signature = computed(() => items.value.map(i => keyOf(i.kind, i.id)).join(','))
  watch(signature, () => clear())

  function has(kind: SelectionKind, id: number) {
    return selected.value.has(keyOf(kind, id))
  }

  function replace(next: Set<string>) {
    // A new Set rather than mutation, so template reads stay reactive.
    selected.value = next
  }

  function toggle(kind: SelectionKind, id: number) {
    const key = keyOf(kind, id)
    const next = new Set(selected.value)
    next.has(key) ? next.delete(key) : next.add(key)
    anchor.value = key
    replace(next)
  }

  /** Extend from the last clicked row to this one, inclusive. */
  function extendTo(kind: SelectionKind, id: number) {
    const key = keyOf(kind, id)
    const keys = items.value.map(i => keyOf(i.kind, i.id))
    const from = anchor.value ? keys.indexOf(anchor.value) : -1
    const to = keys.indexOf(key)
    if (from === -1 || to === -1) return toggle(kind, id)

    const [lo, hi] = from <= to ? [from, to] : [to, from]
    const next = new Set(selected.value)
    for (let i = lo; i <= hi; i++) next.add(keys[i])
    replace(next)
  }

  /**
   * Returns true when the click was a selection gesture and the caller should
   * not also open the item.
   */
  function handleClick(kind: SelectionKind, id: number, event: MouseEvent): boolean {
    if (event.shiftKey) {
      // Or the browser paints a text selection across every row in the range.
      window.getSelection()?.removeAllRanges()
      extendTo(kind, id)
      return true
    }
    if (event.metaKey || event.ctrlKey) {
      toggle(kind, id)
      return true
    }
    return false
  }

  function selectAll() {
    replace(new Set(items.value.map(i => keyOf(i.kind, i.id))))
  }

  function clear() {
    anchor.value = null
    if (selected.value.size) replace(new Set())
  }

  const count = computed(() => selected.value.size)
  const active = computed(() => count.value > 0)
  const folderIds = computed(() => items.value
    .filter(i => i.kind === 'folder' && selected.value.has(keyOf(i.kind, i.id)))
    .map(i => i.id))
  const bookIds = computed(() => items.value
    .filter(i => i.kind === 'book' && selected.value.has(keyOf(i.kind, i.id)))
    .map(i => i.id))
  const allSelected = computed(() =>
    items.value.length > 0 && count.value === items.value.length)

  return {
    selected, count, active, folderIds, bookIds, allSelected,
    has, toggle, extendTo, handleClick, selectAll, clear,
  }
}
