#!/bin/bash
# Runs once, as root, at first boot. Editing it does not re-run it on an
# existing box; Terraform applies the edit by stopping and starting the
# instance (downtime), so change it only when a rebuild is intended.
set -euxo pipefail
# First boot races unattended-upgrades for the dpkg lock; wait instead of dying.
APT="apt-get -o DPkg::Lock::Timeout=300"
$APT update
$APT install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=arm64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable" > /etc/apt/sources.list.d/docker.list
$APT update
# Cap container logs or they fill the root volume. Written BEFORE the package
# install: the postinst starts dockerd, which reads daemon.json only at start.
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'JSON'
{"log-driver": "json-file", "log-opts": {"max-size": "10m", "max-file": "3"}}
JSON
$APT install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
systemctl enable --now docker
usermod -aG docker ubuntu
mkdir -p /opt/hax && chown ubuntu:ubuntu /opt/hax && chmod 750 /opt/hax
