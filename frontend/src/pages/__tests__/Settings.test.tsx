import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/services/api'
import { Settings } from '../Settings'

vi.mock('@/services/api', () => ({
  api: {
    getStoragePreferences: vi.fn(async () => ({ auto_tier_enabled: false })),
    updateStoragePreferences: vi.fn(async (value) => value),
  },
}))
vi.mock('@/hooks/useDocumentTitle', () => ({ useDocumentTitle: vi.fn() }))
vi.mock('@/context/authContext', () => ({ useAuth: () => ({ user: { email: 'a@example.com', userId: 'user-a' }, signOut: vi.fn() }) }))
vi.mock('@/config/env', () => ({ getConfig: () => ({ awsRegion: 'ap-south-1', apiBaseUrl: 'https://example.invalid' }) }))

describe('Settings storage preferences', () => {
  beforeEach(() => vi.clearAllMocks())

  it('loads and saves the live toggle; leaves the coming-soon toggle disabled', async () => {
    render(<Settings />)
    const liveToggle = await screen.findByRole('switch', { name: 'Allow ASCOS to move my unpinned files between tiers automatically' })
    expect(liveToggle).not.toBeChecked()
    fireEvent.click(liveToggle)
    await waitFor(() => expect(api.updateStoragePreferences).toHaveBeenCalledWith({ auto_tier_enabled: true }))

    const comingSoon = screen.getByRole('switch', { name: 'Require confirmation before archiving to Cold (Coming soon)' })
    expect(comingSoon).toBeDisabled()
    expect(api.updateStoragePreferences).toHaveBeenCalledTimes(1)
  })
})
