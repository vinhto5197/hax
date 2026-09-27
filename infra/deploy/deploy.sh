#!/usr/bin/env bash
# Build, push and roll the box. Runs on a laptop or a CI runner; nothing here
# needs a shell on the box. Secrets never pass through: the box's
# /opt/hax/.env is written once by hand (README) and only read here.
#
#   infra/deploy/deploy.sh [build|push|roll|all] [sha]
#
# build  hax-python:latest and hax-web:latest from the Dockerfiles (arm64: the
#        box is Graviton, so build on Apple Silicon or an arm64 runner).
# push   tag both as ghcr.io/<owner>/hax-{python,web}:<sha> and push.
# roll   over SSM, the box fetches compose.prod.yml + Caddyfile at <sha> from
#        the public repo, pins the two image tags in /opt/hax/images.env, then
#        compose pull + up -d. So <sha> must be pushed: a deploy is always a
#        commit on GitHub, never a working tree.
# all    the three in order (default). sha defaults to the short HEAD sha.
#
# Env: GHCR_OWNER (default: gh api user), GITHUB_REPO (default <owner>/hax),
# GHCR_TOKEN (CI: docker login with it; a laptop logs in once by hand),
# HAX_INSTANCE_ID (default: terraform output), AWS_REGION (default us-east-1).
set -euo pipefail
cd "$(dirname "$0")/../.."

STEP=${1:-all}
TAG=${2:-$(git rev-parse --short HEAD)}
OWNER=${GHCR_OWNER:-$(gh api user -q .login)}
REPO=${GITHUB_REPO:-$OWNER/hax}
REGION=${AWS_REGION:-us-east-1}
PY_IMAGE="ghcr.io/$OWNER/hax-python:$TAG"
WEB_IMAGE="ghcr.io/$OWNER/hax-web:$TAG"

build() {
  docker build -f infra/docker/python.Dockerfile -t hax-python:latest .
  # Empty NEXT_PUBLIC_API_URL: the browser calls /api on its own origin.
  docker build -f infra/docker/web.Dockerfile --build-arg NEXT_PUBLIC_API_URL= -t hax-web:latest .
}

push() {
  if [[ -n "${GHCR_TOKEN:-}" ]]; then
    echo "$GHCR_TOKEN" | docker login ghcr.io -u "$OWNER" --password-stdin
  fi
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
curl -fsSL "$raw/compose.prod.yml" -o compose.prod.yml
curl -fsSL "$raw/Caddyfile" -o Caddyfile
printf 'HAX_PYTHON_IMAGE=%s\nHAX_WEB_IMAGE=%s\n' '$PY_IMAGE' '$WEB_IMAGE' > images.env
compose() { docker compose --env-file .env --env-file images.env -f compose.prod.yml "\$@"; }
compose pull --quiet
compose up -d --remove-orphans
compose ps
docker image prune -f > /dev/null
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
