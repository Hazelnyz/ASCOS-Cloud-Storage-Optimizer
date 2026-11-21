import { useState, useMemo } from 'react'
import { Sparkles, TrendingUp, TrendingDown, Minus } from 'lucide-react'
import { useAsyncData } from '@/hooks/useAsyncData'
import { api } from '@/services/api'
import { TierBadge } from '@/components/common/TierBadge'
import { Skeleton } from '@/components/common/Skeleton'
import { EmptyState } from '@/components/common/EmptyState'
import { ErrorState } from '@/components/common/ErrorState'
import { MetricCard } from '@/components/common/MetricCard'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { dedupePredictions, bandOf, countByBand, type Band } from '@/lib/predictions'
import { tierFromStorageClass, type FileSummary, type Prediction } from '@/types'

export function Predictions() {
  useDocumentTitle('AI Predictions')
  
  const [activeBand, setActiveBand] = useState<Band | null>(null)
  const [sortColumn, setSortColumn] = useState<'p_access' | 'prediction_timestamp'>('p_access')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc')

  const { data: predictions, error: predictionsError, loading: predictionsLoading, reload: reloadPredictions } = useAsyncData(
    (signal) => api.getFrequentlyUsed({ signal })
  )
  
  const { data: files, error: filesError, loading: filesLoading, reload: reloadFiles } = useAsyncData(
    (signal) => api.listFiles({ signal })
  )

  const { data: preferences } = useAsyncData(
    (signal) => (typeof api.getStoragePreferences === 'function' ? api.getStoragePreferences({ signal }) : Promise.resolve(null))
  )

  const [isAutoTiering, setIsAutoTiering] = useState(false)
  const [autoTierProgress, setAutoTierProgress] = useState<string | null>(null)
  const [autoTierResult, setAutoTierResult] = useState<{ success: number; failed: number } | null>(null)

  const error = predictionsError || filesError
  const loading = predictionsLoading || filesLoading

  if (error) return <ErrorState error={error} onRetry={reloadPredictions} />

  // Dedupe and join with file metadata
  const deduped = useMemo(() => dedupePredictions(predictions ?? []), [predictions])
  
  const fileMap = useMemo(() => {
    const map = new Map<string, FileSummary>()
    for (const file of files ?? []) {
      map.set(file.fileId, file)
    }
    return map
  }, [files])

  const joined = useMemo(() => {
    return deduped.map(p => ({
      ...p,
      file: fileMap.get(p.fileId ?? '') || null
    }))
  }, [deduped, fileMap])

  // Filter by band
  const filtered = useMemo(() => {
    if (!activeBand) return joined
    return joined.filter(row => bandOf(row.pAccess) === activeBand)
  }, [joined, activeBand])

  // Sort
  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      let comparison = 0
      if (sortColumn === 'p_access') {
        comparison = (a.pAccess ?? 0) - (b.pAccess ?? 0)
      } else if (sortColumn === 'prediction_timestamp') {
        comparison = (a.predictionTimestamp || '').localeCompare(b.predictionTimestamp || '')
      }
      return sortDirection === 'asc' ? comparison : -comparison
    })
  }, [filtered, sortColumn, sortDirection])

  // Stats
  const bandCounts = useMemo(() => countByBand(deduped), [deduped])
  const newestTimestamp = useMemo(() => {
    if (deduped.length === 0) return null
    return deduped.reduce((max, p) => 
      (p.predictionTimestamp && p.predictionTimestamp > max) ? p.predictionTimestamp : max, ''
    )
  }, [deduped])

  const candidateRows = useMemo(() => {
    return joined.filter(row => {
      if (!row.file || row.file.protected) return false
      const current = tierFromStorageClass(row.file.storageClass)
      const target = row.banditChoice || (row.candidateTiers.length > 0 ? row.candidateTiers[0] : null)
      return Boolean(current && target && current !== target)
    })
  }, [joined])

  const handleRunAutoTier = async () => {
    if (candidateRows.length === 0 || isAutoTiering) return
    setIsAutoTiering(true)
    setAutoTierResult(null)
    let success = 0
    let failed = 0

    for (let i = 0; i < candidateRows.length; i++) {
      const row = candidateRows[i]
      const file = row.file!
      const target = row.banditChoice || row.candidateTiers[0]
      setAutoTierProgress(`Migrating ${file.filename || file.fileId} to ${target} (${i + 1}/${candidateRows.length})...`)
      try {
        await api.changeTier(file.fileId, { targetTier: target as any })
        success++
      } catch (err) {
        console.error(`Auto-tier failed for ${file.fileId}:`, err)
        failed++
      }
    }

    setAutoTierProgress(null)
    setIsAutoTiering(false)
    setAutoTierResult({ success, failed })
    reloadFiles?.()
    reloadPredictions?.()
  }

  const handleSingleAutoTier = async (fileId: string, targetTier: any) => {
    try {
      await api.changeTier(fileId, { targetTier })
      reloadFiles?.()
      reloadPredictions?.()
    } catch (err) {
      console.error(`Tier change failed for ${fileId}:`, err)
    }
  }

  // Loading state
  if (loading && (!predictions || !files)) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map(i => (
            <div key={i} className="rounded-xl border border-surface-border bg-surface-card p-4">
              <Skeleton className="h-4 w-24 mb-2" />
              <Skeleton className="h-8 w-16 mb-2" />
              <Skeleton className="h-3 w-32" />
            </div>
          ))}
        </div>
        <div className="rounded-xl border border-surface-border bg-surface-card p-4">
          <Skeleton className="h-4 w-full mb-4" />
          {[1, 2, 3, 4, 5].map(i => (
            <Skeleton key={i} className="h-12 w-full mb-2" />
          ))}
        </div>
      </div>
    )
  }

  // Empty state
  if (deduped.length === 0) {
    return (
      <EmptyState
        icon={<Sparkles className="h-5 w-5" />}
        title="No predictions yet"
        description="Predictions are generated by a scheduled batch job."
      />
    )
  }

  const formatDate = (iso: string) => {
    const date = new Date(iso)
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  }

  const handleSort = (column: 'p_access' | 'prediction_timestamp') => {
    if (sortColumn === column) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
    } else {
      setSortColumn(column)
      setSortDirection('desc')
    }
  }

  const topReasonsText = (topReasons: Prediction['topReasons']) => {
    if (!topReasons || topReasons.length === 0) return '-'
    return topReasons.slice(0, 3).map(r => r.feature).join(', ')
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-100">AI Predictions</h2>
          <p className="text-sm text-slate-500">
            Per-file access-probability predictions from your access activity.
          </p>
          {newestTimestamp && (
            <p className="mt-1 text-xs text-slate-500">
              Last updated: {formatDate(newestTimestamp)}
            </p>
          )}
        </div>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="FILES ANALYZED"
          value={String(deduped.length)}
          icon={<Sparkles className="h-4 w-4" />}
          hint="Distinct files with predictions"
        />
        <MetricCard
          label="HIGH PROBABILITY"
          value={String(bandCounts.high)}
          icon={<TrendingUp className="h-4 w-4" />}
          hint="p_access >= 0.7"
          onClick={() => setActiveBand(activeBand === 'high' ? null : 'high')}
        />
        <MetricCard
          label="MEDIUM PROBABILITY"
          value={String(bandCounts.medium)}
          icon={<Minus className="h-4 w-4" />}
          hint="0.3 <= p_access < 0.7"
          onClick={() => setActiveBand(activeBand === 'medium' ? null : 'medium')}
        />
        <MetricCard
          label="LOW PROBABILITY"
          value={String(bandCounts.low)}
          icon={<TrendingDown className="h-4 w-4" />}
          hint="p_access < 0.3"
          onClick={() => setActiveBand(activeBand === 'low' ? null : 'low')}
        />
      </div>

      {/* Auto-Tiering Banner */}
      <div className="rounded-xl border border-indigo-500/30 bg-indigo-500/10 p-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-indigo-400" />
              <h3 className="text-sm font-semibold text-slate-100">Automatic Storage Tier Optimization</h3>
              {preferences?.auto_tier_enabled && (
                <span className="rounded-full bg-emerald-400/20 px-2 py-0.5 text-xs font-medium text-emerald-300">
                  Auto-Tier Enabled
                </span>
              )}
            </div>
            <p className="text-xs text-slate-400">
              {candidateRows.length > 0
                ? `${candidateRows.length} unpinned file${candidateRows.length === 1 ? '' : 's'} have candidate recommendations different from their current tier.`
                : 'All analyzed files are currently stored in their optimal tiers.'}
            </p>
          </div>
          <button
            onClick={handleRunAutoTier}
            disabled={candidateRows.length === 0 || isAutoTiering}
            className="flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-medium text-white transition-colors hover:bg-indigo-500 disabled:opacity-40 disabled:hover:bg-indigo-600 focus:outline-none focus:ring-2 focus:ring-indigo-400"
          >
            {isAutoTiering ? (
              <span className="flex items-center gap-2">
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" />
                <span>Applying Auto-Tier...</span>
              </span>
            ) : (
              <span>Run Auto-Tiering ({candidateRows.length})</span>
            )}
          </button>
        </div>

        {autoTierProgress && (
          <p className="mt-3 text-xs text-indigo-300 animate-pulse">{autoTierProgress}</p>
        )}

        {autoTierResult && (
          <div className="mt-3 rounded-lg bg-emerald-950/40 border border-emerald-500/30 p-2 text-xs text-emerald-200">
            ✓ Successfully auto-migrated {autoTierResult.success} file{autoTierResult.success === 1 ? '' : 's'} in S3!
            {autoTierResult.failed > 0 && ` (${autoTierResult.failed} failed)`}
          </div>
        )}
      </div>

      {/* Explanation card */}
      <div className="rounded-xl border border-surface-border bg-surface-card p-4 text-sm text-slate-400">
        <p>
          <strong className="text-slate-200">p_access</strong> is the LightGBM model's predicted probability that a file will be accessed again within the prediction horizon (7 days). It does not decide the storage tier directly: the policy engine turns p_access into one or more <strong className="text-slate-200">candidate tiers</strong>, and a contextual bandit (Thompson Sampling) chooses among ambiguous candidates. The bandit learns from your feedback; until feedback is collected it has no learned preference.
        </p>
      </div>

      {/* Table */}
      <div className="rounded-xl border border-surface-border bg-surface-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">AI predictions table</caption>
            <thead>
              <tr className="border-b border-surface-border text-xs font-medium uppercase tracking-wide text-slate-500">
                <th scope="col" className="px-4 py-3 text-left">FILE</th>
                <th scope="col" className="px-4 py-3 text-left">CURRENT TIER</th>
                <th scope="col" className="px-4 py-3 text-left cursor-pointer hover:text-slate-300" onClick={() => handleSort('p_access')}>
                  P(ACCESS)
                </th>
                <th scope="col" className="px-4 py-3 text-left">CANDIDATE TIER(S)</th>
                <th scope="col" className="px-4 py-3 text-left">RECOMMENDATION</th>
                <th scope="col" className="px-4 py-3 text-left">REASON</th>
                <th scope="col" className="px-4 py-3 text-left cursor-pointer hover:text-slate-300" onClick={() => handleSort('prediction_timestamp')}>
                  PREDICTION TIME
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-border/60">
              {sorted.map((row, i) => {
                const file = row.file
                const currentTier = file ? tierFromStorageClass(file.storageClass) : null
                const isPinned = file?.protected === true
                const pAccessPercent = row.pAccess !== null ? Math.round(row.pAccess * 100) : '-'
                const isMediumBand = row.pAccess !== null && row.pAccess >= 0.3 && row.pAccess < 0.7

                return (
                  <tr key={row.fileId ?? i} className="hover:bg-white/[0.02]">
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-100">{file?.filename || row.fileId || '—'}</div>
                      {row.fileId && (
                        <div className="text-xs text-slate-500" title={row.fileId}>{row.fileId}</div>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {currentTier ? <TierBadge tier={currentTier} /> : '-'}
                    </td>
                    <td className="px-4 py-3">
                      <div className={`font-medium ${isMediumBand ? 'text-amber-400' : 'text-slate-100'}`}>
                        {pAccessPercent}%
                      </div>
                      {row.pAccess !== null && (
                        <div className="mt-1 h-1 w-full rounded-full bg-slate-800">
                          <div 
                            className="h-full rounded-full bg-slate-400"
                            style={{ width: `${row.pAccess * 100}%` }}
                          />
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {row.candidateTiers.map(t => <TierBadge key={t} tier={t} />)}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      {isPinned ? (
                        <div>
                          <span className="inline-flex items-center rounded-full border border-slate-600 bg-slate-800 px-2 py-0.5 text-xs font-medium text-slate-300">
                            Pinned
                          </span>
                          <div className="mt-1 text-xs text-slate-500">no automatic tier change</div>
                        </div>
                      ) : (
                        <div className="flex items-center gap-2">
                          {row.banditChoice ? (
                            <TierBadge tier={row.banditChoice} />
                          ) : row.candidateTiers.length > 0 ? (
                            <TierBadge tier={row.candidateTiers[0]} />
                          ) : (
                            '-'
                          )}
                          {currentTier && (row.banditChoice || row.candidateTiers[0]) && currentTier !== (row.banditChoice || row.candidateTiers[0]) && (
                            <button
                              onClick={() => handleSingleAutoTier(row.fileId!, (row.banditChoice || row.candidateTiers[0]) as any)}
                              className="rounded bg-indigo-500/20 px-2 py-0.5 text-[11px] font-medium text-indigo-300 transition-colors hover:bg-indigo-500/30"
                              title="Apply this recommended tier change now"
                            >
                              Auto-Apply
                            </button>
                          )}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-400">
                      {topReasonsText(row.topReasons)}
                    </td>
                    <td className="px-4 py-3 text-slate-400">
                      {row.predictionTimestamp ? formatDate(row.predictionTimestamp) : '-'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {activeBand && (
        <button
          onClick={() => setActiveBand(null)}
          className="text-sm text-slate-500 hover:text-slate-300"
        >
          Clear filter
        </button>
      )}

      {/* Model note footer */}
      {import.meta.env.VITE_MODEL_NOTE && (
        <div className="text-xs text-slate-600">
          {import.meta.env.VITE_MODEL_NOTE}
        </div>
      )}
    </div>
  )
}
