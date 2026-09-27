# infra/terraform

One EC2 box (`t4g.small`, Ubuntu 24.04 arm64, Docker), an Elastic IP, RDS
Postgres 16 (`db.t4g.micro`, private), one private S3 bucket for uploads, and
the IAM role that ties them together — all in the default VPC of `us-east-1`.
The box is managed through SSM Session Manager; there is no SSH.

Every command below runs on the laptop with AWS credentials for the account
(`aws configure`, region `us-east-1`), unless it says "on the box". The
`.envrc` here unsets the dev MinIO `AWS_*` keys that the root `.envrc`
exports; without it the CLI and Terraform would use those and get
`InvalidClientTokenId`.

## What costs money

While it exists: the `t4g.small` instance and its 20 GB gp3 root volume, the
`db.t4g.micro` RDS instance and its 20 GB gp3 storage + 7 days of backups, and
the Elastic IP (AWS bills every public IPv4 address, attached or not). Cents a
month: the uploads bucket and the state bucket. The box runs with standard
CPU credits (it throttles rather than bills when they run out); RDS's `t4g`
credits are always unlimited and cannot be changed. `terraform destroy` removes
everything except the state bucket, which the bootstrap module owns.

## 1. Bootstrap remote state (once per account)

```sh
cd infra/terraform/bootstrap
terraform init
terraform apply
terraform output
```

Creates the state bucket (`hax-tfstate-<suffix>`, versioned, private,
encrypted). State locking is S3-native, so there is no lock table. This module
keeps its own state in
a local `terraform.tfstate` (gitignored): it creates the backend, so it cannot
use it. Keep that file; the bucket is `prevent_destroy`.

## 2. Point the root module at the backend

```sh
cd ..   # back to infra/terraform
cp backend.hcl.example backend.hcl   # fill bucket from step 1
terraform init -backend-config=backend.hcl
```

`backend.hcl` is gitignored (the bucket name carries a random suffix). Init
downloads the providers pinned by `.terraform.lock.hcl` and connects to the
remote state.

## 3. Variables

```sh
cp terraform.tfvars.example terraform.tfvars
```

On the Free account plan also set `db_backup_retention_days = 1` (its
maximum; RDS rejects more with `FreeTierRestrictionError`). Set `domain` and a
strong `db_master_password` (e.g. `openssl rand -base64 32 |
tr -d '/+='`; RDS rejects `/`, `@`, `"` and spaces). `terraform.tfvars` is
gitignored. The password also lands in the remote state, which is why the state
bucket is private and encrypted.

## 4. Plan

```sh
terraform plan -out=tfplan
```

Expect 15 resources to add and nothing to change or destroy. Read it:
nothing outside the list at the top of this file should appear.

## 5. Apply

```sh
terraform apply tfplan
```

Takes ~10 minutes, most of it RDS. The box boots and runs `user-data.sh` once
(Docker Engine + the `docker compose` plugin, `/opt/hax`); give it a couple of
minutes after apply before opening a session.

## 6. Outputs

```sh
terraform output
```

- `elastic_ip` — the domain's A record.
- `rds_endpoint` — `host:5432` for `DATABASE_URL` / `MIGRATIONS_DATABASE_URL`
  (append `?sslmode=require`; RDS forces TLS).
- `s3_bucket` — `S3_BUCKET` in the box's `.env`. No AWS keys go in that `.env`:
  the containers get credentials from the instance role.
- `instance_id`, `ssm_command` — `aws ssm start-session --target <id>` opens a
  shell on the box (needs the Session Manager plugin for the AWS CLI). The
  session logs in as `ssm-user`; run `sudo -iu ubuntu` first — `/opt/hax` and
  the docker group belong to `ubuntu`.

## 7. RDS bootstrap

RDS is reachable only from the box. From an SSM session on the box, run
`rds-bootstrap.sql` as the master user: it enables `vector` and creates the
least-privilege `hax_app` role the app connects as (the same block
`infra/compose/postgres/init.sql` runs in dev). The exact commands sit next to
that file.

## 8. Box setup and first deploy

The compose file, Caddyfile and filled `.env` go to `/opt/hax` on the box, then
`docker compose pull` and `up -d` (on the box it is the `docker compose` plugin;
the laptop's standalone `docker-compose` is equivalent). The runbook is
`infra/deploy/README.md`.
