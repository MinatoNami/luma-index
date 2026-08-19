import type { Book } from '~/composables/useLibrary'

/**
 * Sending one large file in pieces, so a dropped connection is cheap.
 *
 * A single multipart POST is all-or-nothing. Over a link that drops every few
 * minutes — a relayed Tailscale path, hotel wifi, a phone — a 600 MB upload
 * never lands, and each attempt starts again from zero.
 *
 * The server's `received` is the only thing that decides where to send next.
 * A chunk that fails is retried from there; a chunk the server already has
 * comes back 409 with the real offset, which is a correction rather than an
 * error. Nothing here trusts its own idea of how far it got.
 */

/** Below this a plain POST is simpler and a retry costs little. */
export const CHUNKED_ABOVE_BYTES = 16 * 1024 * 1024

const MAX_ATTEMPTS_PER_CHUNK = 5
const BACKOFF_MS = [500, 1500, 4000, 10_000]

export interface ChunkProgress {
  file: string
  sent: number
  total: number
  /** 0–100, for anything that wants to draw a bar. */
  percent: number
}

interface StartResponse { id: number; received: number; size: number; chunk_size: number }

export function useChunkedUpload() {
  const { api, ensureCsrf } = useApi()

  const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

  async function begin(file: File, folder: number | null): Promise<StartResponse> {
    return await api<StartResponse>('/library/uploads/chunked/', {
      method: 'POST',
      body: { filename: file.name, size: file.size, folder },
    })
  }

  /**
   * Push one slice. Returns the server's new resume point.
   *
   * A 409 carries `received`, which is the truth — the caller seeks there and
   * carries on rather than failing the whole file.
   */
  async function putChunk(id: number, offset: number, blob: Blob): Promise<number> {
    const result = await api<{ received: number }>(
      `/library/uploads/chunked/${id}/`,
      { method: 'PUT', params: { offset: String(offset) }, body: blob,
        headers: { 'Content-Type': 'application/octet-stream' } },
    )
    return result.received
  }

  async function resumePoint(id: number): Promise<number> {
    const state = await api<{ received: number }>(`/library/uploads/chunked/${id}/`)
    return state.received
  }

  async function sendOne(
    file: File,
    folder: number | null,
    onProgress?: (p: ChunkProgress) => void,
  ): Promise<{ book: Book; outcome: string }> {
    await ensureCsrf()
    const started = await begin(file, folder)
    const chunkSize = started.chunk_size || 8 * 1024 * 1024
    let sent = started.received

    const report = () => onProgress?.({
      file: file.name,
      sent,
      total: file.size,
      percent: file.size ? Math.min(100, Math.round((sent / file.size) * 100)) : 100,
    })
    report()

    while (sent < file.size) {
      const end = Math.min(sent + chunkSize, file.size)
      let attempt = 0

      for (;;) {
        try {
          sent = await putChunk(started.id, sent, file.slice(sent, end))
          break
        } catch (err: any) {
          // The server knows where it is; take its word and continue.
          if (err?.status === 409 || err?.response?.status === 409) {
            const received = err?.data?.received ?? await resumePoint(started.id)
            sent = received
            break
          }
          // Anything else may be the link. Retry the same slice from the
          // server's resume point, since a partial write still counts.
          attempt += 1
          if (attempt >= MAX_ATTEMPTS_PER_CHUNK) throw err
          await sleep(BACKOFF_MS[Math.min(attempt - 1, BACKOFF_MS.length - 1)])
          try {
            sent = await resumePoint(started.id)
          } catch {
            // Could not even ask — let the next attempt's backoff cover it.
          }
        }
      }
      report()
    }

    return await api<{ book: Book; outcome: string }>(
      `/library/uploads/chunked/${started.id}/complete/`, { method: 'POST' },
    )
  }

  return { sendOne, CHUNKED_ABOVE_BYTES }
}
