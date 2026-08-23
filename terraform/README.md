# ASCOS Terraform — Stage 1: Bootstrap / Remote State

## What this stage does (and doesn't do)

Creates exactly **one thing** in AWS: an S3 bucket to hold Terraform's own
state file, with versioning, encryption, and public access blocked.

It does **not** create any ASCOS application infrastructure — no Cognito,
no app S3 buckets, no DynamoDB, no Lambda. Those start in Stage 2 onward.

No DynamoDB table is created anywhere in this stage. Locking uses
Terraform's native S3 locking (`use\_lockfile = true`), per the master
reference §30 — DynamoDB-based locking is a deprecated Terraform backend
option and is deliberately not used here.

## Why two folders (`bootstrap/` and the root)?

Terraform can't store its state in a bucket that doesn't exist yet. So:

1. `bootstrap/` is a small, separate Terraform config that runs **once**,
using plain local state (a `.tfstate` file on your machine), just to
create the state bucket.
2. The root folder (this one) is the *real* project config. It's told
"store your state in the bucket bootstrap just made" via `backend.hcl`.

After step 1 is done, you basically never touch `bootstrap/` again unless
you're tearing down the whole project.



\## Current status



Bootstrap is complete and has been applied to AWS.



\- S3 state bucket: `ascos-dev-tfstate-477554784986`

\- Region: `ap-south-1`

\- Bucket versioning, AES256 encryption, Block Public Access, and TLS-only policy are enabled.

\- Root Terraform is now configured to use this bucket as its S3 remote backend.

\- S3-native state locking is enabled with `use\_lockfile = true`.

\- Root `terraform init` completed successfully.



The bootstrap configuration uses local state because it creates the bucket

that the root configuration needs for remote state. The root configuration

now uses the S3 backend.



\### Running the root configuration



From the root `terraform/` directory:



```bash

terraform init -backend-config=backend.hcl

terraform plan

## 

## Design choices made (open items, given sensible defaults)

|Decision|Default chosen|Why|
|-|-|-|
|`environment` default|`dev`|Master reference doesn't fix this; `dev` is the obvious starting point before staging/prod exist|
|State bucket naming|`{project\_name}-{environment}-tfstate-{suffix}`|Readable, sortable if you add more environments later; `{suffix}` is required (not defaulted) because S3 bucket names are globally unique — you must supply something like your AWS account ID|
|State key path|`ascos/dev/terraform.tfstate`|Leaves room for `ascos/staging/...`, `ascos/prod/...` later without restructuring the bucket|
|Bootstrap bucket lock (`prevent\_destroy`)|enabled|Stops an accidental `terraform destroy` in bootstrap from deleting the bucket every other stage's state lives in|

These are implementation details, not frozen architectural decisions — say
the word if you'd like any of them changed.

## What's intentionally NOT here yet

* `iam-team.tf`, `cognito.tf` — Stage 2
* `s3.tf` (the actual app storage bucket) — Stage 3
* `dynamodb.tf`, `lambda.tf`, `api-gateway.tf`, `cloudtrail.tf`,
`eventbridge.tf`, `cloudwatch.tf`, `sns.tf`, `frontend-hosting.tf` —
Stages 4–9

`main.tf` in the root has a comment map of what arrives in which stage,
so nothing gets built out of order without a reason.

