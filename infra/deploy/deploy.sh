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
#        compose pull + migrate + up -d + caddy reload. So <sha> must be pushed: a deploy is always a
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
  local remote cmd_id status sha deadline
  # Any commit-ish is accepted, but the images are tagged by the 7-char sha,
  # so resolve to that first; then prove both images exist before a single
  # byte changes on the box.
  sha=$(gh api "repos/$REPO/commits/$TAG" -q .sha 2>/dev/null) \
    || { echo "$TAG is not on GitHub ($REPO): push first"; exit 1; }
  TAG=${sha:0:7}
  PY_IMAGE="ghcr.io/$OWNER/hax-python:$TAG"
  WEB_IMAGE="ghcr.io/$OWNER/hax-web:$TAG"
  for image in "$PY_IMAGE" "$WEB_IMAGE"; do
    docker manifest inspect "$image" > /dev/null 2>&1 \
      || { echo "$image is not on GHCR: build + push first"; exit 1; }
  done
  local raw="https://raw.githubusercontent.com/$REPO/$TAG/infra/compose"

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
# Nothing the running stack reads changes until the pull and the migrate
# have succeeded: the three files land as .new/.next, the pull and the
# one-off migrate run from those, and only then are they promoted. A failure
# before that point leaves the box exactly as it was. (up -d recreates
# api/worker BEFORE compose runs the migrate they depend on, so a migrate
# that failed inside up -d would leave every /api/* route dead; the one-off
# gate runs while the old containers still serve. compose's own migrate
# dependency then re-runs upgrade, a no-op at head.)
curl -fsSL "$raw/compose.prod.yml" -o compose.prod.yml.new
curl -fsSL "$raw/Caddyfile" -o Caddyfile.new
printf 'HAX_PYTHON_IMAGE=%s\nHAX_WEB_IMAGE=%s\n' '$PY_IMAGE' '$WEB_IMAGE' > images.env.next
compose() { docker compose --env-file .env --env-file "\${IMAGES_ENV:-images.env}" -f "\${COMPOSE_FILE:-compose.prod.yml}" "\$@"; }
IMAGES_ENV=images.env.next COMPOSE_FILE=compose.prod.yml.new compose pull --quiet
# stdin from /dev/null: SSM feeds this script to the shell on stdin, and a
# `run` that attaches stdin would swallow the rest of the script as its
# input — the roll would end here, "successfully", with nothing promoted.
IMAGES_ENV=images.env.next COMPOSE_FILE=compose.prod.yml.new compose run --rm -T migrate < /dev/null
mv compose.prod.yml.new compose.prod.yml
# The Caddyfile is written IN PLACE, not renamed over: the caddy container
# bind-mounts this one file, which pins its inode, so a rename would leave
# the container reading the old file forever and the reload below would
# re-read it.
cat Caddyfile.new > Caddyfile && rm Caddyfile.new
mv images.env.next images.env
compose up -d --remove-orphans
# Caddy reads its file only at start, and up -d does not recreate a container
# whose bind-mounted config changed, so a Caddyfile change would otherwise
# never apply. A graceful reload picks up the file with no dropped connection
# — when the container still sees the host's file. If its view differs (the
# mount is pinned to an inode the host no longer has), recreate it once; the
# certificates live in a volume, so that costs a second, not a new issuance.
if compose exec -T caddy cat /etc/caddy/Caddyfile | cmp -s - Caddyfile; then
  compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
else
  echo "caddy's Caddyfile differs from the host's: recreating caddy"
  compose up -d --force-recreate caddy
fi
compose ps
# Only the running images stay on the box; superseded sha tags are pullable
# from GHCR (a rollback re-pulls, about a minute) and would otherwise fill
# the root volume.
docker image prune -af > /dev/null
REMOTE
)
  cmd_id=$(aws ssm send-command --region "$REGION" --instance-ids "$instance" \
    --document-name AWS-RunShellScript --comment "hax deploy $TAG" \
    --parameters "commands=[\"echo $(printf %s "$remote" | base64 | tr -d '\n') | base64 -d | sudo -u ubuntu -H bash\"],executionTimeout=[\"1200\"]" \
    --query Command.CommandId --output text)
  echo "ssm command $cmd_id on $instance"
  # The invocation record appears a few seconds after send-command; only
  # that absence is tolerated. Any other error (an expired session, a
  # revoked role, throttling) is shown and ends the wait, as does the
  # deadline, which sits above the command's own executionTimeout.
  deadline=$((SECONDS + 1500))
  while :; do
    if status=$(aws ssm get-command-invocation --region "$REGION" --command-id "$cmd_id" \
        --instance-id "$instance" --query Status --output text 2> /tmp/ssm-poll.err); then
      :
    elif grep -q InvocationDoesNotExist /tmp/ssm-poll.err && (( SECONDS < deadline )); then
      status=Pending
    else
      cat /tmp/ssm-poll.err; echo "deploy failed: could not read the command's status"; exit 1
    fi
    (( SECONDS < deadline )) || { echo "deploy failed: still $status after 25 min"; exit 1; }
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
