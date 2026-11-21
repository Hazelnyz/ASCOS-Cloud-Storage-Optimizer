// Tiny pub/sub so the HTTP layer can tell the auth layer "the session is dead"
// without importing React. AuthProvider subscribes; http.ts publishes.

type Listener = () => void
const listeners = new Set<Listener>()

export function onSessionExpired(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function notifySessionExpired(): void {
  listeners.forEach((l) => l())
}
