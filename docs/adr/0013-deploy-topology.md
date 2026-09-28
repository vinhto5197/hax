# 0013 — Deploy topology: one box, managed data, thin edge

**Status:** accepted
**Date:** 2026-09-27

## Context

M3 puts hax on a public URL early, so that M4 and M5 ride a running
pipeline instead of ending in a one-off deploy. At this volume (a handful of
users) every managed component beyond the data stores adds a bill without
adding capability, and each has a configuration-level upgrade path. Nothing
in the code is provider-locked: object storage is boto3 with a configurable
endpoint (MinIO in dev), and Postgres, Redis and SMTP are plain protocols.

## Decision

**AWS core, thin edge**, provisioned by Terraform (`infra/terraform`):

- **One EC2 box** (`t4g.small`, Graviton, Ubuntu 24.04) runs the compose
  topology from `infra/compose/compose.prod.yml`: Caddy, api, worker, web,
  Redis, and a `migrate` one-shot. Caddy is the only service with published
  ports; it terminates TLS with Let's Encrypt and routes `/api/*` to uvicorn
  (SSE flushed, never buffered) and everything else to Next, so web and API
  are one origin and cookies are first-party. `/internal/*` is not routed
  publicly: Next's server reaches it over the compose network.
- **RDS Postgres 16** (`db.t4g.micro`, pgvector built in, TLS forced) in the
  box's availability zone, reachable only from the box's security group. The
  app connects as `hax_app`; the master user owns the schema and runs
  migrations (ADR 0012). `infra/terraform/rds-bootstrap.sql` is the
  once-per-database step RDS cannot run for us.
- **S3** for uploads, private, encrypted, reached through the **instance
  role** — no static AWS keys anywhere on the box. IMDSv2 only, hop limit 2
  so containers can still fetch role credentials.
- **Redis on the box** (`redis:7-alpine`, append-only, `noeviction`): broker
  and auth cache. A managed cache buys nothing at two users.
- **No SSH.** The box is managed through SSM Session Manager (instance role +
  agent); the security group opens 80/443 only.
- **Terraform state** in a versioned, private S3 bucket with S3-native
  locking (`use_lockfile`), created by a separate bootstrap module with
  local state. No DynamoDB table.
- **DNS** at Cloudflare, DNS-only (grey cloud): nothing sits in front of the
  SSE stream, and Let's Encrypt's HTTP challenge reaches Caddy directly. The
  registrar is separate (Porkbun).
- **Email** through Resend's SMTP endpoint, the same `SMTP_*` contract Mailpit
  serves in dev. SES's sandbox exit is a wait we did not need.
- **Deploys** are `infra/deploy/deploy.sh`: build both images, push to GHCR
  tagged by commit sha, then one SSM Run Command on the box that fetches the
  compose file and Caddyfile *at that sha from the public repo*, pins the
  image tags in `/opt/hax/images.env`, and runs `compose pull` + `up -d`. A
  deploy is therefore always a pushed commit, never a working tree, and
  rollback is `roll <older sha>`. CI (slice 3) calls the same script.
- **Secrets** live only in `/opt/hax/.env`, written by hand once, mode 600,
  read by compose. They never transit the deploy script or CI. The
  laptop-side mirror is a gitignored file. One file, but compose narrows it
  per service: the owner-role URL reaches only the `migrate` one-shot, and
  the web container gets no database, broker, model or mail credential.
- **Account plan: Free** (six months, hard spending cap, $200 credit). Its one
  observed restriction is RDS backup retention ≤ 1 day, so retention is a
  variable set in `terraform.tfvars`; the config defaults to 7. Upgrading to
  Paid is one click and keeps everything.

Hardening chosen at first apply because it cannot be added in place later:
encrypted root volume; standard (not unlimited) CPU credits so a runaway
cannot become a bill; `ignore_changes` on the AMI and subnet so a newer
Ubuntu image never replaces the box (and with it Caddy's certificates and the
Redis volume).

## Alternatives considered

- **Fargate / ECS** from the start: more moving parts (task definitions,
  ALB, NAT or public tasks, log driver) for the same two containers. Kept as
  the M3.5 path; the images and compose contract do not change.
- **ALB + ACM + Route 53**: worth it at a second box. Caddy does TLS and
  routing on one.
- **ElastiCache**: Redis is a broker and a small cache here; a managed
  instance would cost more than the box.
- **SES**: production access is a support request with a wait; Resend is
  verified in minutes on the same SMTP contract.
- **Cloudflare proxy** (orange cloud): buffers and time-limits long
  responses on the free tier and complicates the ACME challenge. Off until
  abuse makes it worth the three fixes.
- **Managed CI-side Terraform** (Atlantis, HCP): plan-on-PR is the right
  shape for a team; for one operator, plan read at the laptop is the review.
- **Embedding compose files in the SSM command**: worked, but the parameter
  size limit is poorly documented and the payload grew past 7 KB; fetching
  from GitHub at the sha is smaller and makes "deploy = pushed commit" a
  rule the script enforces.

## Consequences

- Single box, single AZ: a box failure is downtime until `terraform apply`
  rebuilds it (about ten minutes; the Elastic IP and DNS carry over, Caddy
  re-issues certificates). Redis contents (queued jobs, rate-limit counters)
  die with the box; nothing durable lives there.
- A deploy recreates the app containers, so each deploy is a few seconds of
  downtime. Zero-downtime is an M3.5 concern (a second box behind an ALB).
- `deploy.sh` enforces "image `<sha>` is commit `<sha>`": build and push
  refuse a dirty tree, a non-HEAD sha and an existing tag. Rollback is
  `roll <older sha>`, but across a migration the schema must be downgraded
  first (the runbook has the command); expand-only migrations keep that rare.
- Only the running images stay on the box; GHCR keeps every sha, so a
  rollback is a pull, not a rebuild.
- RDS point-in-time recovery reaches back one day on the Free plan. A
  manual snapshot before a risky migration is the operator's move.
- Uploads are not versioned by choice (user data is sensitive; a deleted
  document must be gone), so an app-side delete is unrecoverable.
- The dev MinIO credentials are named `S3_ACCESS_KEY_ID`/`S3_SECRET_ACCESS_KEY`,
  never `AWS_*`: the repo's shell exports `.env`, and AWS tools would read
  those first and authenticate to the real account with MinIO's keys.
- Every "thin" choice above has its upgrade listed under M3.5 in CLAUDE.md:
  ALB + ACM + Route 53, ElastiCache, SES, CloudWatch alarms, Fargate, a
  staging variable, OIDC for the deploy job, RDS CA verification, CSP nonce.
