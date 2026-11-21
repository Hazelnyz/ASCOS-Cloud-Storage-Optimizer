import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Modal } from '../Modal'

describe('Modal', () => {
  it('traps Tab focus within the dialog and wraps at both ends', async () => {
    const user = userEvent.setup()
    render(
      <Modal open title="Test dialog" onClose={() => {}}>
        <button>First</button>
        <button>Second</button>
      </Modal>,
    )
    // The close button lives in the header, before the content in DOM order,
    // so it is the first focusable element - this is the trap's real,
    // deterministic order, not an assumption about which control "should" win.
    const closeBtn = screen.getByRole('button', { name: 'Close dialog' })
    const first = screen.getByRole('button', { name: 'First' })
    const second = screen.getByRole('button', { name: 'Second' })

    expect(closeBtn).toHaveFocus()
    await user.tab()
    expect(first).toHaveFocus()
    await user.tab()
    expect(second).toHaveFocus()
    await user.tab() // wraps back to the first focusable element
    expect(closeBtn).toHaveFocus()
    await user.tab({ shift: true }) // wraps backward too
    expect(second).toHaveFocus()
  })

  it('calls onClose on Escape when dismissible', async () => {
    const onClose = vi.fn()
    const user = userEvent.setup()
    render(<Modal open title="Test" onClose={onClose}><button>X</button></Modal>)
    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('ignores Escape when not dismissible (e.g. an action is in progress)', async () => {
    const onClose = vi.fn()
    const user = userEvent.setup()
    render(<Modal open title="Test" onClose={onClose} dismissible={false}><button>X</button></Modal>)
    await user.keyboard('{Escape}')
    expect(onClose).not.toHaveBeenCalled()
  })

  it('restores focus to the trigger element on close', () => {
    const trigger = document.createElement('button')
    trigger.textContent = 'Open'
    document.body.appendChild(trigger)
    trigger.focus()
    expect(trigger).toHaveFocus()

    const { rerender, unmount } = render(<Modal open={false} title="Test" onClose={() => {}}><button>X</button></Modal>)
    rerender(<Modal open title="Test" onClose={() => {}}><button>X</button></Modal>)
    rerender(<Modal open={false} title="Test" onClose={() => {}}><button>X</button></Modal>)
    expect(trigger).toHaveFocus()
    unmount()
    trigger.remove()
  })
})
