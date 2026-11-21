import { describe, it, expect } from 'vitest'
import { formatPAccess, formatRelativeShort } from '../format'

describe('formatPAccess', () => {
  it('renders null as an em dash, never a fabricated percentage', () => {
    expect(formatPAccess(null)).toBe('—')
  })

  it('renders a real probability as a percentage', () => {
    expect(formatPAccess(0.82)).toBe('82%')
  })
})

describe('formatRelativeShort', () => {
  const now = Date.parse('2026-10-03T12:00:00Z')
  it('renders null/invalid as an em dash', () => {
    expect(formatRelativeShort(null, now)).toBe('—')
    expect(formatRelativeShort('not a date', now)).toBe('—')
  })
  it('uses compact relative units', () => {
    expect(formatRelativeShort('2026-10-03T11:59:30Z', now)).toBe('Just now')
    expect(formatRelativeShort('2026-10-03T11:55:00Z', now)).toBe('5 min ago')
    expect(formatRelativeShort('2026-10-03T09:00:00Z', now)).toBe('3 h ago')
    expect(formatRelativeShort('2026-09-30T12:00:00Z', now)).toBe('3 d ago')
  })
  it('never goes negative for a timestamp slightly in the future (clock skew)', () => {
    expect(formatRelativeShort('2026-10-03T12:00:05Z', now)).toBe('Just now')
  })
})
