/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_COGNITO_USER_POOL_ID?: string
  readonly VITE_COGNITO_CLIENT_ID?: string
  readonly VITE_AWS_REGION?: string
  readonly VITE_BUDGET_MONTHLY_USD?: string
  readonly VITE_BUDGET_ALERT_PERCENT?: string
  readonly VITE_PREDICTIONS_ENABLED?: string
  readonly VITE_MODEL_NOTE?: string
  readonly VITE_OLLAMA_ENABLED?: string
  readonly VITE_OLLAMA_URL?: string
  readonly VITE_OLLAMA_MODEL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
