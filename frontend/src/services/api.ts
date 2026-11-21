// Typed ASCOS API client - the only module UI code uses to reach the backend.
//
// Covers exactly the routes that do real work today:
//   GET    /files                         POST /files/upload-url
//   GET    /files/{id}/download-url       GET  /files/{id}/metadata
//   DELETE /files/{id}                    POST /files/{id}/share-url
//   GET    /files/frequently-used         POST /files/{id}/tier/change
//   POST   /files/{id}/protect            DELETE /files/{id}/protect
// Tier forecast and feedback are intentionally NOT wrapped: forecast-fn and
// feedback-writer-fn are still the Stage 5 scaffold (return a 200
// "stage5_scaffold" message and do nothing), so calling them would
// misrepresent a no-op as success. See src/lib/capabilities.ts.

import { getConfig } from '@/config/env'
import { authService } from './authService'
import { notifySessionExpired } from './authEvents'
import { createHttpClient, type HttpClient } from './http'
import {
  adaptAnalyticsSummary, adaptBudgetUpdate, adaptCostSummary, adaptDeleteResult, adaptDownloadLink, adaptFileList, adaptMetadata, adaptSecuritySummary,
  adaptPredictions, adaptProtectResult, adaptShareLink, adaptStoragePreferences, adaptTierChangeResult, adaptUploadTicket,
} from './adapters'
import type {
  AnalyticsSummary, BudgetUpdate, CostSummary, DownloadLink, FileMetadata, FileSummary, Prediction, ProtectResult, SecuritySummary,
  ShareLink, StoragePreferences, StorageTier, TierChangeResult, UploadTicket,
} from '@/types'

export interface CallOptions {
  signal?: AbortSignal
}

export interface ASCOSApi {
  getAnalyticsSummary(opts?: CallOptions): Promise<AnalyticsSummary>
  getSecuritySummary(opts?: CallOptions): Promise<SecuritySummary>
  listFiles(opts?: CallOptions): Promise<FileSummary[]>
  getFileMetadata(fileId: string, opts?: CallOptions): Promise<FileMetadata>
  requestUploadTicket(filename: string, opts?: CallOptions): Promise<UploadTicket>
  getDownloadLink(fileId: string, opts?: CallOptions): Promise<DownloadLink>
  createShareLink(fileId: string, opts?: CallOptions): Promise<ShareLink>
  deleteFile(fileId: string, opts?: CallOptions): Promise<void>
  getFrequentlyUsed(opts?: CallOptions): Promise<Prediction[]>
  changeTier(fileId: string, targetTier: StorageTier, opts?: CallOptions): Promise<TierChangeResult>
  protectFile(fileId: string, opts?: CallOptions): Promise<ProtectResult>
  unprotectFile(fileId: string, opts?: CallOptions): Promise<ProtectResult>
  getCostSummary(opts?: CallOptions): Promise<CostSummary>
  updateBudget(budget: BudgetUpdate, opts?: CallOptions): Promise<BudgetUpdate>
  getStoragePreferences(opts?: CallOptions): Promise<StoragePreferences>
  updateStoragePreferences(preferences: StoragePreferences, opts?: CallOptions): Promise<StoragePreferences>
}

const fileUrl = (fileId: string, suffix = '') => `/files/${encodeURIComponent(fileId)}${suffix}`

export function createApi(http: HttpClient): ASCOSApi {
  return {
    getAnalyticsSummary: (o) => http.request({ path: '/api/analytics/summary', signal: o?.signal, parse: adaptAnalyticsSummary }),
    getSecuritySummary: (o) => http.request({ path: '/api/security/summary', signal: o?.signal, parse: adaptSecuritySummary }),
    listFiles: (o) => http.request({ path: '/files', signal: o?.signal, parse: adaptFileList }),
    getFileMetadata: (id, o) => http.request({ path: fileUrl(id, '/metadata'), signal: o?.signal, parse: adaptMetadata }),
    requestUploadTicket: (filename, o) =>
      http.request({ method: 'POST', path: '/files/upload-url', body: { filename }, signal: o?.signal, parse: adaptUploadTicket }),
    getDownloadLink: (id, o) => http.request({ path: fileUrl(id, '/download-url'), signal: o?.signal, parse: adaptDownloadLink }),
    createShareLink: (id, o) =>
      http.request({ method: 'POST', path: fileUrl(id, '/share-url'), signal: o?.signal, parse: adaptShareLink }),
    deleteFile: (id, o) => http.request({ method: 'DELETE', path: fileUrl(id), signal: o?.signal, parse: adaptDeleteResult }),
    getFrequentlyUsed: (o) => http.request({ path: '/files/frequently-used', signal: o?.signal, parse: adaptPredictions }),
    changeTier: (id, targetTier, o) =>
      http.request({
        method: 'POST',
        path: fileUrl(id, '/tier/change'),
        body: { targetTier },
        signal: o?.signal,
        parse: adaptTierChangeResult,
      }),
    protectFile: (id, o) =>
      http.request({ method: 'POST', path: fileUrl(id, '/protect'), signal: o?.signal, parse: adaptProtectResult }),
    unprotectFile: (id, o) =>
      http.request({ method: 'DELETE', path: fileUrl(id, '/protect'), signal: o?.signal, parse: adaptProtectResult }),
    getCostSummary: (o) => http.request({ path: '/cost/summary', signal: o?.signal, parse: adaptCostSummary }),
    updateBudget: (budget, o) => http.request({ method: 'PUT', path: '/cost/budget', body: budget, signal: o?.signal, parse: adaptBudgetUpdate }),
    getStoragePreferences: (o) => http.request({ path: '/settings/storage-preferences', signal: o?.signal, parse: adaptStoragePreferences }),
    updateStoragePreferences: (preferences, o) => http.request({ method: 'PUT', path: '/settings/storage-preferences', body: preferences, signal: o?.signal, parse: adaptStoragePreferences }),
  }
}

let instance: ASCOSApi | null = null

function impl(): ASCOSApi {
  if (!instance) {
    instance = createApi(
      createHttpClient({
        baseUrl: getConfig().apiBaseUrl,
        getToken: () => authService.getAccessToken(),
        refreshSession: () => authService.refreshSession(),
        onSessionExpired: notifySessionExpired,
      }),
    )
  }
  return instance
}

/** Lazily-bound singleton (configuration errors surface in the UI, not at import). */
export const api: ASCOSApi = {
  getAnalyticsSummary: (o) => impl().getAnalyticsSummary(o),
  getSecuritySummary: (o) => impl().getSecuritySummary(o),
  listFiles: (o) => impl().listFiles(o),
  getFileMetadata: (id, o) => impl().getFileMetadata(id, o),
  requestUploadTicket: (f, o) => impl().requestUploadTicket(f, o),
  getDownloadLink: (id, o) => impl().getDownloadLink(id, o),
  createShareLink: (id, o) => impl().createShareLink(id, o),
  deleteFile: (id, o) => impl().deleteFile(id, o),
  getFrequentlyUsed: (o) => impl().getFrequentlyUsed(o),
  changeTier: (id, t, o) => impl().changeTier(id, t, o),
  protectFile: (id, o) => impl().protectFile(id, o),
  unprotectFile: (id, o) => impl().unprotectFile(id, o),
  getCostSummary: (o) => impl().getCostSummary(o),
  updateBudget: (budget, o) => impl().updateBudget(budget, o),
  getStoragePreferences: (o) => impl().getStoragePreferences(o),
  updateStoragePreferences: (preferences, o) => impl().updateStoragePreferences(preferences, o),
}
