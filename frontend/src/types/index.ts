// ASCOS domain model.
//
// Field names follow what the DEPLOYED backend actually returns (camelCase).
// Backend -> domain conversion happens in exactly one place:
// src/services/adapters.ts. Components never see raw response shapes.
//
// Nothing here models data the backend does not currently provide (no
// prediction_id, model_version, top_reasons, recommended_tier, ...). Those
// arrive with later stages (Stage 10 ML pipeline).

export type StorageTier = 'HOT' | 'WARM' | 'COLD'

/** Logical tier -> S3 storage class label (Master Reference section 26). */
export const TIER_STORAGE_CLASS: Record<StorageTier, string> = {
  HOT: 'S3 Standard',
  WARM: 'S3 Standard-IA',
  COLD: 'S3 Glacier Instant Retrieval',
}

/** Raw S3 StorageClass value -> logical tier. Anything else is "unmapped". */
const S3_CLASS_TO_TIER: Record<string, StorageTier> = {
  STANDARD: 'HOT',
  STANDARD_IA: 'WARM',
  GLACIER_IR: 'COLD',
}

export function tierFromStorageClass(storageClass: string | null | undefined): StorageTier | null {
  if (!storageClass) return null
  return S3_CLASS_TO_TIER[storageClass.toUpperCase()] ?? null
}

export function isStorageTier(v: unknown): v is StorageTier {
  return v === 'HOT' || v === 'WARM' || v === 'COLD'
}

/**
 * One row of GET /files. `filename` and `storageClass` come from the list
 * endpoint's per-object HeadObject; either is null when that lookup failed for
 * the object (the backend degrades per file instead of failing the whole list).
 */
export interface FileSummary {
  fileId: string
  filename: string | null
  size: number
  lastModified: string
  storageClass: string | null
  /** Server-recorded upload time; null for files uploaded before it was stamped. */
  uploadedAt: string | null
  /** Pinned state from the list endpoint; null when the backend could not report it (unknown, not "unpinned"). */
  protected: boolean | null
  /** When the file was pinned (ISO); null if unpinned, unknown, or pinned before timestamps were stored. */
  pinnedAt: string | null
}

/** GET /files/{fileId}/metadata */
export interface FileMetadata {
  fileId: string
  filename: string | null
  size: number
  lastModified: string | null
  /** Server-recorded upload time, when the object carries it. */
  uploadedAt: string | null
  /** Newest download/share of this file (ISO); null if none recorded OR the lookup failed (see recentAccessCount). */
  lastAccessedAt: string | null
  /** Downloads + shares in the last `accessWindowDays` days. null = the lookup failed (unknown, not zero). */
  recentAccessCount: number | null
  accessWindowDays: number | null
  contentType: string | null
  /** Raw S3 storage class (STANDARD, STANDARD_IA, GLACIER_IR, ...). */
  storageClass: string
}

/** POST /files/{fileId}/tier/change */
export interface TierChangeResult {
  fileId: string
  previousTier: StorageTier
  newTier: StorageTier
  /** "no_action_needed" when the file was already at the requested tier - not an error. */
  status: 'changed' | 'no_action_needed'
  protected: boolean
}

/**
 * POST or DELETE /files/{fileId}/protect. `tierChanged`/`newTier` only appear
 * on the POST (protect) response - DELETE (unprotect) never moves the file.
 */
export interface ProtectResult {
  fileId: string
  protected: boolean
  tierChanged: boolean | null
  newTier: StorageTier | null
  /** Set on a first pin; null on unpin and on a repeat pin of an already-pinned file ("unchanged"). */
  pinnedAt: string | null
}

/** POST /files/upload-url */
export interface UploadTicket {
  fileId: string
  uploadUrl: string
  /** Headers the browser PUT must send exactly as given (they are signed). */
  headers: Record<string, string> | null
  expiresInSeconds: number | null
}

export interface DownloadLink {
  fileId: string
  url: string
}

export interface ShareLink {
  fileId: string
  url: string
  /** Requested validity end, when the backend reports it. */
  expiresAt: string | null
  expiresInSeconds: number | null
}

/** One item of GET /files/frequently-used - only what the backend returns. */
export interface Prediction {
  fileId: string | null
  pAccess: number | null
  candidateTiers: StorageTier[]
  banditChoice: StorageTier | null
  predictionTimestamp: string | null
  /** SHAP feature contributions: list of {feature, contribution} where contribution is a string like "-1.3717" */
  topReasons: Array<{ feature: string; contribution: string }> | null
}

export interface AnalyticsTierSummary {
  tier: StorageTier
  files: number
  bytes: number
}

export interface AnalyticsTypeSummary {
  type: string
  files: number
}

export interface AnalyticsStoragePoint {
  day: string
  bytes: number
}

export interface AnalyticsAccessPoint {
  day: string
  reads: number
  writes: number
  downloads: number
}

export interface AnalyticsSummary {
  tiers: AnalyticsTierSummary[]
  types: AnalyticsTypeSummary[]
  storageOverTime: AnalyticsStoragePoint[]
  access: AnalyticsAccessPoint[]
  optimization: { monthlySavings: number } | null
}

export type SecurityEventType = 'download' | 'write' | 'delete' | 'share'

export interface SecurityActivityCounts {
  download: number
  write: number
  delete: number
  share: number
}

export interface SecuritySummary {
  authentication: {
    provider: 'Cognito'
    lastSignIn: string | null
  }
  protectedFiles: { count: number }
  anomaly: {
    status: 'active' | 'not_connected'
    rule: 'baseline'
    lastRun: string | null
    openCount: number
  }
  activity: {
    last24h: SecurityActivityCounts
    last7d: SecurityActivityCounts
    truncated: boolean
  }
  detections: Array<{
    rule: 'download_volume' | 'delete_volume'
    severity: 'Low' | 'Medium' | 'High'
    status: 'Logged'
    count: number
    threshold: number
    mode: 'learning' | 'baseline'
    windowStart: string
    detectedAt: string
  }>
}

export interface AuthUser {
  userId: string
  email: string
  /** From the pool's custom:display_name attribute (optional, UI-only - see cognito.tf). Null if never set. */
  displayName: string | null
}

export interface CostSummary {
  budget: number | null
  alert_threshold: number | null
  estimated_spent: number
  breakdown: CostBreakdownItem[]
  storage_by_tier: StorageTierCosts
  rates_used: CostRates
  computed_at: string
  ml_savings_estimate: number | null
  budget_config: { min: number; max: number; step: number; alert_threshold_min: number; alert_threshold_max: number }
}

export interface CostBreakdownItem {
  category: string
  amount: number | null
}

export interface StorageTierCosts {
  HOT: { bytes: number; gb: number; rate: number; cost: number }
  WARM: { bytes: number; gb: number; rate: number; cost: number }
  COLD: { bytes: number; gb: number; rate: number; cost: number }
}

export interface CostRates {
  storage: { HOT: number; WARM: number; COLD: number }
  requests: {
    standard_write: number
    standard_read: number
    warm_write: number
    warm_read: number
    cold_write: number
    cold_read: number
    delete: number
  }
  retrieval: { warm: number; cold: number }
  notes: string
}

export interface BudgetUpdate {
  budget: number
  alert_threshold: number
}

export interface StoragePreferences {
  auto_tier_enabled: boolean
}
