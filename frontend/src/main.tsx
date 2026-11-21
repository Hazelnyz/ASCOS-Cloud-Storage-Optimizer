import React from 'react'
import ReactDOM from 'react-dom/client'
import './index.css'
import { validateEnv } from './config/validate'
import { ConfigError } from './pages/ConfigError'

const root = ReactDOM.createRoot(document.getElementById('root')!)
const result = validateEnv(import.meta.env as unknown as Record<string, string | undefined>)

if (!result.ok) {
  // Misconfigured: show a clear error (variable names only) and never start the app.
  root.render(<ConfigError problems={result.problems} />)
} else {
  // Imported lazily so nothing that needs configuration runs before validation.
  void import('./App').then(({ default: App }) => {
    root.render(
      <React.StrictMode>
        <App />
      </React.StrictMode>,
    )
  })
}
