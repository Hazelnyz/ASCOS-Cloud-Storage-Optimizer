import { useEffect, useState } from 'react'
import { AlertTriangle, Info, Save, Wallet } from 'lucide-react'
import { ErrorState } from '@/components/common/ErrorState'
import { EmptyState } from '@/components/common/EmptyState'
import { Skeleton } from '@/components/common/Skeleton'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useAsyncData } from '@/hooks/useAsyncData'
import { formatBytes, formatUsd } from '@/lib/format'
import { budgetAlertAmount, budgetRemaining, budgetUsagePercent, formatEstimatedUsd } from '@/lib/budget'
import { api } from '@/services/api'
import type { CostSummary } from '@/types'

function CostCardLoading({ title }: { title: string }) {
  return <section className="rounded-xl border border-surface-border bg-surface-card p-5 shadow-panel"><h3 className="mb-5 text-sm font-semibold text-slate-100">{title}</h3><div role="status" aria-label={`Loading ${title}`}><Skeleton className="mb-4 h-10 w-1/2" /><Skeleton className="mb-4 h-3 w-full" /><Skeleton className="h-28 w-full" /></div></section>
}

function Money({ value }: { value: number }) {
  return <>{formatEstimatedUsd(value)}</>
}

function ProgressBar({ value }: { value: number }) {
  const bounded = Math.max(0, Math.min(value, 100))
  return <div className="h-2.5 overflow-hidden rounded-full bg-white/5" role="progressbar" aria-label="Estimated budget usage" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(bounded)}><div className="h-full rounded-full bg-emerald-400 transition-[width]" style={{ width: `${bounded}%` }} /></div>
}

function BudgetOverview({ summary, budgetInput, alertInput, loading, error, reload }: { summary: CostSummary | null; budgetInput: string; alertInput: string; loading: boolean; error: unknown; reload: () => void }) {
  if (loading && !summary) return <CostCardLoading title="Monthly Budget" />
  if (error || !summary) return <section className="rounded-xl border border-surface-border bg-surface-card p-5 shadow-panel"><ErrorState error={error} onRetry={reload} title="Budget summary unavailable" /></section>
  const budget = budgetInput === '' ? summary.budget : Number(budgetInput)
  const alertThreshold = alertInput === '' ? (summary.alert_threshold ?? 80) : Number(alertInput)
  const usage = budgetUsagePercent(summary.estimated_spent, budget)
  const remaining = budgetRemaining(summary.estimated_spent, budget)
  const alertAmount = budgetAlertAmount(budget, alertThreshold)
  return <section className="rounded-xl border border-surface-border bg-surface-card p-5 shadow-panel">
    <div className="mb-5 flex items-start justify-between gap-4"><div className="flex items-center gap-2 text-slate-300"><Wallet className="h-4 w-4" aria-hidden="true" /><h3 className="text-sm font-semibold text-slate-100">Monthly Budget</h3></div><p className="text-lg font-semibold tabular-nums text-slate-50" aria-label={budget === null ? 'Budget not configured' : `Budget ${formatUsd(budget)} per month`}>{budget === null ? '—' : `${formatUsd(budget)}/mo`}</p></div>
    <div className="mb-2 flex items-center justify-between gap-3 text-xs"><span className="text-slate-300">{summary.estimated_spent === null ? 'Estimated spend not available' : <><span className="font-medium text-slate-100"><Money value={summary.estimated_spent} /></span> estimated spent this month</>}</span><span className="shrink-0 text-slate-400">{usage === null ? '—' : `${usage.toFixed(1)}% of budget`}</span></div>
    <ProgressBar value={usage ?? 0} />
    {budget === null ? <p className="mt-3 text-xs text-slate-500">Set a monthly budget below to track estimated usage.</p> : <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
      <div className="rounded-lg border border-surface-border bg-surface-raised p-3"><p className="text-xs text-slate-500">Remaining</p><p className={`mt-1 text-base font-semibold tabular-nums ${remaining !== null && remaining < 0 ? 'text-rose-300' : 'text-slate-100'}`}>{remaining === null ? '—' : <Money value={remaining} />}</p></div>
      <div className="rounded-lg border border-surface-border bg-surface-raised p-3"><p className="text-xs text-slate-500">Alert threshold</p><p className="mt-1 text-base font-semibold tabular-nums text-slate-100">{alertAmount === null ? '—' : <Money value={alertAmount} />}</p><p className="text-[11px] text-slate-500">{alertThreshold}% of budget</p></div>
      <div className="rounded-lg border border-surface-border bg-surface-raised p-3"><p className="text-xs text-slate-500">Usage %</p><p className="mt-1 text-base font-semibold tabular-nums text-slate-100">{usage === null ? '—' : `${usage.toFixed(1)}%`}</p></div>
    </div>}
  </section>
}

function BudgetControls({ summary, budgetInput, setBudgetInput, alertInput, setAlertInput, loading, error, reload }: { summary: CostSummary | null; budgetInput: string; setBudgetInput: (value: string) => void; alertInput: string; setAlertInput: (value: string) => void; loading: boolean; error: unknown; reload: () => void }) {
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<unknown>(null)
  const [saved, setSaved] = useState(false)
  const budgetConfig = summary?.budget_config

  const budgetValue = Number(budgetInput)
  const alertValue = Number(alertInput)
  const canSave = Boolean(summary && budgetConfig && budgetInput !== '' && Number.isFinite(budgetValue) && budgetValue >= budgetConfig.min && budgetValue <= budgetConfig.max && (budgetValue - budgetConfig.min) % budgetConfig.step === 0 && Number.isFinite(alertValue) && alertValue >= budgetConfig.alert_threshold_min && alertValue <= budgetConfig.alert_threshold_max && !saving)

  async function saveBudget(event: React.FormEvent) {
    event.preventDefault()
    if (!canSave) return
    setSaving(true)
    setSaveError(null)
    setSaved(false)
    try {
      await api.updateBudget({ budget: budgetValue, alert_threshold: alertValue })
      setSaved(true)
      reload()
    } catch (caught) {
      setSaveError(caught)
    } finally {
      setSaving(false)
    }
  }

  if (loading && !summary) return <CostCardLoading title="Adjust your budget" />
  if (error || !summary || !budgetConfig) return <section className="rounded-xl border border-surface-border bg-surface-card p-5 shadow-panel"><ErrorState error={error ?? new Error('Budget configuration unavailable')} onRetry={reload} title="Budget controls unavailable" /></section>

  return <section className="rounded-xl border border-surface-border bg-surface-card p-5 shadow-panel">
    <h3 className="mb-4 text-sm font-semibold text-slate-100">Adjustable Budget</h3>
    <form onSubmit={saveBudget} className="space-y-5">
      <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
        <label className="grid gap-2 text-xs text-slate-400">Monthly budget (USD)
          <input aria-label="Monthly budget in USD" className="w-full rounded-lg border border-surface-border bg-surface-raised px-3 py-2 text-sm text-slate-100 outline-none focus:border-accent" type="number" min={budgetConfig.min} max={budgetConfig.max} step={budgetConfig.step} value={budgetInput} onChange={(event) => { setBudgetInput(event.target.value); setSaved(false) }} />
        </label>
        <p className="text-xs text-slate-500">Range: {formatUsd(budgetConfig.min)}–{formatUsd(budgetConfig.max)}</p>
      </div>
      <label className="grid gap-2 text-xs text-slate-400">Budget slider <span className="text-slate-200">{budgetInput === '' ? 'Choose a value' : `${formatUsd(budgetValue)} per month`}</span>
        <input aria-label="Monthly budget slider" className="w-full accent-indigo-400" type="range" min={budgetConfig.min} max={budgetConfig.max} step={budgetConfig.step} value={budgetInput === '' ? budgetConfig.min : budgetValue} onChange={(event) => { setBudgetInput(event.target.value); setSaved(false) }} />
      </label>
      <label className="grid gap-2 text-xs text-slate-400">Alert threshold <span className="text-slate-200">{alertValue}%</span>
        <input aria-label="Alert threshold slider" className="w-full accent-amber-400" type="range" min={budgetConfig.alert_threshold_min} max={budgetConfig.alert_threshold_max} step="1" value={alertValue} onChange={(event) => { setAlertInput(event.target.value); setSaved(false) }} />
      </label>
      {Boolean(saveError) && <ErrorState error={saveError} title="Budget could not be saved" />}
      <div className="flex flex-wrap items-center gap-3"><button className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50" type="submit" disabled={!canSave}><Save className="h-4 w-4" aria-hidden="true" />{saving ? 'Saving…' : 'Save budget'}</button>{saved && <span role="status" className="text-xs text-emerald-300">Budget saved to your account.</span>}</div>
    </form>
  </section>
}

function CostBreakdown({ summary, loading, error, reload }: { summary: CostSummary | null; loading: boolean; error: unknown; reload: () => void }) {
  const [notesOpen, setNotesOpen] = useState(false)
  if (loading && !summary) return <CostCardLoading title="Estimated Cost Breakdown" />
  if (error || !summary) return <section className="rounded-xl border border-surface-border bg-surface-card p-5 shadow-panel"><ErrorState error={error} onRetry={reload} title="Cost breakdown unavailable" /></section>
  if (summary.breakdown.length === 0) return <section className="rounded-xl border border-surface-border bg-surface-card p-5 shadow-panel"><h3 className="mb-4 text-sm font-semibold text-slate-100">Estimated Cost Breakdown</h3><EmptyState icon={<Wallet className="h-5 w-5" />} title="No cost components available" description="The service returned no cost breakdown for this account." /></section>
  const hasUsage = summary.breakdown.some((row) => row.amount !== null && row.amount !== 0)
  const tierForCategory: Record<string, keyof CostSummary['storage_by_tier']> = {
    'Storage - Hot': 'HOT',
    'Storage - Warm': 'WARM',
    'Storage - Cold': 'COLD',
  }
  return <section className="rounded-xl border border-surface-border bg-surface-card p-5 shadow-panel">
    <div className="mb-4 flex items-start justify-between gap-3"><div><h3 className="text-sm font-semibold text-slate-100">Estimated Cost Breakdown</h3><p className="mt-1 text-xs text-slate-500">Estimated per-user costs for the current month</p></div><span className="text-xs text-slate-500">USD</span></div>
    {!hasUsage && <div className="mb-3 flex items-center gap-2 rounded-lg border border-dashed border-surface-border px-3 py-2 text-xs text-slate-500"><AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />No billable usage has been recorded for this month.</div>}
    <ul className="divide-y divide-surface-border">{summary.breakdown.map((row) => {
      const tier = tierForCategory[row.category]
      const storage = tier ? summary.storage_by_tier[tier] : null
      return <li key={row.category} className="flex items-center justify-between gap-4 py-3 text-sm"><span className="min-w-0 text-slate-300"><span>{row.category}</span>{storage && <span className="mt-1 block text-xs text-slate-500">{formatBytes(storage.bytes)}</span>}</span><span className="shrink-0 text-right font-medium tabular-nums text-slate-100">{row.amount === null ? 'Not available' : <Money value={row.amount} />}</span></li>
    })}</ul>
    <div className="mt-4 flex items-center gap-2 border-t border-surface-border pt-3 text-xs text-slate-500"><span>Estimated from your files and activity.</span><span className="group relative inline-flex"><button type="button" aria-label="Show cost estimate notes" aria-expanded={notesOpen} onClick={() => setNotesOpen((open) => !open)} className="rounded-full text-slate-400 outline-none hover:text-slate-200 focus-visible:ring-2 focus-visible:ring-accent"><Info className="h-3.5 w-3.5" aria-hidden="true" /></button><span role="tooltip" className={`${notesOpen ? 'visible opacity-100' : 'invisible opacity-0'} absolute bottom-full left-0 z-20 mb-2 w-72 rounded-lg border border-surface-border bg-surface-raised p-3 text-xs leading-relaxed text-slate-300 shadow-xl transition group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100`}>{summary.rates_used.notes}</span></span></div>
    {summary.ml_savings_estimate !== null && <p className="mt-4 text-sm font-medium text-emerald-300">Estimated ML savings opportunity: {formatUsd(summary.ml_savings_estimate)}/mo</p>}
  </section>
}

export function Budget() {
  useDocumentTitle('Cost & Budget')
  const query = useAsyncData((signal) => api.getCostSummary({ signal }))
  const summary = query.data
  const [budgetInput, setBudgetInput] = useState('')
  const [alertInput, setAlertInput] = useState('80')
  useEffect(() => {
    if (summary) {
      setBudgetInput(summary.budget === null ? '' : String(summary.budget))
      setAlertInput(String(summary.alert_threshold ?? 80))
    }
  }, [summary?.budget, summary?.alert_threshold])

  return <div className="min-w-0 space-y-5">
    <header><h2 className="text-lg font-semibold text-slate-100">Cost &amp; Budget</h2><p className="text-sm text-slate-500">Estimated costs from your own storage and recorded usage. This is an estimate, not live AWS billing.</p></header>
    <div className="grid min-w-0 grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
      <div className="min-w-0 space-y-5"><BudgetOverview summary={summary} budgetInput={budgetInput} alertInput={alertInput} loading={query.loading} error={query.error} reload={query.reload} /><BudgetControls summary={summary} budgetInput={budgetInput} setBudgetInput={setBudgetInput} alertInput={alertInput} setAlertInput={setAlertInput} loading={query.loading} error={query.error} reload={query.reload} /></div>
      <div className="min-w-0"><CostBreakdown summary={summary} loading={query.loading} error={query.error} reload={query.reload} /></div>
    </div>
  </div>
}
