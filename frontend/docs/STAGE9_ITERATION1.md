feedback write-through; planned Isolation Forest anomaly scoring; protected-file backend
# ASCOS Stage 9 — Iteration 1: Integration + Correctness Pass

Scope: connect the existing frontend to the real deployed backend, remove all
fake production behaviour, fix confirmed bugs, and make small, cited backend
fixes. Not a redesign — the existing pages, layout, and visual language are
preserved. A second iteration will cover further UX/visual polish.

## A. What was changed

Frontend: every page now uses the real API (`services/api.ts`) instead of
mock data; a Cognito SRP authentication layer replaced the mock login;
config validation (`config/validate.ts`) makes the app refuse to start —
and the production build refuse to build — without real configuration; a
typed HTTP client (`services/http.ts`) with a 401-refresh-once policy and
safe error messages; a domain adapter layer (`services/adapters.ts`) that is
the one place backend response shapes are trusted; real two-step presigned
upload with progress (`services/upload.ts`); real download/share/delete;
`ErrorBoundary`, a 404 page, per-route document titles, code splitting,
a real favicon, an accessible `Modal`/`Dropdown` with focus trapping and
keyboard navigation, `ConfirmDialog` replacing `window.confirm`, an
`aria-live` toast region, and a `CapabilityNotice` component that renders an
honest "not available yet" state wherever a backend capability does not
exist. `tailwind.config.js` overrides `slate-500`/`slate-600` to meet WCAG AA
contrast (measured, not assumed — see `lib/format.ts` colour notes below).

Backend (small, cited fixes — see `docs/BACKEND_FIXES.md`): `file-upload-url-fn`
now percent-encodes the filename before signing it as S3 metadata (fixes the
reproduced `ParamValidationError` on non-ASCII filenames), signs a
`Content-Disposition` header carrying the real filename, and signs an
`uploaded-at` metadata field; `file-metadata-fn` decodes the filename back
and returns `uploadedAt`; `file-download-url-fn` and `file-share-fn` now
return `expiresAt`; `file-list-fn` now returns each object's `storageClass`;
`forecast-fn`, `tier-change-fn`, `feedback-writer-fn`,
`training-orchestrator-fn`, and `prediction-fn` no longer log the raw event
(which included the caller's `Authorization` header) — they log a redacted
summary instead.

## B. What existing UI was preserved

Sidebar/topbar/mobile-nav structure, the dark cloud-console visual language,
route list and page inventory (Dashboard, My Files, AI Predictions, Protected
Files, Analytics, Security, Cost & Budget, Settings), `Button`, `MetricCard`,
`TierBadge`, `ProtectedBadge`, `EmptyState`, `LoadingState`, the Tailwind
token approach, and the tier colour language (Hot/Warm/Cold).

## C. Real AWS capabilities now connected

Cognito authentication (sign in/up/verify/reset, session persistence, 401
handling); `GET /files`; `POST /files/upload-url` + real S3 PUT;
`GET /files/{id}/download-url`; `GET /files/{id}/metadata`;
`DELETE /files/{id}`; `POST /files/{id}/share-url`;
`GET /files/frequently-used` (returns an honestly empty list today — see D).

## D. Authentication status

Real, via `amazon-cognito-identity-js` performing the SRP handshake (the App
Client is SRP-only). Implemented: sign in, sign up, email verification,
resend code, forgot/reset password, sign-out, session persistence across
reloads, a `new_password_required` challenge, redirect-after-login to the
originally requested page (validated same-origin, see `lib/redirect.ts`), and
one automatic session refresh on a 401 before signing the user out.

**Not implemented / not testable here:** MFA and other Cognito challenge
types — `authService` fails these truthfully (`unsupported_challenge`) rather
than pretending to handle them, since the pool's MFA configuration was not
confirmed in this session. **NOT TESTABLE — BACKEND CAPABILITY NOT
IMPLEMENTED IN THIS SESSION:** I do not have `cognito.tf`, so I could not
confirm the App Client's refresh-token lifetime or which standard attributes
sign-up requires; the sign-up form currently only collects email + password.

## E. S3 upload/download status

Upload: real two-step presigned flow (`POST /files/upload-url` then a browser
`PUT`), with per-file progress, retry (always requests a fresh URL, since
retrying with an expired URL is a category of the fixed 403 case), and a
client-side check against the S3 single-PUT limit (5 GiB). Non-ASCII
filenames are fixed end-to-end and covered by both a moto regression test
(`tests/test_backend_fixes.py`, backend side) and the live smoke test.
Download and share now cause the browser to save the file under its real
name via the new `Content-Disposition` header. **NOT TESTABLE — BACKEND
CAPABILITY NOT IMPLEMENTED:** files over 5 GiB (would need multipart upload,
out of scope); whether a presigned URL genuinely survives its full stated
`expiresIn` given Lambda execution-role credential lifetime (flagged in the
handler docstrings for Stage 11).

## F. API status

All 7 real Stage 6 routes are wired through one typed client with a
normalized `ApiError` (400/401/403/404/409/429/5xx/network/timeout/malformed,
each with a safe, non-leaking message). The 3 Stage 5 scaffold routes (tier
forecast, tier change, feedback) are intentionally **not** wrapped in
`services/api.ts` — calling them would represent a no-op as success, which
Rule 4 of the Stage 9 prompt forbids. Their UI surfaces use
`CapabilityNotice` instead.

## G. Mock/demo data removed

`src/services/mockApi.ts` and `src/data/` (all mock fixtures) were deleted
entirely — not hidden behind a flag. `VITE_DATA_MODE` no longer exists.
There is no code path in this build that can render fabricated data; the
production build fails outright if configuration is missing (verified: see
`docs/BACKEND_FIXES.md` / testing log below).

## H. Hardcoded configuration removed

No AWS region, API URL, Cognito IDs, user IDs, file IDs, or credentials
appear in source. `config/validate.ts` is the single validation point, used
by both the runtime (`config/env.ts`) and the Vite build itself
(`vite.config.ts`), so a misconfigured production build fails at build time,
not silently at runtime. `.env.example` documents each variable and where it
comes from (`terraform output`).

## I. Backend fixes made

See `docs/BACKEND_FIXES.md` for the full list with rationale. Summary: 5
handler files modified (`file-upload-url-fn`, `file-metadata-fn`,
`file-download-url-fn`, `file-share-fn`, `file-list-fn`) plus 5 scaffold
handlers had their logging sanitized (`forecast-fn`, `tier-change-fn`,
`feedback-writer-fn`, `training-orchestrator-fn`, `prediction-fn`). All are
provided as complete replacement files, not diffs, to avoid ambiguity — see
the `backend-fixes/` folder alongside this ZIP.

## J. Terraform changes made

**None applied.** A proposed, reviewed-but-unapplied CORS change is in
`terraform-changes/api-cors.diff.md` (S3 bucket CORS + `frontend_origin` ->
`frontend_origins` list). I do not have your actual `.tf` files in this
session, so this is a proposal against the documented shape, not a verified
patch — paste the real files and I will turn it into an exact change, then
run `terraform fmt`/`validate`/`plan` and show you the plan before anything
is applied, per your rule.

## K. Tests actually run

- `npm run typecheck` — clean (0 errors)
- `npm run lint` — clean (0 errors, 0 warnings)
- `npm run build` — succeeds; verified to **fail** when configuration is
  missing (tested by temporarily removing `.env.local`)
- `npm test` (Vitest) — **48/48 passing**, covering: config validation (9),
  redirect-safety / open-redirect prevention (8), `formatPAccess` honest-null
  rendering (2), backend response adapters incl. malformed-shape rejection
  (10), HTTP client incl. 401-refresh-once and no-infinite-loop (8), Modal
  focus trap incl. wrap-around both directions (4), ConfirmDialog (3), upload
  validation incl. size limit (4)
- `python3 tests/test_backend_fixes.py` (moto-mocked, matching the existing
  project test pattern) — **36/36 passing**, covering the non-ASCII filename
  fix end-to-end (upload -> real S3 PUT -> metadata decode, 4 filenames),
  download/share `expiresAt`, list `storageClass`, and that all 5 scaffold
  handlers never log an Authorization header or token value

## L. Live AWS tests actually run

**None from this session** — I do not have credentials or network access to
your AWS account. `scripts/smoke-live.mjs` is written and ready
(`npm run smoke:live`), covering: unauthenticated 401, real Cognito sign-in,
file list, non-ASCII filename upload with a real S3 PUT, metadata round-trip,
download/share `expiresAt`, an empty (expected) `frequently-used` response,
a 404 on a nonexistent file, and cleanup. Please run it against the real
deployed stack and share the output.

## M. Tests that could not be run and why

**NOT TESTABLE — BACKEND CAPABILITY NOT IMPLEMENTED:** tier forecast, tier
change, feedback (scaffold routes, Stage 10); protected file pin/unpin (no
route exists); live prediction data (`prediction-fn` is a scaffold, so
`frequently-used` is genuinely empty); anomaly/security incident data
(`anomaly-scorer-fn` is a hardcoded stub); live AWS billing (no billing API
exposed). **NOT TESTABLE IN THIS SESSION:** anything requiring real AWS
credentials, a second real test user (cross-user isolation), or a live
browser (manual responsive/keyboard walkthrough).

## N. Known remaining limitations

Sign-up only collects email + password (Cognito's required standard
attributes were not confirmed); MFA/challenge types beyond
`new_password_required` are not handled; files >5 GiB are not supported
(would need multipart upload); Analytics has no backend route at all yet, so
it shows a permanent honest empty state rather than any chart; Dashboard's
tier distribution only reflects files whose `storageClass` is present (older
objects uploaded before the Stage 9 `file-list-fn` fix will show as
"Unmapped" until the fix is live); the budget figures are only shown if
`VITE_BUDGET_MONTHLY_USD`/`VITE_BUDGET_ALERT_PERCENT` are explicitly set —
I could not confirm from this session whether that $100/80% configuration
exists in Terraform or was set by hand, so I did not invent a source for it.

## O. Stage 10 dependencies

Real LightGBM predictions (populates `frequently-used-fn`'s table and unlocks
the Predictions page and Dashboard's AI panel); SHAP explanations; Thompson
Sampling bandit choice; real tier forecast/change execution; feedback
write-through; planned Isolation Forest anomaly scoring; protected-file backend
routes (pin/unpin/list) — not part of Stage 10 per the ML schema, but the
frontend cannot show real protected-file state until some backend owns that
table; access-event analytics API for the Analytics page.

## P. Stage 11 dependencies

Full authenticated end-to-end validation across all 10 routes; cross-user
isolation testing; verifying presigned URL lifetime against Lambda credential
expiry; concurrent/duplicate-click race testing; full responsive/manual
accessibility walkthrough on real devices; confirming `frequently-used-fn`'s
response shape once real prediction data exists (it currently omits
`prediction_id`/`model_version`/`top_reasons`, which the Predictions page and
a future feedback UI will need — flagged, not fixed here per scope).

## Q. Exact files changed

See `MANIFEST.md` in this ZIP for the complete, categorized file list.

## R. Git commit recommendations

Frontend (all under `frontend/`, one commit per group):
1. `frontend: replace mock API with typed client, adapters, and error model`
2. `frontend: add real Cognito SRP authentication`
3. `frontend: add real file operations (upload/download/share/delete/list)`
4. `frontend: add accessible Modal/Dropdown/ConfirmDialog, error boundary, 404 page`
5. `frontend: honest capability states for forecast/tier-change/feedback/predictions/security/billing`
6. `frontend: build hygiene (lockfile, gitignore, code splitting, config validation)`

Backend (each its own commit, per your own "smallest safe change" rule):
7. `fix(file-upload-url-fn): percent-encode filename metadata to support non-ASCII filenames`
8. `fix(file-metadata-fn): decode filename, return uploadedAt`
9. `fix(file-download-url-fn,file-share-fn): return expiresAt`
10. `fix(file-list-fn): return storageClass in the list response`
11. `fix(scaffolds): stop logging Authorization header via raw event dump`

Terraform (only after you approve and I've seen the real files):
12. `infra: add S3 bucket CORS and convert frontend_origin to a list`

## S. ZIP contents

This delivery is **not** a single "completed frontend ZIP" — it is organized
as: `frontend/` (the full frontend project, ready for `npm ci`),
`backend-fixes/` (5 complete replacement handler files + the moto test
script), `terraform-changes/` (the proposed CORS diff, unapplied), and this
document plus `MANIFEST.md` at the root. This split matches your rule that
Terraform changes require your review before any apply, and lets you drop
`backend-fixes/*/handler.py` directly over the matching files in
`F:\ASCOS\backend\` for review/commit.
