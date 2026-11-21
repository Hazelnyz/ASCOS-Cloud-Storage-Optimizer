import { useEffect, useRef, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'
import { MobileNav } from './MobileNav'
import { titleForPath } from './navItems'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { AssistantChat } from '@/components/common/AssistantChat'

export function Layout() {
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const location = useLocation()
  const mainRef = useRef<HTMLElement>(null)
  const firstRender = useRef(true)
  const title = titleForPath(location.pathname) ?? 'ASCOS'

  useDocumentTitle(title)

  // Move focus to the page content on navigation so keyboard/screen-reader
  // users land on the new page instead of staying on the nav link.
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false
      return
    }
    mainRef.current?.focus()
  }, [location.pathname])

  return (
    <div className="flex h-screen overflow-hidden bg-surface">
      <a href="#main" className="sr-skip">Skip to content</a>
      <Sidebar />
      <MobileNav open={mobileNavOpen} onClose={() => setMobileNavOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar title={title} onOpenMobileNav={() => setMobileNavOpen(true)} />
        <main id="main" ref={mainRef} tabIndex={-1} className="flex-1 overflow-y-auto p-4 outline-none sm:p-6">
          <div className="mx-auto max-w-7xl">
            <Outlet />
          </div>
        </main>
      </div>
      <AssistantChat />
    </div>
  )
}
