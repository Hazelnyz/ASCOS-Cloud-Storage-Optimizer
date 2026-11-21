# ASCOS Frontend

React + TypeScript + Vite + Tailwind frontend for ASCOS (Adaptive Self-Learning
Cloud Storage Optimization System). See `/docs/STAGE9_ITERATION1.md` for what
this iteration changed and why.

## Quick start

```bash
npm ci
cp .env.example .env.local   # fill in from `terraform output`, see below
npm run dev                  # http://localhost:3000
```

There is **no mock/demo mode**. The app requires real configuration to start,
in development and in production alike — see `.env.example`.

## Getting configuration values

```bash
cd ../terraform
terraform output -raw api_endpoint
terraform output -raw cognito_user_pool_id
terraform output -raw cognito_app_client_id
terraform output -raw aws_region
```

## Scripts

| Script | What it does |
|---|---|
| `npm run dev` | Start the dev server on port 3000 (fixed — matches the API's CORS origin) |
| `npm run build` | Type-check, then build. **Fails the build** if configuration is missing/invalid. |
| `npm run typecheck` | `tsc --noEmit` against both the app and Vite config |
| `npm run lint` | ESLint |
| `npm test` | Vitest (unit + component tests) |
| `npm run smoke:live` | Live smoke test against the real deployed backend — see below |

## Architecture

```
pages/        one file per route, thin — data loading + composition only
components/   common/ (design-system primitives), layout/, files/
services/     api.ts (typed client), authService.ts (Cognito),
              http.ts (fetch/retry/401 handling), adapters.ts (backend -> domain
              type mapping, the ONLY place response shapes are trusted),
              upload.ts (two-step presigned upload), errors.ts
context/      AuthProvider, ToastProvider
hooks/        useAsyncData, useFileMetadata, useFocusTrap, useDocumentTitle
lib/          capabilities.ts (what's live vs. deferred), format.ts, redirect.ts
config/       env.ts / validate.ts — the only place import.meta.env is read
```

**No mock API exists in this codebase.** Every page calls the real backend
through `services/api.ts`. Capabilities the backend does not implement yet
(tier forecast/change, feedback, protected files, live predictions, anomaly
detection, billing) are represented honestly via `lib/capabilities.ts` and
`CapabilityNotice` — never faked.

## Live smoke test

```bash
export ASCOS_TEST_EMAIL=you@example.com
export ASCOS_TEST_PASSWORD='...'
npm run smoke:live
```

Requires a real, already-confirmed Cognito test user. This exercises the real
deployed API Gateway, Cognito, and S3 — including the non-ASCII-filename
regression test. It is a smoke test, not Stage 11 end-to-end validation (no
cross-user isolation check, no concurrency testing).

## Known deferred functionality

See `lib/capabilities.ts` for the authoritative, in-code list. Summary: tier
forecast/change, recommendation feedback, protected-file pin/unpin, live ML
predictions, anomaly detection, and live AWS billing are all backend
capabilities that do not exist yet (Stage 10/11 or a later backend addition).
The UI reflects this honestly rather than simulating any of them.
