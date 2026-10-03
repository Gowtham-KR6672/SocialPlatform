#!/bin/bash
# Pull the latest code, refresh the secrets from AWS SSM Parameter Store and
# (re)start the containers. Run on the EC2 server as root:
#     bash /opt/socialplatform/deploy/aws/deploy.sh
# GitHub Actions runs this through AWS Systems Manager on every push to main.
set -euo pipefail

APP_DIR=/opt/socialplatform
ENV_PARAM=${SP_ENV_PARAM:-/socialplatform/app-env}
ENV_FILE=/etc/socialplatform/app.env

# region of this instance (IMDSv2)
TOKEN=$(curl -fsS -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
REGION=$(curl -fsS -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/placement/region)

cd "$APP_DIR"
git config --global --add safe.directory "$APP_DIR" >/dev/null 2>&1 || true
git fetch --quiet origin main
git reset --hard --quiet origin/main
echo "code: $(git log --oneline -1)"

# secrets: one SecureString parameter holding the whole KEY=VALUE env file
install -d -m 700 /etc/socialplatform
aws ssm get-parameter --region "$REGION" --name "$ENV_PARAM" --with-decryption \
    --query Parameter.Value --output text > "$ENV_FILE.new"
chmod 600 "$ENV_FILE.new"
mv "$ENV_FILE.new" "$ENV_FILE"

DOMAIN=$(grep -E '^DOMAIN=' "$ENV_FILE" | head -1 | cut -d= -f2-)
export DOMAIN

cd "$APP_DIR/deploy/aws"
docker compose up -d --build --remove-orphans
docker image prune -f >/dev/null

# wait for the app to answer (up to ~2 minutes)
for i in $(seq 1 24); do
  if docker compose exec -T app python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:5000/api/me',timeout=5)" >/dev/null 2>&1; then
    echo "app is up — https://$DOMAIN"
    exit 0
  fi
  sleep 5
done
echo "app did not answer in time — check: docker compose -f $APP_DIR/deploy/aws/docker-compose.yml logs app" >&2
exit 1
