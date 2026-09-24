# SocialPlatform

Plan, produce, approve and publish social media content to Instagram, Facebook,
YouTube, X, LinkedIn, Threads, TikTok and Pinterest from one dashboard, then track
comments, analytics and the inbox in one place.

## Run locally

```bash
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000. On Windows you can also double-click `start.bat`.

## Deploy on Render

This repo includes a `Dockerfile` and a `render.yaml` Blueprint.

1. In Render: **New + → Blueprint** → select this repository.
2. Fill in the environment variables it asks for (see `.env.example`):
   - `DATABASE_URL` (Supabase Postgres, transaction pooler, port 6543), required so data survives restarts
   - `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (+ a public bucket named `uploads`), required so uploaded media survives restarts and platforms can fetch it
   - `CLAUDE_API_KEY` (optional), for AI captions
   - Email alerts and weekly reports (optional): add `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
     `SMTP_PASS`, `SMTP_FROM` later, or enter them in the app under Setup → Alerts & reports
3. After the first deploy, open **Setup** and register each platform's redirect URI
   (shown there, based on your Render URL) in that platform's developer console.

## Connecting platforms

Each platform needs an App ID and Secret from its developer console. The **Guide**
button next to each platform in Setup lists the steps and the redirect URI to register.
