import { useAsyncData } from '@/hooks/useAsyncData'
import { api } from '@/services/api'

export function useSecuritySummary() {
  return useAsyncData((signal) => api.getSecuritySummary({ signal }))
}