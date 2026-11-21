import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConfirmDialog } from '../ConfirmDialog'

describe('ConfirmDialog', () => {
  it('shows the filename-specific message and calls onConfirm', async () => {
    const onConfirm = vi.fn()
    const user = userEvent.setup()
    render(
      <ConfirmDialog open title="Delete file?" confirmLabel="Delete" onConfirm={onConfirm} onCancel={() => {}}>
        <p><span>report.pdf</span> will be permanently deleted.</p>
      </ConfirmDialog>,
    )
    expect(screen.getByText('report.pdf')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Delete' }))
    expect(onConfirm).toHaveBeenCalledTimes(1)
  })

  it('shows a safe error message and keeps the dialog open (no raw backend text)', () => {
    render(
      <ConfirmDialog open title="Delete file?" confirmLabel="Delete" error="That file could not be found." onConfirm={() => {}} onCancel={() => {}}>
        content
      </ConfirmDialog>,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('That file could not be found.')
  })

  it('disables Cancel and hides the close button while busy', () => {
    render(
      <ConfirmDialog open title="Delete file?" confirmLabel="Delete" busy onConfirm={() => {}} onCancel={() => {}}>
        content
      </ConfirmDialog>,
    )
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Close dialog' })).toBeDisabled()
  })
})
