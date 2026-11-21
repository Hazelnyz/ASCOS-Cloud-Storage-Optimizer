import { defineConfig } from 'vitest/config'
import { loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { validateEnv } from './src/config/validate'

export default defineConfig(({ command, mode }) => {
  const allEnv = loadEnv(mode, process.cwd(), '')
  // Fail the production build - not the user's browser - when configuration is
  // missing or malformed. Only variable NAMES are printed, never values.
  if (command === 'build' && mode !== 'test') {
    const env = loadEnv(mode, process.cwd(), 'VITE_')
    const result = validateEnv(env)
    if (!result.ok) {
      throw new Error(
        'ASCOS build aborted - invalid frontend configuration:\n  - ' +
          result.problems.join('\n  - ') +
          '\nSet the VITE_* variables (see .env.example) before building.',
      )
    }
  }

  return {
    plugins: [react()],
    resolve: { alias: { '@': path.resolve(__dirname, './src') } },
    // amazon-cognito-identity-js expects a Node-style `global`.
    define: { global: 'globalThis' },
    // Port 3000 matches the API Gateway CORS origin currently deployed
    // (frontend_origin default http://localhost:3000). strictPort avoids the dev
    // server silently moving to another port that CORS would then reject.
    server: {
      port: 3000,
      strictPort: true,
      ...(allEnv.VITE_OLLAMA_URL ? {
        proxy: {
          '/ollama': {
            target: allEnv.VITE_OLLAMA_URL,
            changeOrigin: true,
            rewrite: (path: string) => path.replace(/^\/ollama/, ''),
          },
        },
      } : {}),
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks: {
            react: ['react', 'react-dom', 'react-router-dom'],
            charts: ['recharts'],
            cognito: ['amazon-cognito-identity-js'],
          },
        },
      },
    },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      css: false,
      restoreMocks: true,
    },
  }
})
