import { useEffect, useReducer, useRef } from 'react'
import { api } from '@/services/api'
import type { FileMetadata } from '@/types'

// The list endpoint returns ids/sizes only, so names come from
// GET /files/{id}/metadata. To avoid an uncontrolled N+1 burst this hook:
//   - fetches with a small concurrency limit,
//   - stops at a hard cap (files beyond it show "name loads on open"),
//   - caches results for the session (cleared on sign-out),
//   - cancels everything on unmount.

export const METADATA_CONCURRENCY = 4
export const METADATA_HYDRATE_CAP = 200

// Entries older than this are re-fetched the next time the file is shown (the old value stays
// on screen meanwhile), so access history (last accessed / recent accesses) does not stay
// frozen for the whole session after a download or share.
export const METADATA_TTL_MS = 30_000

const cache = new Map<string, FileMetadata>()
const fetchedAt = new Map<string, number>()
const failedIds = new Set<string>()

function isStale(id: string): boolean {
  return Date.now() - (fetchedAt.get(id) ?? 0) > METADATA_TTL_MS
}

export function clearMetadataCache(): void {
  cache.clear()
  fetchedAt.clear()
  failedIds.clear()
}

export function cacheMetadata(meta: FileMetadata): void {
  cache.set(meta.fileId, meta)
  fetchedAt.set(meta.fileId, Date.now())
  failedIds.delete(meta.fileId)
}

export function invalidateMetadata(fileId: string): void {
  cache.delete(fileId)
  fetchedAt.delete(fileId)
  failedIds.delete(fileId)
}

export function useFileMetadata(ids: string[], cap: number = METADATA_HYDRATE_CAP) {
  const [, rerender] = useReducer((n: number) => n + 1, 0)
  const key = ids.join('|')
  const idsRef = useRef(ids)
  idsRef.current = ids

  useEffect(() => {
    const controller = new AbortController()
    const queue = idsRef.current.slice(0, cap).filter((id) => (!cache.has(id) || isStale(id)) && !failedIds.has(id))
    let active = 0

    const pump = () => {
      while (!controller.signal.aborted && active < METADATA_CONCURRENCY && queue.length > 0) {
        const id = queue.shift() as string
        active += 1
        api
          .getFileMetadata(id, { signal: controller.signal })
          .then((meta) => cacheMetadata(meta))
          .catch(() => {
            if (!controller.signal.aborted) failedIds.add(id)
          })
          .finally(() => {
            active -= 1
            if (controller.signal.aborted) return
            rerender()
            pump()
          })
      }
    }
    pump()
    return () => controller.abort()
  }, [key, cap])

  const considered = ids.slice(0, cap)
  return {
    get: (id: string): FileMetadata | undefined => cache.get(id),
    failed: (id: string): boolean => failedIds.has(id),
    loadedCount: considered.filter((id) => cache.has(id)).length,
    pendingCount: considered.filter((id) => !cache.has(id) && !failedIds.has(id)).length,
    capped: ids.length > cap,
    cap,
  }
}
