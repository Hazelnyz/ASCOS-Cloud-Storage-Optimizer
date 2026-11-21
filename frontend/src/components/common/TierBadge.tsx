import type { StorageTier } from '@/types'
import { TIER_STORAGE_CLASS } from '@/types'
import { TIER_COLORS } from '@/lib/tierColors'

interface TierBadgeProps {
  /** null = the storage class is unknown or not one of the three ASCOS tiers. */
  tier: StorageTier | null
  showClass?: boolean
  /** Raw S3 class, shown when the tier cannot be mapped. */
  rawClass?: string | null
}

export function TierBadge({ tier, showClass = false, rawClass }: TierBadgeProps) {
  if (!tier) {
    return (
      <span
        className="inline-flex items-center rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-xs font-medium text-slate-400"
        title={rawClass ? `Unmapped S3 storage class: ${rawClass}` : 'Tier not loaded yet'}
      >
        {rawClass ? 'UNMAPPED' : '—'}
      </span>
    )
  }
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium"
      style={{
        color: TIER_COLORS[tier],
        borderColor: `${TIER_COLORS[tier]}66`,
        backgroundColor: `${TIER_COLORS[tier]}1a`,
      }}
      title={TIER_STORAGE_CLASS[tier]}
    >
      {tier}
      {showClass && <span className="text-[10px] font-normal opacity-80">· {TIER_STORAGE_CLASS[tier]}</span>}
    </span>
  )
}
