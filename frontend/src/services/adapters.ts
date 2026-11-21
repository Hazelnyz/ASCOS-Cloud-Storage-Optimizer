// The ONE place backend response shapes are converted into domain types.
// Every function validates what it reads and throws ApiError('malformed') on a
// mismatch, so a backend contract drift surfaces as a clear error instead of
// `undefined` leaking into the UI.

import { ApiError } from './errors'
import {
  isStorageTier,
  type DownloadLink, type FileMetadata, type FileSummary, type Prediction,
  type AnalyticsSummary, type ProtectResult, type SecuritySummary, type ShareLink, type StorageTier, type TierChangeResult, type UploadTicket,
  type BudgetUpdate, type CostSummary, type StoragePreferences,
} from '@/types'

type Rec = Record<string, unknown>

function malformed(): never {
  throw new ApiError('malformed')
}

function rec(v: unknown): Rec {
  if (typeof v !== 'object' || v === null || Array.isArray(v)) return malformed()
  return v as Rec
}

function reqStr(v: unknown): string {
  return typeof v === 'string' && v.length > 0 ? v : malformed()
}

function optStr(v: unknown): string | null {
  return typeof v === 'string' && v.length > 0 ? v : null
}

function reqNum(v: unknown): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : malformed()
}

function optNum(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

function nullableNum(v: unknown): number | null {
  return v === null || v === undefined ? null : reqNum(v)
}

function arr(v: unknown): unknown[] {
  return Array.isArray(v) ? v : malformed()
}

function reqBool(v: unknown): boolean {
  return typeof v === 'boolean' ? v : malformed()
}

function reqTier(v: unknown): StorageTier {
  return typeof v === 'string' && isStorageTier(v.toUpperCase()) ? (v.toUpperCase() as StorageTier) : malformed()
}

export function adaptFileList(raw: unknown): FileSummary[] {
  return arr(rec(raw).files).map((item) => {
    const r = rec(item)
    return {
      fileId: reqStr(r.fileId),
      filename: optStr(r.filename),
      size: reqNum(r.size),
      lastModified: reqStr(r.lastModified),
      storageClass: optStr(r.storageClass),
      uploadedAt: optStr(r.uploadedAt),
      protected: typeof r.protected === 'boolean' ? r.protected : null,
      pinnedAt: optStr(r.pinnedAt),
    }
  })
}

export function adaptMetadata(raw: unknown): FileMetadata {
  const r = rec(raw)
  return {
    fileId: reqStr(r.fileId),
    filename: optStr(r.filename),
    size: reqNum(r.size),
    lastModified: optStr(r.lastModified),
    uploadedAt: optStr(r.uploadedAt),
    lastAccessedAt: optStr(r.lastAccessedAt),
    recentAccessCount: optNum(r.recentAccessCount),
    accessWindowDays: optNum(r.accessWindowDays),
    contentType: optStr(r.contentType),
    storageClass: optStr(r.storageClass) ?? 'STANDARD',
  }
}

export function adaptUploadTicket(raw: unknown): UploadTicket {
  const r = rec(raw)
  let headers: Record<string, string> | null = null
  if (r.headers !== undefined && r.headers !== null) {
    const h = rec(r.headers)
    headers = {}
    for (const [k, v] of Object.entries(h)) headers[k] = reqStr(v)
  }
  return {
    fileId: reqStr(r.fileId),
    uploadUrl: reqStr(r.uploadUrl),
    headers,
    expiresInSeconds: optNum(r.expiresInSeconds),
  }
}

export function adaptDownloadLink(raw: unknown): DownloadLink {
  const r = rec(raw)
  return { fileId: reqStr(r.fileId), url: reqStr(r.downloadUrl) }
}

export function adaptShareLink(raw: unknown): ShareLink {
  const r = rec(raw)
  return {
    fileId: reqStr(r.fileId),
    url: reqStr(r.shareUrl),
    expiresAt: optStr(r.expiresAt),
    expiresInSeconds: optNum(r.expiresInSeconds),
  }
}

export function adaptDeleteResult(raw: unknown): void {
  if (rec(raw).deleted !== true) malformed()
}

/** POST /files/{fileId}/tier/change. status is "no_action_needed" when the
 * file was already at the requested tier - a valid, non-error outcome. */
export function adaptTierChangeResult(raw: unknown): TierChangeResult {
  const r = rec(raw)
  const status = r.status === 'no_action_needed' ? 'no_action_needed' : r.status === 'changed' ? 'changed' : malformed()
  return {
    fileId: reqStr(r.fileId),
    previousTier: reqTier(r.previousTier),
    newTier: reqTier(r.newTier),
    status,
    protected: reqBool(r.protected),
  }
}

/** POST or DELETE /files/{fileId}/protect. tierChanged/newTier are absent on
 * the DELETE (unprotect) response, since unprotecting never moves the file. */
export function adaptProtectResult(raw: unknown): ProtectResult {
  const r = rec(raw)
  return {
    fileId: reqStr(r.fileId),
    protected: reqBool(r.protected),
    tierChanged: typeof r.tierChanged === 'boolean' ? r.tierChanged : null,
    newTier: toTier(r.newTier),
    pinnedAt: optStr(r.pinnedAt),
  }
}

function toTier(v: unknown): StorageTier | null {
  if (typeof v !== 'string') return null
  const upper = v.toUpperCase()
  return isStorageTier(upper) ? upper : null
}

/** Maps the backend's top_reasons list. Tolerant: old rows (written before
 * explanations existed) have none, so a missing/invalid value becomes null and
 * invalid items are skipped. Contribution may arrive as a signed string
 * ("-1.3717") or a number; it is kept as a string. */
function toTopReasons(v: unknown): Array<{ feature: string; contribution: string }> | null {
  if (!Array.isArray(v)) return null
  const out: Array<{ feature: string; contribution: string }> = []
  for (const item of v) {
    if (typeof item !== 'object' || item === null || Array.isArray(item)) continue
    const o = item as Rec
    const feature = typeof o.feature === 'string' && o.feature.length > 0 ? o.feature : null
    const c = o.contribution
    const contribution =
      typeof c === 'string' && c.length > 0 ? c
        : typeof c === 'number' && Number.isFinite(c) ? String(c)
          : null
    if (feature !== null && contribution !== null) out.push({ feature, contribution })
  }
  return out
}

/** GET /files/frequently-used. Only fields the backend returns are mapped. */
export function adaptPredictions(raw: unknown): Prediction[] {
  return arr(rec(raw).predictions).map((item) => {
    const r = rec(item)
    const tiers = Array.isArray(r.candidateTiers) ? r.candidateTiers : []
    return {
      fileId: optStr(r.fileId),
      pAccess: optNum(r.pAccess),
      candidateTiers: tiers.map(toTier).filter((t): t is StorageTier => t !== null),
      banditChoice: toTier(r.banditChoice),
      predictionTimestamp: optStr(r.predictionTimestamp),
      topReasons: toTopReasons(r.topReasons),
    }
  })
}

export function adaptAnalyticsSummary(raw: unknown): AnalyticsSummary {
  const r = rec(raw)
  const tiers = arr(r.tiers).map((value) => {
    const row = rec(value)
    return {
      tier: reqTier(row.tier),
      files: reqNum(row.files),
      bytes: reqNum(row.bytes),
    }
  })
  const types = arr(r.types).map((value) => {
    const row = rec(value)
    return { type: reqStr(row.type), files: reqNum(row.files) }
  })
  const storageOverTime = arr(r.storageOverTime).map((value) => {
    const row = rec(value)
    return { day: reqStr(row.day), bytes: reqNum(row.bytes) }
  })
  const access = arr(r.access).map((value) => {
    const row = rec(value)
    return {
      day: reqStr(row.day),
      reads: reqNum(row.reads),
      writes: reqNum(row.writes),
      downloads: reqNum(row.downloads),
    }
  })
  let optimization: AnalyticsSummary['optimization'] = null
  if (r.optimization !== null && r.optimization !== undefined) {
    const value = rec(r.optimization)
    optimization = { monthlySavings: reqNum(value.monthlySavings) }
  }
  return { tiers, types, storageOverTime, access, optimization }
}

export function adaptCostSummary(raw: unknown): CostSummary {
  const r = rec(raw)
  const storage = rec(r.storage_by_tier)
  const tierCost = (tier: StorageTier): CostSummary['storage_by_tier'][StorageTier] => {
    const row = rec(storage[tier])
    return { bytes: reqNum(row.bytes), gb: reqNum(row.gb), rate: reqNum(row.rate), cost: reqNum(row.cost) }
  }
  const rates = rec(r.rates_used)
  const storageRates = rec(rates.storage)
  const requestRates = rec(rates.requests)
  const retrievalRates = rec(rates.retrieval)
  const budgetConfig = rec(r.budget_config)
  const breakdown = arr(r.breakdown).map((value) => {
    const row = rec(value)
    return { category: reqStr(row.category), amount: row.amount === null ? null : reqNum(row.amount) }
  })
  const optimization = nullableNum(r.ml_savings_estimate)
  return {
    budget: nullableNum(r.budget),
    alert_threshold: nullableNum(r.alert_threshold),
    estimated_spent: reqNum(r.estimated_spent),
    breakdown,
    storage_by_tier: { HOT: tierCost('HOT'), WARM: tierCost('WARM'), COLD: tierCost('COLD') },
    rates_used: {
      storage: { HOT: reqNum(storageRates.HOT), WARM: reqNum(storageRates.WARM), COLD: reqNum(storageRates.COLD) },
      requests: {
        standard_write: reqNum(requestRates.standard_write), standard_read: reqNum(requestRates.standard_read),
        warm_write: reqNum(requestRates.warm_write), warm_read: reqNum(requestRates.warm_read),
        cold_write: reqNum(requestRates.cold_write), cold_read: reqNum(requestRates.cold_read), delete: reqNum(requestRates.delete),
      },
      retrieval: { warm: reqNum(retrievalRates.warm), cold: reqNum(retrievalRates.cold) },
      notes: typeof rates.notes === 'string' ? rates.notes : malformed(),
    },
    computed_at: reqStr(r.computed_at),
    ml_savings_estimate: optimization,
    budget_config: {
      min: reqNum(budgetConfig.min), max: reqNum(budgetConfig.max), step: reqNum(budgetConfig.step),
      alert_threshold_min: reqNum(budgetConfig.alert_threshold_min), alert_threshold_max: reqNum(budgetConfig.alert_threshold_max),
    },
  }
}

export function adaptBudgetUpdate(raw: unknown): BudgetUpdate {
  const r = rec(raw)
  return { budget: reqNum(r.budget), alert_threshold: reqNum(r.alert_threshold) }
}

export function adaptStoragePreferences(raw: unknown): StoragePreferences {
  const r = rec(raw)
  return { auto_tier_enabled: reqBool(r.auto_tier_enabled) }
}

export function adaptSecuritySummary(raw: unknown): SecuritySummary {
  const r = rec(raw)
  const authentication = rec(r.authentication)
  const protectedFiles = rec(r.protectedFiles)
  const anomaly = rec(r.anomaly)
  const detections = arr(r.detections).map((value) => {
    const row = rec(value)
    if (row.rule !== 'download_volume' && row.rule !== 'delete_volume') malformed()
    if (row.severity !== 'Low' && row.severity !== 'Medium' && row.severity !== 'High') malformed()
    if (row.status !== 'Logged') malformed()
    if (row.mode !== 'learning' && row.mode !== 'baseline') malformed()
    const detection: SecuritySummary['detections'][number] = {
      rule: row.rule,
      severity: row.severity,
      status: row.status,
      count: reqNum(row.count),
      threshold: reqNum(row.threshold),
      mode: row.mode,
      windowStart: reqStr(row.windowStart),
      detectedAt: reqStr(row.detectedAt),
    }
    return detection
  })
  if (authentication.provider !== 'Cognito') malformed()
  if (anomaly.status !== 'active' && anomaly.status !== 'not_connected') malformed()
  if (anomaly.rule !== 'baseline') malformed()
  const activity = rec(r.activity)
  const last24h = rec(activity.last24h)
  const last7d = rec(activity.last7d)
  const countActivity = (counts: Rec): SecuritySummary['activity']['last24h'] => ({
    download: reqNum(counts.download),
    write: reqNum(counts.write),
    delete: reqNum(counts.delete),
    share: reqNum(counts.share),
  })
  if (typeof activity.truncated !== 'boolean') malformed()
  const summary: SecuritySummary = {
    authentication: { provider: 'Cognito', lastSignIn: optStr(authentication.lastSignIn) },
    protectedFiles: { count: reqNum(protectedFiles.count) },
    anomaly: {
      status: anomaly.status,
      rule: 'baseline',
      lastRun: optStr(anomaly.lastRun),
      openCount: reqNum(anomaly.openCount),
    },
    activity: {
      last24h: countActivity(last24h),
      last7d: countActivity(last7d),
      truncated: activity.truncated,
    },
    detections,
  }
  return summary
}
