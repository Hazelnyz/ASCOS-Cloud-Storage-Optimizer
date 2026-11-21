// Two-step direct-to-S3 upload (Master Reference sections 4 and 8):
//   1. POST /files/upload-url  -> { fileId, uploadUrl, headers }
//   2. PUT the bytes straight to S3 with those exact headers.
// File bodies never pass through API Gateway or Lambda. A retry ALWAYS asks for
// a fresh upload URL (the previous one may have expired and belongs to a
// different fileId).

import { ApiError } from './errors'
import type { ASCOSApi } from './api'

/** S3 single-request PUT limit (5 GiB). Larger files would need multipart upload. */
export const MAX_SINGLE_PUT_BYTES = 5 * 1024 ** 3
export const MAX_FILENAME_LENGTH = 255

export interface UploadOptions {
  onProgress?: (fraction: number) => void
  signal?: AbortSignal
}

export function validateUploadFile(file: File): void {
  if (!file.name || !file.name.trim() || file.name.length > MAX_FILENAME_LENGTH) {
    throw new ApiError('validation', null, `File names must be 1-${MAX_FILENAME_LENGTH} characters.`)
  }
  if (file.size > MAX_SINGLE_PUT_BYTES) throw new ApiError('too_large')
}

/** True when a header value is plain printable ASCII (safe to send raw). */
function isPlainAscii(v: string): boolean {
  return /^[\x20-\x7E]+$/.test(v)
}

export function putWithProgress(
  url: string,
  body: Blob,
  headers: Record<string, string>,
  { onProgress, signal }: UploadOptions,
): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PUT', url)
    for (const [k, v] of Object.entries(headers)) xhr.setRequestHeader(k, v)

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total)
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress?.(1)
        resolve()
      } else if (xhr.status === 403) {
        reject(new ApiError('link_expired', 403))
      } else {
        reject(new ApiError('server', xhr.status))
      }
    }
    xhr.onerror = () => reject(new ApiError('network'))
    xhr.onabort = () => reject(new ApiError('aborted'))

    const abort = () => xhr.abort()
    if (signal) {
      if (signal.aborted) {
        reject(new ApiError('aborted'))
        return
      }
      signal.addEventListener('abort', abort, { once: true })
    }
    xhr.send(body)
  })
}

export async function uploadFile(
  api: ASCOSApi,
  file: File,
  options: UploadOptions = {},
): Promise<{ fileId: string }> {
  validateUploadFile(file)
  const ticket = await api.requestUploadTicket(file.name, { signal: options.signal })

  let headers = ticket.headers
  if (!headers) {
    // Older backend (before the Unicode filename fix) does not return headers:
    // the signed header is x-amz-meta-filename = the raw name. That is only safe
    // for plain ASCII, so refuse rather than send something S3 will reject.
    if (!isPlainAscii(file.name)) throw new ApiError('unsupported')
    headers = { 'x-amz-meta-filename': file.name }
  }

  await putWithProgress(ticket.uploadUrl, file, headers, options)
  return { fileId: ticket.fileId }
}
