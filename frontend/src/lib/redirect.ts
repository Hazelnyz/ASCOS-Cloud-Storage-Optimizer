/**
 * Post-login redirect targets must be same-origin, app-relative paths. Anything
 * else (absolute URLs, protocol-relative //host, backslash tricks, the login
 * page itself) falls back to the dashboard, so a crafted link cannot bounce a
 * signed-in user to another site.
 */
export function safeRedirectPath(candidate: unknown): string {
  if (typeof candidate !== 'string') return '/'
  if (!candidate.startsWith('/') || candidate.startsWith('//')) return '/'
  if (candidate.includes('\\')) return '/'
  // eslint-disable-next-line no-control-regex -- deliberately rejecting raw control characters
  if (/[\u0000-\u001f]/.test(candidate)) return '/'
  if (candidate === '/login' || candidate.startsWith('/login?') || candidate.startsWith('/login/')) return '/'
  return candidate
}
