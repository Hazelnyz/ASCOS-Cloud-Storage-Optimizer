import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useAnalyticsSummary } from '@/hooks/useAnalyticsSummary'
import { ErrorState } from '@/components/common/ErrorState'
import { Skeleton } from '@/components/common/Skeleton'
import { formatBytes, formatUsd } from '@/lib/format'
import { TIER_COLORS } from '@/lib/tierColors'
import { Cell, Legend, Line, Pie, PieChart, Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, ComposedChart, LabelList, TooltipProps } from 'recharts'
import { NameType, ValueType } from 'recharts/types/component/DefaultTooltipContent'

const TYPE_COLOR = '#818cf8'
const ACTIVITY_COLORS = { reads: '#6366f1', writes: '#f59e0b', downloads: '#0ea5e9' }

function dateTick(day: string): string {
  return new Date(`${day}T00:00:00Z`).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', timeZone: 'UTC',
  })
}

function DeduplicatedTooltip({ active, payload, label }: TooltipProps<ValueType, NameType>) {
  if (!active || !payload || !payload.length) return null

  const seen = new Set<string>()
  const deduplicatedPayload = payload.filter((item) => {
    const key = item.dataKey as string | undefined
    if (!key || seen.has(key)) return false
    seen.add(key)
    return true
  })

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900 p-3 shadow-lg">
      <p className="mb-2 text-xs font-medium text-slate-300">{dateTick(String(label))}</p>
      {deduplicatedPayload.map((entry, index) => (
        <div key={index} className="flex items-center gap-2 text-xs">
          <div className="h-2 w-2 rounded-full" style={{ backgroundColor: entry.color ?? '#818cf8' }} />
          <span className="text-slate-400">{entry.name ?? 'Unknown'}:</span>
          <span className="font-medium text-slate-100">{String(entry.value ?? 0)}</span>
        </div>
      ))}
    </div>
  )
}

function ChartCard({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section className="min-w-0 overflow-hidden rounded-xl border border-surface-border bg-surface-card p-5 shadow-panel">
      <div className="mb-4">
        <h3 className="text-sm font-semibold text-slate-100">{title}</h3>
        {subtitle && <p className="mt-1 text-xs text-slate-500">{subtitle}</p>}
      </div>
      {children}
    </section>
  )
}

function EmptyChart({ children }: { children: React.ReactNode }) {
  return <div className="flex h-64 items-center justify-center px-4 text-center text-sm text-slate-500">{children}</div>
}

function AnalyticsSkeleton() {
  return (
    <div className="space-y-5" role="status" aria-label="Loading analytics">
      <div className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-3">
        {[0, 1, 2].map((item) => (
          <section key={item} className="rounded-xl border border-surface-border bg-surface-card p-5">
            <Skeleton className="mb-5 h-4 w-40" />
            <Skeleton className="h-64 w-full" />
          </section>
        ))}
      </div>
      <section className="rounded-xl border border-surface-border bg-surface-card p-5">
        <Skeleton className="mb-5 h-4 w-40" />
        <Skeleton className="h-80 w-full" />
      </section>
    </div>
  )
}

export function Analytics() {
  useDocumentTitle('Analytics')
  const { data, error, loading, reload } = useAnalyticsSummary()

  if (loading && !data) return <AnalyticsSkeleton />
  if (error || !data) return <ErrorState error={error} onRetry={reload} title="Analytics could not be loaded" />

  const tierTotal = data.tiers.reduce((total, row) => total + row.files, 0)
  const storageHasData = data.storageOverTime.some((row) => row.bytes > 0)
  const firstNonZeroIndex = data.storageOverTime.findIndex((row) => row.bytes > 0)
  const storageData = firstNonZeroIndex > 0 ? data.storageOverTime.slice(Math.max(0, firstNonZeroIndex - 3)) : data.storageOverTime
  const storageStartDate = storageData[0]?.day
  const accessStartDate = data.access[0]?.day
  const accessEndDate = data.access[data.access.length - 1]?.day
  const accessSubtitle = accessStartDate && accessEndDate
    ? `Activity from ${dateTick(accessStartDate)} to ${dateTick(accessEndDate)} · reads, writes, downloads, shares`
    : 'Reads, writes, downloads, shares'

  return (
    <div className="min-w-0 space-y-5">
      <header>
        <h2 className="text-lg font-semibold text-slate-100">Analytics</h2>
        <p className="text-sm text-slate-500">Storage and access activity from your files and recorded events.</p>
      </header>

      <div className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-3">
        <ChartCard title="Storage Usage Over Time" subtitle={storageStartDate ? `Since ${dateTick(storageStartDate)}` : undefined}>
          {!storageHasData ? <EmptyChart>No files uploaded yet.</EmptyChart> : (
            <div className="h-64 min-w-0">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={storageData} margin={{ top: 8, right: 24, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="storageFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#6366f1" stopOpacity={0.35} />
                      <stop offset="100%" stopColor="#6366f1" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#273244" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="day" tickFormatter={dateTick} tick={{ fill: '#94a3b8', fontSize: 11 }} minTickGap={24} axisLine={false} />
                  <YAxis tickFormatter={(value: number) => formatBytes(value)} tick={{ fill: '#94a3b8', fontSize: 11 }} width={58} axisLine={false} />
                  <Tooltip labelFormatter={(label) => dateTick(String(label))} formatter={(value) => [formatBytes(Number(value)), 'Storage']} contentStyle={{ background: '#151b26', border: '1px solid #2a3140', borderRadius: 8, color: '#e2e8f0' }} />
                  <Area type="monotone" dataKey="bytes" name="Storage" stroke="#6366f1" fill="url(#storageFill)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </ChartCard>

        <ChartCard title="Storage Tier Distribution">
          {tierTotal === 0 ? <EmptyChart>No files uploaded yet.</EmptyChart> : (
            <div className="relative h-64 min-w-0">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={data.tiers} dataKey="files" nameKey="tier" innerRadius="52%" outerRadius="78%" paddingAngle={3} stroke="#151b26" strokeWidth={2}>
                    {data.tiers.map((row) => <Cell key={row.tier} fill={TIER_COLORS[row.tier]} />)}
                  </Pie>
                  <Tooltip formatter={(value, name) => [`${value} files`, name]} contentStyle={{ background: '#151b26', border: '1px solid #2a3140', borderRadius: 8, color: '#e2e8f0' }} />
                  <Legend verticalAlign="bottom" height={28} formatter={(value) => <span className="text-xs text-slate-400">{value}</span>} />
                </PieChart>
              </ResponsiveContainer>
              <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-2xl font-semibold text-slate-100">{tierTotal}</span>
                <span className="text-xs text-slate-500">files</span>
              </div>
            </div>
          )}
        </ChartCard>

        <ChartCard title="Files by Type">
          {data.types.length === 0 ? <EmptyChart>No files uploaded yet.</EmptyChart> : (
            <div className="min-w-0" style={{ height: Math.max(256, data.types.length * 34) }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.types} layout="vertical" margin={{ top: 0, right: 48, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke="#273244" strokeDasharray="3 3" horizontal={false} />
                  <XAxis type="number" allowDecimals={false} tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} />
                  <YAxis type="category" dataKey="type" interval={0} width={78} tick={{ fill: '#cbd5e1', fontSize: 11 }} axisLine={false} />
                  <Tooltip formatter={(value) => [`${value} files`, 'Files']} contentStyle={{ background: '#151b26', border: '1px solid #2a3140', borderRadius: 8, color: '#e2e8f0' }} />
                  <Bar dataKey="files" name="Files" fill={TYPE_COLOR} radius={[0, 4, 4, 0]}>
                    <LabelList dataKey="files" position="right" fill="#94a3b8" fontSize={11} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </ChartCard>
      </div>

      <ChartCard title="Access Activity" subtitle={accessSubtitle}>
        {data.access.length === 0 ? <EmptyChart>Access activity will appear once reads, writes and downloads are logged.</EmptyChart> : (
          <div className="h-80 min-w-0">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={data.access} margin={{ top: 8, right: 24, left: 0, bottom: 32 }}>
                <defs>
                  <linearGradient id="readsFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={ACTIVITY_COLORS.reads} stopOpacity={0.25} />
                    <stop offset="100%" stopColor={ACTIVITY_COLORS.reads} stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="writesFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={ACTIVITY_COLORS.writes} stopOpacity={0.25} />
                    <stop offset="100%" stopColor={ACTIVITY_COLORS.writes} stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="downloadsFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={ACTIVITY_COLORS.downloads} stopOpacity={0.25} />
                    <stop offset="100%" stopColor={ACTIVITY_COLORS.downloads} stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="sharesFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#a855f7" stopOpacity={0.25} />
                    <stop offset="100%" stopColor="#a855f7" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#273244" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="day" tickFormatter={dateTick} tick={{ fill: '#94a3b8', fontSize: 11 }} minTickGap={24} interval="preserveStartEnd" axisLine={false} />
                <YAxis allowDecimals={false} tick={{ fill: '#94a3b8', fontSize: 11 }} width={34} axisLine={false} />
                <Tooltip content={<DeduplicatedTooltip />} />
                <Legend verticalAlign="bottom" height={32} formatter={(value) => <span className="text-xs text-slate-400">{value}</span>} />
                <Area type="monotone" dataKey="reads" stroke={ACTIVITY_COLORS.reads} strokeWidth={2} fill="url(#readsFill)" dot={false} activeDot={false} isAnimationActive={false} />
                <Area type="monotone" dataKey="writes" stroke={ACTIVITY_COLORS.writes} strokeWidth={2} fill="url(#writesFill)" dot={false} activeDot={false} isAnimationActive={false} />
                <Area type="monotone" dataKey="downloads" stroke={ACTIVITY_COLORS.downloads} strokeWidth={2} fill="url(#downloadsFill)" dot={false} activeDot={false} isAnimationActive={false} />
                <Area type="monotone" dataKey="shares" stroke="#a855f7" strokeWidth={2} fill="url(#sharesFill)" dot={false} activeDot={false} isAnimationActive={false} />
                <Line type="monotone" dataKey="reads" name="Reads" stroke={ACTIVITY_COLORS.reads} strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} />
                <Line type="monotone" dataKey="writes" name="Writes" stroke={ACTIVITY_COLORS.writes} strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} />
                <Line type="monotone" dataKey="downloads" name="Downloads" stroke={ACTIVITY_COLORS.downloads} strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} />
                <Line type="monotone" dataKey="shares" name="Shares" stroke="#a855f7" strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}
      </ChartCard>

      {data.optimization !== null && (
        <aside className="rounded-xl border border-emerald-400/20 bg-emerald-400/5 px-5 py-4">
          <p className="text-xs font-medium uppercase text-emerald-300">Estimated optimization opportunity</p>
          <p className="mt-1 text-xl font-semibold text-slate-100">{formatUsd(data.optimization.monthlySavings)} / month</p>
          <p className="mt-1 text-xs text-slate-400">Estimated storage-cost difference using current tiers, stored recommendations, and forecast-plan per-GB rates. Not live AWS billing.</p>
        </aside>
      )}
    </div>
  )
}