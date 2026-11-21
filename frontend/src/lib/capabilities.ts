// Single source of truth for which backend capabilities are NOT live yet.
// Every "not available" state in the UI reads from here, so when a later stage
// makes a capability real, the flag flips in one place and the UI follows.
// This is deliberately static text - it records deployment status, it is not a
// health probe.

export interface Capability {
  available: boolean
  /** Shown to the user where the capability would appear. */
  reason: string
  /** Which project stage delivers it. */
  stage: string
}

export const CAPABILITIES = {
  tierForecast: {
    available: false,
    stage: 'Stage 10',
    reason: 'Cost forecasting is not implemented yet: the forecast endpoint is still a placeholder that returns no forecast.',
  },
  tierChange: {
    // tier-change-fn performs a real CopyObject for manual changes. Automatic,
    // ML-driven tier movement is a separate capability (see `predictions`).
    available: true,
    stage: 'Stage 9',
    reason: 'Manual tier changes are live. Automatic, ML-driven tier movement is not active yet.',
  },
  feedback: {
    available: false,
    stage: 'Stage 10',
    reason: 'Recommendation feedback is not active yet: the feedback endpoint is still a placeholder and does not store anything.',
  },
  protectedFiles: {
    // GET /files reports `protected`/`pinnedAt` per file (file-list-fn reads protected_files).
    // This notice only shows when that lookup failed (field null), i.e. pin state is unknown.
    available: false,
    stage: 'Pin status unavailable',
    reason: 'Pin status could not be loaded right now, so this list cannot be shown. Your pins are not lost - try reloading in a moment.',
  },
  predictions: {
    available: import.meta.env.VITE_PREDICTIONS_ENABLED === 'true',
    stage: 'Stage 10',
    reason: 'Live predictions are not available yet: the LightGBM inference pipeline is not connected, so no prediction records are produced.',
  },
  anomalyDetection: {
    available: true,
    stage: 'Stage 7',
    reason: 'Scheduled hourly download/delete volume rules are active. Isolation Forest scoring, step-up challenges, and automated containment remain planned.',
  },
  liveBilling: {
    available: false,
    stage: 'Later stage',
    reason: 'Live AWS spend is not connected to this app: no billing API is exposed to the frontend.',
  },
  accessTrends: {
    available: false,
    stage: 'Stage 10',
    reason: 'Access-event trends need an API over the access_event log, which is not exposed yet.',
  },
} as const satisfies Record<string, Capability>

export type CapabilityKey = keyof typeof CAPABILITIES
