import { describe, it, expect } from 'vitest'
import { safeRedirectPath } from '../redirect'

describe('safeRedirectPath', () => {
  it('accepts a plain app-relative path', () => {
    expect(safeRedirectPath('/files')).toBe('/files')
  })

  it('rejects an absolute external URL', () => {
    expect(safeRedirectPath('https://evil.example.com')).toBe('/')
  })

  it('rejects a protocol-relative URL (open-redirect vector)', () => {
    expect(safeRedirectPath('//evil.example.com')).toBe('/')
  })

  it('rejects a backslash trick some browsers normalise to //', () => {
    expect(safeRedirectPath('/\\evil.example.com')).toBe('/')
  })

  it('rejects a path containing control characters', () => {
    expect(safeRedirectPath('/files\u0000')).toBe('/')
  })

  it('rejects a path not starting with /', () => {
    expect(safeRedirectPath('files')).toBe('/')
  })

  it('rejects looping back to the login page', () => {
    expect(safeRedirectPath('/login')).toBe('/')
    expect(safeRedirectPath('/login?next=/files')).toBe('/')
  })

  it('falls back to / for a non-string value', () => {
    expect(safeRedirectPath(undefined)).toBe('/')
    expect(safeRedirectPath(42)).toBe('/')
  })
})
