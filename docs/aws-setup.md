# AWS Infrastructure for tag2now

Current production setup and the one-time AWS provisioning behind it.

## Architecture

```
Route 53 (tag2now.click)
    │
    ├── CloudFront ──────► Lightsail :80  (static assets only)
    │                          nginx serves /dist
    │
    └── (direct) ────────► Lightsail :8000  (/api, not via CloudFront)

Lightsail single instance — docker compose
    ├── fe    (nginx + built SPA)
    ├── be    (FastAPI)
    ├── redis
    ├── postgres
    └── dynamodb-local
```

Only static assets go through CloudFront. `/api/` calls reach the instance
directly, so they never appear in CloudFront logs — which is exactly what makes
the access logs usable as a page-load counter (see [Analytics](#analytics)).

## Deployment

**Images** are built and pushed to ECR by GitHub Actions
(`.github/workflows/deploy.yml`, triggered on `v*` tags):

| Repo | ECR repository |
|------|----------------|
| tag2now-BE | `tag2-now/be` |
| tag2now-FE | `tag2-now/fe` |

**Release is automatic.** The same `v*` tag that builds the image also runs a
`deploy` job that SSHes into Lightsail. Each repo releases only its own service
and pins only its own image tag, so a BE release never rolls `fe` and vice versa:

| Repo | Writes to `.env.prod` | Restarts | Also uploads |
|------|----------------------|----------|--------------|
| tag2now-BE | `BE_IMAGE_TAG` | `be` | `compose.prod.yml` |
| tag2now-FE | `FE_IMAGE_TAG` | `fe` | — |

`compose.prod.yml` is owned by **tag2now-BE** — it describes the whole stack,
including `fe`. Edit it in that repo; a BE release scp's it over the instance's
copy, so on-instance edits are lost.

The BE job runs `alembic upgrade head` against the new image *before* replacing
the serving container, so a failed migration leaves the old container running.

### Actions configuration

Both repos live in the **`tag2now`** GitHub organization and deploy to the same
instance, so everything except the ECR repository name is identical between
them. Define the shared values **once at the org level** rather than copying
them into each repo — the SSH key in particular, since a rotation applied to
only one repo leaves half the stack unreleasable.

Scope every org secret to **"Selected repositories" → `tag2now-BE`,
`tag2now-FE`**. "All repositories" would hand the production SSH key to any repo
anyone later creates in the org.

**Org-level** (Settings → Secrets and variables → Actions, on the organization):

| Name | Kind | Value |
|------|------|-------|
| `PROD_SSH_PRIVATE_KEY` | secret | private key whose public half is in the instance's `authorized_keys` |
| `PROD_SSH_KNOWN_HOSTS` | secret | output of `ssh-keyscan <instance-ip>` |
| `PROD_HOST` | secret | instance IP or hostname |
| `PROD_USER` | secret | SSH user |
| `PROD_DEPLOY_PATH` | secret | directory holding `compose.prod.yml` and `.env.prod` |
| `ECR_REGISTRY` | variable | `864573346741.dkr.ecr.ap-northeast-2.amazonaws.com` |
| `AWS_REGION` | variable | `ap-northeast-2` |

**Repo-level** (each repo, because the values genuinely differ):

| Name | Kind | tag2now-BE | tag2now-FE |
|------|------|------------|------------|
| `ECR_REPOSITORY` | variable | `tag2-now/be` | `tag2-now/fe` |
| `AWS_ROLE_ARN` | secret | OIDC role for the `build` job | same, unless one role covers both ECR repos |

If a single OIDC role can push to both ECR repositories, promote `AWS_ROLE_ARN`
to the org as well; that depends on the role's trust policy and repository
conditions, which are not documented here.

**The `production` environment stays per-repo.** GitHub has no org-level
environments, so create it in both repos — it is what the `deploy` job's
`environment: production` refers to, and where a required-reviewer gate would go
if prod releases should need approval. Org secrets resolve normally inside an
environment-scoped job, so nothing needs duplicating into the environment
itself.

> Org secrets scoped to selected repositories require a public repo on the Free
> plan, or a Team/Enterprise plan for private repos. On a Free org with private
> repos, define all of the above per-repo instead — the workflows are unchanged
> either way, since `secrets.*` and `vars.*` resolve identically at both levels.

`StrictHostKeyChecking=yes` is enforced, so `PROD_SSH_KNOWN_HOSTS` must be
correct or the job fails rather than trusting an unknown host.

The **instance** performs its own `aws ecr get-login-password`, so its IAM role
(or on-box credentials) needs `ecr:GetAuthorizationToken` and pull permissions —
the workflow's `AWS_ROLE_ARN` is only used by the `build` job on the runner.

To release by hand — a rollback, or when Actions is unavailable:

```bash
cd "$PROD_DEPLOY_PATH"
sed -i 's/^BE_IMAGE_TAG=.*/BE_IMAGE_TAG=v1.2.3/' .env.prod
aws ecr get-login-password --region ap-northeast-2   | docker login --username AWS --password-stdin 864573346741.dkr.ecr.ap-northeast-2.amazonaws.com
docker compose --env-file .env.prod -f compose.prod.yml pull be
docker compose --env-file .env.prod -f compose.prod.yml run --rm be python -m alembic upgrade head
docker compose --env-file .env.prod -f compose.prod.yml up -d be
```

For the first release after Alembic adoption, an already-provisioned database
must be recorded at the baseline instead of recreated:

```bash
docker compose --env-file .env.prod -f compose.prod.yml run --rm be python -m alembic stamp head
```

Run `stamp` exactly once, only after confirming the existing schema matches the
baseline migration. All later releases use `upgrade head`, which the deploy job
does for you.

## Secrets

RPCN credentials live in **`.env.prod` on the instance** — not in Secrets
Manager, not in the repo. The instance runs its own `compose.yml` (not the one
in this repo, which is for local development) and pulls the file in via
`env_file`:

```yaml
services:
  be:
    env_file:
      - .env.prod
```

So a plain `docker compose up -d` picks the credentials up; no `--env-file`
flag is needed.

Required keys: `RPCN_USER`, `RPCN_PASSWORD` (see the module docstring in
`src/app.py` for the full list).

## Analytics

Two independent sources. Both are effectively free; they cover each other's
blind spots.

| Source | Counts | Blind spot |
|--------|--------|------------|
| GA4 | real user sessions | ad blockers drop ~10–30% |
| CloudFront logs | every page load | includes bots |

### GA4

Measurement ID `G-S4Y67MPNPR`, embedded in `tag2now-FE/index.html`. Device
category (mobile/desktop/tablet) and OS (Android/iOS/Windows/macOS) are
collected automatically by Enhanced Measurement — no per-event code.

Reports → Tech → Tech details. Date range is freely selectable.

Note: the SPA has no router, so GA4 records one `page_view` per load. Tab
switches are not tracked.

### CloudFront access logs → S3 → Athena

One-time setup:

```bash
# 1. Log bucket (ACLs required — CloudFront standard logging writes via ACL)
aws s3api create-bucket \
  --bucket tag2now-cf-logs \
  --region ap-northeast-2 \
  --create-bucket-configuration LocationConstraint=ap-northeast-2

aws s3api put-bucket-ownership-controls \
  --bucket tag2now-cf-logs \
  --ownership-controls 'Rules=[{ObjectOwnership=BucketOwnerPreferred}]'

# 2. Expire logs after 90 days
aws s3api put-bucket-lifecycle-configuration \
  --bucket tag2now-cf-logs \
  --lifecycle-configuration '{
    "Rules": [{
      "ID": "expire-90d",
      "Status": "Enabled",
      "Filter": {"Prefix": "cf/"},
      "Expiration": {"Days": 90}
    }]
  }'
```

Then enable **standard logging** on the CloudFront distribution (console:
Distribution → Settings → Edit → Standard logging → on), pointing at
`tag2now-cf-logs` with prefix `cf/`.

Create the Athena table once:

```sql
CREATE EXTERNAL TABLE IF NOT EXISTS cf_logs (
  `date` DATE, time STRING, x_edge_location STRING, sc_bytes BIGINT,
  c_ip STRING, cs_method STRING, cs_host STRING, cs_uri_stem STRING,
  sc_status INT, cs_referer STRING, cs_user_agent STRING, cs_uri_query STRING,
  cs_cookie STRING, x_edge_result_type STRING, x_edge_request_id STRING,
  x_host_header STRING, cs_protocol STRING, cs_bytes BIGINT, time_taken FLOAT,
  x_forwarded_for STRING, ssl_protocol STRING, ssl_cipher STRING,
  x_edge_response_result_type STRING, cs_protocol_version STRING,
  fle_status STRING, fle_encrypted_fields INT, c_port INT,
  time_to_first_byte FLOAT, x_edge_detailed_result_type STRING,
  sc_content_type STRING, sc_content_len BIGINT,
  sc_range_start BIGINT, sc_range_end BIGINT
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY '\t'
LOCATION 's3://tag2now-cf-logs/cf/'
TBLPROPERTIES ('skip.header.line.count'='2');
```

Platform breakdown over any period (Athena has no 30-day query limit):

```sql
SELECT
  CASE
    WHEN cs_user_agent LIKE '%Android%' THEN 'Android'
    WHEN REGEXP_LIKE(cs_user_agent, 'iPhone|iPad|iPod') THEN 'iOS'
    WHEN cs_user_agent LIKE '%Windows%' THEN 'Windows'
    WHEN cs_user_agent LIKE '%Mac OS X%' THEN 'macOS'
    WHEN cs_user_agent LIKE '%Linux%' THEN 'Linux'
    ELSE 'Other'
  END AS os,
  COUNT(DISTINCT c_ip) AS unique_visitors,
  COUNT(*)             AS page_loads
FROM cf_logs
WHERE "date" BETWEEN DATE '2026-06-01' AND DATE '2026-08-31'
  AND cs_uri_stem IN ('/', '/index.html')
GROUP BY 1
ORDER BY 2 DESC;
```

Two details make this number trustworthy:

- **`cs_uri_stem IN ('/', '/index.html')`** — the rooms tab polls `/api/rooms/all`
  every 10 s (`useRooms.ts`), so counting requests would massively over-weight
  long-lived desktop sessions. Filtering to page loads sidesteps that entirely.
- **`COUNT(DISTINCT c_ip)`** — visitors, not hits.

Bots are not excluded; add a `cs_user_agent NOT LIKE '%bot%'` filter if the
numbers look inflated.

### Cost

| Item | ~Monthly |
|------|----------|
| GA4 | $0 |
| CloudFront standard logging | $0 (feature is free) |
| S3 storage (~0.5 GB, 90-day expiry) | ~$0.013 |
| Athena (~1 query/month) | ~$0.003 |
| **Total** | **< $0.02** |

CloudWatch custom metrics were considered and rejected: ~$0.30 per
metric-dimension combination per month (~$4 here), with cardinality risk as
dimensions grow, in exchange for real-time dashboards that platform stats do not
need.
