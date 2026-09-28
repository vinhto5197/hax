# infra/terraform

One EC2 box (`t4g.small`, Ubuntu 24.04 arm64, Docker), an Elastic IP, RDS
Postgres 16 (`db.t4g.micro`, private), one private S3 bucket for uploads, and
the IAM role that ties them together — all in the default VPC of `us-east-1`.
The box is managed through SSM Session Manager; there is no SSH.

Every command below runs on the laptop with AWS credentials for the account
(`aws configure`, region `us-east-1`), unless it says "on the box".

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

RDS is reachable only from the box, so this runs there, once, before the
first migration (the RLS migration grants to `hax_app` and needs the role).
`rds-bootstrap.sql` enables `vector` and creates the least-privilege
`hax_app` role the app connects as — the block `infra/compose/postgres/init.sql`
runs in dev.

On the laptop, generate the app password and keep it for the box's `.env`:

```sh
openssl rand -base64 32 | tr -d '/+='
```

Open a session (`ssm_command` output), `sudo -iu ubuntu`, then paste, with
the three placeholders filled (`rds_endpoint` without the `:5432`):

```sh
docker run --rm -i -e PGPASSWORD='<master password>' postgres:16 \
  psql -h <rds host> -U hax -d hax -v ON_ERROR_STOP=1 \
  -v app_password='<app password>' -f - <<'SQL'
<contents of rds-bootstrap.sql>
SQL
```

The heredoc feeds the file to `psql -f -`; `docker run` pulls the `postgres:16`
image the first time (~150 MB). psql negotiates TLS on its own — RDS forces
it. The last two statements print the check: `hax_app | f | f` and
`vector | 0.8.x`. Passwords are given on the command line only inside the
SSM session; they land in that shell's history, so `history -c` afterwards.

## 8. Box setup and first deploy

The filled `.env` goes to `/opt/hax` on the box by hand, once; everything
else — images, compose file, Caddyfile, `pull` and `up` — is
`infra/deploy/deploy.sh`, run from the laptop (later from CI). The runbook is
`infra/deploy/README.md`.
