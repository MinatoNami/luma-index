import { describe, expect, it } from 'vitest'
import { ref } from 'vue'

import { useSelection, type SelectableItem } from '~/composables/useSelection'

const rows = (...items: [string, number][]): SelectableItem[] =>
  items.map(([kind, id]) => ({ kind: kind as 'folder' | 'book', id }))

const library = () => rows(['folder', 1], ['folder', 2], ['book', 10], ['book', 11], ['book', 12])

describe('ticking things', () => {
  it('starts with nothing selected and no toolbar', () => {
    const s = useSelection(ref(library()))

    expect(s.count.value).toBe(0)
    expect(s.active.value).toBe(false)
  })

  it('separates folders from books, whatever order they were ticked in', () => {
    const s = useSelection(ref(library()))

    s.toggle('book', 11)
    s.toggle('folder', 1)

    expect(s.folderIds.value).toEqual([1])
    expect(s.bookIds.value).toEqual([11])
  })

  it('toggles the same row off again', () => {
    const s = useSelection(ref(library()))

    s.toggle('book', 10)
    s.toggle('book', 10)

    expect(s.count.value).toBe(0)
  })

  it('does not confuse a folder with a book that shares its id', () => {
    const s = useSelection(ref(rows(['folder', 7], ['book', 7])))

    s.toggle('folder', 7)

    expect(s.folderIds.value).toEqual([7])
    expect(s.bookIds.value).toEqual([])
  })
})

describe('shift-clicking a range', () => {
  it('covers everything between the anchor and the click, inclusive', () => {
    const s = useSelection(ref(library()))

    s.toggle('folder', 2)
    s.extendTo('book', 11)

    expect(s.folderIds.value).toEqual([2])
    expect(s.bookIds.value).toEqual([10, 11])
  })

  it('reads the same range backwards', () => {
    const s = useSelection(ref(library()))

    s.toggle('book', 12)
    s.extendTo('folder', 2)

    expect(s.count.value).toBe(4)
  })

  it('spans the folder/book boundary, because the eye does', () => {
    const s = useSelection(ref(library()))

    s.toggle('folder', 1)
    s.extendTo('book', 10)

    expect(s.folderIds.value).toEqual([1, 2])
    expect(s.bookIds.value).toEqual([10])
  })

  it('follows the drawn order when files come first', () => {
    // What "Type / files first" produces: the same rows, flipped. A range
    // measured against the other order would take rows the user cannot see
    // between the two they clicked.
    const s = useSelection(ref(rows(['book', 10], ['book', 11], ['folder', 1], ['folder', 2])))

    s.toggle('book', 11)
    s.extendTo('folder', 1)

    expect(s.bookIds.value).toEqual([11])
    expect(s.folderIds.value).toEqual([1])
  })

  it('falls back to a plain toggle with nothing to measure from', () => {
    const s = useSelection(ref(library()))

    s.extendTo('book', 11)

    expect(s.bookIds.value).toEqual([11])
  })
})

describe('what a click means', () => {
  it('leaves a plain click to open the item', () => {
    const s = useSelection(ref(library()))

    const handled = s.handleClick('book', 10, new MouseEvent('click'))

    expect(handled).toBe(false)
    expect(s.count.value).toBe(0)
  })

  it('treats ctrl and cmd as select, not open', () => {
    const s = useSelection(ref(library()))

    expect(s.handleClick('book', 10, new MouseEvent('click', { ctrlKey: true }))).toBe(true)
    expect(s.handleClick('book', 11, new MouseEvent('click', { metaKey: true }))).toBe(true)
    expect(s.bookIds.value).toEqual([10, 11])
  })

  it('treats shift as a range', () => {
    const s = useSelection(ref(library()))

    s.handleClick('folder', 1, new MouseEvent('click', { ctrlKey: true }))
    const handled = s.handleClick('book', 10, new MouseEvent('click', { shiftKey: true }))

    expect(handled).toBe(true)
    expect(s.count.value).toBe(3)
  })
})

describe('select all and clear', () => {
  it('takes everything on the page', () => {
    const items = ref(library())
    const s = useSelection(items)

    s.selectAll()

    expect(s.count.value).toBe(5)
    expect(s.allSelected.value).toBe(true)
  })

  it('is not "all selected" on an empty listing', () => {
    const s = useSelection(ref([]))

    s.selectAll()

    expect(s.allSelected.value).toBe(false)
  })

  it('clears', () => {
    const s = useSelection(ref(library()))

    s.selectAll()
    s.clear()

    expect(s.count.value).toBe(0)
  })
})

describe('when the listing changes underneath', () => {
  it('drops the selection rather than keeping the survivors', async () => {
    // A still-ticked id from the folder you just left is a selection you cannot
    // see, and the toolbar would act on it.
    const items = ref(library())
    const s = useSelection(items)
    s.selectAll()

    items.value = rows(['book', 99])
    await Promise.resolve()

    expect(s.count.value).toBe(0)
  })

  it('keeps the selection when the same rows arrive again', async () => {
    // A background refresh returns a new array with the same contents; losing
    // the selection there would look like the app forgetting.
    const items = ref(library())
    const s = useSelection(items)
    s.toggle('book', 10)

    items.value = library()
    await Promise.resolve()

    expect(s.bookIds.value).toEqual([10])
  })
})
