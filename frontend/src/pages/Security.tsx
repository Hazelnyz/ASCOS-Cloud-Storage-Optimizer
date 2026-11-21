import { Activity, Clock3, Fingerprint, ShieldAlert, ShieldCheck } from 'lucide-react'
import { ErrorState } from '@/components/common/ErrorState'
import { Skeleton } from '@/components/common/Skeleton'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useSecuritySummary } from '@/hooks/useSecuritySummary'
import type { SecurityEventType, SecuritySummary } from '@/types'

const EVENT_BADGE_CLASSES: Record<SecurityEventType, string> = {
  download: 'border-blue-400/30 bg-blue-400/10 text-blue-300',
  write: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-300',
  delete: 'border-rose-400/30 bg-rose-400/10 text-rose-300',
  share: 'border-violet-400/30 bg-violet-400/10 text-violet-300',
}

const EVENT_TYPES: SecurityEventType[] = ['download', 'write', 'delete', 'share']
const EVENT_LABELS: Record<SecurityEventType, string> = {
  download: 'Download', write: 'Write', delete: 'Delete', share: 'Share',
}
const SEVERITY_BADGE_CLASSES = {
  Low: 'border-blue-400/30 bg-blue-400/10 text-blue-300',
  Medium: 'border-amber-400/30 bg-amber-400/10 text-amber-300',
  High: 'border-rose-400/30 bg-rose-400/10 text-rose-300',
}
const RULE_LABELS = {
  download_volume: 'Unusual download volume',
  delete_volume: 'Unusual delete volume',
}

function countTotal(counts: SecuritySummary['activity']['last24h']): number {
  return EVENT_TYPES.reduce((total, type) => total + counts[type], 0)
}

function displayCount(count: number, truncated: boolean): string {
  return truncated ? `${count}+` : String(count)
}

function Card({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <section className="min-w-0 overflow-hidden rounded-xl border border-surface-border bg-surface-card p-4 shadow-panel">
      <div className="mb-3 flex items-center gap-2 text-slate-400">
        {icon}
        <h3 className="text-sm font-semibold text-slate-100">{title}</h3>
      </div>
      {children}
    </section>
  )
}

function SecuritySkeleton() {
  return (
    <div className="space-y-5" role="status" aria-label="Loading security summary">
      <div className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((item) => (
          <section key={item} className="rounded-xl border border-surface-border bg-surface-card p-4">
            <Skeleton className="mb-4 h-4 w-36" />
            <Skeleton className="mb-2 h-7 w-28" />
            <Skeleton className="h-3 w-40" />
          </section>
        ))}
      </div>
      <section className="rounded-xl border border-surface-border bg-surface-card p-4">
        <Skeleton className="mb-4 h-4 w-40" />
        <Skeleton className="h-10 w-full" />
      </section>
      <section className="rounded-xl border border-surface-border bg-surface-card p-4">
        <Skeleton className="mb-4 h-4 w-44" />
        {[0, 1, 2, 3].map((item) => <Skeleton key={item} className="mb-2 h-12 w-full" />)}
      </section>
    </div>
  )
}

function ageLabel(timestamp: string, now = Date.now()): string {
  const parsed = new Date(timestamp).getTime()
  if (!Number.isFinite(parsed)) return 'Time unavailable'
  const seconds = Math.max(0, Math.floor((now - parsed) / 1000))
  if (seconds < 60) return 'Just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`
  const days = Math.floor(hours / 24)
  if (days === 0) return 'Today'
  if (days < 30) return `${days} day${days === 1 ? '' : 's'} ago`
  const months = Math.floor(days / 30)
  if (months < 12) return `${Math.max(1, months)} month${months <= 1 ? '' : 's'} ago`
  const years = Math.floor(days / 365)
  return `${years} year${years === 1 ? '' : 's'} ago`
}

function timestampLabel(timestamp: string): string {
  const parsed = new Date(timestamp)
  if (!Number.isFinite(parsed.getTime())) return 'Time unavailable'
  if (Date.now() - parsed.getTime() > 7 * 24 * 60 * 60 * 1000) {
    return parsed.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  }
  return ageLabel(timestamp)
}

function countLabel(count: number): string {
  return Number.isInteger(count) ? String(count) : count.toFixed(2)
}

export function Security() {
  useDocumentTitle('Security')
  const { data, error, loading, reload } = useSecuritySummary()

  if (loading && !data) return <SecuritySkeleton />
  if (error || !data) return <ErrorState error={error} onRetry={reload} title="Security summary could not be loaded" />

  return (
    <div className="min-w-0 space-y-5">
      <header>
        <h2 className="text-lg font-semibold text-slate-100">Security</h2>
        <p className="text-sm text-slate-500">Account security status and anomaly monitoring.</p>
      </header>

      <div className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card icon={<Fingerprint className="h-4 w-4 text-blue-400" aria-hidden="true" />} title="Authentication">
          <p className="text-xl font-semibold text-slate-100">{data.authentication.provider}</p>
          <p className="mt-1 text-xs text-slate-400">
            {data.authentication.lastSignIn
              ? <>Last sign-in <time dateTime={data.authentication.lastSignIn} title={ageLabel(data.authentication.lastSignIn)}>{timestampLabel(data.authentication.lastSignIn)}</time></>
              : 'Sign-in time is not available in this session.'}
          </p>
        </Card>

        <Card icon={<ShieldCheck className="h-4 w-4 text-emerald-400" aria-hidden="true" />} title="Protected Files">
          <p className="text-xl font-semibold text-slate-100">{data.protectedFiles.count}</p>
          <p className="mt-1 text-xs text-slate-400">
            {data.protectedFiles.count === 0 ? 'No protected files.' : 'Files protected from automatic tier changes.'}
          </p>
        </Card>

        <Card icon={<ShieldAlert className="h-4 w-4 text-amber-400" aria-hidden="true" />} title="Anomaly Monitoring">
          {data.anomaly.status === 'active' ? (
            <>
              <p className="text-xl font-semibold text-emerald-300">Active</p>
              <p className="mt-1 text-xs text-slate-400">
                Checked {data.anomaly.lastRun ? ageLabel(data.anomaly.lastRun) : 'time unavailable'}
              </p>
              <p className="mt-1 text-xs text-slate-400">{data.anomaly.openCount} in last 24h</p>
            </>
          ) : (
            <>
              <p className="text-xl font-semibold text-slate-100">Monitoring pending</p>
              <p className="mt-1 text-xs text-slate-400">Rule-based detection is being set up</p>
            </>
          )}
        </Card>

        <Card icon={<Activity className="h-4 w-4 text-indigo-400" aria-hidden="true" />} title="Recent Activity">
          <p className="text-xl font-semibold text-slate-100">{displayCount(countTotal(data.activity.last24h), data.activity.truncated)}</p>
          <p className="mt-1 text-xs text-slate-400">
            {displayCount(countTotal(data.activity.last7d), data.activity.truncated)} recorded in the last 7 days.
          </p>
        </Card>
      </div>

      <section className="min-w-0 rounded-xl border border-surface-border bg-surface-card p-4 shadow-panel" aria-label="Activity counts">
        <div className="grid min-w-0 grid-cols-1 gap-4 md:grid-cols-2">
          {([
            ['Last 24 hours', data.activity.last24h],
            ['Last 7 days', data.activity.last7d],
          ] as const).map(([period, counts]) => (
            <div key={period} className="min-w-0">
              <div className="mb-3 flex items-center justify-between gap-2">
                <h3 className="text-xs font-semibold text-slate-200">{period}</h3>
                {period === 'Last 7 days' && data.activity.truncated && (
                  <span className="text-xs text-slate-400">5,000+ events; counts are minimums</span>
                )}
              </div>
              <div className="flex flex-wrap gap-2">
                {EVENT_TYPES.map((type) => (
                  <span
                    key={type}
                    aria-label={`${period} ${EVENT_LABELS[type]} ${counts[type]}${data.activity.truncated ? '+' : ''}`}
                    className={`inline-flex items-center gap-2 rounded-md border px-2 py-1 text-xs font-medium ${EVENT_BADGE_CLASSES[type]}`}
                  >
                    {EVENT_LABELS[type]} <span className="tabular-nums">{counts[type]}{data.activity.truncated ? '+' : ''}</span>
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section aria-label="Recent Detections" className="min-w-0 overflow-hidden rounded-xl border border-surface-border bg-surface-card shadow-panel">
        <div className="border-b border-surface-border px-4 py-3">
          <div className="flex items-center gap-2">
            <Clock3 className="h-4 w-4 text-slate-400" aria-hidden="true" />
            <h3 className="text-sm font-semibold text-slate-100">Recent Detections</h3>
          </div>
          <p className="mt-1 pl-6 text-xs text-slate-400">Hourly download and delete volume rules. Status is logged; containment is not applied.</p>
        </div>
        {data.detections.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-slate-500">No detections recorded.</p>
        ) : (
          <ul className="divide-y divide-surface-border/70">
            {data.detections.map((detection) => (
              <li key={`${detection.windowStart}-${detection.rule}`} className="flex min-w-0 flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:gap-4">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-slate-100">{RULE_LABELS[detection.rule]}</p>
                  <p className="mt-1 text-xs text-slate-400">
                    {countLabel(detection.count)} events this hour (usual limit: {countLabel(detection.threshold)})
                  </p>
                  {detection.mode === 'learning' && <p className="mt-1 text-xs text-slate-500">Learning baseline</p>}
                </div>
                <div className="flex shrink-0 flex-wrap items-center gap-2">
                  <span className={`inline-flex items-center rounded-md border px-2 py-1 text-[11px] font-medium ${SEVERITY_BADGE_CLASSES[detection.severity]}`}>
                    {detection.severity}
                  </span>
                  <span className="inline-flex items-center rounded-md border border-slate-500/30 bg-slate-500/10 px-2 py-1 text-[11px] font-medium text-slate-300">
                    {detection.status}
                  </span>
                  <time className="text-xs text-slate-400" dateTime={detection.detectedAt} title={timestampLabel(detection.detectedAt)}>
                    {ageLabel(detection.detectedAt)}
                  </time>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}