import { TrendingUp, TrendingDown } from 'lucide-react'

interface MLExplanationProps {
  /** SHAP feature contributions: list of {feature, contribution} where contribution is a string like "-1.3717" */
  topReasons: Array<{ feature: string; contribution: string }> | null
}

export function MLExplanation({ topReasons }: MLExplanationProps) {
  if (!topReasons || topReasons.length === 0) {
    return (
      <div className="text-xs text-slate-500 italic">
        No explanation available
      </div>
    )
  }

  return (
    <div className="space-y-1.5">
      {topReasons.map((reason, i) => {
        const contribution = parseFloat(reason.contribution)
        const isPositive = contribution > 0
        const isNegative = contribution < 0

        return (
          <div key={i} className="flex items-center gap-2 text-xs">
            {isPositive ? (
              <TrendingUp className="h-3 w-3 text-emerald-500" aria-hidden="true" />
            ) : isNegative ? (
              <TrendingDown className="h-3 w-3 text-rose-500" aria-hidden="true" />
            ) : null}
            <span className="text-slate-400">{reason.feature}</span>
            <span className={`ml-auto font-mono tabular-nums ${isPositive ? 'text-emerald-400' : isNegative ? 'text-rose-400' : 'text-slate-500'}`}>
              {contribution > 0 ? '+' : ''}{contribution.toFixed(3)}
            </span>
          </div>
        )
      })}
    </div>
  )
}
