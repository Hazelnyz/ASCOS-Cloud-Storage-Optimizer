import { api } from '@/services/api'
import { useAsyncData } from '@/hooks/useAsyncData'

export function useAnalyticsSummary() {
  return useAsyncData((signal) => api.getAnalyticsSummary({ signal }))
}