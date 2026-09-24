# Social Media Production Dashboard V28 — container image (for Render, etc.)
# Online build: Supabase Postgres (DATABASE_URL) + Supabase Storage + Claude API.
FROM python:3.12-slim

# ffmpeg is needed to extract a video frame for AI captions.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

# data/ and uploads/ are created at runtime. On a host with no persistent disk
# (Render free), set DATABASE_URL (Supabase Postgres) so data persists, and the
# Supabase Storage env vars so uploaded videos persist + are publicly fetchable.
ENV PORT=5000
EXPOSE 5000

# One worker + threads keeps the in-memory task/generation progress consistent.
CMD ["sh", "-c", "gunicorn -w 1 --threads 8 -b 0.0.0.0:${PORT} --timeout 300 app:app"]
