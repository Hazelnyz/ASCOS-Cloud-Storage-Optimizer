# Stage 9 backend fixes

Small, cited fixes to existing Stage 6 handlers, plus a logging fix to the
Stage 5 scaffolds. Each is provided as a **complete replacement file** (not a
diff) under `backend-fixes/<function-name>/handler.py` in this delivery, to
avoid ambiguity when you copy it over the real file in `F:\ASCOS\backend\`.

None of these touch IAM, add a permission, or change a route's request/response
contract in a way the frontend doesn't already expect (the frontend's adapter
layer treats every new field as optional/nullable, so it works against both
the old and new handler versions).

## 1. `file-upload-url-fn` — non-ASCII filename crash (confirmed bug)

**Before:** `s3.generate_presigned_url(..., Params={"Metadata": {"filename": filename}})`
with the raw filename. boto3 raises `ParamValidationError` for any non-ASCII
value in S3 object metadata (S3 constraint, not a choice made here) — this
was reproduced directly:

```
'résumé.pdf' -> ParamValidationError: Non ascii characters found in S3
metadata for key "filename", value: "résumé.pdf"
```

The handler only caught `ClientError`, so this became an uncaught exception
→ Lambda returns a raw 500 with no useful message.

**After:** the filename is percent-encoded (`urllib.parse.quote`) before being
placed in the signed metadata, which is always ASCII. The response now
returns the exact `headers` map the client must send (`x-amz-meta-filename`,
`x-amz-meta-uploaded-at`, `Content-Disposition`) so the frontend never needs
to know the encoding scheme itself.

**Also fixed in the same change** (both required the same signed-headers
mechanism, so bundled to avoid re-touching this function three times):
- `Content-Disposition: attachment; filename="..."; filename*=UTF-8''...`
  is now signed at upload time, so downloads/shares save under the real
  filename instead of the raw UUID `fileId`.
- `uploaded-at` is stored in object metadata at upload time, since S3's
  `LastModified` is overwritten by `CopyObject` during a future tier change
  (Stage 5/10 `tier-change-fn`) — without this, `file_age_days` (ML schema
  section 2) would silently reset after the first tier move.

## 2. `file-metadata-fn` — decode filename, return `uploadedAt`

Decodes the percent-encoded filename back to its original form
(`urllib.parse.unquote`), with a fallback to the raw value if decoding ever
fails (never 500 a metadata read over a decode edge case). Returns the new
`uploadedAt` field (`null` for objects uploaded before this fix — there's no
way to backfill a value that was never recorded).

## 3. `file-download-url-fn` / `file-share-fn` — `expiresAt`

Both now return an absolute `expiresAt` timestamp alongside the existing
`expiresInSeconds`-equivalent value, computed from `datetime.now(UTC) +
timedelta(seconds=...)`. The frontend no longer needs to assume "24 hours"
independent of what was actually signed.

**Caveat, flagged for Stage 11, not fixed here:** AWS documents that a URL
signed with a Lambda execution role's *temporary* credentials can stop
working when those credentials expire, even if the signed `ExpiresIn` window
has not elapsed. `expiresAt` reflects the signed value; whether it is
reliably honoured in practice should be checked in Stage 11 live testing.

## 4. `file-list-fn` — `storageClass` in the list response

`ListObjectsV2` already returns each object's `StorageClass` in the same API
call (no extra cost, no extra permission) — it was being read from the S3
response and then discarded. Now included in each list item. Filenames are
still **not** returned by this endpoint (would need either a `HeadObject` per
object at list time, or a separate registry — out of scope for this fix).

## 5. `forecast-fn`, `tier-change-fn`, `feedback-writer-fn`,
   `training-orchestrator-fn`, `prediction-fn` — stop logging the raw event

**Before:** `logger.info(...); json.dumps(event)`. For any route reached
through API Gateway's HTTP API, `event` includes the incoming request
headers — including the caller's live `Authorization: Bearer <token>` header.
Every invocation of these five scaffold functions was writing the caller's
Cognito access token into CloudWatch Logs in plaintext.

**After:** logs a redacted summary only (HTTP method, path, and whether an
Authorization header was present — never its value). Verified via a moto
test that asserts the literal token string never appears in anything logged.

## Testing

`backend-fixes/tests/test_backend_fixes.py` — a standalone moto-mocked
script matching the project's existing test pattern (see `tests/test_handlers.py`
from Stage 6). Run with `AWS_DEFAULT_REGION=ap-south-1 python3
backend-fixes/tests/test_backend_fixes.py`. **36/36 passing**, including the
non-ASCII filename fix exercised end-to-end (percent-encode at upload → a
real moto S3 `put_object` using the exact signed headers → decode at
metadata read) for four filenames: accented Latin, Tamil script, a curly
apostrophe, and a plain-ASCII control case.

## Not changed

- `file-delete-fn`, `access-event-writer-fn`, `anomaly-scorer-fn` — no
  Stage 9 fix identified for these; not included in this delivery.
- No IAM policy changes. No new environment variables required (the fixes
  use data already available in the event/response).
