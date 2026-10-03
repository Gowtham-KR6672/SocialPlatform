# SocialPlatform on AWS

```
            your domain (DNS A record → Elastic IP)
                           │ HTTPS
            ┌──────────────▼───────────────┐
            │ EC2 (Amazon Linux 2023)       │      IAM role: S3 bucket access,
            │  caddy  :443 ──► app :5000    │      SSM (deploys + shell, no SSH)
            └───────┬───────────────┬───────┘
                    │ 5432 (private) │ HTTPS
            ┌───────▼──────┐  ┌──────▼───────┐
            │ RDS Postgres  │  │ S3 bucket     │  media, public-read objects so
            │ (no public IP)│  │ uploads/…     │  Instagram/Threads/TikTok can fetch
            └──────────────┘  └──────────────┘
```

Region: **us-east-1**. Everything is tagged `app=socialplatform`.

| Piece | What | Notes |
|---|---|---|
| EC2 | `t3.small`, 30 GB gp3, Elastic IP | Docker Compose: `app` + `caddy` (Let's Encrypt HTTPS) |
| RDS | PostgreSQL 16, `db.t4g.micro`, 20 GB gp3, encrypted, 7-day backups | Only the EC2 security group can connect |
| S3 | one bucket, `uploads/` objects public-read | The EC2 role writes; nobody else can |
| SSM Parameter Store | `/socialplatform/app-env` (SecureString) | The whole env file: `DATABASE_URL`, `SECRET_KEY`, `ENCRYPTION_KEY`, … |
| GitHub Actions | `.github/workflows/deploy-aws.yml` | On push to `main`: OIDC → role → SSM runs `deploy.sh` on the server |

Rough cost: ~$15 EC2 + ~$15 RDS + ~$4 public IP + a little S3 ≈ **$35/month** (less while in the AWS free tier).

## Day-to-day

* **Deploy:** push to `main` (GitHub Actions), or on the server: `sudo bash /opt/socialplatform/deploy/aws/deploy.sh`
* **Shell on the server:** AWS console → EC2 → instance → *Connect* → *Session Manager* (no SSH key, port 22 closed)
* **Logs:** `cd /opt/socialplatform/deploy/aws && sudo docker compose logs -f app`
* **Change a secret / setting:** edit the `/socialplatform/app-env` parameter in Systems Manager → Parameter Store, then deploy.
* **Database backups:** RDS keeps 7 days of automatic snapshots (point-in-time restore).

## After moving to a new domain

Every platform app must list the new address — Setup → each platform's *Add Details* popup shows the exact redirect URI:

* Meta (Instagram, Facebook, Threads): Valid OAuth Redirect URIs, privacy / terms / data-deletion URLs, app domains
* Google (YouTube): Authorized redirect URI + authorized domain
* X, LinkedIn, Pinterest: callback / redirect URL
* TikTok: redirect URI **and** URL-properties verification for the new domain (new verification file)
