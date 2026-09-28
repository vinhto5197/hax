#!/usr/bin/env bash
# Build, push and roll the box. Runs on a laptop or a CI runner; nothing here
# needs a shell on the box. Secrets never pass through: the box's
# /opt/hax/.env is written once by hand (README) and only read here.
#
#   infra/deploy/deploy.sh [build|push|roll|all] [sha]
#
# build  hax-python:latest and hax-web:latest from the Dockerfiles, for
#        linux/arm64 (the box is Graviton; an amd64 runner cross-builds).
#        Refuses a dirty tree: the image must be the commit it will be tagged
#        as (DEPLOY_ALLOW_DIRTY=1 overrides, for local experiments only).
# push   tag both as ghcr.io/<owner>/hax-{python,web}:<HEAD sha> and push.
#        Tags are immutable by convention: an existing tag is never
#        overwritten (DEPLOY_OVERWRITE=1 overrides, e.g. a CI re-run).
# roll   over SSM, the box fetches compose.prod.yml + Caddyfile at <sha> from
#        the public repo, pins the two image tags in /opt/hax/images.env, then
#        compose pull + up -d. So <sha> must be pushed: a deploy is always a
#        commit on GitHub, never a working tree.
# all    the three in order (default). build/push always use HEAD; a sha
#        argument is accepted by roll only (rollback), never by build or push,
#        so an image can never carry a sha other than the tree it was built from.
#
# Env: GHCR_OWNER (default: gh api user), GITHUB_REPO (default <owner>/hax),
# GHCR_TOKEN (CI: docker login with it; a laptop logs in once by hand),
# GH_TOKEN (CI: for the commit-exists check; a laptop's gh is logged in),
# HAX_INSTANCE_ID (default: terraform output), AWS_REGION (default us-east-1).
# CI (.github/workflows/ci.yml) sets all of these and runs `all`.
set -euo pipefail
cd "$(dirname "$0")/../.."
export AWS_PAGER=""

STEP=${1:-all}
HEAD_SHA=$(git rev-parse --short HEAD)
TAG=${2:-$HEAD_SHA}
OWNER=${GHCR_OWNER:-$(gh api user -q .login)}
REPO=${GITHUB_REPO:-$OWNER/hax}
REGION=${AWS_REGION:-us-east-1}
PY_IMAGE="ghcr.io/$OWNER/hax-python:$TAG"
WEB_IMAGE="ghcr.io/$OWNER/hax-web:$TAG"

# build and push describe HEAD's tree, so they refuse any other sha and any
# uncommitted change: what gets tagged <sha> must be exactly commit <sha>.
at_head_and_clean() {
  [[ $TAG == "$HEAD_SHA" ]] || { echo "$STEP builds HEAD ($HEAD_SHA); pass a sha to roll only"; exit 1; }
  if [[ -z "${DEPLOY_ALLOW_DIRTY:-}" && -n "$(git status --porcelain)" ]]; then
    echo "working tree is dirty: commit first (DEPLOY_ALLOW_DIRTY=1 to override)"; exit 1
  fi
}

build() {
  at_head_and_clean
  docker build --platform linux/arm64 -f infra/docker/python.Dockerfile -t hax-python:latest .
  # Empty NEXT_PUBLIC_API_URL: the browser calls /api on its own origin.
  docker build --platform linux/arm64 -f infra/docker/web.Dockerfile --build-arg NEXT_PUBLIC_API_URL= -t hax-web:latest .
}

push() {
  at_head_and_clean
  if [[ -n "${GHCR_TOKEN:-}" ]]; then
    echo "$GHCR_TOKEN" | docker login ghcr.io -u "$OWNER" --password-stdin
  fi
  local image
  for image in "$PY_IMAGE" "$WEB_IMAGE"; do
    if [[ -z "${DEPLOY_OVERWRITE:-}" ]] && docker manifest inspect "$image" > /dev/null 2>&1; then
      echo "$image already exists on GHCR; tags are immutable (DEPLOY_OVERWRITE=1 to override)"; exit 1
    fi
  done
  docker tag hax-python:latest "$PY_IMAGE" && docker push "$PY_IMAGE"
  docker tag hax-web:latest "$WEB_IMAGE" && docker push "$WEB_IMAGE"
}

roll() {
  local instance=${HAX_INSTANCE_ID:-$(terraform -chdir=infra/terraform output -raw instance_id)}
  local raw="https://raw.githubusercontent.com/$REPO/$TAG/infra/compose"
  local remote cmd_id status
  gh api "repos/$REPO/commits/$TAG" --silent 2>/dev/null \
    || { echo "$TAG is not on GitHub ($REPO): push first"; exit 1; }

  # Runs on the box as ubuntu (owner of /opt/hax, in the docker group).
  # --env-file twice: .env for SITE_ADDRESS, images.env for the image tags;
  # the services' env_file default is /opt/hax/.env already.
  remote=$(cat <<REMOTE
set -euo pipefail
cd /opt/hax
test -f .env || { echo "/opt/hax/.env missing: write it first (infra/deploy/README.md)"; exit 1; }
# One roll at a time: a CI run and a laptop rollback, or two queued runs,
# must not interleave their file writes and compose ups. Waits up to 10 min.
exec 9> .deploy.lock
flock -w 600 9 || { echo "another deploy holds /opt/hax/.deploy.lock"; exit 1; }
curl -fsSL "$raw/compose.prod.yml" -o compose.prod.yml.new && mv compose.prod.yml.new compose.prod.yml
curl -fsSL "$raw/Caddyfile" -o Caddyfile.new && mv Caddyfile.new Caddyfile
printf 'HAX_PYTHON_IMAGE=%s\nHAX_WEB_IMAGE=%s\n' '$PY_IMAGE' '$WEB_IMAGE' > images.env.new && mv images.env.new images.env
compose() { docker compose --env-file .env --env-file images.env -f compose.prod.yml "\$@"; }
compose pull --quiet
compose up -d --remove-orphans
compose ps
# Only the running images stay on the box; superseded sha tags are pullable
# from GHCR (a rollback re-pulls, about a minute) and would otherwise fill
# the root volume.
docker image prune -af > /dev/null
REMOTE
)
  cmd_id=$(aws ssm send-command --region "$REGION" --instance-ids "$instance" \
    --document-name AWS-RunShellScript --comment "hax deploy $TAG" \
    --parameters "commands=[\"echo $(printf %s "$remote" | base64 | tr -d '\n') | base64 -d | sudo -u ubuntu -H bash\"],executionTimeout=[\"900\"]" \
    --query Command.CommandId --output text)
  echo "ssm command $cmd_id on $instance"
  while :; do
    status=$(aws ssm get-command-invocation --region "$REGION" --command-id "$cmd_id" \
      --instance-id "$instance" --query Status --output text 2>/dev/null || echo Pending)
    case $status in
      Pending|InProgress|Delayed) sleep 5 ;;
      *) break ;;
    esac
  done
  aws ssm get-command-invocation --region "$REGION" --command-id "$cmd_id" --instance-id "$instance" \
    --query '[StandardOutputContent,StandardErrorContent]' --output text
  [[ $status == Success ]] || { echo "deploy failed: $status"; exit 1; }
}

case $STEP in
  build) build ;;
  push) push ;;
  roll) roll ;;
  all) build; push; roll ;;
  *) echo "usage: $0 [build|push|roll|all] [sha]"; exit 2 ;;
esac
