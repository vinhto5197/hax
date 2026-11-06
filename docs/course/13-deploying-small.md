# 13. Deploying small

Threads: B (full-stack engineering) · C (building with Claude Code)

## The idea

hax went live in the middle of the build, not at the end, so every later feature would ship through a running pipeline. Think of opening a food stall before a restaurant: one counter, one cook, a real fridge from a supplier. The dining room waits until people queue for tables.

## How hax does it

The whole site runs on one rented server. In AWS terms (Amazon Web Services, the cloud provider) that is one EC2 box (a virtual machine): a small `t4g.small` with an arm64 chip (the processor design phones use) running Ubuntu (a common Linux system). On it, Docker Compose runs a group of containers (each program sealed in its own box with everything it needs) from one file: the API (the backend that answers the app's requests), two background workers, the web app, Redis (a fast in-memory store), a one-shot `migrate` job (it updates the database's layout, then exits), and Caddy. Caddy, a web server, is the only thing reachable from outside. It gets TLS certificates (the padlock) and sends `/api/*` to the API and everything else to the web app, so the browser sees one site. The file is [compose.prod.yml](../../infra/compose/compose.prod.yml).

Postgres runs on RDS (AWS's managed database), reachable only from the box. Uploaded files go to S3 (AWS's file storage). The box reaches S3 through an instance role (AWS grants the machine itself permission), so no AWS key is stored on it. There is no SSH (remote login): the box is managed through SSM (AWS Systems Manager, which runs commands on it for you).

All of this is described in Terraform, a tool that turns text files into cloud resources, under [infra/terraform](../../infra/terraform/README.md).

A deploy is [deploy.sh](../../infra/deploy/deploy.sh): build two images (the packaged programs containers start from), push them to GHCR (GitHub's container registry) tagged with the commit's sha (the short code that names one commit), then one SSM command that fetches the compose file and Caddyfile *at that commit* and rolls the stack. A deploy is always a pushed commit; a rollback is `roll <older sha>`. CI (continuous integration, the checks GitHub runs on every push) calls the same script after lint (automatic style and error checks), tests, web checks and browser journeys (scripted runs of the site in a real browser) pass on `main` ([ci.yml](../../.github/workflows/ci.yml)). It signs in to AWS with OIDC, a short-lived identity token GitHub issues to that one workflow, so no AWS key is stored in GitHub either.

## What was decided, and why

[ADR 0013](../adr/0013-deploy-topology.md) calls this "AWS core, thin edge." At a handful of users, each managed extra adds a bill and no capability, so the ADR defers them, each with an upgrade path: Fargate (managed containers), a load balancer (worth it at a second box), ElastiCache (managed Redis, which would cost more than the box). A stored AWS key for CI, the spec's first draft, lost to OIDC: the same amount of Terraform, and nothing to leak.

The trade-off is written down: one box in one zone means a box failure is downtime until Terraform rebuilds it, and each deploy costs a few seconds of downtime. Hardening that cannot be added later was chosen at the first apply: an encrypted disk, CPU credits that throttle instead of billing, and ignoring newer Ubuntu images so one never replaces the box.

## The episode

**The replace that would have deleted the database (`30f9dba`).** The database's availability zone (the data center it lives in) was read from the box. Terraform works in two steps: a plan (a preview of every change) and an apply (making them). During a box replacement that value is unknown until apply, and RDS cannot move zones in place. So Terraform planned to replace the database too. With no final snapshot and the provider deleting automated backups by default, a routine box replace "would have deleted every user's data." The fix reads the zone from the subnet, known at plan time, and adds `prevent_destroy` (a setting that makes Terraform refuse any plan that deletes the database) and backups kept on delete. The README now says to check the database is absent from the plan.

**SSM's stdin (`da26bee`, `5a24f6a`, `d7d1356`, `a937ad4`, `feccba1`).** First, Caddyfile changes never applied, so a reload was added; then the reload read the old file, because a single-file bind mount (one file on the box shown inside a container) pins the file's inode (its identity on disk) and a rename left the container on the old one. The file is now written in place, and Caddy recreated once if its copy differs. Then rolls "succeeded" with nothing promoted. SSM feeds the script to the shell on stdin (a program's input stream), and `compose run` (start a one-off container) handed that stream to the migrate container, which swallowed the rest of the script. Six days later two `compose exec` calls (run a command in a running container) did the same: every roll ended before its cleanup, and old images filled the disk until a pull failed. Every attached command now reads from `/dev/null`, and a cleanup also runs before the pull.

**Migrate first (`bb79ef4`).** `up -d` recreated the API before the database migration it depends on, so a failing migration took every `/api/*` route down. The roll now runs the migration as a one-off gate while the old containers still serve.

**The import check (`0d9c1fe`).** An image whose code failed at import passed that gate and crash-looped live (crashed, restarted, crashed again). Now the roll imports the API and worker code from the new image before anything changes. The same commit fixed tags that grew past 7 characters.

**Pinned images and a vanished registry (`ff5eb83`, `f00e468`).** Caddy and Redis were pinned by digest (the exact image bytes), so they no longer float to a newer version. The same commit added a hook that stops coding agents from reading the secret env files. Separately, MinIO, a program that imitates S3 on a laptop, saw its images leave public registries, and a fresh clone could not start the dev stack. RustFS, another S3 imitation, replaced it after each storage call was checked against it.

## Look at

- [docs/adr/0013-deploy-topology.md](../adr/0013-deploy-topology.md): topology, alternatives, RustFS addendum
- [infra/compose/compose.prod.yml](../../infra/compose/compose.prod.yml): the services, Caddy as the only published port, pinned images
- [.github/workflows/ci.yml](../../.github/workflows/ci.yml): the checks, then the deploy job with OIDC
- [infra/terraform/README.md](../../infra/terraform/README.md): costs, the safe box replace
- [infra/deploy/deploy.sh](../../infra/deploy/deploy.sh): the roll and its comments
- [infra/deploy/README.md](../../infra/deploy/README.md): rollback, what the roll checks
- `30f9dba`: RDS zone from the subnet; `prevent_destroy`; keep backups on delete
- `da26bee`, `5a24f6a`, `d7d1356`: reload, write in place, recreate Caddy when its view differs
- `a937ad4`, `feccba1`: no attached command reads the roll script as stdin; prune before pulling
- `bb79ef4`: migrate before the roll touches the running containers
- `0d9c1fe`: the import check; 7-character tags
- `ff5eb83`: images pinned by digest; the env-file guard
- `f00e468`: RustFS replaces MinIO as the S3 stand-in
