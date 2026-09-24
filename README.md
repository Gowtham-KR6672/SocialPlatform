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
   - `ENCRYPTION_KEY`, a Fernet key that encrypts OAuth tokens and secrets in the database
     (generate once, never change it)
   - AI (optional): choose the provider in **Setup → Credentials → AI provider** and paste its key there,
     or set one of `CLAUDE_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`.
     Gemini and Groq have free tiers; OpenRouter has free models (ids ending in `:free`).
   - Email alerts and weekly reports (optional): add `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
     `SMTP_PASS`, `SMTP_FROM` later, or enter them in the app under Setup → Alerts & reports
3. After the first deploy, open **Setup** and register each platform's redirect URI
   (shown there, based on your Render URL) in that platform's developer console.

## Connecting platforms

The SuperAdmin enters **one approved app per platform** (App ID and Secret) in Setup.
Every client connects through those apps, so a client only clicks **Connect** and signs in.
A client may optionally use their own app instead. The **Guide** button next to each
platform lists the steps and the redirect URI to register.

## Clients and security

- Each client account (with its Sub-Users) is a separate workspace: posts, connected accounts,
  inbox, messages, analytics, library, brand kit and links are visible only inside it.
  Only the SuperAdmin sees across clients (Team & Brands → Client accounts).
- Passwords are hashed with scrypt; logins are rate-limited; OAuth tokens, app secrets and
  2FA secrets are encrypted at rest.
- Two-factor login (authenticator app + recovery codes) is turned on in **My profile**.
- Forgot password emails a one-time link (needs SMTP and an email on the profile).
- Setup → **Client sign-up** closes public registration once clients are set up.
