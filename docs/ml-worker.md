# ASCOS ML inference worker

## Phase 1 architecture

The Master Reference §9 names ONNX inference inside `prediction-fn` as the intended serving path. This worker is a documented Phase 1 deviation: the current batch inference path uses LightGBM, SHAP, and pandas, which do not fit the existing Lambda ZIP package. A private S3 release bucket and one optional EC2 worker run the existing `ml.inference.batch_driver.run(user_ids=[...])` implementation. This phase adds no API route or frontend control.

The standard SQS queue long-polls one task at a time. Each task is JSON with `user_id` and a UUID `run_id`. The worker pins `MODEL_VERSION`, calls the batch driver for that user, and deletes the SQS message only after a complete successful run. A failed or invalid task remains unacknowledged; SQS redrives it after three receives to the dead-letter queue. Stable UUID5 prediction IDs make a successful file write safe to repeat after a partial run or message redelivery.

SQS visibility defaults to six hours and the worker refreshes it while inference is running. SQS permits a maximum visibility horizon of 12 hours from first receipt; do not use this worker for runs that can exceed that horizon. Set `ml_worker_visibility_timeout_seconds` above normal end-to-end inference duration.

The EC2 instance uses the default VPC's default subnet, an outbound HTTPS-only security group with no ingress, IMDSv2, an encrypted gp3 root disk, and the `AmazonSSMManagedInstanceCore` instance profile policy. Set `ml_worker_enabled = false` to omit the EC2 instance while retaining the queue, artifact bucket, and IAM resources.

## Build and upload a release ZIP

From the repository root in PowerShell, create a ZIP whose top level contains the `ml/` package, including model artifacts and `ml/worker/requirements.txt`:

```powershell
Compress-Archive -Path .\ml -DestinationPath .\ml-worker-release.zip -Force
```

Upload it to the private artifact bucket. Get the bucket name from the Terraform output `ml_worker_artifact_bucket`; the default object key is `ml-worker/worker-release.zip`.

Upload the ZIP before creating or replacing the enabled EC2 instance; its bootstrap downloads this object and will fail if the key is absent.

```powershell
aws s3 cp .\ml-worker-release.zip s3://<ml_worker_artifact_bucket-output>/ml-worker/worker-release.zip --region ap-south-1
```

For releases, prefer a new object key and update `ml_worker_artifact_key` so the EC2 user-data change replaces the instance and installs the selected ZIP. Update `ml_worker_model_version` at the same time when changing models. The bucket is versioned, encrypted with SSE-S3, blocks public access, and denies non-TLS requests.

The instance bootstrap installs Python 3.11, `libgomp`, AWS CLI, and unzip; downloads the pinned ZIP using its instance profile; creates a virtual environment; installs the pinned requirements; and starts `ascos-ml-worker.service`. Application logs go to stdout/stderr and are available through journald. Systems Manager Session Manager provides administration without an inbound SSH rule.

## Queue message

```json
{"user_id":"<Cognito-sub>","run_id":"<UUID generated for this prediction run>"}
```

Only a trusted producer should send messages. This worker has read/write permissions across user data because it handles queued users; it scopes S3 listing to `{user_id}/` and does not discover all users when processing a task.
