import { Activity, Coins, Files as FilesIcon, HardDrive, Lightbulb, Sparkles } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useAsyncData } from '@/hooks/useAsyncData'
import { useAnalyticsSummary } from '@/hooks/useAnalyticsSummary'
import { api } from '@/services/api'
import { tierFromStorageClass, TIER_STORAGE_CLASS, type FileSummary, type StorageTier } from '@/types'
import { MetricCard } from '@/components/common/MetricCard'
import { Skeleton } from '@/components/common/Skeleton'
import { ErrorState } from '@/components/common/ErrorState'
import { EmptyState } from '@/components/common/EmptyState'
import { TierBadge } from '@/components/common/TierBadge'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { formatBytes, formatPercent, formatUsd, effectiveModified } from '@/lib/format'
import { formatEstimatedUsd } from '@/lib/budget'
import { TIER_COLORS } from '@/lib/tierColors'
import { countHighAccess, DASHBOARD_TIERS, formatDashboardRelativeTime, getTierStats, optimizationCandidates, recentFiles, recentRecommendations } from '@/lib/dashboard'

const TIER_RATES: Record<StorageTier, number> = {
  HOT: 0.025,
  WARM: 0.0138,
  COLD: 0.005,
}

function Card({ title, subtitle, children, action }: { title: string; subtitle?: string; children: React.ReactNode; action?: React.ReactNode }) {
  return <section className="min-w-0 overflow-hidden rounded-xl border border-surface-border bg-surface-card p-4 shadow-panel">
    <div className="mb-4 flex items-start justify-between gap-3"><div><h3 className="text-sm font-semibold text-slate-100">{title}</h3>{subtitle && <p className="mt-1 text-xs text-slate-500">{subtitle}</p>}</div>{action}</div>{children}
  </section>
}

function LoadingCard({ title }: { title: string }) {
  return <Card title={title}><div role="status" aria-label={`Loading ${title}`}><Skeleton className="mb-3 h-5 w-2/3" /><Skeleton className="mb-2 h-10 w-full" /><Skeleton className="h-3 w-1/2" /></div></Card>
}

function FileLabel({ file }: { file: FileSummary }) { return <span className="truncate" title={file.filename ?? file.fileId}>{file.filename || file.fileId}</span> }

export function Dashboard() {
  useDocumentTitle('Dashboard')
  const filesQuery = useAsyncData((signal) => api.listFiles({ signal }))
  const predictionsQuery = useAsyncData((signal) => api.getFrequentlyUsed({ signal }))
  const analyticsQuery = useAnalyticsSummary()
  const costQuery = useAsyncData((signal) => api.getCostSummary({ signal }))
  const files = filesQuery.data ?? []
  const predictions = predictionsQuery.data ?? []
  const tierStats = getTierStats(files)
  const recommendations = recentRecommendations(predictions, files)
  const candidates = optimizationCandidates(predictions, files)
  const protectedCount = files.filter((file) => file.protected === true).length
  const protectedKnown = files.every((file) => file.protected !== null)
  const totalBytes = files.reduce((sum, file) => sum + file.size, 0)
  const summary = analyticsQuery.data

  const fileMap = new Map(files.map((f) => [f.fileId, f]))
  const computedSavings = candidates.reduce((sum, pred) => {
    const f = pred.fileId ? fileMap.get(pred.fileId) : undefined
    const current = f ? tierFromStorageClass(f.storageClass) : null
    const target = pred.banditChoice ?? pred.candidateTiers[0]
    if (current && target && TIER_RATES[current] > TIER_RATES[target]) {
      const gb = (f?.size ?? 0) / (1024 ** 3)
      return sum + gb * (TIER_RATES[current] - TIER_RATES[target])
    }
    return sum
  }, 0)
  const optimizationSavings = summary?.optimization?.monthlySavings ?? (computedSavings > 0 ? computedSavings : null)

  const baselineCost = totalBytes > 0
    ? (tierStats.HOT.bytes / (1024 ** 3)) * TIER_RATES.HOT +
      (tierStats.WARM.bytes / (1024 ** 3)) * TIER_RATES.WARM +
      (tierStats.COLD.bytes / (1024 ** 3)) * TIER_RATES.COLD
    : 0
  const estimatedCost = costQuery.data
    ? formatEstimatedUsd(costQuery.data.estimated_spent)
    : formatEstimatedUsd(baselineCost)

  return <div className="min-w-0 space-y-5">
    <header><h2 className="text-lg font-semibold text-slate-100">Overview</h2><p className="text-sm text-slate-500">A snapshot of your storage, activity, and model recommendations.</p></header>

    <div className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {filesQuery.loading && !filesQuery.data ? <LoadingCard title="Total Files" /> : filesQuery.error ? <Card title="Total Files"><ErrorState error={filesQuery.error} onRetry={filesQuery.reload} title="File totals unavailable" /></Card> : <MetricCard label="Total Files" value={String(files.length)} icon={<FilesIcon className="h-4 w-4" aria-hidden="true" />} hint="Across all tiers" />}
      {filesQuery.loading && !filesQuery.data ? <LoadingCard title="Storage Used" /> : filesQuery.error ? <Card title="Storage Used"><ErrorState error={filesQuery.error} onRetry={filesQuery.reload} title="Storage total unavailable" /></Card> : <MetricCard label="Storage Used" value={formatBytes(totalBytes)} icon={<HardDrive className="h-4 w-4" aria-hidden="true" />} hint="Hot + Warm + Cold" />}
      {costQuery.loading && !costQuery.data && filesQuery.loading ? <LoadingCard title="Est. Monthly Cost" /> : <MetricCard label="Est. Monthly Cost" value={estimatedCost} icon={<Coins className="h-4 w-4" aria-hidden="true" />} hint="Based on current storage & rates" />}
      <MetricCard label="Optimization Opportunity" value={optimizationSavings !== null && optimizationSavings > 0 ? formatEstimatedUsd(optimizationSavings) : (candidates.length > 0 ? '<$0.01' : '$0.00')} icon={<Lightbulb className="h-4 w-4" aria-hidden="true" />} hint={candidates.length > 0 ? `${candidates.length} candidate file${candidates.length === 1 ? '' : 's'}` : 'All files in optimal tiers'} />
    </div>

    <div className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
      <Card title="Storage Tier Distribution" subtitle="Logical tiers - not separate buckets">
        {filesQuery.loading && !filesQuery.data ? <div role="status" aria-label="Loading storage tiers"><Skeleton className="mb-4 h-3 w-full" />{[1, 2, 3].map((n) => <Skeleton key={n} className="mb-4 h-12 w-full" />)}</div> : filesQuery.error ? <ErrorState error={filesQuery.error} onRetry={filesQuery.reload} title="Storage tiers unavailable" /> : files.length === 0 ? <EmptyState icon={<HardDrive className="h-5 w-5" />} title="No files yet" description="Upload a file to see its storage tier." /> : <div className="space-y-4">{DASHBOARD_TIERS.map((tier: StorageTier) => {
          const stats = tierStats[tier]
          return <div key={tier} className="min-w-0"><div className="mb-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1"><span className="flex items-center gap-2"><TierBadge tier={tier} /><span className="text-xs text-slate-500">{TIER_STORAGE_CLASS[tier]}</span></span><span className="text-right text-xs tabular-nums text-slate-400">{stats.count} {stats.count === 1 ? 'file' : 'files'} - {formatBytes(stats.bytes)} - {formatPercent(stats.percent)}</span></div><div className="h-2 w-full overflow-hidden rounded-full bg-white/5" role="img" aria-label={`${tier} ${formatPercent(stats.percent)} of files`}><div className="h-full rounded-full" style={{ width: `${stats.percent}%`, backgroundColor: TIER_COLORS[tier] }} /></div></div>
        })}</div>}
        <p className="mt-4 text-xs text-slate-500">Tier recommendations from the model. Select files in My Files to change tiers, or enable auto-tiering in Settings.</p>
      </Card>

      <Card title="AI Optimization Overview">
        {predictionsQuery.loading && !predictionsQuery.data ? <div role="status" aria-label="Loading AI optimization"><Skeleton className="mb-4 h-3 w-2/3" />{[1, 2, 3, 4].map((n) => <Skeleton key={n} className="mb-3 h-12 w-full" />)}</div> : predictionsQuery.error ? <ErrorState error={predictionsQuery.error} onRetry={predictionsQuery.reload} title="Predictions unavailable" /> : recommendations.length === 0 ? <EmptyState icon={<Sparkles className="h-5 w-5" />} title="No predictions yet" description="AI optimization stats will appear when files have predictions." /> : <>
          <div className="grid grid-cols-2 gap-3">{[
            ['Files Analyzed', String(recommendations.length), 'files with a latest prediction'],
            ['High-Access Predictions', String(countHighAccess(predictions)), 'p_access ≥ 0.7'],
            ['Optimization Candidates', String(candidates.length), 'unpinned tier changes'],
            ['Protected Files', protectedKnown ? String(protectedCount) : '—', protectedKnown ? 'pinned files' : 'Pin state unavailable'],
          ].map(([label, value, hint]) => <div key={label} className="rounded-lg border border-surface-border bg-surface-raised p-3"><p className="text-[11px] font-medium text-slate-400">{label}</p><p className="mt-1 text-xl font-semibold text-slate-100">{value}</p><p className="mt-1 text-[11px] text-slate-500">{hint}</p></div>)}</div>
          {(summary?.optimization || (optimizationSavings !== null && optimizationSavings > 0)) && <div className="mt-4 rounded-lg border border-emerald-400/20 bg-emerald-400/5 px-3 py-2"><p className="text-xs text-emerald-300">Predicted savings opportunity: <strong>{formatEstimatedUsd(summary?.optimization?.monthlySavings ?? optimizationSavings ?? 0)}/mo</strong></p></div>}
        </>}
      </Card>
    </div>

    <div className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-2">
      <Card title="Recent Files" subtitle="Most recently uploaded or modified">
        {filesQuery.loading && !filesQuery.data ? <div role="status" aria-label="Loading recent files">{[1, 2, 3, 4, 5].map((n) => <Skeleton key={n} className="mb-3 h-10 w-full" />)}</div> : filesQuery.error ? <ErrorState error={filesQuery.error} onRetry={filesQuery.reload} title="Recent files unavailable" /> : recentFiles(files).length === 0 ? <EmptyState icon={<Activity className="h-5 w-5" />} title="No recent files" description="Uploaded files will appear here." /> : <ul className="divide-y divide-surface-border/60">{recentFiles(files).slice(0, 5).map((file) => <li key={file.fileId} className="flex min-w-0 items-center justify-between gap-3 py-3"><span className="min-w-0 truncate text-sm font-medium text-slate-200"><FileLabel file={file} /></span><span className="flex shrink-0 items-center gap-2"><TierBadge tier={tierFromStorageClass(file.storageClass)} rawClass={file.storageClass} /><time className="text-xs text-slate-500" dateTime={effectiveModified(file)}>{formatDashboardRelativeTime(effectiveModified(file))}</time></span></li>)}</ul>}
      </Card>

      <Card title="Recent AI Recommendations" subtitle="Latest prediction for each file" action={<Link to="/predictions" className="text-xs font-medium text-indigo-300 hover:text-indigo-200">View all<span className="sr-only"> predictions</span></Link>}>
        {predictionsQuery.loading && !predictionsQuery.data ? <div role="status" aria-label="Loading recommendations">{[1, 2, 3, 4, 5].map((n) => <Skeleton key={n} className="mb-3 h-12 w-full" />)}</div> : predictionsQuery.error ? <ErrorState error={predictionsQuery.error} onRetry={predictionsQuery.reload} title="Recommendations unavailable" /> : recommendations.length === 0 ? <EmptyState icon={<Sparkles className="h-5 w-5" />} title="No predictions yet" description="Recommendations will appear when the model has analyzed files." /> : <ul className="divide-y divide-surface-border/60">{recommendations.slice(0, 5).map(({ prediction, file }, index) => {
          const tier = file ? tierFromStorageClass(file.storageClass) : null
          const pinned = file?.protected === true || (prediction.candidateTiers.length === 0 && !prediction.banditChoice)
          return <li key={prediction.fileId ?? index} className="min-w-0 py-3"><div className="flex min-w-0 items-center justify-between gap-3"><span className="min-w-0 truncate text-sm font-medium text-slate-200">{file?.filename || prediction.fileId || 'Unknown file'}</span><span className="shrink-0 text-xs font-medium tabular-nums text-slate-300">P(access) {prediction.pAccess === null ? '—' : `${Math.round(prediction.pAccess * 100)}%`}</span></div><div className="mt-1 flex min-w-0 flex-wrap items-center gap-1.5 text-xs text-slate-500">{pinned ? <><span>Pinned - no automatic change</span></> : <><span>Current:</span><TierBadge tier={tier} /><span aria-hidden="true">-&gt;</span><span>Candidates:</span>{prediction.candidateTiers.length ? prediction.candidateTiers.map((candidate) => <TierBadge key={candidate} tier={candidate} />) : <span>—</span>}</>}</div></li>
        })}</ul>}
      </Card>
    </div>
  </div>
}
