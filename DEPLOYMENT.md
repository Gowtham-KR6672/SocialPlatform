# Deployment guide — client demo

Short version: **for a client demo, deploy with the Claude API provider on a
small cloud host (Render / Railway / Fly.io / a tiny VPS) behind HTTPS.**
Use Ollama only if you keep it on a machine that actually has the RAM/GPU for
`qwen3-vl:8b`, and expose that machine with a tunnel.

Why: the dashboard is a small Flask app, so it hosts anywhere. The only heavy
part is the **local AI (Ollama)** — an 8B vision model needs ~8–12 GB RAM and is
slow on a cheap VM. For a demo you want it snappy and reliable, so switch the
**Content Writing** provider (and, if you like, keep captions) to the **Claude
API**, which needs no local model — then the whole thing runs on a $5–10 host.

---

## Option A — Cloud host + Claude API  ✅ recommended for the demo

1. Push this folder to a Git repo.
2. On **Render** (or Railway/Fly.io): "New Web Service" → point at the repo.
   - It auto-detects the **Dockerfile** included here. (Or set the start command
     `gunicorn -w 1 --threads 8 -b 0.0.0.0:$PORT app:app`.)
3. Add a persistent disk/volume mounted at `/app/data` and `/app/uploads` so the
   SQLite DB and uploaded videos survive restarts.
4. Set env var `SECRET_KEY` to a random string.
5. Open the app → **Content Writing → AI settings** → provider **Claude API** →
   paste your Anthropic key. Done — share the HTTPS URL with the client.

This also fixes Instagram publishing: set that host's public URL as the
**Public base URL** in Instagram settings so IG can fetch the videos.

## Option B — Runs on your machine + a tunnel  (keep local Ollama)

Best if you want to demo the **local** `qwen3-vl:8b` model.

1. Run it locally: `start.bat` (Windows) / `./start.sh` (Mac/Linux).
2. Expose it with a tunnel so the client gets a public link:
   - **Cloudflare Tunnel**: `cloudflared tunnel --url http://localhost:5000`
   - or **ngrok**: `ngrok http 5000`
3. Share the printed HTTPS URL. Your PC does the AI; the client just opens a link.

## Option C — One VM you control (VPS)

`git clone` on an Ubuntu VM, then:
```
pip install -r requirements.txt gunicorn
gunicorn -w 1 --threads 8 -b 0.0.0.0:5000 app:app
```
Put **nginx** (or Caddy for automatic HTTPS) in front for TLS + a domain.
Add Ollama on the same VM only if it has ≥12 GB RAM.

---

## Quick comparison

| Need | Best choice |
|------|-------------|
| Fastest, cheapest, reliable demo | **A** — cloud + Claude API |
| Must show the local Ollama model | **B** — local + Cloudflare/ngrok tunnel |
| Full control / recurring client env | **C** — VPS + nginx/Caddy |

## Notes
- `data/app.db` holds all state; `uploads/` holds videos — persist both.
- Set `SECRET_KEY` in production (env var) — don't ship the default.
- The container image runs with **gunicorn** (already in the Dockerfile).
- Ollama is **not** in the container image on purpose; use Claude API there.
