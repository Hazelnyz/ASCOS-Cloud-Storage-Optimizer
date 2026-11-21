#!/usr/bin/env node
/**
 * ASCOS Stage 9 live smoke test.
 *
 * Exercises the REAL deployed API Gateway + Cognito + S3 stack with a real
 * test account. This is a smoke test, not Stage 11: it checks that the
 * integration works end to end for ONE user, not cross-user isolation or
 * every edge case in the Stage 9 prompt's test list.
 *
 * Usage:
 *   node scripts/smoke-live.mjs
 *
 * Required environment (read from .env.local if present, or the shell):
 *   VITE_API_BASE_URL, VITE_COGNITO_USER_POOL_ID, VITE_COGNITO_CLIENT_ID, VITE_AWS_REGION
 *   ASCOS_TEST_EMAIL, ASCOS_TEST_PASSWORD  (a real, already-confirmed test user)
 *
 * Never run this against a shared/production account without knowing it will
 * create and delete a real test object under that user's prefix.
 */
import { CognitoUserPool, CognitoUser, AuthenticationDetails } from 'amazon-cognito-identity-js'
import { readFileSync, existsSync } from 'node:fs'

function loadDotEnvLocal() {
  if (!existsSync('.env.local')) return
  for (const line of readFileSync('.env.local', 'utf8').split('\n')) {
    const m = /^([A-Z0-9_]+)=(.*)$/.exec(line.trim())
    if (m && !process.env[m[1]]) process.env[m[1]] = m[2]
  }
}
loadDotEnvLocal()

const required = [
  'VITE_API_BASE_URL', 'VITE_COGNITO_USER_POOL_ID', 'VITE_COGNITO_CLIENT_ID',
  'ASCOS_TEST_EMAIL', 'ASCOS_TEST_PASSWORD',
]
const missing = required.filter((k) => !process.env[k])
if (missing.length > 0) {
  console.error(`Missing required environment variables: ${missing.join(', ')}`)
  process.exit(1)
}

const API_BASE = process.env.VITE_API_BASE_URL.replace(/\/+$/, '')
let passed = 0
let failed = 0

function check(name, condition, detail = '') {
  if (condition) {
    passed += 1
    console.log(`  ok   ${name}`)
  } else {
    failed += 1
    console.log(`  FAIL ${name}${detail ? `  ${detail}` : ''}`)
  }
}

function signIn() {
  const pool = new CognitoUserPool({ UserPoolId: process.env.VITE_COGNITO_USER_POOL_ID, ClientId: process.env.VITE_COGNITO_CLIENT_ID })
  const user = new CognitoUser({ Username: process.env.ASCOS_TEST_EMAIL, Pool: pool })
  return new Promise((resolve, reject) => {
    user.authenticateUser(
      new AuthenticationDetails({ Username: process.env.ASCOS_TEST_EMAIL, Password: process.env.ASCOS_TEST_PASSWORD }),
      {
        onSuccess: (session) => resolve(session.getAccessToken().getJwtToken()),
        onFailure: (err) => reject(err),
        newPasswordRequired: () => reject(new Error('Test account requires a new password - set one before running this script.')),
      },
    )
  })
}

async function call(token, method, path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  })
  let json = null
  try { json = await res.json() } catch { /* no body */ }
  return { status: res.status, json }
}

async function main() {
  console.log(`ASCOS live smoke test against ${API_BASE}\n`)

  console.log('Auth:')
  const unauth = await call('invalid-token', 'GET', '/files')
  check('GET /files with an invalid token returns 401', unauth.status === 401, `got ${unauth.status}`)

  const token = await signIn().catch((err) => {
    console.error(`Sign-in failed: ${err.message}`)
    process.exit(1)
  })
  check('sign-in succeeds and returns an access token', typeof token === 'string' && token.length > 0)

  console.log('\nFile list:')
  const before = await call(token, 'GET', '/files')
  check('GET /files returns 200', before.status === 200, JSON.stringify(before.json))
  check('GET /files response has a files array', Array.isArray(before.json?.files))

  console.log('\nUpload (Unicode filename regression check):')
  const filename = 'ascos-smoke-résumé-✓.txt'
  const uploadTicket = await call(token, 'POST', '/files/upload-url', { filename })
  check('POST /files/upload-url returns 200 for a non-ASCII filename', uploadTicket.status === 200, JSON.stringify(uploadTicket.json))
  const fileId = uploadTicket.json?.fileId
  const uploadUrl = uploadTicket.json?.uploadUrl
  const signedHeaders = uploadTicket.json?.headers ?? { 'x-amz-meta-filename': encodeURIComponent(filename) }

  if (uploadUrl) {
    const putRes = await fetch(uploadUrl, { method: 'PUT', headers: signedHeaders, body: 'smoke test content' })
    check('Browser-style PUT to the presigned URL succeeds', putRes.ok, `status ${putRes.status}`)
  } else {
    check('Browser-style PUT to the presigned URL succeeds', false, 'no uploadUrl returned - skipped')
  }

  console.log('\nMetadata (filename round-trip):')
  if (fileId) {
    const meta = await call(token, 'GET', `/files/${fileId}/metadata`)
    check('GET metadata returns 200', meta.status === 200, JSON.stringify(meta.json))
    check('metadata.filename matches the original Unicode filename', meta.json?.filename === filename, `got ${JSON.stringify(meta.json?.filename)}`)
    check('metadata.storageClass is present', typeof meta.json?.storageClass === 'string')
  }

  console.log('\nDownload URL:')
  if (fileId) {
    const dl = await call(token, 'GET', `/files/${fileId}/download-url`)
    check('GET download-url returns 200', dl.status === 200)
    check('download-url response includes expiresAt', typeof dl.json?.expiresAt === 'string', JSON.stringify(dl.json))
  }

  console.log('\nShare URL:')
  if (fileId) {
    const share = await call(token, 'POST', `/files/${fileId}/share-url`)
    check('POST share-url returns 200', share.status === 200)
    check('share-url response includes expiresAt', typeof share.json?.expiresAt === 'string', JSON.stringify(share.json))
  }

  console.log('\nFrequently used (expected empty until Stage 10):')
  const freq = await call(token, 'GET', '/files/frequently-used')
  check('GET frequently-used returns 200', freq.status === 200)
  check('frequently-used response has a predictions array', Array.isArray(freq.json?.predictions))

  console.log('\nCross-file 404:')
  const missing404 = await call(token, 'GET', '/files/does-not-exist/metadata')
  check('metadata for a non-existent fileId returns 404', missing404.status === 404, `got ${missing404.status}`)

  console.log('\nCleanup:')
  if (fileId) {
    const del = await call(token, 'DELETE', `/files/${fileId}`)
    check('DELETE cleans up the smoke-test file', del.status === 200, JSON.stringify(del.json))
  }

  console.log(`\n${passed} passed, ${failed} failed`)
  console.log('\nNOT covered by this script (see Stage 11 in the Master Reference):')
  console.log('  - cross-user isolation (needs a second test account)')
  console.log('  - share-link expiry behaviour over real time')
  console.log('  - concurrent/duplicate-click races')
  console.log('  - tablet/mobile layout (manual only)')
  process.exit(failed > 0 ? 1 : 0)
}

main()
