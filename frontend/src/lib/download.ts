/**
 * Start a browser download for a presigned URL. The backend sets
 * `Content-Disposition: attachment`, so the browser saves the file (with its
 * original name) instead of navigating away from the app.
 */
export function triggerDownload(url: string): void {
  const a = document.createElement('a')
  a.href = url
  a.rel = 'noopener noreferrer'
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  a.remove()
}
