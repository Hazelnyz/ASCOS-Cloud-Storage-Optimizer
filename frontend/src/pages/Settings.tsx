import { LogOut } from 'lucide-react'
import { useAuth } from '@/context/authContext'
import { getConfig } from '@/config/env'
import { Button } from '@/components/common/Button'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useAsyncData } from '@/hooks/useAsyncData'
import { api } from '@/services/api'
import { useState } from 'react'

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between border-b border-surface-border/60 py-2.5 text-sm last:border-0">
      <span className="text-slate-400">{label}</span>
      <span className="font-mono text-xs text-slate-300">{value}</span>
    </div>
  )
}

export function Settings() {
  useDocumentTitle('Settings')
  const { user, signOut } = useAuth()
  const cfg = getConfig()
  const preferences = useAsyncData((signal) => api.getStoragePreferences({ signal }), [])
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  async function setAutoTierEnabled(enabled: boolean) {
    setSaving(true)
    setSaveError(null)
    try {
      const updated = await api.updateStoragePreferences({ auto_tier_enabled: enabled })
      preferences.mutate(() => updated)
    } catch {
      setSaveError('Could not save storage preferences. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="max-w-lg space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-slate-100">Settings</h2>
        <p className="text-sm text-slate-500">Account and connection details.</p>
      </div>

      <div className="rounded-xl border border-surface-border bg-surface-card p-4 shadow-panel">
        <h3 className="mb-2 text-sm font-semibold text-slate-100">Account</h3>
        <Row label="Email" value={user?.email ?? '—'} />
        <Row label="User ID" value={user?.userId ?? '—'} />
      </div>

      <div className="rounded-xl border border-surface-border bg-surface-card p-4 shadow-panel">
        <h3 className="mb-2 text-sm font-semibold text-slate-100">Connection</h3>
        <Row label="Region" value={cfg.awsRegion} />
        <Row label="API base URL" value={cfg.apiBaseUrl} />
      </div>

      <section aria-labelledby="storage-preferences-title" className="rounded-xl border border-surface-border bg-surface-card p-4 shadow-panel">
        <h3 id="storage-preferences-title" className="text-sm font-semibold text-slate-100">Storage Preferences</h3>
        <p className="mt-1 text-xs text-slate-400">Choose whether ASCOS may move your unpinned files between storage tiers automatically.</p>
        {preferences.loading && <div role="status" aria-label="Loading storage preferences" className="mt-4 h-12 animate-pulse rounded-lg bg-slate-800/70" />}
        {Boolean(preferences.error) && !preferences.loading && (
          <div className="mt-4 rounded-lg border border-red-900/60 bg-red-950/20 p-3 text-sm text-red-300" role="alert">
            <p>Storage preferences could not be loaded.</p>
            <button type="button" className="mt-2 underline" onClick={preferences.reload}>Try again</button>
          </div>
        )}
        {!preferences.loading && !preferences.error && preferences.data && (
          <div className="mt-4 divide-y divide-surface-border/60">
            <label className="flex cursor-pointer items-center justify-between gap-4 py-3">
              <span>
                <span className="block text-sm text-slate-200">Allow ASCOS to move my unpinned files between tiers automatically</span>
                <span className="mt-1 block text-xs text-slate-500">Automatic tier execution is not enabled yet.</span>
              </span>
              <input
                aria-label="Allow ASCOS to move my unpinned files between tiers automatically"
                type="checkbox"
                role="switch"
                className="h-4 w-4 accent-emerald-500"
                checked={preferences.data.auto_tier_enabled}
                disabled={saving}
                onChange={(event) => void setAutoTierEnabled(event.currentTarget.checked)}
              />
            </label>
            <div className="flex items-center justify-between gap-4 py-3 opacity-60">
              <span>
                <span className="block text-sm text-slate-300">Require confirmation before archiving to Cold</span>
                <span className="mt-1 block text-xs text-slate-500">Coming soon</span>
              </span>
              <input aria-label="Require confirmation before archiving to Cold (Coming soon)" type="checkbox" role="switch" disabled className="h-4 w-4" />
            </div>
            {saveError && <p role="alert" className="pt-3 text-sm text-red-300">{saveError}</p>}
          </div>
        )}
      </section>

      <Button variant="secondary" icon={<LogOut className="h-3.5 w-3.5" />} onClick={() => void signOut()}>Sign out</Button>
    </div>
  )
}
