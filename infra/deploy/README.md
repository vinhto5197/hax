# infra/deploy

How a commit reaches the box. `deploy.sh` is the whole mechanism: build the
two images, push them to GHCR, and tell the box (over SSM) to fetch the
compose files at that commit and restart on the new tags. CI runs the same
script; by hand it is one command. The box was provisioned by
`infra/terraform` (its README, steps 1–7, come first).

## Once: what the script cannot do for you

1. **DNS.** In Cloudflare (DNS-only, grey cloud): an `A` record for the
   domain pointing at `terraform output elastic_ip`. Wait until
   `dig +short <domain>` answers with it. Caddy asks Let's Encrypt for a
   certificate on first start, and the challenge must reach the box.
2. **GHCR login on the laptop.** The `gh` token needs the packages scopes:
   `gh auth refresh -s write:packages,read:packages`, then
   `gh auth token | docker login ghcr.io -u <github user> --password-stdin`.
3. **Package visibility.** After the first push, make both packages public
   (GitHub → your profile → Packages → `hax-python` / `hax-web` → Package
   settings → Change visibility). The repo is public and the images hold no
   secrets, and a public package lets the box pull with no credentials.
4. **`/opt/hax/.env` on the box.** Copy `.env.prod.example` to
   `infra/compose/.env.prod` (gitignored), fill every `<placeholder>` — the
   Terraform outputs give `rds_endpoint` and `s3_bucket`; the two database
   passwords come from `terraform.tfvars` (master) and the RDS bootstrap
   (`hax_app`); `AUTH_SECRET` and `INTERNAL_API_SECRET` from
   `openssl rand -base64 32`. Until email is set up, leave `SMTP_HOST` at an
   unreachable value so `send_email` fails fast instead of hanging. Then in
   an SSM session (`terraform output ssm_command`, `sudo -iu ubuntu`):

   ```sh
   cat > /opt/hax/.env <<'ENV'
   <paste the filled file>
   ENV
   chmod 600 /opt/hax/.env
   ```

   The file never leaves that directory: the script reads it, CI never sees
   it. Rotating a value is editing it there and `deploy.sh roll` (or the
   `up -d --force-recreate` below): containers read `env_file` only when
   they are created, never on `restart`.

## Every deploy: push to main

Only the tip of `main` rolls: the deploy job first asks GitHub for the
current tip and exits green without deploying when this run's commit is
older (two close pushes finishing out of order, or a re-run of an old run).

`.github/workflows/ci.yml` runs lint, tests, the web checks and a
generated-types drift check on every push and pull request; on a push to
`main` that passes, its `deploy` job runs `deploy.sh all` on an arm64 runner:
GHCR login with the run's own token, AWS access by assuming the deploy role
with the run's OIDC token (`infra/terraform/ci.tf`; no AWS key is stored in
GitHub), one deploy at a time (`concurrency: deploy-prod`). Watch it under
the repo's Actions tab; the job's last step prints the box's container table.

Two repository settings, once (Settings → Secrets and variables → Actions):
secret `AWS_DEPLOY_ROLE_ARN` = `terraform output deploy_role_arn`; variable
`HAX_INSTANCE_ID` = `terraform output instance_id`.

## By hand: the fallback and the rollback

```sh
git push                         # the box fetches compose files at the sha
infra/deploy/deploy.sh           # build + push + roll, at HEAD
```

Or by step: `deploy.sh build`, `deploy.sh push`, `deploy.sh roll [sha]`. A roll
also reloads Caddy gracefully, because `up -d` leaves a running container
alone when only its bind-mounted Caddyfile changed; the file is written in
place for the same reason (a single-file bind mount pins the inode, so a
renamed-over file is invisible to the container). If the container's view
still differs from the host's file, the roll recreates Caddy instead of
reloading it: a second of downtime, no new certificate (they live in a volume).
`build` and `push` always describe HEAD and refuse a dirty tree or an
existing tag, so an image named `<sha>` is exactly commit `<sha>`.

**Rollback** is `deploy.sh roll <older sha>`: images are kept per sha on
GHCR. If a migration landed between the two shas, roll back the schema first
or `migrate` fails on the old image ("Can't locate revision"). A failing
migrate stops the roll before it touches the running containers, so the box
keeps serving the newer commit and `images.env` still names it; nothing is
half-applied, but the rollback has not happened. On the box, with the
*current* image:

```sh
hc run --rm migrate alembic -c alembic.ini downgrade <revision at the older sha>
```

then `roll <older sha>`. Keep migrations expand-only where possible so a
rollback rarely needs this. One known exception: the migration that made
`users.email` nullable cannot be reversed while demo visitors exist — run
`DELETE FROM users WHERE email IS NULL` as the owner role first, or the
downgrade fails on the NOT NULL constraint.

On the box, `roll` takes `/opt/hax/.deploy.lock` (a second roll waits, up
to ten minutes), fetches `compose.prod.yml` and `Caddyfile` and writes the
image tags as staged copies next to `.env`, pulls, runs `migrate` once as a
throwaway container, and only then promotes the three files and runs
`up -d`; a failure before the promotion leaves the box untouched. Compose
orders the rest: `migrate` runs to head, `api` and `worker` wait for it, `caddy` waits
for `api` healthy. First deploy: `up` pulls ~1 GB of images, and Caddy's
certificate takes a few seconds after that; watch it with the logs below.

Verify: `https://<domain>` shows a real padlock and the landing page with the demo composer;
`https://<domain>/api/conversations` answers 401.

## When something is wrong

The uptime monitor (external, five-minute interval on `/api/health`) emails
first. Then, on the box: `docker ps` shows each container's health label;
`hc logs --tail=200 <service>` has the last minutes; `cat images.env` says
which commit is running (it is written only after that commit's migrate
succeeded). Rolling back is the section above. Database
recovery is from RDS's automated backups (console → the instance →
Maintenance & backups; one-day window on the Free plan): restore to a NEW
instance, repoint `DATABASE_URL` in `/opt/hax/.env`, `roll`.

## On the box

`terraform output ssm_command`, then `sudo -iu ubuntu`, `cd /opt/hax`, and

```sh
alias hc='docker compose --env-file .env --env-file images.env -f compose.prod.yml'
hc ps
hc logs -f --tail=100 caddy      # or api, worker, web, migrate
hc up -d --force-recreate worker # after editing .env (restart does NOT reload env_file)
```

Both `--env-file` flags matter: `.env` carries `SITE_ADDRESS`, `images.env`
the two image tags the last deploy pinned. Without them compose falls back
to `hax-python`/`hax-web`, which do not exist on the box.
