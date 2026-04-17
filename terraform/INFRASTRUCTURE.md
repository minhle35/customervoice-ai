# AWS Infrastructure — CustomerVoice AI

Managed with Terraform. All resources deploy to `ap-southeast-2` (Sydney).

---

## Remote State

Terraform state is stored remotely so it can be shared and is not lost if your machine changes.

| Resource | Purpose |
|---|---|
| S3 bucket `customervoice-ai-tf-state-1776227497` | Stores `terraform.tfstate` encrypted at rest |
| DynamoDB table `terraform-lock` | Prevents two people running `terraform apply` at the same time |

---

## Architecture Overview

```
User browser
     │
     ▼
Vercel (Next.js frontend)
     │  NEXT_PUBLIC_API_URL = https://api.customer-analyticsgo.trade
     │  next.config.js rewrites /api/* → backend
     ▼
Cloudflare DNS (api CNAME → ALB, proxy OFF)
     │
     ▼
ALB (public, HTTPS only)
     │  port 443 → TLS terminated here
     │  port 80  → 301 redirect to HTTPS
     ▼
ECS Fargate — private subnet
     ├── backend service  (FastAPI, port 8000)
     └── worker service   (Celery)
           │                    │
           ▼                    ▼
          RDS               ElastiCache
       PostgreSQL 16            Redis 7
       (private subnet)     (private subnet)

NAT Gateway — lets private subnets call external APIs
(SerpAPI, OpenRouter, HuggingFace model downloads)
```

---

## Networking (`vpc.tf`)

| Resource | Value | Purpose |
|---|---|---|
| VPC | `10.0.0.0/16` | Isolated network for all resources |
| Public subnets | `10.0.0.0/24`, `10.0.1.0/24` | ALB only — faces the internet |
| Private subnets | `10.0.10.0/24`, `10.0.11.0/24` | ECS tasks, RDS, Redis — no direct internet access |
| Internet Gateway | — | Public subnets reach the internet |
| NAT Gateway | — | Private subnets make outbound calls (SerpAPI, OpenRouter, HuggingFace) |

**Security Groups — least privilege:**
- `alb-sg`: accepts port 80 and 443 from anywhere
- `backend-sg`: accepts port 8000 from ALB only
- `rds-sg`: accepts port 5432 from backend only
- `redis-sg`: accepts port 6379 from backend only

---

## Database (`rds.tf`)

| Setting | Value |
|---|---|
| Engine | PostgreSQL 16 |
| Instance | `db.t3.micro` |
| Storage | 20GB gp2, auto-scales to 100GB |
| Database name | `customer_voice_ai` |
| Username | `postgres` |
| Backups | 7-day retention, daily at 03:00–04:00 UTC |
| Public access | Disabled — VPC only |
| Deletion protection | Enabled |
| Final snapshot | Taken on destroy |

pgvector is enabled via Alembic migration (`CREATE EXTENSION IF NOT EXISTS vector`) — no custom parameter group needed.

---

## Cache (`elasticache.tf`)

| Setting | Value |
|---|---|
| Engine | Redis 7 |
| Instance | `cache.t3.micro` |
| Nodes | 1 |
| Port | 6379 |

Used as Celery broker (`/0`) and result backend (`/1`).

---

## Container Registry (`ecr.tf`)

| Setting | Value |
|---|---|
| Repository | `customervoice-ai-backend` |
| Tag mutability | Mutable (`:latest` can be overwritten) |
| Scan on push | Enabled — flags CVEs automatically |
| Lifecycle policy | Keep last 10 images, delete older ones |

---

## Compute (`ecs.tf`)

### Cluster
Name: `customervoice-ai`

### Backend Service
| Setting | Value |
|---|---|
| CPU | 0.5 vCPU |
| Memory | 1GB |
| Ephemeral storage | 50GB (increased from default 20GB for sentence-transformers model) |
| Port | 8000 |
| Health check | `GET /health` every 30s |
| Circuit breaker | Enabled — auto-rollback on failed deploy |
| Deployment | Rolling — keeps old task until new one is healthy |

Runs: `alembic upgrade head && uvicorn app.main:app`

### Worker Service
| Setting | Value |
|---|---|
| CPU | 1 vCPU |
| Memory | 2GB |
| Circuit breaker | Enabled |

Runs: `celery -A workers.celery_app worker --autoscale=4,1`

Worker uses more CPU/memory than the backend because it runs ML inference (sentence-transformers embedding generation) and LLM calls.

### Environment Variables
Non-secret config is injected as plain environment variables (DB host, port, Redis URL). Secrets are injected from Secrets Manager at task startup — never stored in plaintext in the task definition.

PyTorch and HuggingFace cache directories are redirected from `/tmp` to `/app/.cache` (which has ephemeral storage) to avoid runtime disk exhaustion:

```hcl
{ name = "TORCH_HOME",              value = "/app/.cache/torch" },
{ name = "TORCHINDUCTOR_CACHE_DIR", value = "/app/.cache/torchinductor" },
{ name = "TRANSFORMERS_CACHE",      value = "/app/.cache/transformers" },
{ name = "HF_HOME",                 value = "/app/.cache/huggingface" },
```

---

## Load Balancer (`alb.tf`)

| Resource | Detail |
|---|---|
| ALB | Public-facing, multi-AZ across 2 public subnets |
| HTTP listener (80) | 301 redirect → HTTPS |
| HTTPS listener (443) | Forwards to backend target group |
| SSL policy | `ELBSecurityPolicy-TLS13-1-2-2021-06` (TLS 1.3) |
| Health check | `GET /health`, 200 required |
| ACM certificate | `api.customer-analyticsgo.trade`, DNS validated via Cloudflare |
| Deletion protection | Enabled |

---

## Frontend (Vercel)

The Next.js frontend is deployed on Vercel — not in AWS. It communicates with the backend via the public ALB.

| Setting | Value |
|---|---|
| Platform | Vercel |
| Project URL | `https://project-5y6ee.vercel.app` |
| Root directory | `frontend/` |
| Framework | Next.js 14 |
| Key env var | `NEXT_PUBLIC_API_URL=https://api.customer-analyticsgo.trade` |

`next.config.js` rewrites all `/api/*` calls through Next.js server to the backend, avoiding CORS issues:

```js
async rewrites() {
  return [{
    source: '/api/:path*',
    destination: `${process.env.NEXT_PUBLIC_API_URL}/api/:path*`,
  }]
}
```

**Important:** `NEXT_PUBLIC_API_URL` must be set in Vercel → Settings → Environment Variables. Without it the rewrite falls back to `http://localhost:8000`, which Vercel blocks as a private address.

---

## Secrets (`secrets.tf`)

Secret name: `customervoice-ai/production`

| Key | Description |
|---|---|
| `DB__PASSWORD` | RDS master password |
| `OPENROUTER_API_KEY` | OpenRouter API key for Gemini 2.0 Flash |
| `GOOGLE_REVIEWS_API_KEY` | SerpAPI key for Google Maps reviews |
| `SECRET_KEY` | FastAPI session secret |

Secrets are injected into ECS containers at startup. Terraform creates the secret with placeholder values — update with real keys via AWS Console or CLI after first apply. Terraform ignores subsequent changes to secret values (`ignore_changes`).

---

## IAM (`iam.tf`)

Two roles with separate responsibilities:

**`ecs-execution` role** — used by ECS itself (not your app):
- Pull images from ECR
- Write logs to CloudWatch
- Read secrets from Secrets Manager at task startup

**`ecs-task` role** — used by your running application:
- Read secrets from Secrets Manager at runtime

---

## DNS

Domain `customer-analyticsgo.trade` is managed in **Cloudflare** (not Route 53). Two manual CNAME records required:

| Name | Target | Purpose |
|---|---|---|
| `_<hash>.api` | `_<hash>.acm-validations.aws` | ACM certificate validation |
| `api` | `<alb-dns>.ap-southeast-2.elb.amazonaws.com` | Route traffic to ALB |

Both records must have Proxy status **OFF** (grey cloud) in Cloudflare.

**After every `terraform apply` that recreates the ALB**, get the new DNS name and update the `api` CNAME:
```bash
terraform output alb_dns_name
```

---

## Outputs

After `terraform apply`, retrieve values with:

```bash
terraform output alb_dns_name              # ALB URL for Cloudflare CNAME
terraform output acm_validation_cname_name # ACM validation record name
terraform output acm_validation_cname_value # ACM validation record value
terraform output ecr_repository_url        # ECR URL for docker push
terraform output rds_endpoint              # RDS host (sensitive)
terraform output redis_endpoint            # Redis host (sensitive)
```

---

## Common Commands

```bash
# Plan changes without applying
export TF_VAR_db_password=$(cat ../settings/db_password.txt)
terraform plan

# Apply changes
export TF_VAR_db_password=$(cat ../settings/db_password.txt)
terraform apply

# Tear down everything
terraform destroy

# Force ECS redeploy after pushing a new image
aws ecs update-service \
  --cluster customervoice-ai \
  --service customervoice-ai-backend \
  --force-new-deployment \
  --region ap-southeast-2

# Release a stuck Terraform state lock
terraform force-unlock <lock-id>
```

### Full deploy sequence (after terraform apply)

```bash
# 1. Update Cloudflare api CNAME to new ALB
terraform output alb_dns_name

# 2. Build CPU-only image (must run from project root)
docker build --platform linux/amd64 -f backend/Dockerfile . -t customervoice-ai-backend

# 3. Push to ECR
ECR_URL=$(terraform output -raw ecr_repository_url)
aws ecr get-login-password --region ap-southeast-2 | \
  docker login --username AWS --password-stdin $ECR_URL
docker tag customervoice-ai-backend:latest $ECR_URL:latest
docker push $ECR_URL:latest

# 4. Force redeploy
aws ecs update-service \
  --cluster customervoice-ai \
  --service customervoice-ai-backend \
  --force-new-deployment \
  --region ap-southeast-2

# 5. Verify
curl https://api.customer-analyticsgo.trade/health
# Expected: {"status":"ok","env":"production"}
```

---

## Deployment Failures & Fixes

### Failure 1 — ACM Certificate Timeout
**Error:** `timeout while waiting for state to become 'ISSUED' (last state: 'PENDING_VALIDATION', timeout: 1h15m0s)`

**Root cause:**
- Cloudflare DNS CNAME record was not added before running `terraform apply`
- ACM timed out after 80 minutes waiting for DNS proof of ownership

**Fix:**
1. Get validation values: `terraform output acm_validation_cname_name/value`
2. Add CNAME to Cloudflare with Proxy = OFF (grey cloud)
3. Re-run `terraform apply` — certificate validates within ~2 minutes

**Result:** Certificate issued successfully on retry.

---

### Failure 2 — RDS Invalid Engine Version
**Error:** `InvalidParameterCombination: Cannot find version 16.3 for postgres`

**Root cause:**
- PostgreSQL 16.3 is not available in `ap-southeast-2` (Sydney)

**Fix:**
- Changed `engine_version = "16.3"` → `"16"` — AWS selects the latest available minor version in the region

**Result:** RDS instance created successfully with PostgreSQL 16.

---

### Failure 3 — pgvector Invalid Parameter Group
**Error:** `InvalidParameterValue: Invalid parameter value: vector for: shared_preload_libraries`

**Root cause:**
- A custom RDS parameter group was setting `shared_preload_libraries = "vector"`
- pgvector is a SQL extension, not a preloadable shared library

**Fix:**
- Removed the custom parameter group from `rds.tf`
- pgvector enabled via Alembic migration instead: `CREATE EXTENSION IF NOT EXISTS vector;`

**Result:** RDS created without parameter group. pgvector enabled at app startup via migration.

---

### Failure 4 — Docker Image Platform Mismatch
**Error:** `CannotPullContainerError: image Manifest does not contain descriptor matching platform 'linux/amd64'`

**Root cause:**
- Image built on Apple Silicon (ARM64) without specifying target platform
- ECS Fargate runs `linux/amd64` only

**Fix:**
- Always build with `--platform linux/amd64`:
```bash
docker build --platform linux/amd64 -f backend/Dockerfile .
```

**Result:** Image runs correctly on Fargate.

---

### Failure 5 — Wrong Docker Build Context
**Error:** `failed to compute cache key: "/backend": not found`

**Root cause:**
- Ran `docker build -t customervoice-ai-backend ./backend` (using `backend/` as the build context)
- The Dockerfile copies from `backend/`, `workers/`, and `pipelines/` — all of which require the **project root** as context
- When context is `./backend`, the paths `backend/pyproject.toml` and `workers/` don't exist relative to it

**Fix:**
- Always run from the project root:
```bash
docker build --platform linux/amd64 -f backend/Dockerfile .
#                                                          ^ project root as context
```

**Result:** Build completes successfully.

---

### Failure 6 — Insufficient Ephemeral Storage (Image Extraction)
**Error:** `no space left on device` during image layer extraction

**Root cause:**
- Default Fargate ephemeral storage is 20GB
- PyTorch with CUDA libraries is ~4–6GB compressed
- Combined with OS, Python packages, and app code, image extraction exceeded 20GB

**Fix:**
- Increased ephemeral storage to 50GB in `ecs.tf`:
```hcl
ephemeral_storage {
  size_in_gib = 50
}
```

**Result:** Image extracted successfully. However, CUDA torch still caused a runtime failure (see Failure 7).

---

### Failure 7 — CUDA PyTorch Causes Runtime Disk Exhaustion
**Error:** `[Errno 28] No space left on device` in `/tmp/torchinductor_appuser/`

**Root cause:**
- `sentence-transformers` lists `torch` as a dependency without specifying an index
- `uv` resolved `torch` from PyPI, which defaults to the CUDA build (~4–6GB of NVIDIA libraries)
- Even with 50GB ephemeral storage, CUDA torch filled the image leaving no room for runtime model caching in `/tmp`
- `torch` was only a transitive dependency so `[tool.uv.sources]` index overrides did not apply to it

**Approach 1 (partial fix):** Redirected cache dirs via environment variables:
```hcl
{ name = "TORCH_HOME",              value = "/app/.cache/torch" },
{ name = "TORCHINDUCTOR_CACHE_DIR", value = "/app/.cache/torchinductor" },
```
This helped but CUDA torch was still in the image.

**Approach 2 (failed):** Added `pip install torch --force-reinstall --index-url .../cpu` as a Dockerfile layer after `uv sync`. Docker layer ordering meant the CPU reinstall ran correctly but uv's cached CUDA packages were still included in earlier layers.

**Fix (definitive):**
1. Added `torch` as a direct dependency in `pyproject.toml` so `[tool.uv.sources]` applies:
```toml
dependencies = [
    "torch",   # direct dep — required for uv.sources index override to apply
    ...
]

[tool.uv.sources]
torch = { index = "pytorch-cpu" }

[[tool.uv.index]]
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu"
explicit = true
```
2. Regenerated the lock file: `uv lock --upgrade-package torch`

**Result:** 19 CUDA/nvidia packages removed from lock file. Image size dropped from ~6–7GB to **2.38GB**. ECS tasks start successfully.

---

### Failure 8 — Wrong Secrets Manager Key Format
**Error:** App crashed on startup — database connection failed

**Root cause:**
- Secret was stored as `DB__PASSWORD = "postgresql+psycopg2://user:pass@host/db"` (full URL as the password value)
- App uses `pydantic-settings` with `env_nested_delimiter="__"` — each config field maps to a separate env var
- Other required keys (`DB__HOST`, `DB__PORT`, `DB__NAME`) were missing entirely

**Fix:**
- Updated Secrets Manager with individual nested keys matching pydantic config fields:
```json
{
  "DB__HOST": "<rds-endpoint>",
  "DB__PORT": "5432",
  "DB__NAME": "customer_voice_ai",
  "DB__USERNAME": "postgres",
  "DB__PASSWORD": "<password>",
  "CELERY__BROKER_URL": "redis://<redis-endpoint>:6379/0",
  "CELERY__RESULT_BACKEND": "redis://<redis-endpoint>:6379/1",
  "OPENROUTER_API_KEY": "...",
  "GOOGLE_REVIEWS_API_KEY": "...",
  "SECRET_KEY": "..."
}
```

**Result:** App starts and connects to database on first attempt.

---

### Failure 9 — Terraform State Out of Sync After Manual Deletion
**Error:** `terraform destroy` showed `0 resources destroyed` after manually deleting AWS resources to reduce costs

**Root cause:**
- NAT Gateway ($43/month), RDS, and ALB were deleted manually via AWS Console/CLI to stop billing
- Terraform state still tracked them as existing — `terraform destroy` tried to destroy but resources were already gone, resulting in 0 actions
- ECS services had `desired_count=1` but could not start tasks because VPC/subnets/security groups were deleted out of band

**Fix:**
- Ran `terraform force-unlock <lock-id>` to clear a stale state lock left from a failed apply
- Confirmed state was still valid: `terraform plan` showed no changes once remaining resources (RDS, ElastiCache, ECR) were accounted for
- Re-ran the full deploy sequence to restore networking and restart ECS tasks

**Result:** Infrastructure fully reconciled. `terraform plan` shows no changes.

---

### Failure 10 — Cloudflare CNAME Pointing to Old ALB After Recreation
**Error:** `curl: (6) Could not resolve host: api.customer-analyticsgo.trade`

**Root cause:**
- After infrastructure was torn down and recreated, the ALB got a new DNS name (new ID in the hostname)
- Old Cloudflare CNAME still pointed to the previous ALB: `customervoice-ai-alb-1737351399.ap-southeast-2.elb.amazonaws.com`
- New ALB: `customervoice-ai-alb-806861507.ap-southeast-2.elb.amazonaws.com`

**Fix:**
- After every `terraform apply` that recreates the ALB, get the new DNS name:
```bash
terraform output alb_dns_name
```
- Update the `api` CNAME in Cloudflare to the new value (Proxy = OFF / grey cloud)

**Result:** DNS resolves correctly to public IPs within 1–2 minutes.

---

### Failure 11 — Vercel Frontend `DNS_HOSTNAME_RESOLVED_PRIVATE`
**Error:** `404: NOT_FOUND — Code: DNS_HOSTNAME_RESOLVED_PRIVATE` in browser dev tools

**Root cause:**
- `next.config.js` rewrites `/api/*` → `${NEXT_PUBLIC_API_URL}/api/*` on the Next.js server (not the browser)
- `NEXT_PUBLIC_API_URL` was not set on Vercel, so it fell back to `http://localhost:8000`
- Vercel's serverless infrastructure blocks outbound requests to `localhost` and private IP ranges as a security measure

**Fix:**
- Set the environment variable in Vercel → Settings → Environment Variables:

| Key | Value |
|---|---|
| `NEXT_PUBLIC_API_URL` | `https://api.customer-analyticsgo.trade` |

- Triggered a redeployment

**Result:** Frontend API calls routed correctly to the AWS backend.
