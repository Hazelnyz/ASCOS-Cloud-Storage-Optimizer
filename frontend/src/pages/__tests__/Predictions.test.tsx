import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/services/api'
import type { FileSummary, Prediction } from '@/types'
import { Predictions } from '../Predictions'

vi.mock('@/services/api', () => ({
  api: {
    getFrequentlyUsed: vi.fn(),
    listFiles: vi.fn(),
  },
}))
vi.mock('@/hooks/useDocumentTitle', () => ({ useDocumentTitle: vi.fn() }))

const prediction: Prediction = {
  fileId: 'test-file-id',
  pAccess: 0.4,
  candidateTiers: [],
  banditChoice: null,
  predictionTimestamp: '2026-10-20T12:00:00Z',
  topReasons: [],
}

const file: FileSummary = {
  fileId: 'test-file-id',
  filename: 'test.txt',
  size: 12,
  lastModified: '2026-10-10T12:00:00Z',
  storageClass: 'STANDARD',
  uploadedAt: null,
  protected: false,
  pinnedAt: null,
}

describe('Predictions page', () => {
  beforeEach(() => {
    vi.mocked(api.getFrequentlyUsed).mockResolvedValue([prediction])
    vi.mocked(api.listFiles).mockResolvedValue([file])
  })

  it('does not infer Pinned from an older empty-candidate prediction when the live file is unpinned', async () => {
    render(<Predictions />)

    expect(await screen.findByText('test.txt')).toBeInTheDocument()
    expect(screen.queryByText('Pinned')).not.toBeInTheDocument()
  })
})
