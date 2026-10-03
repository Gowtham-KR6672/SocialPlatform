#!/bin/bash
# First-boot setup for the EC2 server (Amazon Linux 2023), passed as user data.
# Installs Docker + Compose, adds swap, clones the repo and runs deploy.sh.
# Safe to re-run. Log: /var/log/socialplatform-bootstrap.log
set -euo pipefail
exec > >(tee -a /var/log/socialplatform-bootstrap.log) 2>&1
echo "=== bootstrap $(date -u) ==="

REPO=${SP_REPO:-https://github.com/Gowtham-KR6672/SocialPlatform.git}
APP_DIR=/opt/socialplatform

dnf -y install docker git
systemctl enable --now docker

# Docker Compose v2 plugin
if ! docker compose version >/dev/null 2>&1; then
  mkdir -p /usr/local/lib/docker/cli-plugins
  curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m)" \
       -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi

# 2 GB swap so video conversion (ffmpeg) can't run a small server out of memory
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile swap swap defaults 0 0' >> /etc/fstab
fi

# automatic security updates for the OS
dnf -y install dnf-automatic || true
sed -i 's/^apply_updates.*/apply_updates = yes/' /etc/dnf/automatic.conf 2>/dev/null || true
systemctl enable --now dnf-automatic.timer 2>/dev/null || true

[ -d "$APP_DIR/.git" ] || git clone "$REPO" "$APP_DIR"
bash "$APP_DIR/deploy/aws/deploy.sh"
echo "=== bootstrap done $(date -u) ==="
