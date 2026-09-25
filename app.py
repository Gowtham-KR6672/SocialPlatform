"""
Social Media Production Dashboard  —  Version 28
================================================
A web application for the VA social-media / video-editing workflow.

Runtime : Python 3.9+  /  Flask
Storage : SQLite (data/app.db) locally  — created automatically on first run.
          Supabase Postgres online — used automatically when DATABASE_URL is set
          (see get_db / init_db). File uploads go to Supabase Storage when
          SUPABASE_URL + SUPABASE_SERVICE_KEY + SUPABASE_BUCKET are set.
AI      : ollama qwen3-vl:8b locally (captions + hashtags + content), OR the
          Claude API online — captions analyse a video frame, content writing
          uses the Messages API. Graceful fallback when neither is reachable.

Roles   : superadmin > admin > user.
          Default seeded accounts (change the passwords after first login):
              SuperAdmin  ->  username: Superadmin   password: Super@123
              Admin       ->  username: Admin        password: Admin@123
          Regular users self-register from the login page.

Start it:
    pip install -r requirements.txt
    python app.py
Then open http://127.0.0.1:5000  in your browser.
"""

import os
import re
import json
import time
import shutil
import zipfile
import sqlite3
import hashlib
import secrets
import tempfile
import webbrowser
import subprocess
import threading
import platform
import urllib.request
import urllib.parse
import urllib.error
from io import BytesIO
from datetime import datetime, timedelta

from flask import (
    Flask, request, session, jsonify, send_from_directory,
    render_template, g, abort, send_file, redirect
)

import platforms as P          # V31: real API adapters for every social network

# --------------------------------------------------------------------------- #
#  Paths / config
# --------------------------------------------------------------------------- #
BASE_DIR   = os.path.abspath(os.path.dirname(__file__))
DATA_DIR   = os.path.join(BASE_DIR, "data")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
DB_PATH    = os.path.join(DATA_DIR, "app.db")
DOWNLOAD_DIR = os.path.join(DATA_DIR, "downloads")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

OLLAMA_URL   = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3-vl:8b")

# --------------------------------------------------------------------------- #
#  Deployment backends (V28)
#  Everything below is OFF by default so the app still runs locally on SQLite
#  with local file storage and Ollama exactly like V27. Set these env vars on
#  the cloud host (Render) to switch each subsystem to its online equivalent.
# --------------------------------------------------------------------------- #
# When DATABASE_URL is set (a Supabase Postgres connection string) the whole
# app uses Postgres instead of the local SQLite file — so data persists on a
# host with no permanent disk (Render's free tier). Leave unset to use SQLite.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_POSTGRES = bool(DATABASE_URL)

# Supabase Storage (public bucket) for uploaded videos, so they survive
# restarts AND get a public HTTPS URL that Instagram can fetch from directly.
SUPABASE_URL         = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
SUPABASE_BUCKET      = os.environ.get("SUPABASE_BUCKET", "uploads").strip()
USE_SUPABASE_STORAGE = bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)

# Claude API key (optional): when set, the online build defaults AI features to
# Claude. Locally you can keep using Ollama or paste a key in AI settings.
CLAUDE_API_KEY_ENV = os.environ.get("CLAUDE_API_KEY", "").strip()

app = Flask(__name__, template_folder="templates", static_folder="static")
# NEVER ship the default secret in production — set SECRET_KEY as an env var.
app.secret_key = os.environ.get("SECRET_KEY", "va-dashboard-v28-change-me")
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024  # 512 MB uploads


# --------------------------------------------------------------------------- #
#  Supabase Storage (V28) — optional public bucket for uploaded videos.
#  When enabled, every upload is mirrored to Supabase so it survives a host
#  with no persistent disk (Render free), AND gets a public HTTPS URL that
#  Instagram can fetch directly (no tunnel needed). Local disk is still used
#  as a fast cache + for FFmpeg frame extraction.
# --------------------------------------------------------------------------- #
def _supabase_public_url(fname):
    if not (USE_SUPABASE_STORAGE and fname):
        return ""
    return (f"{SUPABASE_URL}/storage/v1/object/public/"
            f"{SUPABASE_BUCKET}/{urllib.parse.quote(fname)}")


def _local_upload(fname):
    """Local path of an uploaded file, fetching it back from Supabase Storage when the
    ephemeral disk no longer has it. Returns "" when it can't be found."""
    if not fname:
        return ""
    local = os.path.join(UPLOAD_DIR, os.path.basename(fname))
    if os.path.exists(local):
        return local
    url = _supabase_public_url(os.path.basename(fname))
    if not url:
        return ""
    try:
        with urllib.request.urlopen(url, timeout=120) as r, open(local, "wb") as fh:
            shutil.copyfileobj(r, fh)
        return local
    except Exception:
        try: os.remove(local)
        except Exception: pass
        return ""


def _guess_content_type(fname):
    ext = (fname.rsplit(".", 1)[-1] if "." in fname else "").lower()
    return {"mp4": "video/mp4", "mov": "video/quicktime", "webm": "video/webm",
            "m4v": "video/x-m4v", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "png": "image/png", "gif": "image/gif", "pdf": "application/pdf",
            "webp": "image/webp", "mkv": "video/x-matroska", "avi": "video/x-msvideo"
            }.get(ext, "application/octet-stream")


def _supabase_upload_bytes(fname, data, content_type=None):
    """Upload bytes to the Supabase Storage bucket; return the public URL or ''."""
    if not USE_SUPABASE_STORAGE:
        return ""
    url = (f"{SUPABASE_URL}/storage/v1/object/"
           f"{SUPABASE_BUCKET}/{urllib.parse.quote(fname)}")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "apikey": SUPABASE_SERVICE_KEY,
        "Content-Type": content_type or _guess_content_type(fname),
        "x-upsert": "true",
    })
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            if r.status in (200, 201):
                return _supabase_public_url(fname)
    except urllib.error.HTTPError as e:  # noqa
        try:
            body = e.read().decode("utf-8", "replace")[:500]
        except Exception:
            body = ""
        try: app.logger.warning(f"Supabase upload failed for {fname}: {e} :: {body}")
        except Exception: pass
    except Exception as e:  # noqa
        try: app.logger.warning(f"Supabase upload failed for {fname}: {e}")
        except Exception: pass
    return ""


def _supabase_upload_path(local_path, fname):
    if not USE_SUPABASE_STORAGE:
        return ""
    try:
        with open(local_path, "rb") as fh:
            return _supabase_upload_bytes(fname, fh.read())
    except Exception:
        return ""


def _supabase_delete(fname):
    """Delete an object from the Supabase Storage bucket (best-effort)."""
    if not (USE_SUPABASE_STORAGE and fname):
        return
    url = (f"{SUPABASE_URL}/storage/v1/object/"
           f"{SUPABASE_BUCKET}/{urllib.parse.quote(fname)}")
    req = urllib.request.Request(url, method="DELETE", headers={
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "apikey": SUPABASE_SERVICE_KEY})
    try:
        with urllib.request.urlopen(req, timeout=30):
            pass
    except Exception as e:  # noqa
        try: app.logger.warning(f"Supabase delete failed for {fname}: {e}")
        except Exception: pass


# --------------------------------------------------------------------------- #
#  Recommended tools  (shown in the Setup window, installed before login)
#  Download URLs point at the official vendor installers.
# --------------------------------------------------------------------------- #
RECOMMENDED_TOOLS = [
    {
        "id": "python",
        "name": "Python 3",
        "desc": "Runtime that powers this dashboard and its helper scripts.",
        "category": "Required · Runtime",
        "win_url": "https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe",
        "mac_url": "https://www.python.org/ftp/python/3.12.4/python-3.12.4-macos11.pkg",
        "detect": "python",
    },
    {
        "id": "ffmpeg",
        "name": "FFmpeg",
        "desc": "Extracts a frame from each video so the AI model can analyse it.",
        "category": "Required · Video",
        # BtbN GitHub builds come off GitHub's CDN (fast). The old gyan.dev
        # mirror is frequently rate-limited, which is why downloads crawled.
        "win_url": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
        "mac_url": "https://evermeet.cx/ffmpeg/getrelease/zip",
        "detect": "ffmpeg",
    },
]


# --------------------------------------------------------------------------- #
#  Database helpers
#
#  V28: the app runs on SQLite locally (unchanged from V27) and on Supabase
#  Postgres online (when DATABASE_URL is set). To avoid rewriting ~150 raw
#  `db.execute("... ?", (...))` call sites, a thin compatibility layer makes a
#  psycopg (Postgres) connection behave like the sqlite3 connection the code
#  already expects:
#     • "?" placeholders are translated to "%s"
#     • SQLite-only "COLLATE NOCASE" is stripped (we use lower()=lower() instead)
#     • rows support BOTH row["col"] and row[0], and dict(row)
#     • INSERTs into id-tables get "RETURNING id" so cursor.lastrowid works
#  Everything commits per-statement (autocommit) which matches how the app uses
#  the DB (single write followed by commit()).
# --------------------------------------------------------------------------- #

# Tables whose primary key is a plain `id` column — INSERTs here can use
# RETURNING id so the existing `cursor.lastrowid` reads keep working on Postgres.
_ID_TABLES = {
    "users", "videos", "calendar_items", "notifications", "ig_comments",
    "content_items", "video_comments", "notification_replies",
    "conversations", "messages",
    # V31
    "social_accounts", "post_targets", "jobs", "activity_log", "brands",
    "queue_slots", "review_links", "stats_history", "inbox_comments",
    # V32
    "account_stats", "dm_messages", "brand_kits", "library_items", "bio_pages", "short_links", "link_clicks",
}
_INSERT_RE = re.compile(r"^\s*INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)


def _to_pg(sql):
    """Translate SQLite-flavoured SQL to Postgres-flavoured SQL."""
    sql = sql.replace("COLLATE NOCASE", "")
    # SQLite "INSERT OR IGNORE INTO ..." -> Postgres "INSERT INTO ... ON CONFLICT DO NOTHING".
    # (Postgres rejects "OR IGNORE"; this is why per-user notification hide/read failed online.)
    if re.search(r"INSERT\s+OR\s+IGNORE\s+INTO", sql, re.IGNORECASE):
        sql = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", sql, flags=re.IGNORECASE)
        sql = sql.rstrip().rstrip(";")
        if "ON CONFLICT" not in sql.upper():
            sql = sql + " ON CONFLICT DO NOTHING"
    # positional placeholders: ? -> %s  (leave %s untouched)
    sql = sql.replace("?", "%s")
    return sql


class _PGRow(dict):
    """A dict that also supports integer indexing (row[0]) and .keys() order."""
    def __init__(self, cols, values):
        super().__init__(zip(cols, values))
        self._cols = cols
    def __getitem__(self, key):
        if isinstance(key, int):
            return self.get(self._cols[key])
        return super().__getitem__(key)


class _PGCursor:
    def __init__(self, raw):
        self._raw = raw
        self.lastrowid = None

    @property
    def rowcount(self):
        try:
            return self._raw.rowcount
        except Exception:
            return -1
    def _wrap(self, rows):
        cols = [c.name for c in (self._raw.description or [])]
        return [_PGRow(cols, r) for r in rows]
    def fetchone(self):
        r = self._raw.fetchone()
        if r is None:
            return None
        cols = [c.name for c in (self._raw.description or [])]
        return _PGRow(cols, r)
    def fetchall(self):
        return self._wrap(self._raw.fetchall())
    def __iter__(self):
        return iter(self.fetchall())


class _PGConn:
    """psycopg connection wrapped to look like a sqlite3 connection."""
    def __init__(self, conn):
        self._conn = conn
        self.row_factory = None      # accepted + ignored (sqlite3 compatibility)
    def execute(self, sql, params=()):
        q = _to_pg(sql)
        m = _INSERT_RE.match(sql)
        want_id = bool(m) and (m.group(1).lower() in _ID_TABLES) and ("RETURNING" not in sql.upper())
        if want_id:
            q = q.rstrip().rstrip(";") + " RETURNING id"
        cur = self._conn.cursor()
        cur.execute(q, tuple(params) if params else None)
        wrapped = _PGCursor(cur)
        if want_id:
            try:
                row = cur.fetchone()
                wrapped.lastrowid = row[0] if row else None
            except Exception:
                wrapped.lastrowid = None
        return wrapped
    def executescript(self, script):
        # Postgres can run multiple statements in one execute()
        cur = self._conn.cursor()
        cur.execute(_to_pg(script))
        return _PGCursor(cur)
    def commit(self):
        try: self._conn.commit()
        except Exception: pass
    def close(self):
        try: self._conn.close()
        except Exception: pass


def db_connect():
    """Open a raw DB connection for the active backend (usable in any thread)."""
    if USE_POSTGRES:
        import psycopg
        # prepare_threshold=None disables server-side prepared statements, which
        # is REQUIRED when connecting through Supabase's transaction pooler
        # (pgBouncer transaction mode) — otherwise queries intermittently fail
        # with "prepared statement does not exist".
        conn = psycopg.connect(DATABASE_URL, autocommit=True, prepare_threshold=None)
        return _PGConn(conn)
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def get_db():
    if "db" not in g:
        # request-scoped connection; several requests can hit the DB at once
        # (the server is threaded — see __main__), so on SQLite we wait for a
        # lock instead of failing, and on Postgres each request gets its own
        # pooled connection.
        g.db = db_connect()
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# --------------------------------------------------------------------------- #
#  Passwords (V32): scrypt via Werkzeug (memory-hard, OWASP-recommended).
#  Old SHA-256 hashes still verify and are upgraded on the next login.
# --------------------------------------------------------------------------- #
from werkzeug.security import generate_password_hash, check_password_hash


def _legacy_hash(pw):
    return hashlib.sha256(("va$" + (pw or "")).encode("utf-8")).hexdigest()


def hash_pw(pw):
    return generate_password_hash(pw or "")


def verify_pw(stored, pw):
    if not stored:
        return False
    if stored.startswith(("scrypt:", "pbkdf2:")):
        try:
            return check_password_hash(stored, pw or "")
        except Exception:
            return False
    return secrets.compare_digest(stored, _legacy_hash(pw))


def pw_needs_upgrade(stored):
    return bool(stored) and not stored.startswith("scrypt:")


# --------------------------------------------------------------------------- #
#  Encryption at rest (V32) for OAuth tokens and secrets. Uses ENCRYPTION_KEY
#  (a Fernet key) when set, else a key derived from SECRET_KEY. Values are
#  stored as "enc1:<token>"; plaintext from older versions still reads fine
#  and is encrypted automatically at startup.
# --------------------------------------------------------------------------- #
ENC_PREFIX = "enc1:"
_FERNET = None


def _fernet():
    global _FERNET
    if _FERNET is None:
        import base64
        from cryptography.fernet import Fernet, MultiFernet
        derived = base64.urlsafe_b64encode(hashlib.sha256(("sp-enc:" + app.secret_key).encode()).digest())
        keys = []
        env_key = (os.environ.get("ENCRYPTION_KEY") or "").strip()
        if env_key:
            try:
                keys.append(Fernet(env_key.encode()))
            except Exception:
                pass
        keys.append(Fernet(derived))
        _FERNET = MultiFernet(keys)
    return _FERNET


def enc(v):
    if v is None or v == "" or (isinstance(v, str) and v.startswith(ENC_PREFIX)):
        return v
    return ENC_PREFIX + _fernet().encrypt(str(v).encode("utf-8")).decode()


def dec(v):
    if isinstance(v, str) and v.startswith(ENC_PREFIX):
        try:
            return _fernet().decrypt(v[len(ENC_PREFIX):].encode()).decode("utf-8")
        except Exception:
            return ""
    return v


_SECRET_SETTING_SUFFIXES = ("_secret", "_api_key", "smtp_pass", "ig_token", "_client_secret")


def _is_secret_setting(key):
    return any(key.endswith(x) for x in _SECRET_SETTING_SUFFIXES)


# --------------------------------------------------------------------------- #
#  Login rate limiting (V32) — in-memory sliding window (single web worker).
# --------------------------------------------------------------------------- #
_RATE = {}
_RATE_LOCK = threading.Lock()


def client_ip():
    fwd = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return fwd or (request.remote_addr or "?")


def rate_limited(key, limit, window, hit=True):
    """True if `key` already has >= limit events in the last `window` seconds."""
    now = time.time()
    with _RATE_LOCK:
        lst = [t for t in _RATE.get(key, []) if now - t < window]
        over = len(lst) >= limit
        if hit and not over:
            lst.append(now)
        _RATE[key] = lst
        if len(_RATE) > 20000:                     # keep memory bounded
            for k in list(_RATE)[:5000]:
                _RATE.pop(k, None)
    return over


def rate_clear(key):
    with _RATE_LOCK:
        _RATE.pop(key, None)


# --------------------------------------------------------------------------- #
#  Two-factor authentication (V32) — TOTP (RFC 6238), works with Google
#  Authenticator, Microsoft Authenticator, 1Password, Authy…
# --------------------------------------------------------------------------- #
def _totp_code(secret_b32, counter):
    import base64
    import hmac
    import struct
    key = base64.b32decode(secret_b32.upper() + "=" * (-len(secret_b32) % 8))
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return "%06d" % ((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 1000000)


def totp_verify(secret_b32, code, window=1):
    code = re.sub(r"\D", "", code or "")
    if not (secret_b32 and len(code) == 6):
        return False
    now = int(time.time() // 30)
    return any(secrets.compare_digest(_totp_code(secret_b32, now + w), code) for w in range(-window, window + 1))


def totp_new_secret():
    import base64
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def init_db():
    db = db_connect()
    if not USE_POSTGRES:
        # WAL lets readers and a writer work at the same time, so loading one
        # panel is never blocked by a background job writing in another. It's a
        # file-level setting, so every later connection inherits it. (Postgres
        # handles concurrency natively — no PRAGMA needed.)
        try:
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("PRAGMA busy_timeout = 15000")
        except Exception:
            pass
    schema = """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            display_name TEXT,
            email TEXT,
            phone TEXT,
            password_hash TEXT,
            role TEXT DEFAULT 'user',
            is_test INTEGER DEFAULT 0,
            google_connected INTEGER DEFAULT 0,
            instagram_connected INTEGER DEFAULT 0,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            filename TEXT,
            status TEXT DEFAULT 'new',          -- new | inprogress | completed
            owner TEXT,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS calendar_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,                  -- YYYY-MM-DD
            title TEXT,
            filename TEXT,
            caption TEXT,
            hashtags TEXT,
            state TEXT DEFAULT 'scheduled',      -- scheduled | approved | published
            approved INTEGER DEFAULT 0,
            owner TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT,
            kind TEXT,                           -- info | remove | upload | approval | publish | comment
            actor TEXT,
            link TEXT,                           -- optional target, e.g. "published:<id>"
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS ig_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER,
            ig_comment_id TEXT,
            commenter TEXT,
            text TEXT,
            like_count INTEGER DEFAULT 0,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS content_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            body TEXT,
            provider TEXT,
            owner TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS video_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER,
            author TEXT,
            author_id INTEGER,
            text TEXT,
            tagged_user_id INTEGER,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS notification_reads (
            notification_id INTEGER,
            user_id INTEGER,
            PRIMARY KEY (notification_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS notification_replies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notification_id INTEGER,
            author TEXT,
            author_id INTEGER,
            text TEXT,
            created_at TEXT
        );

        -- V20: Messenger-style chat (1:1, group, and video-linked conversations)
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            is_group INTEGER DEFAULT 0,
            video_id INTEGER,               -- set when this chat is a video's discussion
            created_by INTEGER,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS conversation_members (
            conversation_id INTEGER,
            user_id INTEGER,
            last_read_id INTEGER DEFAULT 0,
            PRIMARY KEY (conversation_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER,
            author_id INTEGER,
            author TEXT,
            text TEXT,
            files TEXT,                     -- JSON list of attachment urls
            created_at TEXT
        );

        -- V22: per-user "deleted from my list" notifications (doesn't affect others)
        CREATE TABLE IF NOT EXISTS notification_hidden (
            notification_id INTEGER,
            user_id INTEGER,
            PRIMARY KEY (notification_id, user_id)
        );
        -- V31: connected social accounts (one per user / brand / platform)
        CREATE TABLE IF NOT EXISTS social_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, brand_id INTEGER, platform TEXT,
            account_id TEXT, account_name TEXT,
            token TEXT, refresh_token TEXT, expires_at REAL,
            extra TEXT, mode TEXT, status TEXT, last_error TEXT,
            warned_at TEXT, created_at TEXT, updated_at TEXT
        );
        -- V31: one row per (calendar item, platform) — per-platform publish status
        CREATE TABLE IF NOT EXISTS post_targets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER, platform TEXT, status TEXT,
            remote_id TEXT, permalink TEXT, message TEXT, error TEXT,
            attempts INTEGER DEFAULT 0, simulated INTEGER DEFAULT 0,
            started_at TEXT, published_at TEXT,
            views INTEGER DEFAULT 0, likes INTEGER DEFAULT 0,
            comments INTEGER DEFAULT 0, shares INTEGER DEFAULT 0,
            stats_at TEXT, created_at TEXT
        );
        -- V31: durable background job queue (publishing with retries)
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT, payload TEXT, status TEXT,
            attempts INTEGER DEFAULT 0, max_attempts INTEGER DEFAULT 3,
            run_at TEXT, locked_at TEXT, last_error TEXT,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, username TEXT, action TEXT,
            target_type TEXT, target_id INTEGER, detail TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS brands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER, name TEXT, color TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS queue_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER, brand_id INTEGER, dow INTEGER, time TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS review_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER, token TEXT, created_by INTEGER, status TEXT,
            client_name TEXT, client_note TEXT, decided_at TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS stats_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_id INTEGER, captured_at TEXT,
            views INTEGER, likes INTEGER, comments INTEGER, shares INTEGER
        );
        CREATE TABLE IF NOT EXISTS inbox_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER, target_id INTEGER, platform TEXT,
            remote_comment_id TEXT, author TEXT, text TEXT,
            likes INTEGER DEFAULT 0, created_at TEXT, sentiment TEXT,
            status TEXT, reply_text TEXT, replied_at TEXT, replied_by TEXT,
            reply_error TEXT
        );
        -- V32: daily account-level stats (followers, reach, profile views)
        CREATE TABLE IF NOT EXISTS account_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER, user_id INTEGER, platform TEXT, day TEXT,
            followers INTEGER DEFAULT 0, reach INTEGER DEFAULT 0, impressions INTEGER DEFAULT 0,
            profile_views INTEGER DEFAULT 0, media_count INTEGER DEFAULT 0, captured_at TEXT
        );
        -- V32: Instagram / Facebook direct messages
        CREATE TABLE IF NOT EXISTS dm_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER, user_id INTEGER, platform TEXT, conversation_id TEXT,
            participant_id TEXT, participant_name TEXT, remote_id TEXT, from_id TEXT, from_name TEXT,
            text TEXT, created_at TEXT, direction TEXT, status TEXT, sent_by TEXT
        );
        CREATE TABLE IF NOT EXISTS brand_kits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER, brand_id INTEGER, logo TEXT, color_primary TEXT, color_secondary TEXT,
            tone TEXT, default_hashtags TEXT, banned_words TEXT, website TEXT, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS library_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER, brand_id INTEGER, kind TEXT, title TEXT, body TEXT, filename TEXT,
            created_by TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS bio_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER, brand_id INTEGER, slug TEXT, title TEXT, bio TEXT, avatar TEXT,
            theme TEXT, links TEXT, show_posts INTEGER DEFAULT 1, created_at TEXT, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS short_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER, code TEXT, url TEXT, label TEXT, item_id INTEGER, platform TEXT,
            utm_source TEXT, utm_medium TEXT, utm_campaign TEXT, utm_content TEXT,
            clicks INTEGER DEFAULT 0, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS link_clicks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            link_id INTEGER, workspace_id INTEGER, at TEXT, day TEXT, referrer TEXT
        );
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            number TEXT,
            amount REAL,
            seats INTEGER,
            price REAL,
            method TEXT,
            period_start TEXT,
            period_end TEXT,
            created_at TEXT
        );
        """
    if USE_POSTGRES:
        # SQLite's "INTEGER PRIMARY KEY AUTOINCREMENT" becomes Postgres SERIAL.
        schema = schema.replace("INTEGER PRIMARY KEY AUTOINCREMENT",
                                "SERIAL PRIMARY KEY")
    db.executescript(schema)
    db.commit()

    # migrations: add columns to existing tables (ignored if already present)
    _migrations = [
        ("users", "google_account", "TEXT"),
        ("users", "instagram_account", "TEXT"),
        ("notifications", "link", "TEXT"),
        ("calendar_items", "published_date", "TEXT"),
        ("calendar_items", "ig_media_id", "TEXT"),
        ("calendar_items", "ig_permalink", "TEXT"),
        ("calendar_items", "ig_like_count", "INTEGER DEFAULT 0"),
        # ---- V14: per-user connections, presence, Drive ------------------- #
        ("users", "last_seen", "TEXT"),
        ("users", "current_activity", "TEXT"),
        ("users", "avatar", "TEXT"),
        ("users", "google_email", "TEXT"),
        ("users", "google_token", "TEXT"),          # OAuth token JSON (isolated per user)
        ("users", "drive_folder_id", "TEXT"),
        ("users", "drive_folder_link", "TEXT"),
        ("users", "ig_username", "TEXT"),
        ("users", "ig_user_id", "TEXT"),
        ("users", "ig_token", "TEXT"),              # IG token (isolated per user)
        ("videos", "owner_id", "INTEGER"),
        ("videos", "drive_file_id", "TEXT"),
        ("videos", "drive_link", "TEXT"),
        ("videos", "download_link", "TEXT"),
        ("calendar_items", "owner_id", "INTEGER"),
        ("calendar_items", "drive_file_id", "TEXT"),
        ("calendar_items", "drive_link", "TEXT"),
        ("calendar_items", "content_type", "TEXT"),   # reel | post | story
        # ---- V16: per-user download permission (folder access) ------------ #
        ("users", "can_download", "INTEGER DEFAULT 0"),
        # ---- V17: per-user approval permission (admin-granted) ------------ #
        ("users", "can_approve", "INTEGER DEFAULT 0"),
        # ---- V18: video description --------------------------------------- #
        ("videos", "description", "TEXT"),
        # ---- V19: deadlines, completion tracking (Reports) ---------------- #
        ("videos", "deadline", "TEXT"),
        ("videos", "completed_at", "TEXT"),
        ("videos", "completed_by", "TEXT"),
        ("videos", "completed_by_id", "INTEGER"),
        ("video_comments", "files", "TEXT"),          # JSON list of attachment urls
        ("notification_replies", "files", "TEXT"),     # JSON list of chat attachment urls
        # ---- V20: video hashtags (full edit) ------------------------------ #
        ("videos", "hashtags", "TEXT"),
        # ---- V28.1: per-user tab-access override (JSON list; NULL=role default)
        ("users", "access_tabs", "TEXT"),
        # ---- V28.2: notification targeting. NULL/'all' = everyone (legacy);
        #      otherwise a comma-separated list of recipient user ids.
        ("notifications", "audience", "TEXT"),
        # ---- V28.3: live Instagram comment count on published items
        ("calendar_items", "ig_comments_count", "INTEGER DEFAULT 0"),
        # ---- V28.4: per-user permission to view/edit API + OAuth credentials
        ("users", "can_view_credentials", "INTEGER DEFAULT 0"),
        # ---- V29: Sub-Users (a primary User is the admin of its Sub-Users) ---
        ("users", "parent_id", "INTEGER"),               # NULL = primary account
        ("users", "allowed_videos", "TEXT"),             # sub-user: 'all' | JSON id list | NULL
        ("users", "can_edit", "INTEGER DEFAULT 1"),      # sub-user may edit/update/manage videos
        # ---- V29: per-User subscription (billing entity = primary user) ------
        ("users", "subscription_status", "TEXT"),        # active | expired | NULL(none)
        ("users", "subscription_expiry", "TEXT"),        # ISO date the plan is paid until
        ("users", "subscription_seats", "INTEGER DEFAULT 1"),
        # ---- V29: calendar scheduling (auto-publish at date / exact time) ----
        ("calendar_items", "publish_time", "TEXT"),       # 'HH:MM' (optional exact time)
        ("calendar_items", "auto_publish", "INTEGER DEFAULT 1"),
        ("calendar_items", "publish_state", "TEXT"),      # scheduled|publishing|published|failed
        ("calendar_items", "publish_pct", "INTEGER DEFAULT 0"),
        # ---- V30 (Social_Platform): first-time onboarding completion flag -----
        ("users", "onboarding_done", "INTEGER DEFAULT 0"),
        # ---- V30: per-user connections for the extra platforms (each user
        #      connects their OWN account). Instagram already exists above. ------
        ("users", "fb_connected", "INTEGER DEFAULT 0"),
        ("users", "fb_account", "TEXT"),
        ("users", "fb_user_id", "TEXT"),
        ("users", "fb_token", "TEXT"),
        ("users", "yt_connected", "INTEGER DEFAULT 0"),
        ("users", "yt_account", "TEXT"),
        ("users", "yt_channel_id", "TEXT"),
        ("users", "yt_token", "TEXT"),
        ("users", "tw_connected", "INTEGER DEFAULT 0"),
        ("users", "tw_account", "TEXT"),
        ("users", "tw_user_id", "TEXT"),
        ("users", "tw_token", "TEXT"),
        # ---- V30: recommended hashtags for written content ------------------
        ("content_items", "hashtags", "TEXT"),
        # ---- V31: multi-platform publishing -----------------------------------
        ("calendar_items", "platforms", "TEXT"),           # JSON list of target platforms
        ("calendar_items", "platform_captions", "TEXT"),   # JSON {platform: caption}
        ("calendar_items", "media", "TEXT"),               # JSON list of filenames (carousel)
        ("calendar_items", "media_kind", "TEXT"),          # video | image | carousel | text
        ("calendar_items", "thumbnail", "TEXT"),
        ("calendar_items", "variants", "TEXT"),            # JSON {platform: converted filename}
        ("calendar_items", "tz", "TEXT"),                  # IANA zone of the scheduler
        ("calendar_items", "publish_at", "TEXT"),          # UTC ISO instant to publish
        ("calendar_items", "recycle_days", "INTEGER"),     # evergreen: re-post after N days
        ("calendar_items", "recycled_from", "INTEGER"),
        ("calendar_items", "recycled_to", "INTEGER"),
        ("calendar_items", "brand_id", "INTEGER"),
        ("calendar_items", "yt_title", "TEXT"),
        ("calendar_items", "yt_privacy", "TEXT"),
        ("calendar_items", "queue_on_approve", "INTEGER DEFAULT 0"),
        ("calendar_items", "review_note", "TEXT"),
        ("users", "publish_platforms", "TEXT"),            # JSON list; NULL = all platforms
        ("users", "active_brand_id", "INTEGER"),
        ("inbox_comments", "parent_remote_id", "TEXT"),   # reply → id of the comment it answers
        # ---- V32: security ------------------------------------------------------
        ("users", "company_name", "TEXT"),             # workspace / client name (primary accounts)
        ("users", "disabled", "INTEGER DEFAULT 0"),    # 1 = workspace suspended by the SuperAdmin
        ("users", "totp_secret", "TEXT"),
        ("users", "totp_pending", "TEXT"),
        ("users", "totp_enabled", "INTEGER DEFAULT 0"),
        ("users", "recovery_codes", "TEXT"),
        ("users", "reset_token_hash", "TEXT"),
        ("users", "reset_token_exp", "REAL"),
        # ---- V32: imported posts, tracked links -----------------------------------
        ("calendar_items", "source", "TEXT"),             # NULL/dashboard | imported
        ("calendar_items", "external_thumb", "TEXT"),
        ("calendar_items", "external_url", "TEXT"),
        ("calendar_items", "link_url", "TEXT"),           # website link for UTM tracking
        ("calendar_items", "link_campaign", "TEXT"),
        ("calendar_items", "description", "TEXT"),        # longer text (YouTube, Facebook, LinkedIn, Pinterest)
        ("social_accounts", "imported_at", "TEXT"),
    ]
    for tbl, col, typ in _migrations:
        try:
            if USE_POSTGRES:
                db.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS {col} {typ}")
            else:
                db.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {typ}")
            db.commit()
        except Exception:
            pass  # already exists

    # ------------------------------------------------------------------ #
    # Seed the two permanent default accounts (V28).
    #
    #  Roles: superadmin > admin > user.
    #    SuperAdmin  ->  username: Superadmin   password: Super@123
    #    Admin       ->  username: Admin        password: Admin@123
    #
    #  Both are marked is_test=0 so "Delete test accounts" can NEVER remove
    #  them. Regular users self-register from the login page. Passwords can be
    #  changed after first login (SuperAdmin/Admin from their profile; users
    #  from their profile or via the login "Forgot password" flow).
    #
    #  Seeding is idempotent and matches usernames case-insensitively: if an
    #  account already exists we only make sure it is permanent and has the
    #  right role — we NEVER overwrite a password that has since been changed.
    #  Login itself is case-insensitive (see api_login).
    # ------------------------------------------------------------------ #
    now = datetime.utcnow().isoformat()

    def _seed_account(username, display, pw, role):
        row = db.execute(
            "SELECT id FROM users WHERE lower(username)=lower(?)", (username,)).fetchone()
        if row:
            db.execute(
                "UPDATE users SET username=?, role=?, is_test=0 WHERE id=?",
                (username, role, row[0]))
        else:
            db.execute(
                "INSERT INTO users "
                "(username, display_name, email, password_hash, role, is_test, "
                " created_at, google_connected, instagram_connected) "
                "VALUES (?,?,?,?,?,0,?,0,0)",   # start unconnected — users connect their own accounts
                (username, display, "", hash_pw(pw), role, now))

    # One-time cleanup of the old V27 default seeds so they don't linger.
    for legacy in ("testuser",):
        try:
            db.execute("DELETE FROM users WHERE lower(username)=lower(?) AND is_test=1",
                       (legacy,))
        except Exception:
            pass

    # Online, set SUPERADMIN_PASSWORD / ADMIN_PASSWORD (render.yaml generates them) so the
    # public defaults below never guard a live site. Only used when the account is first created.
    _seed_account("Superadmin", "Super Admin",
                  os.environ.get("SUPERADMIN_PASSWORD") or "Super@123", "superadmin")
    # V29: no separate Admin role — the second seed is a primary User (company).
    _seed_account("Admin",      "Administrator",
                  os.environ.get("ADMIN_PASSWORD") or "Admin@123", "user")

    # V31: demo (simulated) connections were removed — only real OAuth accounts remain
    try:
        db.execute("DELETE FROM social_accounts WHERE mode='demo' OR token IS NULL OR token=''")
    except Exception:
        pass
    db.commit()
    _encrypt_existing_secrets(db)
    _promote_superadmin_creds(db)
    _migrate_subuser_tabs(db)

    db.commit()
    db.close()


def _migrate_subuser_tabs(db):
    """V36: Sub-Users with a custom section list get the newer sections once, so nobody loses access."""
    try:
        if get_setting(db, "v36_tabs_migrated") == "1":
            return
        for r in db.execute("SELECT id, access_tabs FROM users WHERE access_tabs IS NOT NULL AND access_tabs<>''").fetchall():
            try:
                tabs = json.loads(r["access_tabs"])
            except Exception:
                continue
            if isinstance(tabs, list):
                tabs += [t for t in V35_NEW_TABS if t not in tabs]
                db.execute("UPDATE users SET access_tabs=? WHERE id=?", (json.dumps(tabs), r["id"]))
        set_setting(db, "v36_tabs_migrated", "1")
        db.commit()
    except Exception as e:  # noqa
        print("sub-user tab migration skipped:", e)


def _encrypt_existing_secrets(db):
    """One-time (idempotent) migration: encrypt tokens/secrets stored in plaintext."""
    try:
        for r in db.execute("SELECT id, token, refresh_token, extra FROM social_accounts").fetchall():
            vals = [enc(r["token"]), enc(r["refresh_token"]), enc(r["extra"])]
            if vals != [r["token"], r["refresh_token"], r["extra"]]:
                db.execute("UPDATE social_accounts SET token=?, refresh_token=?, extra=? WHERE id=?",
                           vals + [r["id"]])
        cols = ["ig_token", "fb_token", "yt_token", "tw_token", "google_token"]
        for r in db.execute(f"SELECT id, {', '.join(cols)} FROM users").fetchall():
            new = [enc(r[c]) for c in cols]
            if new != [r[c] for c in cols]:
                db.execute(f"UPDATE users SET {', '.join(c + '=?' for c in cols)} WHERE id=?", new + [r["id"]])
        for r in db.execute("SELECT key, value FROM settings").fetchall():
            if r["value"] and _is_secret_setting(r["key"]) and not str(r["value"]).startswith(ENC_PREFIX):
                db.execute("UPDATE settings SET value=? WHERE key=?", (enc(r["value"]), r["key"]))
        db.commit()
    except Exception as e:  # noqa
        try: print("secret encryption migration skipped:", e)
        except Exception: pass


# --------------------------------------------------------------------------- #
#  Settings helpers  (key/value store — e.g. Instagram Graph API credentials)
# --------------------------------------------------------------------------- #
def get_setting(db, key, default=""):
    # use positional access so this works on both Row and plain-tuple connections
    row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return dec(row[0]) if row else default


def set_setting(db, key, value):
    if value and _is_secret_setting(key):
        value = enc(value)                      # secrets are encrypted at rest
    db.execute("INSERT INTO settings (key, value) VALUES (?,?) "
               "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    db.commit()


# --- Per-USER settings ------------------------------------------------------ #
# Each user brings their OWN social-app credentials (App ID / App Secret per
# platform) and connects their OWN live account. These are stored under a
# user-scoped key so one user's credentials & connection never leak to another
# and are never shared with (or replicated from) the SuperAdmin's.
def uget_setting(db, uid, base, default=""):
    return get_setting(db, f"u{uid}_{base}", default)


def uset_setting(db, uid, base, value):
    set_setting(db, f"u{uid}_{base}", value)


def admin_ids(db):
    """User ids of the SuperAdmin(s). (Clients' own admins are reached through
    owner_and_admins, which adds the item's owner and workspace owner.)"""
    try:
        rows = db.execute(
            "SELECT id FROM users WHERE role='superadmin'").fetchall()
        return [r["id"] for r in rows]
    except Exception:
        return []


def recips(db, *ids):
    """Build a recipient id-set from any mix of ids / lists (None/0 dropped)."""
    out = set()
    for x in ids:
        if x is None:
            continue
        if isinstance(x, (list, tuple, set)):
            for y in x:
                if y:
                    out.add(int(y))
        elif x:
            out.add(int(x))
    return out


def owner_and_admins(db, owner_id):
    """Standard content audience: the item's owner, the owner's primary User
    (a Sub-User's admin), plus SuperAdmins/legacy admins."""
    ids = set(admin_ids(db))
    if owner_id:
        ids.add(owner_id)
        try:
            row = db.execute("SELECT parent_id FROM users WHERE id=?", (owner_id,)).fetchone()
            if row and row["parent_id"]:
                ids.add(row["parent_id"])
        except Exception:
            pass
    return recips(db, *ids)


def add_notification(db, message, kind="info", actor="system", link="", recipients=None):
    """Create a notification.

    recipients=None  → visible to everyone (legacy broadcast; use only for
                       genuinely global/system messages).
    recipients=iterable of user ids → visible ONLY to those users.
    An empty recipient set means nobody sees it, so the insert is skipped.
    """
    if recipients is None:
        audience = "all"
    else:
        ids = recips(db, recipients)
        if not ids:
            return                      # targeted at nobody → don't store
        audience = ",".join(str(i) for i in sorted(ids))
    db.execute(
        "INSERT INTO notifications (message, kind, actor, link, created_at, audience) "
        "VALUES (?,?,?,?,?,?)",
        (message, kind, actor, link, datetime.utcnow().isoformat(), audience),
    )
    db.commit()


# --------------------------------------------------------------------------- #
#  Roles (V29):  superadmin (internal) > user (company) > subuser
#  There is no separate "Admin" role — a primary User is the admin of the
#  Sub-Users it creates. Legacy 'admin' accounts are treated as primary Users.
# --------------------------------------------------------------------------- #
ROLE_LABELS = {"superadmin": "SuperAdmin", "admin": "Admin",        # a primary account = its client's admin
               "user": "Admin", "subuser": "Sub-User"}


def role_of(u):
    """The normalised role string for a user row/dict."""
    try:
        return (u.get("role") if hasattr(u, "get") else u["role"]) or "user"
    except Exception:
        return "user"


def role_label(role):
    """Pretty role label, e.g. 'superadmin' -> 'SuperAdmin'."""
    return ROLE_LABELS.get((role or "user").lower(), "User")


def name_with_role(u):
    """Display name combined with role, e.g. 'John (SuperAdmin)'."""
    if not u:
        return ""
    try:
        name = (u["display_name"] if u["display_name"] else u["username"])
    except Exception:
        name = (u.get("display_name") or u.get("username") or "")
    return f"{name} ({role_label(role_of(u))})"


def is_super(u):
    """True for SuperAdmin only (top-level user management)."""
    return role_of(u) == "superadmin"


def _parent_id(u):
    try:
        return (u.get("parent_id") if hasattr(u, "get") else u["parent_id"])
    except Exception:
        return None


def is_subuser(u):
    """A Sub-User created & managed by a primary User."""
    return role_of(u) == "subuser" or bool(_parent_id(u))


def is_primary_user(u):
    """A company/primary account (subscriber) — the admin of its own Sub-Users."""
    return (not is_super(u)) and (not is_subuser(u))


def is_admin(u):
    """Content/approval/publishing + workspace-management powers. Held by the
    SuperAdmin and by a primary User (over its own Sub-Users). NOT by Sub-Users.
    (Legacy 'admin' accounts fall through here as primary Users.)"""
    return is_super(u) or is_primary_user(u)


def billing_user_id(u):
    """The account that owns the subscription for this login: the primary User
    itself, or a Sub-User's parent User."""
    if not u:
        return None
    pid = _parent_id(u)
    return pid if (is_subuser(u) and pid) else u["id"]


# ---- Subscription (per primary User; Sub-Users inherit their parent's) ------ #
SUB_RENEWAL_WARN_DAYS = 5           # "renewal approaching" window
DEFAULT_SUB_PRICE = 1499.0          # ₹ per seat / month (SuperAdmin can change)


def subscription_price(db):
    try:
        v = get_setting(db, "subscription_price")
        return float(v) if v else DEFAULT_SUB_PRICE
    except Exception:
        return DEFAULT_SUB_PRICE


def _days_left(expiry):
    if not expiry:
        return None
    try:
        exp = datetime.fromisoformat(expiry)
    except Exception:
        try:
            exp = datetime.strptime(expiry[:10], "%Y-%m-%d")
        except Exception:
            return None
    return (exp.date() - datetime.utcnow().date()).days


def subscription_info(db, u):
    """Subscription state for the login's BILLING account (primary user)."""
    bid = billing_user_id(u)
    row = db.execute("SELECT subscription_status, subscription_expiry, subscription_seats "
                     "FROM users WHERE id=?", (bid,)).fetchone() if bid else None
    status = (row["subscription_status"] if row else None) or "none"
    expiry = (row["subscription_expiry"] if row else None) or ""
    seats = (row["subscription_seats"] if row and row["subscription_seats"] else 1)
    days = _days_left(expiry)
    # a plan with a future date is active regardless of a stale stored status
    active = bool(expiry) and (days is not None and days >= 0)
    if status == "none" and not expiry:
        active = False
    return {
        "status": "active" if active else ("expired" if expiry else "none"),
        "expiry": expiry,
        "days_left": days,
        "seats": seats,
        "active": active,
        "renewing_soon": bool(active and days is not None and days <= SUB_RENEWAL_WARN_DAYS),
        "price": subscription_price(db),
        "billing_user_id": bid,
    }


def subscription_active(u):
    """True when the login's billing account has a non-expired subscription.
    The SuperAdmin is never gated. If no plan was ever set up, we DON'T lock the
    account (so first-run / self-hosted installs keep working) — locking only
    kicks in once a subscription has been started and then lapses."""
    if is_super(u):
        return True
    try:
        db = get_db()
    except Exception:
        return True
    info = subscription_info(db, u)
    if info["status"] == "none":
        return True                 # never subscribed → not enforced yet
    return info["active"]


def can_view_creds(u):
    """The AI connection + settings (API key, model, redirect base) and the
    OAuth app credentials are SuperAdmin-ONLY. Regular users never see or edit
    them — they simply USE the AI features with the key the SuperAdmin has
    configured. This gate hides the credentials UI and blocks the write/test
    endpoints for anyone who is not the SuperAdmin."""
    return is_super(u)


def _content_guidelines_bg():
    """The SuperAdmin-configured content-writing guidelines (safe off-request)."""
    try:
        db = db_connect()
        g = get_setting(db, "content_guidelines") or ""
        db.close()
        return g
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
#  Tab access control (V28.1)
#  SuperAdmin decides which sidebar tabs Admins / Users can open. Model:
#    • per-role defaults (settings: access_role_admin / access_role_user)
#    • optional per-user override (users.access_tabs — JSON list, NULL=use role)
#  SuperAdmin always sees every tab (plus the SuperAdmin-only Access & Logins).
# --------------------------------------------------------------------------- #
CONTROLLABLE_TABS = [
    ("input", "Input"), ("calendar", "Calendar"), ("queue", "Queue"), ("published", "Published"),
    ("analytics", "Analytics"), ("inbox", "Inbox"), ("content", "Content Writing"),
    ("library", "Library"), ("bio", "Link in bio"), ("reports", "Reports"),
]
V35_NEW_TABS = ["queue", "analytics", "inbox", "library", "bio"]   # added to existing section lists once
ALL_TAB_KEYS = [k for k, _ in CONTROLLABLE_TABS]
SUPER_ONLY_TABS = ["access", "logins"]


def _role_default_tabs(db, role):
    raw = get_setting(db, "access_role_" + role)
    if raw:
        try:
            vals = json.loads(raw)
            return [k for k in ALL_TAB_KEYS if k in vals]
        except Exception:
            pass
    return list(ALL_TAB_KEYS)   # default: everything allowed (matches old behaviour)


def _user_override_tabs(u):
    try:
        raw = u.get("access_tabs") if hasattr(u, "get") else u["access_tabs"]
    except Exception:
        raw = None
    if not raw:
        return None
    try:
        vals = json.loads(raw)
        return [k for k in ALL_TAB_KEYS if k in vals]
    except Exception:
        return None


def resolved_allowed_tabs(u):
    """The tab keys the given user may open."""
    role = role_of(u)
    if role == "superadmin":
        return list(ALL_TAB_KEYS) + list(SUPER_ONLY_TABS)
    try:
        db = get_db()
    except Exception:
        return list(ALL_TAB_KEYS)
    override = _user_override_tabs(u)
    if override is not None:
        return override
    return _role_default_tabs(db, role if role in ("admin", "user") else "user")


# --------------------------------------------------------------------------- #
#  Auth helpers
# --------------------------------------------------------------------------- #
def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row or _is_suspended(db, row):
        return None
    return dict(row)


def _is_suspended(db, row):
    """True when the login's workspace was suspended by the SuperAdmin."""
    try:
        if row["role"] == "superadmin":
            return False
        if row["disabled"]:
            return True
        if row["parent_id"]:
            p = db.execute("SELECT disabled FROM users WHERE id=?", (row["parent_id"],)).fetchone()
            return bool(p and p["disabled"])
    except (KeyError, IndexError):
        return False
    return False


def require_login():
    u = current_user()
    if not u:
        abort(401)
    return u


def require_super():
    """Guard for SuperAdmin-only endpoints (user management)."""
    u = require_login()
    if not is_super(u):
        abort(403)
    return u


# --------------------------------------------------------------------------- #
#  Workspaces (V32) — each client (a primary User) plus its Sub-Users is one
#  workspace. Everything is scoped through the record's owner, so a client only
#  ever sees its own posts, videos, analytics and inbox. SuperAdmin sees all.
# --------------------------------------------------------------------------- #
def ws_owner_id(db, uid):
    """Workspace (primary account id) a user id belongs to."""
    if not uid:
        return None
    row = db.execute("SELECT id, parent_id FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        return None
    return row["parent_id"] or row["id"]


SOCIAL_MODES = ("central", "individual")


def ws_social_mode(db, ws_id):
    """How a workspace connects social accounts: "central" (only the Client Admin
    connects; every post publishes from the admin's accounts) or "individual"
    (each user connects their own; a post publishes from its owner's accounts)."""
    m = (uget_setting(db, ws_id, "social_mode") or "central") if ws_id else "central"
    return m if m in SOCIAL_MODES else "central"


def social_owner_id(db, uid):
    """Whose social accounts a user works with: the workspace admin's in central mode, else their own."""
    ws = ws_owner_id(db, uid)
    return ws if (ws and ws_social_mode(db, ws) == "central") else uid


def social_locked(db, u):
    """A Sub-User in a centrally managed workspace can't connect/disconnect accounts."""
    return bool(u) and is_subuser(u) and ws_social_mode(db, billing_user_id(u)) == "central"


LOCKED_MSG = "Social accounts in this workspace are managed by your admin."


def ws_member_ids(db, u):
    """User ids in the login's workspace, or None for the SuperAdmin (= all)."""
    if not u or is_super(u):
        return None
    ws = billing_user_id(u)
    ids = [ws] + [r["id"] for r in db.execute("SELECT id FROM users WHERE parent_id=?", (ws,)).fetchall()]
    return ids


def ws_sql(db, u, col="owner_id"):
    """(" AND <col> IN (...)", args) restricting a query to the login's workspace."""
    ids = ws_member_ids(db, u)
    if ids is None:
        return "", []
    return f" AND {col} IN ({','.join('?' * len(ids))})", ids


def in_ws(db, u, owner_id):
    ids = ws_member_ids(db, u)
    return ids is None or (owner_id in ids)


def ws_usernames(db, u):
    ids = ws_member_ids(db, u)
    if ids is None:
        return None
    q = ",".join("?" * len(ids))
    return [r["username"] for r in db.execute(f"SELECT username FROM users WHERE id IN ({q})", ids).fetchall()]


def _user_platform_map(u):
    """{platform: "live"|"demo"|""} for every supported network."""
    out = {k: "" for k in P.ORDER}
    try:
        for r in get_db().execute("SELECT platform FROM social_accounts WHERE user_id=? AND mode='live' "
                                  "AND token IS NOT NULL AND token<>''", (u["id"],)).fetchall():
            if r["platform"] in out:
                out[r["platform"]] = "live"
    except Exception:
        pass
    try:
        if not out["instagram"] and u["ig_token"]:
            out["instagram"] = "live"
    except (KeyError, IndexError):
        pass
    return out


def user_public(u):
    if not u:
        return None
    def _get(k):
        try: return u[k]
        except (KeyError, IndexError): return None
    role = role_of(u)
    return {
        "id": u["id"],
        "username": u["username"],
        "display_name": u["display_name"],
        "email": u["email"],
        "company_name": _get("company_name") or "",
        "phone": u["phone"],
        "role": role,
        "role_label": role_label(role),
        "name_with_role": name_with_role(u),
        "is_super": is_super(u),
        "is_admin": is_admin(u),
        "is_primary_user": is_primary_user(u),
        "is_subuser": is_subuser(u),
        "parent_id": _get("parent_id"),
        "can_edit": (False if is_subuser(u) and not bool(_get("can_edit")) else True),
        "allowed_tabs": resolved_allowed_tabs(u),
        "is_test": bool(u["is_test"]),
        "google_connected": bool(u["google_connected"]),
        "instagram_connected": bool(u["instagram_connected"]),
        "google_account": _get("google_account") or "",
        "instagram_account": _get("instagram_account") or "",
        # permissions (primary users & superadmins implicitly have everything)
        "can_download": bool(_get("can_download")) or is_admin(u),
        "can_approve": bool(_get("can_approve")) or is_admin(u),
        "can_view_creds": can_view_creds(u),
        # subscription snapshot for the billing account
        "subscription": (subscription_info(get_db(), u) if u else None),
        # first-time onboarding — the Welcome popup + wizard show only until done
        "onboarding_done": bool(_get("onboarding_done")),
        "totp_enabled": bool(_get("totp_enabled")),
        # per-user platform connection status (each user connects their OWN)
        "platforms": _user_platform_map(u),
        "active_brand_id": _get("active_brand_id"),
        "publish_platforms": _allowed_platforms(u),
        # user can enter the dashboard regardless of connections (connections are
        # now managed from the Setup panel at any time).
        "fully_connected": True,
    }


# --------------------------------------------------------------------------- #
#  Frontend shell
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/favicon.ico")
def favicon():
    return ("", 204)


@app.route("/uploads/<path:fn>")
def uploaded_file(fn):
    # Serve the local cache when present; otherwise (e.g. after a restart wiped
    # the ephemeral disk) redirect to the Supabase public URL.
    local = os.path.join(UPLOAD_DIR, fn)
    if os.path.exists(local):
        return send_from_directory(UPLOAD_DIR, fn)
    if USE_SUPABASE_STORAGE:
        return redirect(_supabase_public_url(fn))
    return send_from_directory(UPLOAD_DIR, fn)


# --------------------------------------------------------------------------- #
#  API : session / auth
# --------------------------------------------------------------------------- #
@app.route("/api/me")
def api_me():
    return jsonify({"user": user_public(current_user())})


# --- Subscription gate: when a plan has lapsed, the account becomes read-only.
#     Login + all viewing (GET) still work; create/edit/update/publish are
#     blocked until payment. The SuperAdmin and these whitelisted paths are
#     never gated (so the user can still log out and pay to re-enable).
_SUB_EXEMPT_PREFIXES = (
    "/api/login", "/api/logout", "/api/me", "/api/heartbeat", "/api/presence",
    "/api/subscription", "/api/notifications", "/api/calls", "/api/register",
    "/api/forgot", "/api/reset",
)


_WS_GUARDS = [
    ("/api/calendar/", "cid", "SELECT owner_id FROM calendar_items WHERE id=?"),
    ("/api/published/", "cid", "SELECT owner_id FROM calendar_items WHERE id=?"),
    ("/api/videos/", "vid", "SELECT owner_id FROM videos WHERE id=?"),
    ("/api/chat/video/", "vid", "SELECT owner_id FROM videos WHERE id=?"),
    ("/api/targets/", "tid", "SELECT c.owner_id FROM post_targets t JOIN calendar_items c ON c.id=t.item_id WHERE t.id=?"),
    ("/api/inbox/", "iid", "SELECT c.owner_id FROM inbox_comments i JOIN calendar_items c ON c.id=i.item_id WHERE i.id=?"),
]


@app.errorhandler(500)
def _server_error(e):
    """Record unexpected errors in data/errors.log (and the server log) and give the
    browser a readable reason instead of a bare 500 page."""
    import traceback
    orig = getattr(e, "original_exception", None) or e
    tb = "".join(traceback.format_exception(type(orig), orig, orig.__traceback__))
    try:
        with open(os.path.join(DATA_DIR, "errors.log"), "a", encoding="utf-8") as fh:
            fh.write(f"\n[{datetime.utcnow().isoformat()}Z] {request.method} {request.path}\n{tb}")
    except Exception:
        pass
    print(f"ERROR {request.method} {request.path}\n{tb}", flush=True)
    if request.path.startswith("/api/"):
        return jsonify({"error": f"Server error ({type(orig).__name__}: {str(orig)[:160]}). "
                                 "Details were saved to data/errors.log."}), 500
    return "Internal Server Error", 500


@app.before_request
def _enforce_workspace():
    """Stop one client from opening another client's item by guessing its id."""
    path = request.path or ""
    args = request.view_args or {}
    if not path.startswith("/api/") or not args:
        return
    u = current_user()
    if not u or is_super(u):
        return
    db = get_db()
    for prefix, key, sql in _WS_GUARDS:
        if path.startswith(prefix) and key in args:
            row = db.execute(sql, (args[key],)).fetchone()
            if row is not None and not in_ws(db, u, row[0]):
                return jsonify({"error": "Not found."}), 404
            return
    if path.startswith("/api/content/") and "cid" in args:
        row = db.execute("SELECT owner FROM content_items WHERE id=?", (args["cid"],)).fetchone()
        if row is not None and row[0] not in (ws_usernames(db, u) or []):
            return jsonify({"error": "Not found."}), 404
    if path.startswith("/api/notifications/") and "nid" in args:
        row = db.execute("SELECT audience FROM notifications WHERE id=?", (args["nid"],)).fetchone()
        if row is not None:
            aud = row[0] or "all"
            if aud != "all" and str(u["id"]) not in aud.split(","):
                return jsonify({"error": "Not found."}), 404


@app.before_request
def _enforce_subscription():
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    path = request.path or ""
    if not path.startswith("/api/"):
        return
    if any(path.startswith(p) for p in _SUB_EXEMPT_PREFIXES):
        return
    u = current_user()
    if not u or is_super(u):
        return
    if not subscription_active(u):
        return jsonify({
            "error": "Your subscription has expired. Viewing still works, but "
                     "creating, editing and publishing are disabled until you "
                     "renew in Subscription & Billing.",
            "subscription_required": True,
        }), 402


# --------------------------------------------------------------------------- #
#  Username / password validation (V21)
# --------------------------------------------------------------------------- #
def _validate_username(name):
    """Return an error string, or None if the username is acceptable."""
    if not name:
        return "Choose a username."
    if re.search(r"\s", name):
        return "Username can't contain spaces."
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{3,}", name):
        return ("Username must be at least 3 characters and use only letters, "
                "numbers, and . _ - (no spaces).")
    return None


def _validate_password(pw):
    """Password must be 6+ chars with at least one number and one special char."""
    if len(pw or "") < 6:
        return "Password must be at least 6 characters."
    if not re.search(r"\d", pw):
        return "Password must contain at least one number."
    if not re.search(r"[^A-Za-z0-9]", pw):
        return "Password must contain at least one special character (e.g. ! @ # $ %)."
    return None


@app.route("/api/register", methods=["POST"])
def api_register():
    if rate_limited("register:" + client_ip(), 10, 3600):
        return jsonify({"error": "Too many sign-ups from this network. Try again later."}), 429
    if (get_setting(get_db(), "allow_signup") or "1") == "0":
        return jsonify({"error": "Sign-up is closed. Ask the administrator for an account."}), 403
    d = request.get_json(force=True)
    username = (d.get("username") or "").strip()
    password = d.get("password") or ""
    email    = (d.get("email") or "").strip()   # optional
    phone    = (d.get("phone") or "").strip()   # optional
    uerr = _validate_username(username)
    if uerr:
        return jsonify({"error": uerr}), 400
    perr = _validate_password(password)
    if perr:
        return jsonify({"error": perr}), 400
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE lower(username)=lower(?)", (username,)).fetchone():
        return jsonify({"error": "That username is already taken — choose another."}), 409
    db.execute(
        "INSERT INTO users (username, display_name, email, phone, password_hash, role, created_at) "
        "VALUES (?,?,?,?,?, 'user', ?)",
        (username, username, email, phone, hash_pw(password),
         datetime.utcnow().isoformat()),
    )
    db.commit()
    row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    session["uid"] = row["id"]
    return jsonify({"user": user_public(dict(row))})


@app.route("/api/reset-password", methods=["POST"])
def api_reset_password():
    """Step 1 of "Forgot password": email a one-time reset link (30 minutes).
    The response never reveals whether the username exists."""
    if rate_limited("reset:" + client_ip(), 5, 3600):
        return jsonify({"error": "Too many reset requests. Try again in an hour."}), 429
    d = request.get_json(force=True) or {}
    username = (d.get("username") or "").strip()
    if not username:
        return jsonify({"error": "Enter your username."}), 400
    db = get_db()
    if not _smtp_cfg(db)["host"]:
        return jsonify({"error": "Password reset by email isn't set up on this server. "
                                 "Ask your administrator to reset your password."}), 400
    row = db.execute("SELECT * FROM users WHERE lower(username)=lower(?)", (username,)).fetchone()
    if row and (row["email"] or "").strip():
        token = secrets.token_urlsafe(32)
        db.execute("UPDATE users SET reset_token_hash=?, reset_token_exp=? WHERE id=?",
                   (hashlib.sha256(token.encode()).hexdigest(), time.time() + 1800, row["id"]))
        db.commit()
        link = f"{_redirect_base()}/?reset_token={token}"
        threading.Thread(target=_bg_email, args=(row["email"].strip(), "Reset your password",
                         f"Hi {row['display_name'] or row['username']},\n\nSomeone asked to reset your password. "
                         f"Open this link within 30 minutes to choose a new one:\n\n{link}\n\n"
                         f"If it wasn't you, ignore this email."), daemon=True).start()
    return jsonify({"ok": True, "message": "If that account has an email address on file, a reset link "
                                           "has been sent to it."})


@app.route("/api/reset-password/confirm", methods=["POST"])
def api_reset_password_confirm():
    """Step 2: set a new password with the emailed token."""
    if rate_limited("resetc:" + client_ip(), 10, 3600):
        return jsonify({"error": "Too many attempts. Try again later."}), 429
    d = request.get_json(force=True) or {}
    token = (d.get("token") or "").strip()
    newpw = d.get("password") or ""
    perr = _validate_password(newpw)
    if perr:
        return jsonify({"error": perr}), 400
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE reset_token_hash=?",
                     (hashlib.sha256(token.encode()).hexdigest(),)).fetchone() if token else None
    if not row or not row["reset_token_exp"] or float(row["reset_token_exp"]) < time.time():
        return jsonify({"error": "This reset link is invalid or has expired. Request a new one."}), 400
    db.execute("UPDATE users SET password_hash=?, reset_token_hash=NULL, reset_token_exp=NULL WHERE id=?",
               (hash_pw(newpw), row["id"]))
    db.commit()
    log_activity(db, dict(row), "password_reset", "user", row["id"], "via email link")
    return jsonify({"ok": True})


@app.route("/api/login", methods=["POST"])
def api_login():
    d = request.get_json(force=True)
    username = (d.get("username") or "").strip()
    password = d.get("password") or ""
    ip = client_ip()
    ukey, ikey = f"login:{ip}:{username.lower()}", f"loginip:{ip}"
    if rate_limited(ukey, 5, 900, hit=False) or rate_limited(ikey, 25, 900, hit=False):
        return jsonify({"error": "Too many failed attempts. Wait 15 minutes and try again."}), 429
    db = get_db()
    # Login is case-insensitive on the username (so "admin" == "Admin").
    row = db.execute("SELECT * FROM users WHERE lower(username)=lower(?)", (username,)).fetchone()
    if not row or not verify_pw(row["password_hash"], password):
        rate_limited(ukey, 5, 900)
        rate_limited(ikey, 25, 900)
        return jsonify({"error": "Invalid user ID or password. Sign in with your user ID (not your display name)."}), 401
    rate_clear(ukey)
    if _is_suspended(db, row):
        return jsonify({"error": "This workspace is suspended. Please contact your administrator."}), 403
    if pw_needs_upgrade(row["password_hash"]):          # upgrade old SHA-256 hashes
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_pw(password), row["id"]))
        db.commit()
    if row["totp_enabled"]:
        session.clear()
        session["pending_2fa"] = {"uid": row["id"], "at": time.time()}
        return jsonify({"need_2fa": True})
    session.clear()
    session["uid"] = row["id"]
    return jsonify({"user": user_public(dict(row))})


@app.route("/api/login/2fa", methods=["POST"])
def api_login_2fa():
    """Second login step: 6-digit authenticator code or a one-time recovery code."""
    pend = session.get("pending_2fa") or {}
    if not pend or time.time() - float(pend.get("at", 0)) > 300:
        session.pop("pending_2fa", None)
        return jsonify({"error": "Your login timed out. Enter your username and password again."}), 401
    key = f"2fa:{pend['uid']}"
    if rate_limited(key, 6, 900, hit=False):
        return jsonify({"error": "Too many wrong codes. Wait 15 minutes and log in again."}), 429
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (pend["uid"],)).fetchone()
    code = ((request.get_json(force=True) or {}).get("code") or "").strip()
    ok = bool(row) and totp_verify(dec(row["totp_secret"]), code)
    if row and not ok and code:
        codes = _jl(row["recovery_codes"], [])
        h = hashlib.sha256(code.replace("-", "").replace(" ", "").lower().encode()).hexdigest()
        if h in codes:
            codes.remove(h)
            db.execute("UPDATE users SET recovery_codes=? WHERE id=?", (json.dumps(codes), row["id"]))
            db.commit()
            ok = True
            log_activity(db, dict(row), "2fa_recovery_used", "user", row["id"], f"{len(codes)} codes left")
    if not ok:
        rate_limited(key, 6, 900)
        return jsonify({"error": "That code isn't right. Check your authenticator app and try again."}), 401
    rate_clear(key)
    session.clear()
    session["uid"] = row["id"]
    return jsonify({"user": user_public(dict(row))})


@app.route("/api/2fa/setup", methods=["POST"])
def api_2fa_setup():
    """Start enabling 2FA: a new secret + QR code for the authenticator app."""
    u = require_login()
    db = get_db()
    secret = totp_new_secret()
    db.execute("UPDATE users SET totp_pending=? WHERE id=?", (enc(secret), u["id"]))
    db.commit()
    issuer = urllib.parse.quote(os.environ.get("COMPANY_NAME") or "SocialPlatform")
    uri = (f"otpauth://totp/{issuer}:{urllib.parse.quote(u['username'])}?secret={secret}"
           f"&issuer={issuer}&digits=6&period=30")
    svg = ""
    try:
        import qrcode
        import qrcode.image.svg
        img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=8)
        svg = img.to_string(encoding="unicode")
    except Exception:
        svg = ""
    return jsonify({"secret": secret, "otpauth": uri, "qr_svg": svg})


@app.route("/api/2fa/enable", methods=["POST"])
def api_2fa_enable():
    u = require_login()
    db = get_db()
    code = ((request.get_json(force=True) or {}).get("code") or "").strip()
    pending = dec(u.get("totp_pending") or "")
    if not pending or not totp_verify(pending, code):
        return jsonify({"error": "That code doesn't match. Scan the QR code again and enter the current 6-digit code."}), 400
    plain = ["-".join([secrets.token_hex(2), secrets.token_hex(2)]) for _ in range(8)]
    hashed = [hashlib.sha256(c.replace("-", "").encode()).hexdigest() for c in plain]
    db.execute("UPDATE users SET totp_secret=?, totp_pending=NULL, totp_enabled=1, recovery_codes=? WHERE id=?",
               (enc(pending), json.dumps(hashed), u["id"]))
    db.commit()
    log_activity(db, u, "2fa_enabled", "user", u["id"], "")
    return jsonify({"ok": True, "recovery_codes": plain})


@app.route("/api/2fa/disable", methods=["POST"])
def api_2fa_disable():
    u = require_login()
    db = get_db()
    d = request.get_json(force=True) or {}
    if not verify_pw(u["password_hash"], d.get("password") or ""):
        return jsonify({"error": "Your password is incorrect."}), 400
    if not totp_verify(dec(u.get("totp_secret") or ""), d.get("code") or ""):
        return jsonify({"error": "Enter the current 6-digit code from your authenticator app."}), 400
    db.execute("UPDATE users SET totp_secret=NULL, totp_pending=NULL, totp_enabled=0, recovery_codes=NULL "
               "WHERE id=?", (u["id"],))
    db.commit()
    log_activity(db, u, "2fa_disabled", "user", u["id"], "")
    return jsonify({"ok": True})


@app.route("/api/users/<int:uid>/2fa/reset", methods=["POST"])
def api_2fa_reset(uid):
    """SuperAdmin (any user) or a primary account (its Sub-Users) turns 2FA off
    for someone who lost their phone."""
    u = require_login()
    db = get_db()
    tgt = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not tgt or not (is_super(u) or (tgt["parent_id"] == u["id"] and is_primary_user(u))):
        return jsonify({"error": "Not allowed."}), 403
    db.execute("UPDATE users SET totp_secret=NULL, totp_pending=NULL, totp_enabled=0, recovery_codes=NULL "
               "WHERE id=?", (uid,))
    db.commit()
    log_activity(db, u, "2fa_reset", "user", uid, tgt["username"])
    return jsonify({"ok": True})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


# =========================================================================== #
#  Subscription & Billing (per primary User).  UI/UX + workflow — no live
#  payment gateway is wired: /pay records a mock payment, generates an invoice
#  and extends the period. Razorpay / Google Pay are presented as choices.
# =========================================================================== #
def _next_invoice_number(db):
    n = db.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] + 1
    return f"INV-{datetime.utcnow().strftime('%Y%m')}-{n:04d}"


@app.route("/api/subscription")
def api_subscription():
    u = require_login()
    db = get_db()
    info = subscription_info(db, u)
    info["can_manage_price"] = is_super(u)
    info["can_pay"] = is_primary_user(u)      # sub-users can't pay; their parent does
    info["payout_account"] = get_setting(db, "payout_account") if is_super(u) else ""
    info["payout_configured"] = bool(get_setting(db, "payout_account"))
    return jsonify(info)


@app.route("/api/subscription/price", methods=["POST"])
def api_subscription_price():
    """SuperAdmin sets the per-seat price (applies to all Users) and payout account."""
    require_super()
    db = get_db()
    d = request.get_json(force=True) or {}
    if "price" in d:
        try:
            set_setting(db, "subscription_price", str(max(0.0, float(d["price"]))))
        except Exception:
            return jsonify({"error": "Enter a valid price."}), 400
    if "payout_account" in d:
        set_setting(db, "payout_account", (d.get("payout_account") or "").strip())
    return jsonify({"ok": True, "price": subscription_price(db)})


@app.route("/api/subscription/pay", methods=["POST"])
def api_subscription_pay():
    """Mock payment: extends the billing account's plan by one month, records an
    invoice, and re-enables the account. (No real gateway call.)"""
    u = require_login()
    if not is_primary_user(u):
        return jsonify({"error": "Only the primary account can pay the subscription."}), 403
    db = get_db()
    d = request.get_json(force=True) or {}
    method = (d.get("method") or "razorpay").lower()
    if method not in ("razorpay", "gpay", "googlepay"):
        method = "razorpay"
    try:
        seats = max(1, int(d.get("seats") or 1))
    except Exception:
        seats = 1
    price = subscription_price(db)
    amount = round(price * seats * 1.18, 2)          # + 18% GST (display)
    bid = billing_user_id(u)
    # extend from the later of today / current expiry
    cur = db.execute("SELECT subscription_expiry FROM users WHERE id=?", (bid,)).fetchone()
    base = datetime.utcnow()
    if cur and cur["subscription_expiry"]:
        try:
            e = datetime.fromisoformat(cur["subscription_expiry"])
            if e > base:
                base = e
        except Exception:
            pass
    new_exp = base + timedelta(days=30)
    period_start = datetime.utcnow().date().isoformat()
    period_end = new_exp.date().isoformat()
    db.execute("UPDATE users SET subscription_status='active', subscription_expiry=?, "
               "subscription_seats=? WHERE id=?", (new_exp.isoformat(), seats, bid))
    number = _next_invoice_number(db)
    db.execute("INSERT INTO invoices (user_id, number, amount, seats, price, method, "
               "period_start, period_end, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
               (bid, number, amount, seats, price, method, period_start, period_end,
                datetime.utcnow().isoformat()))
    db.commit()
    add_notification(db, f"Payment received — subscription extended to {period_end}. "
                         f"Invoice {number}.", "subscription", u["username"],
                     recipients=[bid])
    return jsonify({"ok": True, "invoice_number": number, "amount": amount,
                    "period_end": period_end, "method": method,
                    "subscription": subscription_info(db, u)})


@app.route("/api/subscription/invoices")
def api_subscription_invoices():
    u = require_login()
    db = get_db()
    bid = billing_user_id(u)
    rows = db.execute("SELECT * FROM invoices WHERE user_id=? ORDER BY id DESC LIMIT 50",
                      (bid,)).fetchall()
    return jsonify({"invoices": [dict(r) for r in rows]})


# =========================================================================== #
#  Sub-Users — a primary User creates & manages Sub-Users and defines each
#  Sub-User's section access, edit rights, and which videos they may manage.
# =========================================================================== #
def _subuser_public(r):
    r = dict(r)
    tabs = None
    if r.get("access_tabs"):
        try: tabs = json.loads(r["access_tabs"])
        except Exception: tabs = None
    vids = r.get("allowed_videos")
    return {
        "id": r["id"], "username": r["username"],
        "display_name": r.get("display_name") or r["username"],
        "online": _is_online(r.get("last_seen")),
        "created_at": r.get("created_at") or "",
        "access_tabs": tabs,                       # None = all controllable tabs
        "can_edit": bool(r.get("can_edit")) if r.get("can_edit") is not None else True,
        "allowed_videos": (vids if vids else "all"),
        "can_approve": bool(r.get("can_approve")),
    }


@app.route("/api/subusers", methods=["GET", "POST"])
def api_subusers():
    u = require_login()
    if not is_primary_user(u):
        return jsonify({"error": "Only a primary User account can manage Sub-Users."}), 403
    db = get_db()
    if request.method == "POST":
        d = request.get_json(force=True) or {}
        username = (d.get("username") or "").strip()
        password = d.get("password") or ""
        display = (d.get("display_name") or username).strip()
        uerr = _validate_username(username)
        if uerr:
            return jsonify({"error": uerr}), 400
        perr = _validate_password(password)
        if perr:
            return jsonify({"error": perr}), 400
        if db.execute("SELECT 1 FROM users WHERE lower(username)=lower(?)", (username,)).fetchone():
            return jsonify({"error": "That username is already taken."}), 409
        tabs = d.get("access_tabs")
        tabs_json = json.dumps([t for t in (tabs or []) if t in ALL_TAB_KEYS]) if isinstance(tabs, list) else None
        can_edit = 1 if d.get("can_edit", True) else 0
        can_approve = 1 if d.get("can_approve") else 0
        allowed_videos = d.get("allowed_videos")
        av = "all" if (allowed_videos in (None, "all")) else json.dumps(allowed_videos)
        db.execute(
            "INSERT INTO users (username, display_name, password_hash, role, parent_id, "
            "access_tabs, can_edit, can_approve, allowed_videos, created_at) "
            "VALUES (?,?,?, 'subuser', ?,?,?,?,?,?)",
            (username, display, hash_pw(password), u["id"], tabs_json, can_edit, can_approve, av,
             datetime.utcnow().isoformat()))
        db.commit()
        add_notification(db, f'Sub-User "{username}" created.', "info", u["username"],
                         recipients=[u["id"]])
        row = db.execute("SELECT * FROM users WHERE lower(username)=lower(?)", (username,)).fetchone()
        return jsonify({"ok": True, "subuser": _subuser_public(row)})
    rows = db.execute("SELECT * FROM users WHERE parent_id=? ORDER BY username", (u["id"],)).fetchall()
    # videos available to scope (this workspace's videos)
    wq, wa = ws_sql(db, u)
    vids = db.execute("SELECT id, title FROM videos WHERE 1=1" + wq + " ORDER BY id DESC LIMIT 200", wa).fetchall()
    return jsonify({
        "subusers": [_subuser_public(r) for r in rows],
        "controllable_tabs": [{"key": k, "label": lbl} for k, lbl in CONTROLLABLE_TABS],
        "videos": [{"id": v["id"], "title": v["title"]} for v in vids],
    })


@app.route("/api/subusers/<int:sid>", methods=["PATCH", "DELETE"])
def api_subuser_edit(sid):
    u = require_login()
    if not is_primary_user(u):
        return jsonify({"error": "Only a primary User account can manage Sub-Users."}), 403
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE id=? AND parent_id=?", (sid, u["id"])).fetchone()
    if not target:
        return jsonify({"error": "Sub-User not found."}), 404
    if request.method == "DELETE":
        for tbl in ("calendar_items", "videos"):
            db.execute(f"UPDATE {tbl} SET owner_id=?, owner=? WHERE owner_id=?", (u["id"], u["username"], sid))
        db.execute("UPDATE content_items SET owner=? WHERE owner=?", (u["username"], target["username"]))
        db.execute("DELETE FROM social_accounts WHERE user_id=?", (sid,))
        db.execute("DELETE FROM users WHERE id=?", (sid,))
        db.commit()
        return jsonify({"ok": True})
    d = request.get_json(force=True) or {}
    if "access_tabs" in d:
        tabs = d.get("access_tabs")
        tabs_json = json.dumps([t for t in (tabs or []) if t in ALL_TAB_KEYS]) if isinstance(tabs, list) else None
        db.execute("UPDATE users SET access_tabs=? WHERE id=?", (tabs_json, sid))
    if "can_edit" in d:
        db.execute("UPDATE users SET can_edit=? WHERE id=?", (1 if d.get("can_edit") else 0, sid))
    if "can_approve" in d:
        db.execute("UPDATE users SET can_approve=? WHERE id=?", (1 if d.get("can_approve") else 0, sid))
    if "allowed_videos" in d:
        av = "all" if (d.get("allowed_videos") in (None, "all")) else json.dumps(d.get("allowed_videos"))
        db.execute("UPDATE users SET allowed_videos=? WHERE id=?", (av, sid))
    if d.get("password"):
        perr = _validate_password(d["password"])
        if perr:
            return jsonify({"error": perr}), 400
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_pw(d["password"]), sid))
    if "display_name" in d and (d.get("display_name") or "").strip():
        db.execute("UPDATE users SET display_name=? WHERE id=?", (d["display_name"].strip(), sid))
    db.commit()
    row = db.execute("SELECT * FROM users WHERE id=?", (sid,)).fetchone()
    return jsonify({"ok": True, "subuser": _subuser_public(row)})


# =========================================================================== #
#  V36 : client workspaces. The SuperAdmin creates a workspace per client with
#  its Client Admin login; the Client Admin manages users and decides how the
#  workspace's social accounts are connected (central vs individual).
# =========================================================================== #
@app.route("/api/workspace/settings", methods=["GET", "POST"])
def api_workspace_settings():
    u = require_login()
    db = get_db()
    ws = billing_user_id(u)
    if request.method == "POST":
        if not is_primary_user(u):
            return jsonify({"error": "Only the workspace admin can change this."}), 403
        d = request.get_json(force=True) or {}
        if d.get("social_mode") in SOCIAL_MODES:
            uset_setting(db, ws, "social_mode", d["social_mode"])
            log_activity(db, u, "social_mode", "workspace", ws, d["social_mode"])
        if "company_name" in d:
            db.execute("UPDATE users SET company_name=? WHERE id=?", ((d.get("company_name") or "").strip()[:120], ws))
            db.commit()
    row = db.execute("SELECT company_name, username FROM users WHERE id=?", (ws,)).fetchone()
    return jsonify({"social_mode": ws_social_mode(db, ws), "is_ws_admin": is_primary_user(u),
                    "company_name": (row["company_name"] if row else "") or "",
                    "admin_username": row["username"] if row else ""})


def _workspace_public(db, r):
    r = dict(r)
    members = [x["id"] for x in db.execute("SELECT id FROM users WHERE parent_id=?", (r["id"],)).fetchall()]
    ids = [r["id"]] + members
    ph = ",".join("?" * len(ids))
    accts = db.execute(f"SELECT platform FROM social_accounts WHERE mode='live' AND user_id IN ({ph})", ids).fetchall()
    posts = db.execute(f"SELECT COUNT(*) FROM calendar_items WHERE owner_id IN ({ph})", ids).fetchone()[0]
    seen = [x["last_seen"] for x in db.execute(f"SELECT last_seen FROM users WHERE id IN ({ph})", ids).fetchall() if x["last_seen"]]
    return {"id": r["id"], "company_name": r.get("company_name") or r["username"], "admin_username": r["username"],
            "admin_name": r.get("display_name") or r["username"], "email": r.get("email") or "",
            "created_at": r.get("created_at") or "", "last_active": max(seen) if seen else "",
            "disabled": bool(r.get("disabled")), "users": len(members), "platforms": sorted({a["platform"] for a in accts}),
            "accounts": len(accts), "posts": posts, "social_mode": ws_social_mode(db, r["id"]),
            "totp_enabled": bool(r.get("totp_enabled"))}


@app.route("/api/workspaces", methods=["GET", "POST"])
def api_workspaces():
    u = require_super()
    db = get_db()
    if request.method == "POST":
        d = request.get_json(force=True) or {}
        company = (d.get("company_name") or "").strip()
        username = (d.get("username") or "").strip()
        password = d.get("password") or ""
        email = (d.get("email") or "").strip()
        mode = d.get("social_mode") if d.get("social_mode") in SOCIAL_MODES else "central"
        if not company:
            return jsonify({"error": "Enter the client / company name."}), 400
        uerr = _validate_username(username)
        if uerr:
            return jsonify({"error": uerr}), 400
        perr = _validate_password(password)
        if perr:
            return jsonify({"error": perr}), 400
        if db.execute("SELECT 1 FROM users WHERE lower(username)=lower(?)", (username,)).fetchone():
            return jsonify({"error": "That username is already taken — choose another."}), 409
        db.execute("INSERT INTO users (username, display_name, email, password_hash, role, company_name, created_at) "
                   "VALUES (?,?,?,?, 'user', ?,?)",
                   (username, (d.get("admin_name") or "").strip() or company, email, hash_pw(password), company[:120], _now()))
        db.commit()
        row = db.execute("SELECT * FROM users WHERE lower(username)=lower(?)", (username,)).fetchone()
        uset_setting(db, row["id"], "social_mode", mode)
        log_activity(db, u, "workspace_created", "workspace", row["id"], company)
        return jsonify({"ok": True, "workspace": _workspace_public(db, row)})
    rows = db.execute("SELECT * FROM users WHERE COALESCE(role,'user')<>'superadmin' AND parent_id IS NULL "
                      "ORDER BY lower(COALESCE(company_name, username))").fetchall()
    return jsonify({"workspaces": [_workspace_public(db, r) for r in rows]})


def _ws_row(db, wid):
    r = db.execute("SELECT * FROM users WHERE id=? AND parent_id IS NULL AND COALESCE(role,'user')<>'superadmin'",
                   (wid,)).fetchone()
    return r


@app.route("/api/workspaces/<int:wid>", methods=["PATCH", "DELETE"])
def api_workspace_edit(wid):
    u = require_super()
    db = get_db()
    r = _ws_row(db, wid)
    if not r:
        return jsonify({"error": "Workspace not found."}), 404
    if request.method == "DELETE":
        d = request.get_json(silent=True) or {}
        name = r["company_name"] or r["username"]
        if (d.get("confirm") or "").strip().lower() != name.strip().lower():
            return jsonify({"error": f'Type the workspace name "{name}" to confirm.'}), 400
        _delete_workspace(db, wid)
        log_activity(db, u, "workspace_deleted", "workspace", wid, name)
        return jsonify({"ok": True})
    d = request.get_json(force=True) or {}
    if "company_name" in d and (d.get("company_name") or "").strip():
        db.execute("UPDATE users SET company_name=? WHERE id=?", (d["company_name"].strip()[:120], wid))
    if "email" in d:
        db.execute("UPDATE users SET email=? WHERE id=?", ((d.get("email") or "").strip(), wid))
    if "admin_name" in d and (d.get("admin_name") or "").strip():
        db.execute("UPDATE users SET display_name=? WHERE id=?", (d["admin_name"].strip(), wid))
    if d.get("social_mode") in SOCIAL_MODES:
        uset_setting(db, wid, "social_mode", d["social_mode"])
    if "disabled" in d:
        db.execute("UPDATE users SET disabled=? WHERE id=?", (1 if d.get("disabled") else 0, wid))
        log_activity(db, u, "workspace_suspended" if d.get("disabled") else "workspace_activated",
                     "workspace", wid, r["company_name"] or r["username"])
    if d.get("password"):
        perr = _validate_password(d["password"])
        if perr:
            return jsonify({"error": perr}), 400
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_pw(d["password"]), wid))
    db.commit()
    return jsonify({"ok": True, "workspace": _workspace_public(db, _ws_row(db, wid))})


def _delete_workspace(db, wid):
    """Remove a client workspace: its logins, social connections and its posts, videos and files."""
    ids = [wid] + [x["id"] for x in db.execute("SELECT id FROM users WHERE parent_id=?", (wid,)).fetchall()]
    ph = ",".join("?" * len(ids))
    names = [x["username"] for x in db.execute(f"SELECT username FROM users WHERE id IN ({ph})", ids).fetchall()]
    items = [x["id"] for x in db.execute(f"SELECT id FROM calendar_items WHERE owner_id IN ({ph})", ids).fetchall()]
    vids = [x["id"] for x in db.execute(f"SELECT id FROM videos WHERE owner_id IN ({ph})", ids).fetchall()]
    accts = [x["id"] for x in db.execute(f"SELECT id FROM social_accounts WHERE user_id IN ({ph})", ids).fetchall()]
    files = []
    for x in db.execute(f"SELECT * FROM calendar_items WHERE owner_id IN ({ph})", ids).fetchall():
        files += _item_files(x) + ([x["thumbnail"]] if _rget(x, "thumbnail") else [])
    files += [x["filename"] for x in db.execute(f"SELECT filename FROM videos WHERE owner_id IN ({ph})", ids).fetchall()
              if x["filename"]]

    def run(sql, args):
        if not args:
            return
        try:
            db.execute(sql.replace("{ph}", ",".join("?" * len(args))), args)
        except Exception as e:  # noqa - a missing optional table must not stop the delete
            print("workspace delete:", e)

    for tbl in ("post_targets", "inbox_comments", "ig_comments", "review_links"):
        run(f"DELETE FROM {tbl} WHERE item_id IN ({{ph}})", items)
    run("DELETE FROM calendar_items WHERE id IN ({ph})", items)
    run("DELETE FROM video_comments WHERE video_id IN ({ph})", vids)
    run("DELETE FROM videos WHERE id IN ({ph})", vids)
    run("DELETE FROM account_stats WHERE account_id IN ({ph})", accts)
    run("DELETE FROM dm_messages WHERE account_id IN ({ph})", accts)
    run("DELETE FROM social_accounts WHERE id IN ({ph})", accts)
    run("DELETE FROM content_items WHERE owner IN ({ph})", names)
    for tbl in ("brand_kits", "library_items", "bio_pages", "short_links"):
        run(f"DELETE FROM {tbl} WHERE workspace_id IN ({{ph}})", [wid])
    run("DELETE FROM brands WHERE owner_id IN ({ph})", [wid])
    run("DELETE FROM queue_slots WHERE owner_id IN ({ph})", ids)
    for tbl in ("notification_reads", "notification_hidden", "conversation_members"):
        run(f"DELETE FROM {tbl} WHERE user_id IN ({{ph}})", ids)
    for i in ids:                         # per-user settings are stored as "u<id>_<name>"; "_" must be escaped
        run("DELETE FROM settings WHERE key LIKE ? ESCAPE '!'", [f"u{i}!_%"])
    run("DELETE FROM users WHERE id IN ({ph})", ids)
    db.commit()
    for f in set(files):                   # local cache copies; Storage copies are left for recovery
        try:
            if f and not _file_in_use(db, f, -1):
                p = os.path.join(UPLOAD_DIR, os.path.basename(f))
                if os.path.exists(p):
                    os.remove(p)
        except Exception:
            pass


# =========================================================================== #
#  First-time onboarding — the Welcome popup + setup wizard show once, then the
#  completion flag is persisted so they never appear again for that user.
# =========================================================================== #
@app.route("/api/onboarding", methods=["GET"])
def api_onboarding_status():
    u = require_login()
    return jsonify({"done": bool(u.get("onboarding_done"))})


@app.route("/api/onboarding/complete", methods=["POST"])
def api_onboarding_complete():
    u = require_login()
    db = get_db()
    db.execute("UPDATE users SET onboarding_done=1 WHERE id=?", (u["id"],))
    db.commit()
    return jsonify({"ok": True})


# =========================================================================== #
#  Setup panel — social platform connections. Each user connects their OWN
#  account. App-level credentials (App ID / App Secret per platform) are set
#  once by a credential-holder; per-user OAuth tokens live on the user row.
# =========================================================================== #
PLATFORMS = [
    {"key": "instagram", "label": "Instagram", "icon": "📸",
     "id_setting": "ig_app_id", "secret_setting": "ig_app_secret",
     "conn_col": "instagram_connected", "acct_col": "ig_username", "token_col": "ig_token"},
    {"key": "facebook",  "label": "Facebook",  "icon": "📘",
     "id_setting": "fb_app_id", "secret_setting": "fb_app_secret",
     "conn_col": "fb_connected", "acct_col": "fb_account", "token_col": "fb_token"},
    {"key": "youtube",   "label": "YouTube",   "icon": "▶️",
     "id_setting": "yt_client_id", "secret_setting": "yt_client_secret",
     "conn_col": "yt_connected", "acct_col": "yt_account", "token_col": "yt_token"},
    {"key": "twitter",   "label": "Twitter / X", "icon": "𝕏",
     "id_setting": "tw_api_key", "secret_setting": "tw_api_secret",
     "conn_col": "tw_connected", "acct_col": "tw_account", "token_col": "tw_token"},
]
_PLAT_BY_KEY = {p["key"]: p for p in PLATFORMS}


def _mask(v):
    """Never expose a full secret in the UI — show only that it is set."""
    if not v:
        return ""
    return "•" * 8


# --- Downloadable setup guides (DOCX / PDF) generated into static/guides/ ---
@app.route("/guides/<path:fn>")
def download_guide(fn):
    gdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "guides")
    if not os.path.exists(os.path.join(gdir, fn)):
        return jsonify({"error": "Guide not found."}), 404
    # Serve inline so the guide renders in the in-app viewer; ?dl=1 forces a
    # download of the PDF.
    as_att = request.args.get("dl") == "1"
    return send_from_directory(gdir, fn, as_attachment=as_att)


@app.route("/api/oauth/<provider>", methods=["POST"])
def api_oauth(provider):
    """
    Simulated Google / Instagram OAuth (real-ready).
    Marks the account connected (so the dashboard unlocks) and stores the
    account label the user provides. To go live: replace this handler with a
    real OAuth redirect flow and store the returned tokens on the profile.
    """
    if provider not in ("google", "instagram"):
        return jsonify({"error": "Unknown provider."}), 400
    if provider == "instagram":
        return jsonify({"error": "Connect Instagram from Setup using the real Instagram sign-in."}), 400
    u = require_login()
    db = get_db()
    d = request.get_json(silent=True) or {}
    # the account label the user is connecting (email for Google, @handle for IG)
    account = (d.get("account") or d.get("handle") or "").strip()
    if not account:
        account = "my.account@gmail.com" if provider == "google" else "@my.account"

    if not u:
        # First social login also creates / signs in a lightweight account.
        uname = re.sub(r"[^A-Za-z0-9_.@-]", "", account) or f"{provider}_user"
        row = db.execute("SELECT * FROM users WHERE username=?", (uname,)).fetchone()
        if not row:
            db.execute(
                "INSERT INTO users (username, display_name, email, role, created_at) "
                "VALUES (?,?,?, 'user', ?)",
                (uname, account, d.get("email") or "", datetime.utcnow().isoformat()),
            )
            db.commit()
            row = db.execute("SELECT * FROM users WHERE username=?", (uname,)).fetchone()
        session["uid"] = row["id"]
        u = dict(row)

    conn_col = "google_connected" if provider == "google" else "instagram_connected"
    acct_col = "google_account"   if provider == "google" else "instagram_account"
    db.execute(f"UPDATE users SET {conn_col}=1, {acct_col}=? WHERE id=?", (account, u["id"]))
    db.commit()
    return jsonify({"user": user_public(current_user())})


@app.route("/api/oauth/<provider>/disconnect", methods=["POST"])
def api_oauth_disconnect(provider):
    """Remove a connected Google / Instagram account (so the user can switch)."""
    if provider not in ("google", "instagram"):
        return jsonify({"error": "Unknown provider."}), 400
    u = require_login()
    db = get_db()
    conn_col = "google_connected" if provider == "google" else "instagram_connected"
    acct_col = "google_account"   if provider == "google" else "instagram_account"
    db.execute(f"UPDATE users SET {conn_col}=0, {acct_col}='' WHERE id=?", (u["id"],))
    db.commit()
    return jsonify({"user": user_public(current_user())})


SIGNIN_URLS = {
    "google": "https://accounts.google.com/signin",
    "instagram": "https://www.instagram.com/accounts/login/",
}


@app.route("/api/oauth/<provider>/open", methods=["POST"])
def api_oauth_open(provider):
    """Open the provider's real sign-in page in the PC's default browser."""
    require_super()
    url = SIGNIN_URLS.get(provider)
    if not url:
        return jsonify({"error": "Unknown provider."}), 400
    try:
        opened = webbrowser.open(url, new=2)
    except Exception:
        opened = False
    if not opened:
        _open_url(url)   # fallback via OS handler
    return jsonify({"ok": True, "url": url})


@app.route("/api/delete-test-accounts", methods=["POST"])
def api_delete_tests():
    require_super()
    db = get_db()
    # if you're logged in as a test account, log out first
    u = current_user()
    if u and u["is_test"]:
        session.clear()
    db.execute("DELETE FROM users WHERE is_test=1")
    db.commit()
    add_notification(db, "Test accounts were deleted. (The permanent admin is kept.)",
                     "info", "system", recipients=admin_ids(db))
    return jsonify({"ok": True})


# --------------------------------------------------------------------------- #
#  API : setup / tools
# --------------------------------------------------------------------------- #
def which(cmd):
    from shutil import which as _which
    return _which(cmd) is not None


def _ollama_exe():
    """
    Locate the Ollama executable even when it is installed but NOT on the PATH
    that this Flask process inherited (common on Windows — the installer adds
    Ollama to the *user* PATH, which a service/older shell may not have picked
    up yet). Checks PATH first, then the standard install locations.
    """
    from shutil import which as _which
    p = _which("ollama") or _which("ollama.exe")
    if p:
        return p
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Ollama", "ollama.exe"),
        os.path.join(os.environ.get("ProgramW6432", r"C:\Program Files"), "Ollama", "ollama.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Ollama", "ollama.exe"),
        os.path.join(home, "AppData", "Local", "Programs", "Ollama", "ollama.exe"),
        "/usr/local/bin/ollama",
        "/usr/bin/ollama",
        "/opt/homebrew/bin/ollama",
        os.path.join(home, ".ollama", "bin", "ollama"),
        "/Applications/Ollama.app/Contents/Resources/ollama",
    ]
    for c in candidates:
        try:
            if c and os.path.exists(c):
                return c
        except Exception:
            continue
    return ""


def _ollama_installed():
    """
    Ollama counts as installed if we can find its executable anywhere OR its
    local server is already answering. Either is enough — we must NOT try to
    re-download/re-install it when it is already present (that caused the
    "[Errno 13] Permission denied: OllamaSetup.exe" error).
    """
    return bool(_ollama_exe()) or _ollama_available()


def _stored_tool_path(tool_id):
    """Path recorded for a portable tool that we extracted from a ZIP."""
    try:
        db = db_connect()
        p = get_setting(db, f"{tool_id}_path")
        db.close()
        return p if (p and os.path.exists(p)) else ""
    except Exception:
        return ""


def _python_installed():
    """
    Python is detected robustly: this dashboard IS a Python program, so if it's
    running at all, Python is installed. We also accept python / python3 / the
    'py' launcher on PATH, or a Python in the standard install folders — this
    fixes 'not detected' when Python is installed but launched via the py
    launcher or a versioned path rather than a bare 'python' on PATH.
    """
    import sys
    if getattr(sys, "executable", "") and os.path.exists(sys.executable):
        return True
    from shutil import which as _which
    if _which("python") or _which("python3") or _which("py"):
        return True
    home = os.path.expanduser("~")
    globs = [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python"),
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        r"C:\\",
    ]
    for base in globs:
        try:
            if base and os.path.isdir(base):
                for name in os.listdir(base):
                    if name.lower().startswith("python") and \
                       os.path.exists(os.path.join(base, name, "python.exe")):
                        return True
        except Exception:
            continue
    return False


def tool_detected(tool):
    """A tool counts as installed if it's on PATH OR we registered it from a ZIP."""
    d = tool.get("detect")
    if not d:
        return None
    # The AI Model (Ollama) has its own robust detection — installed if the
    # executable exists anywhere OR the local server is already reachable.
    if tool.get("id") == "ollama":
        return _ollama_installed()
    # Python: the app runs on Python, so detect it robustly (py launcher, etc.)
    if tool.get("id") == "python":
        return _python_installed()
    return which(d) or bool(_stored_tool_path(tool["id"]))


@app.route("/api/tools")
def api_tools():
    require_login()
    is_win = platform.system() == "Windows"
    out = []
    for t in RECOMMENDED_TOOLS:
        installed = tool_detected(t)
        out.append({
            "id": t["id"],
            "name": t["name"],
            "desc": t["desc"],
            "category": t["category"],
            "url": t["win_url"] if is_win else t["mac_url"],
            "installed": installed,          # True / False / None(unknown)
            "post_note": t.get("post_note"),
        })
    return jsonify({"platform": platform.system(), "tools": out})


@app.route("/api/tools/summary")
def api_tools_summary():
    """% installed + which tools are connected (installed) vs not connected."""
    detectable = [t for t in RECOMMENDED_TOOLS if t.get("detect")]
    connected, missing = [], []
    for t in detectable:
        (connected if tool_detected(t) else missing).append(t["name"])
    total = len(detectable)
    pct = int(round(len(connected) * 100 / total)) if total else 0
    return jsonify({"percent": pct, "installed_count": len(connected),
                    "total": total, "connected": connected, "not_connected": missing})


# background download/install jobs  {tool_id: {status, percent, ...}}
INSTALL_JOBS = {}
INSTALL_CANCEL = {}          # {tool_id: True}  -> abort an in-flight download

# background "make the AI Model ready" job (serve + pull + warm the model)
AIMODEL_JOB = {"status": "idle", "percent": 0, "message": ""}
AIMODEL_LOCK = threading.Lock()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _unique_download_path(url):
    """
    Build a *unique* destination path for a download so we never collide with a
    file that is still locked/open from a previous attempt (the cause of
    "[Errno 13] Permission denied"). If the downloads folder itself isn't
    writable, fall back to the OS temp directory.
    """
    base = url.split("/")[-1].split("?")[0] or "download.bin"
    root, ext = os.path.splitext(base)
    stamped = f"{root}_{secrets.token_hex(4)}{ext}"
    for folder in (DOWNLOAD_DIR, tempfile.gettempdir()):
        try:
            os.makedirs(folder, exist_ok=True)
            candidate = os.path.join(folder, stamped)
            # prove the location is writable before committing to it
            with open(candidate, "wb"):
                pass
            return candidate
        except (PermissionError, OSError):
            continue
    # last resort: a fresh temp file the OS guarantees we can write
    fd, path = tempfile.mkstemp(suffix=ext or ".bin", prefix=root + "_")
    os.close(fd)
    return path


def _download_and_run(tool):
    tid = tool["id"]
    is_win = platform.system() == "Windows"
    url = tool["win_url"] if is_win else tool["mac_url"]
    INSTALL_CANCEL[tid] = False
    try:
        # --- AI Model (Ollama) already installed? Do NOT re-download. -------- #
        # It's already on the machine — just make sure the model is pulled and
        # running in the background instead of trying to reinstall (which is
        # what caused the "Permission denied: OllamaSetup.exe" error).
        if tid == "ollama" and _ollama_installed():
            INSTALL_JOBS[tid] = {"status": "installing", "percent": 100,
                                 "message": "AI Model already installed — preparing the model…"}
            threading.Thread(target=_ensure_ai_model, daemon=True).start()
            st = AIMODEL_JOB.get("status")
            INSTALL_JOBS[tid] = {"status": "done", "percent": 100,
                                 "message": "Ready for use"}
            return

        if not url.lower().endswith((".exe", ".zip", ".dmg", ".msi", ".pkg")):
            INSTALL_JOBS[tid] = {"status": "manual", "percent": 100,
                                 "message": f"Opened the official download page for {tool['name']}."}
            _open_url(url)
            return

        INSTALL_JOBS[tid] = {"status": "downloading", "percent": 0, "downloaded_mb": 0,
                             "total_mb": 0, "speed": "", "message": "Connecting…"}
        fname = _unique_download_path(url)

        # Manual chunked download: big buffer for throughput, a real User-Agent
        # (some CDNs throttle the default urllib agent), live speed, and cancel.
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length", 0) or 0)
            total_mb = round(total / (1024 * 1024), 1) if total else 0
            done = 0
            t0 = time.time()
            chunk = 1024 * 512          # 512 KB per read
            with open(fname, "wb") as fh:
                while True:
                    if INSTALL_CANCEL.get(tid):
                        INSTALL_JOBS[tid] = {"status": "cancelled", "percent":
                            (int(done*100/total) if total else 0),
                            "message": "Download cancelled."}
                        fh.close()
                        try: os.remove(fname)
                        except OSError: pass
                        return
                    buf = resp.read(chunk)
                    if not buf:
                        break
                    fh.write(buf)
                    done += len(buf)
                    elapsed = max(time.time() - t0, 0.001)
                    mbps = (done / (1024 * 1024)) / elapsed
                    done_mb = round(done / (1024 * 1024), 1)
                    pct = int(min(100, done * 100 / total)) if total else 0
                    INSTALL_JOBS[tid] = {
                        "status": "downloading", "percent": pct,
                        "downloaded_mb": done_mb, "total_mb": total_mb,
                        "speed": f"{mbps:.1f} MB/s",
                        "message": (f"Downloading {pct}%  ·  {done_mb} / {total_mb} MB"
                                    f"  ·  {mbps:.1f} MB/s" if total_mb
                                    else f"Downloading {done_mb} MB  ·  {mbps:.1f} MB/s"),
                    }

        INSTALL_JOBS[tid] = {"status": "installing", "percent": 100,
                             "downloaded_mb": total_mb, "total_mb": total_mb,
                             "message": "Download complete — installing…"}

        if fname.lower().endswith(".zip"):
            # A ZIP is not an installer: extract it, install/register the
            # extracted files, then delete the ZIP.
            msg = _install_from_zip(tool, fname)
            INSTALL_JOBS[tid] = {"status": "done", "percent": 100,
                                 "downloaded_mb": total_mb, "total_mb": total_mb,
                                 "message": msg}
        else:
            # Real installer (.exe / .msi / .dmg / .pkg) — launch it.
            if is_win and fname.lower().endswith((".exe", ".msi")):
                os.startfile(fname)  # type: ignore  (Windows only)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", fname])
            else:
                _open_path(fname)
            INSTALL_JOBS[tid] = {"status": "done", "percent": 100,
                                 "downloaded_mb": total_mb, "total_mb": total_mb,
                                 "message": "Ready for use"}
    except Exception as e:  # noqa
        INSTALL_JOBS[tid] = {"status": "error", "percent": 0,
                             "message": f"Could not auto-install: {e}. "
                                        f"Use the manual download link instead."}


def _install_from_zip(tool, zip_path):
    """
    Extract a downloaded .zip, then:
      • if it contains a real installer (setup.exe / *.msi), launch it;
      • otherwise treat it as a portable tool — locate its main binary,
        add its folder to PATH (so it 'installs' for use) and register it.
    Finally delete the .zip. Returns a status message.
    """
    tid = tool["id"]
    detect = (tool.get("detect") or "").lower()
    extract_dir = os.path.join(DATA_DIR, "tools", tid)
    if os.path.isdir(extract_dir):
        shutil.rmtree(extract_dir, ignore_errors=True)
    os.makedirs(extract_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path) as z:
        z.extractall(extract_dir)

    inner_installer, bin_path = None, None
    exe_name = (detect + ".exe") if platform.system() == "Windows" else detect
    for root, _dirs, files in os.walk(extract_dir):
        for f in files:
            fl = f.lower()
            if fl.endswith((".exe", ".msi")) and ("setup" in fl or "install" in fl):
                inner_installer = os.path.join(root, f)
            if detect and (fl == exe_name or fl == detect):
                bin_path = os.path.join(root, f)

    # delete the zip now that it's extracted
    try:
        os.remove(zip_path)
    except OSError:
        pass

    if inner_installer:
        try:
            if platform.system() == "Windows":
                os.startfile(inner_installer)  # type: ignore
            else:
                _open_path(inner_installer)
        except Exception:
            pass
        return "Ready for use"

    # portable tool (e.g. FFmpeg): register the binary so it 'installs'
    if bin_path:
        bin_dir = os.path.dirname(bin_path)
        # make it usable for THIS running app immediately
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
        _db = db_connect()
        set_setting(_db, f"{tid}_path", bin_path)
        _db.close()
        # best-effort: add to the user's PATH for future terminals (Windows)
        if platform.system() == "Windows":
            try:
                cur = os.environ.get("PATH", "")
                subprocess.run(["setx", "PATH", (cur + ";" + bin_dir)[:1800]],
                               capture_output=True, timeout=15)
            except Exception:
                pass
        return "Ready for use"

    return "Ready for use"


def _open_url(url):
    try:
        if platform.system() == "Windows":
            os.startfile(url)  # type: ignore
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", url])
        else:
            subprocess.Popen(["xdg-open", url])
    except Exception:
        pass


def _open_path(p):
    try:
        if platform.system() == "Darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p])
    except Exception:
        pass


@app.route("/api/tools/<tool_id>/install", methods=["POST"])
def api_install(tool_id):
    require_super()                 # downloads & runs installers on the server machine
    tool = next((t for t in RECOMMENDED_TOOLS if t["id"] == tool_id), None)
    if not tool:
        return jsonify({"error": "Unknown tool."}), 404
    INSTALL_CANCEL[tool_id] = False
    INSTALL_JOBS[tool_id] = {"status": "starting", "percent": 0, "message": "Starting…"}
    # runs in a background thread — keeps going even if the Setup window is closed
    threading.Thread(target=_download_and_run, args=(tool,), daemon=True).start()
    return jsonify({"ok": True, "status": "starting"})


@app.route("/api/tools/<tool_id>/cancel", methods=["POST"])
def api_install_cancel(tool_id):
    require_super()
    INSTALL_CANCEL[tool_id] = True
    return jsonify({"ok": True})


@app.route("/api/tools/<tool_id>/status")
def api_install_status(tool_id):
    require_login()
    return jsonify(INSTALL_JOBS.get(tool_id, {"status": "idle", "percent": 0, "message": ""}))


@app.route("/api/tools/<tool_id>/detect")
def api_tool_detect(tool_id):
    """Re-run detection for a single tool now (the 'Check' button in Setup)."""
    require_login()
    tool = next((t for t in RECOMMENDED_TOOLS if t["id"] == tool_id), None)
    if not tool:
        return jsonify({"error": "Unknown tool."}), 404
    return jsonify({"id": tool_id, "installed": tool_detected(tool)})


# --------------------------------------------------------------------------- #
#  API : Input board (videos)  —  Trello-style Input / Processing / Completed
# --------------------------------------------------------------------------- #
STATUSES = ("input", "processing", "completed")
STATUS_LABEL = {"input": "Input", "processing": "Processing", "completed": "Completed"}


@app.route("/api/videos")
def api_videos():
    u = require_login()
    db = get_db()
    wq, wa = ws_sql(db, u)
    rows = db.execute("SELECT * FROM videos WHERE 1=1" + wq + " ORDER BY updated_at DESC", wa).fetchall()
    counts = {s: 0 for s in STATUSES}
    admin_like = is_admin(u)
    can_dl = _user_can_download(u)
    # per-video chat stats: total messages + unread for the current user
    chat = {}
    for c in db.execute(
            "SELECT c.video_id, c.id, "
            " (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) AS total, "
            " (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id AND m.author_id<>? AND m.id > "
            "   COALESCE((SELECT cm.last_read_id FROM conversation_members cm "
            "             WHERE cm.conversation_id=c.id AND cm.user_id=?), 0)) AS unread "
            "FROM conversations c WHERE c.video_id IS NOT NULL", (u["id"], u["id"])).fetchall():
        chat[c["video_id"]] = (c["total"], c["unread"])
    out = []
    for r in rows:
        if r["status"] in counts:
            counts[r["status"]] += 1
        d = dict(r)
        d["chat_count"], d["chat_unread"] = chat.get(r["id"], (0, 0))
        # everyone can SEE every video; downloading is gated per-user (admins,
        # the video's owner, and users granted access can download).
        d["can_download"] = bool(admin_like or can_dl or (r["owner_id"] and r["owner_id"] == u["id"]))
        out.append(d)
    return jsonify({"videos": out, "counts": counts,
                    "is_admin": admin_like, "can_download": can_dl})


def _user_can_download(u):
    if not u:
        return False
    if is_admin(u):
        return True
    try:
        return bool(u.get("can_download"))
    except Exception:
        return False


@app.route("/api/videos", methods=["POST"])
def api_add_video():
    u = require_login()
    db = get_db()
    title = None
    filename = None
    deadline = None
    if request.files.get("file"):
        f = request.files["file"]
        filename = _safe_save(f)
        title = request.form.get("title") or f.filename
        deadline = (request.form.get("deadline") or "").strip() or None
    else:
        d = request.get_json(force=True)
        title = (d.get("title") or "").strip()
        deadline = (d.get("deadline") or "").strip() or None
    if not title:
        return jsonify({"error": "A title is required."}), 400
    now = datetime.utcnow().isoformat()
    # a locally-viewable download link is always available
    download_link = f"/uploads/{filename}" if filename else ""
    # newly uploaded videos land in the Input column (tagged NEW on the client)
    cur = db.execute(
        "INSERT INTO videos (title, filename, status, owner, owner_id, "
        " download_link, deadline, created_at, updated_at) "
        "VALUES (?,?, 'input', ?, ?, ?, ?, ?, ?)",
        (title, filename, u["username"], u["id"], download_link, deadline, now, now),
    )
    db.commit()
    vid = cur.lastrowid
    # Broadcast to ALL users: new video available, with its name + a download link
    # (the link opens the video; the actual download is permission-gated).
    add_notification(db, f'📹 New video "{title}" is available — download link ready.',
                     "upload", u["username"], link=f"video:{vid}",
                     recipients=owner_and_admins(db, u["id"]))

    # If the uploader has Google Drive connected (live token), push the file into
    # THEIR project folder in the background — the upload keeps running even if
    # they navigate away, and shows in the Running Tasks bar.
    gu = _google_user_for(db, u)
    if filename and gu:
        _start_drive_upload_task(gu["id"], vid, os.path.join(UPLOAD_DIR, filename), title)

    return jsonify({"id": vid})


def _google_user_for(db, u):
    """Which Google account backs up an upload: the uploader's own if connected,
    else their workspace owner's. Never another client's Drive."""
    try:
        if u.get("google_token"):
            return u
    except Exception:
        pass
    ws = ws_owner_id(db, u.get("id"))
    if ws and ws != u.get("id"):
        row = db.execute("SELECT * FROM users WHERE id=?", (ws,)).fetchone()
        if row and row["google_token"]:
            return dict(row)
    return None


def _start_drive_upload_task(user_id, video_id, local_path, title, table="videos"):
    """Background: push a local file into the uploader's Google Drive project
    folder and record the Drive ids/links on the given table row (videos or
    calendar_items)."""
    tid = task_new("upload", f'Uploading "{title}" to Google Drive', str(user_id))

    def _run():
        try:
            task_update(tid, percent=15, message="Uploading to Google Drive…")
            db2 = db_connect(); db2.row_factory = sqlite3.Row
            urow = db2.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not urow:
                task_done(tid, ok=False, message="User not found."); return
            dfid, view, download = _drive_upload_file(dict(urow), local_path, os.path.basename(local_path))
            if dfid:
                if table == "calendar_items":
                    db2.execute("UPDATE calendar_items SET drive_file_id=?, drive_link=? WHERE id=?",
                                (dfid, view, video_id))
                else:
                    db2.execute("UPDATE videos SET drive_file_id=?, drive_link=?, download_link=? WHERE id=?",
                                (dfid, view, download, video_id))
                db2.commit()
                task_done(tid, ok=True, message="Uploaded to Google Drive.")
            else:
                task_done(tid, ok=False, message="Drive upload unavailable — kept local copy.")
            db2.close()
        except Exception as e:
            task_done(tid, ok=False, message=f"Upload error: {e}")

    threading.Thread(target=_run, daemon=True).start()


@app.route("/api/videos/<int:vid>/download")
def api_video_download(vid):
    """Permission-gated download. Admins, the owner, and granted users only."""
    u = require_login()
    db = get_db()
    row = db.execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()
    if not row:
        return jsonify({"error": "Not found."}), 404
    is_owner = row["owner_id"] and row["owner_id"] == u["id"]
    if not (_user_can_download(u) or is_owner):
        return jsonify({"error": "You don't have download access. Ask an admin to grant it."}), 403
    # prefer the Google Drive public download link when present
    drive_dl = row["download_link"] or ""
    if drive_dl.startswith("http"):
        return redirect(drive_dl)
    if row["filename"]:
        return send_from_directory(UPLOAD_DIR, row["filename"], as_attachment=True,
                                   download_name=row["filename"])
    return jsonify({"error": "No downloadable file for this video."}), 404


# ---- admin: manage per-user download access (folder access) --------------- #
@app.route("/api/download-access", methods=["GET", "POST"])
def api_download_access():
    u = require_login()
    if not is_admin(u):
        return jsonify({"error": "Only an admin can manage download access."}), 403
    db = get_db()
    if request.method == "POST":
        d = request.get_json(force=True)
        if "grants" in d and isinstance(d["grants"], list):
            # set the full allow-list: these ids can download, everyone else can't
            ids = [int(x) for x in d["grants"]]
            members = ws_member_ids(db, u)
            if members is not None:
                ids = [i for i in ids if i in members]
            if is_super(u):
                db.execute("UPDATE users SET can_download=0")
            else:                  # only this client's own people are touched
                db.execute(f"UPDATE users SET can_download=0 WHERE role != 'superadmin' AND id IN "
                           f"({','.join('?' * len(members))})", members)
            if ids:
                q = ",".join("?" * len(ids))
                db.execute(f"UPDATE users SET can_download=1 WHERE id IN ({q})", ids)
            db.commit()
        elif "user_id" in d:                      # toggle a single user
            tgt_row = db.execute("SELECT role FROM users WHERE id=?", (int(d["user_id"]),)).fetchone()
            if tgt_row and (tgt_row["role"] == "superadmin") and not is_super(u):
                return jsonify({"error": "You can't change the Super Admin's access."}), 403
            if not in_ws(db, u, int(d["user_id"])):
                return jsonify({"error": "User not found."}), 404
            allow = 1 if d.get("allow") else 0
            db.execute("UPDATE users SET can_download=? WHERE id=?", (allow, int(d["user_id"])))
            db.commit()
            tgt = db.execute("SELECT username FROM users WHERE id=?", (int(d["user_id"]),)).fetchone()
            if tgt:
                add_notification(db, f'{u["username"]} {"granted" if allow else "revoked"} '
                                     f'download access {"to" if allow else "from"} {tgt["username"]}.',
                                 "info", u["username"],
                                 recipients=owner_and_admins(db, int(d["user_id"])))
        return jsonify({"ok": True})
    # GET: list all users with their current access flag
    wq, wa = ws_sql(db, u, "id")
    rows = db.execute("SELECT id, username, display_name, role, can_download "
                      "FROM users WHERE 1=1" + wq + " ORDER BY username", wa).fetchall()
    users = [{"id": r["id"], "username": r["username"],
              "display_name": r["display_name"] or r["username"],
              "role": r["role"] or "user",
              "can_download": bool(r["can_download"]) or (r["role"] in ("admin", "superadmin"))}
             for r in rows]
    return jsonify({"users": users})


def _user_can_approve(u):
    if not u:
        return False
    if is_admin(u):
        return True
    try:
        return bool(u.get("can_approve"))
    except Exception:
        return False


# ---- admin: manage per-user APPROVAL access ------------------------------- #
@app.route("/api/approval-access", methods=["GET", "POST"])
def api_approval_access():
    u = require_login()
    if not is_admin(u):
        return jsonify({"error": "Only an admin can manage approval access."}), 403
    db = get_db()
    if request.method == "POST":
        d = request.get_json(force=True)
        if "grants" in d and isinstance(d["grants"], list):
            ids = [int(x) for x in d["grants"]]
            members = ws_member_ids(db, u)
            if members is not None:
                ids = [i for i in ids if i in members]
            if is_super(u):
                db.execute("UPDATE users SET can_approve=0")
            else:                  # only this client's own people are touched
                db.execute(f"UPDATE users SET can_approve=0 WHERE role != 'superadmin' AND id IN "
                           f"({','.join('?' * len(members))})", members)
            if ids:
                q = ",".join("?" * len(ids))
                db.execute(f"UPDATE users SET can_approve=1 WHERE id IN ({q})", ids)
            db.commit()
        elif "user_id" in d:
            tgt_row = db.execute("SELECT role FROM users WHERE id=?", (int(d["user_id"]),)).fetchone()
            if tgt_row and (tgt_row["role"] == "superadmin") and not is_super(u):
                return jsonify({"error": "You can't change the Super Admin's access."}), 403
            if not in_ws(db, u, int(d["user_id"])):
                return jsonify({"error": "User not found."}), 404
            allow = 1 if d.get("allow") else 0
            db.execute("UPDATE users SET can_approve=? WHERE id=?", (allow, int(d["user_id"])))
            db.commit()
            tgt = db.execute("SELECT username FROM users WHERE id=?", (int(d["user_id"]),)).fetchone()
            if tgt:
                add_notification(db, f'{u["username"]} {"granted" if allow else "revoked"} '
                                     f'approval access {"to" if allow else "from"} {tgt["username"]}.',
                                 "info", u["username"],
                                 recipients=owner_and_admins(db, int(d["user_id"])))
        return jsonify({"ok": True})
    wq, wa = ws_sql(db, u, "id")
    rows = db.execute("SELECT id, username, display_name, role, can_approve "
                      "FROM users WHERE 1=1" + wq + " ORDER BY username", wa).fetchall()
    users = [{"id": r["id"], "username": r["username"],
              "display_name": r["display_name"] or r["username"],
              "role": r["role"] or "user",
              # reuse the 'can_download' key so the shared frontend manager works
              "can_download": bool(r["can_approve"]) or (r["role"] in ("admin", "superadmin"))}
             for r in rows]
    return jsonify({"users": users})


# ---- a user asks an admin for access (approval / download) ---------------- #
@app.route("/api/request-access", methods=["POST"])
def api_request_access():
    u = require_login()
    d = request.get_json(silent=True) or {}
    kind = (d.get("kind") or "approval").lower()
    label = "approval" if kind == "approval" else "download"
    db = get_db()
    add_notification(db, f'🔔 {u["username"]} is requesting {label} access.',
                     "info", u["username"], recipients=admin_ids(db))
    return jsonify({"ok": True})


@app.route("/api/videos/<int:vid>", methods=["PATCH"])
def api_update_video(vid):
    u = require_login()
    d = request.get_json(force=True)
    db = get_db()
    row = db.execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()
    if not row:
        return jsonify({"error": "Not found."}), 404

    # Full edit (title / description / hashtags / deadline) — ADMINS ONLY.
    editable = {k: d[k] for k in ("title", "description", "hashtags", "deadline") if k in d}
    if editable:
        if not is_admin(u):
            return jsonify({"error": "Only an admin can edit video details."}), 403
        if "title" in editable and not (editable["title"] or "").strip():
            return jsonify({"error": "Title can't be empty."}), 400
        sets, vals = [], []
        for k, v in editable.items():
            sets.append(f"{k}=?"); vals.append((v or "").strip() or None if k != "title" else (v or "").strip())
        sets.append("updated_at=?"); vals.append(datetime.utcnow().isoformat())
        vals.append(vid)
        db.execute(f"UPDATE videos SET {', '.join(sets)} WHERE id=?", vals)
        db.commit()
        add_notification(db, f'✏️ "{editable.get("title", row["title"])}" details updated by {u["username"]}.',
                         "info", u["username"], link=f"video:{vid}",
                         recipients=owner_and_admins(db, row["owner_id"]))
        return jsonify({"ok": True})

    # otherwise this is a status move
    status = d.get("status")
    if status not in STATUSES:
        return jsonify({"error": "Invalid status."}), 400
    now = datetime.utcnow().isoformat()
    if status == "completed":
        # record who completed it and when (for Reports); keep the first completion
        db.execute("UPDATE videos SET status=?, updated_at=?, completed_at=?, "
                   "completed_by=?, completed_by_id=? WHERE id=?",
                   (status, now, now, u["username"], u["id"], vid))
    else:
        # moving out of completed clears the completion stamp
        if status != "completed" and row["status"] == "completed":
            db.execute("UPDATE videos SET status=?, updated_at=?, completed_at=NULL, "
                       "completed_by=NULL, completed_by_id=NULL WHERE id=?", (status, now, vid))
        else:
            db.execute("UPDATE videos SET status=?, updated_at=? WHERE id=?", (status, now, vid))
    db.commit()
    add_notification(db, f'"{row["title"]}" moved to {STATUS_LABEL[status]} by {u["username"]}.',
                     "info", u["username"], link=f"video:{vid}",
                     recipients=owner_and_admins(db, row["owner_id"]))
    return jsonify({"ok": True})


@app.route("/api/reports")
def api_reports():
    """All videos with deadline vs. completion performance (for the Reports page)."""
    u = require_login()
    db = get_db()
    wq, wa = ws_sql(db, u)
    rows = db.execute("SELECT * FROM videos WHERE 1=1" + wq + " ORDER BY created_at DESC", wa).fetchall()
    out = []
    completed = 0
    for r in rows:
        d = dict(r)
        if r["completed_at"]:
            completed += 1
        # NOTE: the on-time delta is computed on the CLIENT, where the browser's
        # local timezone is known. `deadline` is a local (naive) datetime the
        # admin picked, while `completed_at` is stored in UTC — mixing them on
        # the server produced a timezone-offset error (e.g. +5h30m in IST). The
        # client parses completed_at as UTC and deadline as local, which is
        # correct. We no longer compute delta here.
        d["delta_seconds"] = None
        out.append(d)
    return jsonify({"videos": out, "completed_count": completed, "total": len(rows)})


@app.route("/api/videos/<int:vid>", methods=["DELETE"])
def api_delete_video(vid):
    u = require_login()
    db = get_db()
    row = db.execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()
    if not row:
        return jsonify({"error": "Not found."}), 404
    # Remove the actual video file from backend storage (local, Supabase, Drive)
    # so nothing is left behind after it's deleted from the tool.
    _purge_item_storage(db, row)
    db.execute("DELETE FROM videos WHERE id=?", (vid,))
    db.execute("DELETE FROM video_comments WHERE video_id=?", (vid,))
    db.commit()
    add_notification(db, f'⚠ "{row["title"]}" was REMOVED by {u["username"]}.',
                     "remove", u["username"],
                     recipients=owner_and_admins(db, row["owner_id"]))
    return jsonify({"ok": True})


# ---- video comments (admin leaves change requests + tags a user) ---------- #
@app.route("/api/videos/<int:vid>/comments")
def api_video_comments(vid):
    require_login()
    db = get_db()
    rows = db.execute(
        "SELECT c.*, u.username AS tagged_username, u.display_name AS tagged_name "
        "FROM video_comments c LEFT JOIN users u ON u.id=c.tagged_user_id "
        "WHERE c.video_id=? ORDER BY c.id ASC", (vid,)).fetchall()
    return jsonify({"comments": [dict(r) for r in rows]})


@app.route("/api/videos/<int:vid>/comments", methods=["POST"])
def api_add_video_comment(vid):
    u = require_login()
    db = get_db()
    row = db.execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()
    if not row:
        return jsonify({"error": "Not found."}), 404
    d = request.get_json(force=True)
    text = (d.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Enter a comment."}), 400
    tagged = d.get("tagged_user_id")
    tagged = int(tagged) if tagged else None
    db.execute("INSERT INTO video_comments (video_id, author, author_id, text, tagged_user_id, created_at) "
               "VALUES (?,?,?,?,?,?)",
               (vid, u["username"], u["id"], text, tagged, datetime.utcnow().isoformat()))
    db.commit()
    # notify the tagged user about the requested changes
    if tagged:
        tgt = db.execute("SELECT username FROM users WHERE id=?", (tagged,)).fetchone()
        if tgt:
            add_notification(db, f'💬 {u["username"]} left a note on "{row["title"]}" '
                                 f'and tagged @{tgt["username"]}: "{text[:80]}"',
                             "comment", u["username"], link=f"video:{vid}",
                             recipients=recips(db, tagged, row["owner_id"], admin_ids(db)))
    else:
        add_notification(db, f'💬 {u["username"]} commented on "{row["title"]}".',
                         "comment", u["username"], link=f"video:{vid}",
                         recipients=owner_and_admins(db, row["owner_id"]))
    return jsonify({"ok": True})


@app.route("/api/videos/<int:vid>/revise", methods=["POST"])
def api_revise_video(vid):
    """User uploads a revised version of a video and tags the admins."""
    u = require_login()
    db = get_db()
    row = db.execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()
    if not row:
        return jsonify({"error": "Not found."}), 404
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "Attach the revised video."}), 400
    # The revised file replaces the old one — purge the previous version from
    # backend storage so no orphaned copy is left behind.
    _purge_item_storage(db, row)
    filename = _safe_save(f)
    download_link = f"/uploads/{filename}"
    db.execute("UPDATE videos SET filename=?, download_link=?, drive_link='', drive_file_id='', "
               "status='processing', updated_at=? WHERE id=?",
               (filename, download_link, datetime.utcnow().isoformat(), vid))
    db.commit()
    # push to Drive in the background (uploader's, else the workspace SuperAdmin's)
    gu = _google_user_for(db, u)
    if gu:
        _start_drive_upload_task(gu["id"], vid, os.path.join(UPLOAD_DIR, filename), row["title"])
    add_notification(db, f'🔁 {u["username"]} uploaded a REVISED version of "{row["title"]}" '
                         f'— please review.', "upload", u["username"], link=f"video:{vid}",
                     recipients=owner_and_admins(db, row["owner_id"]))
    return jsonify({"ok": True})


# ---- current user's profile (display name) -------------------------------- #
@app.route("/api/me/profile", methods=["POST"])
def api_update_profile():
    u = require_login()
    d = request.get_json(force=True)
    name = (d.get("display_name") or "").strip()
    if not name:
        return jsonify({"error": "Enter a display name."}), 400
    db = get_db()
    db.execute("UPDATE users SET display_name=? WHERE id=?", (name, u["id"]))
    # optional contact fields (used by the onboarding "Complete Profile" step)
    if "email" in d:
        db.execute("UPDATE users SET email=? WHERE id=?", ((d.get("email") or "").strip(), u["id"]))
    if "phone" in d:
        db.execute("UPDATE users SET phone=? WHERE id=?", ((d.get("phone") or "").strip(), u["id"]))
    db.commit()
    return jsonify({"user": user_public(current_user())})


# --------------------------------------------------------------------------- #
#  API : calendar
# --------------------------------------------------------------------------- #
def _safe_save(fileobj):
    name = re.sub(r"[^A-Za-z0-9._-]", "_", fileobj.filename or "video")
    stamp = secrets.token_hex(4)
    fname = f"{stamp}_{name}"
    local_path = os.path.join(UPLOAD_DIR, fname)
    fileobj.save(local_path)
    # Mirror to Supabase Storage (online) so the file survives restarts and is
    # publicly fetchable; local copy stays for fast serving + frame extraction.
    if USE_SUPABASE_STORAGE:
        _supabase_upload_path(local_path, fname)
    return fname


@app.route("/api/calendar")
def api_calendar():
    u = require_login()
    db = get_db()
    brand = _rget(u, "active_brand_id")
    wq, wa = ws_sql(db, u)
    if brand:
        rows = db.execute("SELECT * FROM calendar_items WHERE brand_id=?" + wq + " ORDER BY date ASC, id ASC",
                          [brand] + wa).fetchall()
    else:
        rows = db.execute("SELECT * FROM calendar_items WHERE 1=1" + wq + " ORDER BY date ASC, id ASC", wa).fetchall()
    today = datetime.now().strftime("%Y-%m-%d")
    targets = _targets_for(db, [r["id"] for r in rows])
    items = []
    for r in rows:
        d = dict(r)
        d["platforms"] = _item_platforms(r)
        d["platform_captions"] = _jl(r["platform_captions"], {})
        d["media"] = _item_files(r)
        d["media_kind"] = _item_kind(r)
        d["variants"] = _jl(r["variants"], {})
        d["targets"] = targets.get(r["id"], [])
        items.append(d)
    by_date = {}
    not_uploaded = 0
    uploaded = 0
    for d in items:
        by_date.setdefault(d["date"], []).append(d)
        if d["state"] == "published":
            uploaded += 1
        elif d["date"] < today:
            not_uploaded += 1     # past its date and still not published
    return jsonify({
        "items": items,
        "by_date": by_date,
        "today": today,
        "not_uploaded": not_uploaded,
        "uploaded": uploaded,
    })


@app.route("/api/calendar/upload", methods=["POST"])
def api_calendar_upload():
    """Upload video(s) only. Captions are generated later, on demand."""
    u = require_login()
    date = request.form.get("date")
    if not date:
        return jsonify({"error": "A date is required."}), 400
    files = request.files.getlist("files") or (
        [request.files["file"]] if request.files.get("file") else [])
    if not files:
        return jsonify({"error": "Attach at least one video."}), 400
    db = get_db()
    created = []
    plats = [x for x in _jl(request.form.get("platforms"), []) if x in SOCIAL] or ["instagram"]
    brand = _rget(u, "active_brand_id")
    if request.form.get("as_carousel") in ("1", "true") and len(files) > 1:
        names = [_safe_save(f) for f in files]
        cur = db.execute(
            "INSERT INTO calendar_items (date, title, filename, media, media_kind, caption, hashtags, state, "
            "approved, owner, owner_id, created_at, platforms, content_type, brand_id) "
            "VALUES (?,?,?,?, 'carousel', '', '', 'uploaded', 0, ?,?,?,?, 'post', ?)",
            (date, (request.form.get("title") or f"Carousel ({len(names)} items)"), names[0], json.dumps(names),
             u["username"], u["id"], datetime.utcnow().isoformat(), json.dumps(plats), brand))
        db.commit()
        log_activity(db, u, "uploaded", "item", cur.lastrowid, f"carousel of {len(names)}")
        add_notification(db, f'New carousel ({len(names)} items) uploaded on {date} by {u["username"]}.',
                         "upload", u["username"], recipients=owner_and_admins(db, u["id"]))
        return jsonify({"ids": [cur.lastrowid]})
    for f in files:
        fname = _safe_save(f)
        kind = _media_kind_for([fname])
        cur = db.execute(
            "INSERT INTO calendar_items "
            "(date, title, filename, caption, hashtags, state, approved, owner, owner_id, created_at, "
            " platforms, media_kind, content_type, brand_id) "
            "VALUES (?,?,?,'','', 'uploaded', 0, ?, ?, ?, ?, ?, ?, ?)",
            (date, f.filename, fname, u["username"], u["id"], datetime.utcnow().isoformat(),
             json.dumps(plats), kind, "reel" if kind == "video" else "post", brand),
        )
        cid = cur.lastrowid
        created.append(cid)
        log_activity(db, u, "uploaded", "item", cid, f.filename or "")
        # Back the file up to Google Drive in the background — the uploader's own
        # Drive if connected, otherwise the workspace SuperAdmin's — and record the
        # shareable Drive link on the calendar item (shown in the UI).
        gu = _google_user_for(db, u)
        if fname and gu:
            _start_drive_upload_task(gu["id"], cid, os.path.join(UPLOAD_DIR, fname),
                                     f.filename or "video", table="calendar_items")
    db.commit()
    add_notification(
        db, f'{len(created)} new video(s) uploaded on {date} by {u["username"]} '
            f'— generate captions to continue.', "upload", u["username"],
        recipients=owner_and_admins(db, u["id"]))
    return jsonify({"ids": created})


# background caption-generation jobs  {item_id: {status, percent, message, caption, hashtags}}
GEN_JOBS = {}


class _Cancelled(Exception):
    pass


def _run_generation(cid, video_path, original_name, user_id="", frames=None):
    # register in the GLOBAL task registry so it shows in the Running Tasks bar
    # on EVERY page (only to the user who started it) and keeps running when the
    # user navigates away.
    tid = task_new("generate", f'Generating caption & hashtags for "{original_name}"', str(user_id))

    def _prog(p, m):
        if task_cancelled(tid):
            raise _Cancelled()           # abort generation immediately on cancel
        GEN_JOBS[cid] = {"status": "running", "percent": p, "message": m}
        task_update(tid, percent=p, message=m)

    GEN_JOBS[cid] = {"status": "running", "percent": 5, "message": "Preparing…"}
    task_update(tid, percent=5, message="Preparing…")
    try:
        kit = None
        try:
            _db = db_connect()
            _r = _db.execute("SELECT owner_id, brand_id FROM calendar_items WHERE id=?", (cid,)).fetchone()
            kit = kit_for_owner(_db, _r["owner_id"], _r["brand_id"]) if _r else None
            _db.close()
        except Exception:
            kit = None
        title, cap, tags, desc, note = generate_caption(video_path, original_name, progress=_prog, kit=kit,
                                                         frames=frames)
        db = db_connect()
        db.execute("UPDATE calendar_items SET title=?, caption=?, hashtags=? WHERE id=?",
                   (title or original_name, cap, tags, cid))
        if desc:                          # a template run never wipes a description
            db.execute("UPDATE calendar_items SET description=? WHERE id=?", (desc, cid))
        db.commit()
        db.close()
        GEN_JOBS[cid] = {"status": "done", "percent": 100,
                         "message": ("Used a basic template: " + note) if note else "Title, caption, description & hashtags ready.",
                         "warning": note, "title": title, "caption": cap, "hashtags": tags, "description": desc}
        try:
            dbn = db_connect()
            _r = dbn.execute("SELECT owner_id FROM calendar_items WHERE id=?", (cid,)).fetchone()
            add_notification(dbn, f'✍️ Content generation completed — caption & hashtags ready for '
                                  f'"{title or original_name}".', "content", "system",
                             recipients=(owner_and_admins(dbn, _r["owner_id"]) if _r else None))
            dbn.close()
        except Exception:
            pass
        task_done(tid, ok=True, message="Caption & hashtags ready.")
    except _Cancelled:
        GEN_JOBS[cid] = {"status": "cancelled", "percent": 0, "message": "Cancelled."}
        task_mark_cancelled(tid)
    except Exception as e:  # noqa
        GEN_JOBS[cid] = {"status": "error", "percent": 0,
                         "message": f"Generation failed: {e}"}
        task_done(tid, ok=False, message=f"Generation failed: {e}")


@app.route("/api/calendar/<int:cid>/generate", methods=["POST"])
def api_calendar_generate(cid):
    u = require_login()
    db = get_db()
    row = db.execute("SELECT * FROM calendar_items WHERE id=?", (cid,)).fetchone()
    if not row:
        return jsonify({"error": "Not found."}), 404
    import base64
    frames = []                           # JPEG frames the browser captured from the video
    for f in ((request.get_json(silent=True) or {}).get("frames") or [])[:4]:
        m = re.match(r"^data:image/jpe?g;base64,(.+)$", str(f), re.S)
        if m:
            try:
                raw = base64.b64decode(m.group(1), validate=False)
            except Exception:
                continue
            if 1000 < len(raw) <= 2 * 1024 * 1024:
                frames.append(raw)
    files = _item_files(row)
    vpath = _local_upload(files[0]) if files else ""
    if not vpath:
        vpath = os.path.join(UPLOAD_DIR, row["filename"] or "")
    GEN_JOBS[cid] = {"status": "starting", "percent": 0, "message": "Starting…"}
    threading.Thread(target=_run_generation, args=(cid, vpath, row["title"], u["id"], frames),
                     daemon=True).start()
    return jsonify({"ok": True, "frames": len(frames)})


@app.route("/api/calendar/<int:cid>/genstatus")
def api_calendar_genstatus(cid):
    require_login()
    return jsonify(GEN_JOBS.get(cid, {"status": "idle", "percent": 0, "message": ""}))


@app.route("/api/calendar/<int:cid>/submit", methods=["POST"])
def api_calendar_submit(cid):
    """Submit a captioned video for upload (moves it into the approval queue)."""
    u = require_login()
    db = get_db()
    row = db.execute("SELECT * FROM calendar_items WHERE id=?", (cid,)).fetchone()
    if not row:
        return jsonify({"error": "Not found."}), 404
    if not ((row["caption"] or "").strip() or (row["hashtags"] or "").strip()):
        return jsonify({"error": "Add a caption or hashtags before pushing to review."}), 400
    db.execute("UPDATE calendar_items SET state='submitted' WHERE id=?", (cid,))
    db.commit()
    log_activity(db, u, "submitted", "item", cid, row["title"])
    add_notification(db, f'"{row["title"]}" ({row["date"]}) submitted for upload by '
                         f'{u["username"]} — awaiting approval.', "upload", u["username"],
                     recipients=owner_and_admins(db, row["owner_id"]))
    return jsonify({"ok": True})


@app.route("/api/calendar/<int:cid>/approve", methods=["POST"])
def api_calendar_approve(cid):
    u = require_login()
    # Approval is admin-only, unless an admin has granted this user approval access.
    if not _user_can_approve(u):
        return jsonify({"error": "Only an admin (or a user granted approval access) "
                                 "can approve content. Ask an admin for access."}), 403
    db = get_db()
    row = db.execute("SELECT * FROM calendar_items WHERE id=?", (cid,)).fetchone()
    if not row:
        return jsonify({"error": "Not found."}), 404
    db.execute("UPDATE calendar_items SET approved=1, state='approved' WHERE id=?", (cid,))
    db.commit()
    log_activity(db, u, "approved", "item", cid, row["title"])
    if _rget(row, "publish_at"):
        db.execute("UPDATE calendar_items SET state='scheduled', publish_state='scheduled' WHERE id=?", (cid,))
        db.commit()
    d_ = request.get_json(silent=True) or {}
    if _rget(row, "queue_on_approve") or d_.get("queue"):
        _apply_queue(db, db.execute("SELECT * FROM calendar_items WHERE id=?", (cid,)).fetchone(), u,
                     d_.get("tz"), d_.get("offset"))
    add_notification(db, f'"{row["title"]}" ({row["date"]}) approved by {u["username"]}.',
                     "approval", u["username"],
                     recipients=owner_and_admins(db, row["owner_id"]))
    return jsonify({"ok": True})


# =========================================================================== #
#  V31 : MULTI-PLATFORM PUBLISHING ENGINE
#  One calendar item → one post_targets row per selected platform. Each target
#  is published by the durable job queue (retries + backoff), with per-platform
#  captions, converted media variants and a live/simulated account per platform.
# =========================================================================== #
SOCIAL = list(P.ORDER)
CRED_KEYS = {
    "instagram": ("ig_app_id", "ig_app_secret"), "facebook": ("fb_app_id", "fb_app_secret"),
    "youtube": ("yt_client_id", "yt_client_secret"), "twitter": ("tw_api_key", "tw_api_secret"),
    "linkedin": ("li_client_id", "li_client_secret"), "threads": ("th_app_id", "th_app_secret"),
    "tiktok": ("tt_client_key", "tt_client_secret"), "pinterest": ("pin_app_id", "pin_app_secret"),
}
# legacy per-user columns kept in sync so older screens keep working
LEGACY_COLS = {
    "instagram": ("instagram_connected", "ig_username", "ig_token", "ig_user_id"),
    "facebook": ("fb_connected", "fb_account", "fb_token", "fb_user_id"),
    "youtube": ("yt_connected", "yt_account", "yt_token", "yt_channel_id"),
    "twitter": ("tw_connected", "tw_account", "tw_token", "tw_user_id"),
}
IMG_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp")
VID_EXT = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v")
RETRY_DELAYS = [60, 300, 900]           # seconds between publish attempts


def _jl(v, default):
    """Lenient JSON load for TEXT columns."""
    if v in (None, ""):
        return default
    if isinstance(v, (list, dict)):
        return v
    try:
        return json.loads(v)
    except Exception:
        return default


def _now():
    return datetime.utcnow().isoformat()


def _rget(row, key, default=None):
    try:
        v = row[key]
        return default if v is None else v
    except (KeyError, IndexError):
        return default


def log_activity(db, u, action, ttype="", tid=None, detail=""):
    try:
        db.execute("INSERT INTO activity_log (user_id, username, action, target_type, target_id, detail, created_at) "
                   "VALUES (?,?,?,?,?,?,?)",
                   (u["id"] if u else None, (u["username"] if u else "system"), action, ttype, tid,
                    (detail or "")[:500], _now()))
        db.commit()
    except Exception:
        pass


def _is_image(fn):
    return (fn or "").lower().endswith(IMG_EXT)


def _item_files(row):
    files = _jl(_rget(row, "media"), None)
    if files:
        return files
    return [row["filename"]] if _rget(row, "filename") else []


def _media_kind_for(files):
    if not files:
        return "text"
    if len(files) > 1:
        return "carousel"
    return "image" if _is_image(files[0]) else "video"


def _item_kind(row):
    return _rget(row, "media_kind") or _media_kind_for(_item_files(row))


def _item_platforms(row):
    p = [x for x in _jl(_rget(row, "platforms"), []) if x in SOCIAL]
    return p or ["instagram"]


def _public_media_url(db, fname):
    if not fname:
        return ""
    if USE_SUPABASE_STORAGE:
        return _supabase_public_url(fname)
    base = (get_setting(db, "public_base_url") or "").strip().rstrip("/")
    return f"{base}/uploads/{urllib.parse.quote(fname)}" if base.startswith("https://") else ""


DESC_PLATFORMS = ("youtube", "facebook", "linkedin", "pinterest")


def _caption_for(row, platform, db=None):
    """Caption for one platform. With `db`, a website link on the post becomes a
    UTM-tracked short link: it replaces {link}, or is appended (except Instagram,
    where caption links aren't clickable — use the link-in-bio page there)."""
    pc = _jl(_rget(row, "platform_captions"), {})
    if (pc.get(platform) or "").strip():
        text = pc[platform].strip()
    else:
        cap, tags = (row["caption"] or "").strip(), (row["hashtags"] or "").strip()
        desc = (_rget(row, "description") or "").strip()
        if desc and platform in DESC_PLATFORMS:     # long-form platforms also get the description
            room = P.PLATFORMS[platform]["caption_max"] - len(cap) - len(tags) - 4
            desc = P.split_text(desc, room) if room > 40 else ""
        else:
            desc = ""
        text = "\n\n".join(x for x in (cap, desc, tags) if x)
    if (_rget(row, "link_url") or "").strip():
        short = post_link(db, row, platform) if db is not None else "https://example.com/r/xxxxxxx"
        if "{link}" in text:
            text = text.replace("{link}", "link in bio" if platform == "instagram" else short)
        elif platform != "instagram":
            text = (text + "\n\n" + short).strip()
    return text.replace("{link}", "")


def _allowed_platforms(u):
    """Platforms this user may publish to (roles per platform)."""
    if not u or is_super(u):
        return list(SOCIAL)
    lst = _jl(_rget(u, "publish_platforms"), None)
    return [p for p in SOCIAL if p in lst] if isinstance(lst, list) else list(SOCIAL)


# ---- connected accounts --------------------------------------------------- #
def _decrypt_account(a):
    a = dict(a)
    a["token"] = dec(a.get("token"))
    a["refresh_token"] = dec(a.get("refresh_token"))
    a["extra"] = dec(a.get("extra")) if isinstance(a.get("extra"), str) else a.get("extra")
    return a


def _account_for_user(db, uid, platform, brand_id=None):
    rows = [_decrypt_account(r) for r in db.execute(
        "SELECT * FROM social_accounts WHERE user_id=? AND platform=? ORDER BY id DESC", (uid, platform)).fetchall()]
    for r in rows:
        if brand_id and r.get("brand_id") == brand_id:
            return r
    for r in rows:
        if not r.get("brand_id"):
            return r
    return rows[0] if rows else None


def _hydrate_account(db, acct):
    """Attach the owner's app credentials (needed for token refresh)."""
    if not acct:
        return None
    a = _decrypt_account(acct)
    a["app_id"], a["app_secret"], _src = app_creds(db, a["user_id"], a["platform"])
    a["extra"] = _jl(a.get("extra"), {})
    return a


def _legacy_account(db, uid, platform):
    """Pre-V31 Instagram tokens lived on the users row — keep them usable."""
    if platform != "instagram" or not uid:
        return None
    row = db.execute("SELECT ig_token, ig_user_id, ig_username FROM users WHERE id=?", (uid,)).fetchone()
    if row and dec(row["ig_token"]):
        return {"id": None, "user_id": uid, "platform": "instagram", "account_id": row["ig_user_id"] or "",
                "account_name": row["ig_username"] or "", "token": dec(row["ig_token"]), "refresh_token": "",
                "expires_at": None, "extra": "{}", "mode": "live", "brand_id": None}
    return None


def _publish_account(db, row, platform):
    """The account a calendar item publishes from, following the workspace's social
    mode (see ws_social_mode). Never another client's."""
    brand = _rget(row, "brand_id")
    cands = []
    if _rget(row, "owner_id"):
        # central mode: the workspace admin's accounts; individual mode: the post owner's own
        cands.append(social_owner_id(db, row["owner_id"]))
    for uid in cands:
        a = _account_for_user(db, uid, platform, brand) or _legacy_account(db, uid, platform)
        if a and a.get("mode") == "live" and a.get("token"):
            return _hydrate_account(db, a)
    return None


def _save_account(db, uid, platform, info, mode="live", brand_id=None):
    now = _now()
    ex = db.execute("SELECT id FROM social_accounts WHERE user_id=? AND platform=? AND COALESCE(brand_id,0)=?",
                    (uid, platform, brand_id or 0)).fetchone()
    vals = (info.get("account_id", ""), info.get("account_name", ""), enc(info.get("token", "")),
            enc(info.get("refresh_token", "")), info.get("expires_at"), enc(json.dumps(info.get("extra") or {})),
            mode, "ok", "", now)
    if ex:
        db.execute("UPDATE social_accounts SET account_id=?, account_name=?, token=?, refresh_token=?, "
                   "expires_at=?, extra=?, mode=?, status=?, last_error=?, updated_at=?, warned_at=NULL "
                   "WHERE id=?", vals + (ex["id"],))
    else:
        db.execute("INSERT INTO social_accounts (account_id, account_name, token, refresh_token, expires_at, "
                   "extra, mode, status, last_error, updated_at, user_id, platform, brand_id, created_at) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", vals + (uid, platform, brand_id, now))
    if platform in LEGACY_COLS:
        c, acol, tcol, icol = LEGACY_COLS[platform]
        db.execute(f"UPDATE users SET {c}=1, {acol}=?, {tcol}=?, {icol}=? WHERE id=?",
                   (info.get("account_name", ""), enc(info.get("token", "")) if mode == "live" else "",
                    info.get("account_id", ""), uid))
        if platform == "instagram":
            db.execute("UPDATE users SET instagram_account=? WHERE id=?", (info.get("account_name", ""), uid))
    db.commit()


def _ensure_fresh(db, a):
    """Refresh an expiring OAuth token before using it."""
    if not a or not a.get("id"):
        return a
    exp = a.get("expires_at")
    if exp and float(exp) < time.time() + 600:
        try:
            upd = P.refresh(a["platform"], a)
        except P.PlatformError as e:
            db.execute("UPDATE social_accounts SET status='expired', last_error=? WHERE id=?", (str(e), a["id"]))
            db.commit()
            raise P.PlatformError(f"{P.PLATFORMS[a['platform']]['label']} session expired — reconnect it in Setup.")
        if upd:
            a.update(upd)
            db.execute("UPDATE social_accounts SET token=?, refresh_token=?, expires_at=?, status='ok', "
                       "last_error='', updated_at=? WHERE id=?",
                       (enc(a["token"]), enc(a.get("refresh_token", "")), a.get("expires_at"), _now(), a["id"]))
            db.commit()
    return a


# ---- media ------------------------------------------------------------------ #
def _build_media(db, row, platform):
    files = _item_files(row)
    variants = _jl(_rget(row, "variants"), {})
    if len(files) == 1 and variants.get(platform):
        files = [variants[platform]]
    items = []
    for f in files:
        path = _local_upload(f)              # re-downloads from Supabase Storage after a redeploy
        if not path:
            raise P.PlatformError(f"The media file {f} can't be found on the server or in storage — "
                                  "replace the video and retry.")
        items.append({"path": path, "url": _public_media_url(db, f), "mime": _guess_content_type(f),
                      "is_video": not _is_image(f)})
    thumb = _rget(row, "thumbnail")
    return {"kind": _media_kind_for(files) if files else "text", "items": items,
            "thumb_path": (_local_upload(thumb) if thumb else ""),
            "thumb_url": _public_media_url(db, thumb) if thumb else ""}


# ---- durable job queue ------------------------------------------------------ #
def job_enqueue(db, kind, payload, delay=0, max_attempts=3):
    run_at = (datetime.utcnow() + timedelta(seconds=delay)).isoformat()
    db.execute("INSERT INTO jobs (kind, payload, status, attempts, max_attempts, run_at, created_at, updated_at) "
               "VALUES (?,?, 'queued', 0, ?,?,?,?)", (kind, json.dumps(payload), max_attempts, run_at, _now(), _now()))
    db.commit()


def _claim_job(db):
    row = db.execute("SELECT * FROM jobs WHERE status='queued' AND run_at<=? ORDER BY run_at, id LIMIT 1",
                     (_now(),)).fetchone()
    if not row:
        return None
    cur = db.execute("UPDATE jobs SET status='running', locked_at=?, attempts=attempts+1, updated_at=? "
                     "WHERE id=? AND status='queued'", (_now(), _now(), row["id"]))
    db.commit()
    if cur.rowcount != 1:
        return None
    j = dict(row)
    j["attempts"] = (j.get("attempts") or 0) + 1
    return j


def _recover_stale(db):
    """Jobs/targets stuck 'running' (e.g. the server restarted mid-publish).
    They are NOT auto-retried: the post may already be live, and retrying could
    double-post — they're marked failed with guidance instead."""
    cutoff = (datetime.utcnow() - timedelta(minutes=20)).isoformat()
    db.execute("UPDATE jobs SET status='failed', last_error='Interrupted', updated_at=? "
               "WHERE status='running' AND locked_at<?", (_now(), cutoff))
    stale = db.execute("SELECT id, item_id FROM post_targets WHERE status='publishing' AND started_at<?",
                       (cutoff,)).fetchall()
    for t in stale:
        db.execute("UPDATE post_targets SET status='failed', error=? WHERE id=?",
                   ("Interrupted while publishing (server restart?). Check the platform before retrying "
                    "so the post isn't duplicated.", t["id"]))
    db.commit()
    for t in stale:
        _finalize_item(db, t["item_id"])


JOB_HANDLERS = {}
_JOB_SEM = threading.Semaphore(3)


def _run_job(job):
    try:
        handler = JOB_HANDLERS.get(job["kind"])
        result = handler(job) if handler else None
        db = db_connect()
        if result and result.get("retry_in") is not None:
            run_at = (datetime.utcnow() + timedelta(seconds=result["retry_in"])).isoformat()
            db.execute("UPDATE jobs SET status='queued', run_at=?, last_error=?, updated_at=? WHERE id=?",
                       (run_at, result.get("error", ""), _now(), job["id"]))
        else:
            st = "failed" if (result and result.get("failed")) else "done"
            db.execute("UPDATE jobs SET status=?, last_error=?, updated_at=? WHERE id=?",
                       (st, (result or {}).get("error", ""), _now(), job["id"]))
        db.commit()
        db.close()
    except Exception as e:  # noqa
        try:
            db = db_connect()
            db.execute("UPDATE jobs SET status='failed', last_error=?, updated_at=? WHERE id=?",
                       (str(e)[:500], _now(), job["id"]))
            db.commit()
            db.close()
        except Exception:
            pass
    finally:
        _JOB_SEM.release()


def _job_worker_loop():
    last_recover = 0
    while True:
        try:
            db = db_connect()
            if time.time() - last_recover > 120:
                _recover_stale(db)
                last_recover = time.time()
            while _JOB_SEM.acquire(blocking=False):
                job = _claim_job(db)
                if not job:
                    _JOB_SEM.release()
                    break
                threading.Thread(target=_run_job, args=(job,), daemon=True).start()
            db.close()
        except Exception:
            pass
        time.sleep(3)


# ---- publishing --------------------------------------------------------------- #
def enqueue_publish(db, row, actor_user=None, platforms=None, content_type=None, actor_name=None):
    """Queue a calendar item for publishing on its (or the given) platforms.
    Idempotent: targets already queued/publishing/published are left alone."""
    plats = [p for p in (platforms or _item_platforms(row)) if p in SOCIAL]
    if not plats:
        raise ValueError("Select at least one platform.")
    if actor_user:
        allowed = _allowed_platforms(actor_user)
        denied = [P.PLATFORMS[p]["label"] for p in plats if p not in allowed]
        if denied:
            raise PermissionError("You don't have permission to publish to " + ", ".join(denied) + ".")
    if content_type:
        db.execute("UPDATE calendar_items SET content_type=? WHERE id=?", (content_type, row["id"]))
    existing = {t["platform"]: t for t in db.execute("SELECT * FROM post_targets WHERE item_id=?",
                                                     (row["id"],)).fetchall()}
    for p in plats:
        if p not in existing:
            db.execute("INSERT INTO post_targets (item_id, platform, status, attempts, created_at) "
                       "VALUES (?,?, 'new', 0, ?)", (row["id"], p, _now()))
    db.commit()
    queued = 0
    actor = actor_name or (actor_user["username"] if actor_user else "scheduler")
    for t in db.execute("SELECT * FROM post_targets WHERE item_id=?", (row["id"],)).fetchall():
        if t["platform"] not in plats:
            continue
        cur = db.execute("UPDATE post_targets SET status='pending', error='' WHERE id=? AND status IN ('new','failed')",
                         (t["id"],))
        db.commit()
        if cur.rowcount == 1:
            job_enqueue(db, "publish", {"target_id": t["id"], "actor": actor})
            queued += 1
    if queued:
        db.execute("UPDATE calendar_items SET publish_state='publishing', publish_pct=5 WHERE id=?", (row["id"],))
        db.commit()
    return queued


def _retryable(err):
    return bool(getattr(err, "retry", False))


def _simulated_result(platform):
    return {"remote_id": "sim_" + secrets.token_hex(5), "permalink": "",
            "message": f"Simulated — connect a live {P.PLATFORMS[platform]['label']} account in Setup to post for real."}


def _job_publish(job):
    pl = _jl(job["payload"], {})
    db = db_connect()
    item_id = None
    try:
        t = db.execute("SELECT * FROM post_targets WHERE id=?", (pl.get("target_id"),)).fetchone()
        if not t or t["status"] == "published":
            return None
        item_id = t["item_id"]
        cur = db.execute("UPDATE post_targets SET status='publishing', started_at=?, error='' "
                         "WHERE id=? AND status IN ('pending','retrying')", (_now(), t["id"]))
        db.commit()
        if cur.rowcount != 1:
            return None                     # someone else is handling it
        row = db.execute("SELECT * FROM calendar_items WHERE id=?", (item_id,)).fetchone()
        if not row:
            db.execute("UPDATE post_targets SET status='failed', error='Item deleted' WHERE id=?", (t["id"],))
            db.commit()
            return None
        platform = t["platform"]
        text = _caption_for(row, platform, db)
        tags = [w for w in (row["hashtags"] or "").split() if w.startswith("#")]
        opts = {"post_type": (row["content_type"] or "reel"), "title": _rget(row, "yt_title") or row["title"],
                "privacy": _rget(row, "yt_privacy") or "public", "tags": tags}
        acct = _publish_account(db, row, platform)
        simulated = 0
        if not acct:
            label = P.PLATFORMS[platform]["label"]
            raise P.PlatformError(f"{label} isn't connected. Connect it in Setup, then retry.")
        acct = _ensure_fresh(db, acct)
        media = _build_media(db, row, platform)
        if media["kind"] == "text" and not text:
            raise P.PlatformError("Nothing to post — add a caption.")
        res = P.publish(platform, acct, media, text, opts)
        db.execute("UPDATE post_targets SET status='published', remote_id=?, permalink=?, message=?, "
                   "simulated=?, published_at=?, attempts=?, error='' WHERE id=?",
                   (res.get("remote_id", ""), res.get("permalink", ""), res.get("message", ""),
                    simulated, _now(), job["attempts"], t["id"]))
        if platform == "instagram":
            db.execute("UPDATE calendar_items SET ig_media_id=?, ig_permalink=? WHERE id=?",
                       ("" if simulated else res.get("remote_id", ""), res.get("permalink", ""), item_id))
        db.commit()
        log_activity(db, None, "published", "item", item_id,
                     f'{P.PLATFORMS[platform]["label"]}{" (simulated)" if simulated else ""}: {row["title"]}')
        return None
    except Exception as e:  # noqa
        msg = str(e) or e.__class__.__name__
        if item_id is None:
            return {"failed": True, "error": msg}
        attempts = job["attempts"]
        if _retryable(e) and attempts < job.get("max_attempts", 3):
            delay = RETRY_DELAYS[min(attempts - 1, len(RETRY_DELAYS) - 1)]
            db.execute("UPDATE post_targets SET status='retrying', error=?, attempts=? WHERE id=?",
                       (f"{msg} — retrying in {delay // 60} min", attempts, pl.get("target_id")))
            db.commit()
            return {"retry_in": delay, "error": msg}
        db.execute("UPDATE post_targets SET status='failed', error=?, attempts=? WHERE id=?",
                   (msg[:800], attempts, pl.get("target_id")))
        db.commit()
        try:
            row = db.execute("SELECT * FROM calendar_items WHERE id=?", (item_id,)).fetchone()
            t = db.execute("SELECT platform FROM post_targets WHERE id=?", (pl.get("target_id"),)).fetchone()
            label = P.PLATFORMS[t["platform"]]["label"] if t else "platform"
            send_alert(db, owner_and_admins(db, row["owner_id"] if row else None),
                       f"Publish failed on {label}",
                       f'❌ "{row["title"] if row else item_id}" failed to publish on {label}: {msg[:300]}',
                       link=f"calendar:{item_id}", event="publish_failed",
                       payload={"item_id": item_id, "platform": t["platform"] if t else "", "error": msg})
        except Exception:
            pass
        return {"failed": True, "error": msg}
    finally:
        if item_id:
            try:
                _finalize_item(db, item_id)
            except Exception:
                pass
        db.close()


JOB_HANDLERS["publish"] = _job_publish


def _finalize_item(db, item_id):
    """Roll per-platform target statuses up into the calendar item."""
    row = db.execute("SELECT * FROM calendar_items WHERE id=?", (item_id,)).fetchone()
    if not row:
        return
    ts = [dict(t) for t in db.execute("SELECT * FROM post_targets WHERE item_id=?", (item_id,)).fetchall()]
    active = [t for t in ts if t["status"] in ("pending", "publishing", "retrying")]
    done = [t for t in ts if t["status"] in ("published", "failed")]
    if active:
        pct = int(10 + 85 * len(done) / max(1, len(done) + len(active)))
        db.execute("UPDATE calendar_items SET publish_state='publishing', publish_pct=? WHERE id=?", (pct, item_id))
        db.commit()
        return
    pub = [t for t in ts if t["status"] == "published"]
    failed = [t for t in ts if t["status"] == "failed"]
    if not (pub or failed):
        return
    was = (row["publish_state"] or "")
    if pub:
        state = "partial" if failed else "published"
        db.execute("UPDATE calendar_items SET state='published', published_date=COALESCE(published_date, ?), "
                   "publish_state=?, publish_pct=100 WHERE id=?",
                   (datetime.now().strftime("%Y-%m-%d"), state, item_id))
    else:
        state = "failed"
        db.execute("UPDATE calendar_items SET publish_state='failed', publish_pct=0 WHERE id=?", (item_id,))
    db.commit()
    if was == "publishing":
        lab = lambda lst: ", ".join(P.PLATFORMS[t["platform"]]["label"] + (" (simulated)" if t.get("simulated") else "")
                                    for t in lst)
        msg = f'✅ "{row["title"]}" published to {lab(pub)}.' if pub else f'❌ "{row["title"]}" failed to publish.'
        if pub and failed:
            msg += f" Failed on {lab(failed)} — open the calendar to retry."
        add_notification(db, msg, "publish", "system", link=f"published:{item_id}",
                         recipients=owner_and_admins(db, row["owner_id"]))
    if pub and _rget(row, "recycle_days") and not _rget(row, "recycled_to"):
        _recycle_item(db, row)


def _recycle_item(db, row):
    """Evergreen: clone a published item N days ahead as an approved, scheduled post."""
    try:
        days = int(row["recycle_days"])
    except Exception:
        return
    if days <= 0:
        return
    new_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    new_at = None
    if _rget(row, "publish_at"):
        try:
            new_at = (datetime.fromisoformat(row["publish_at"]) + timedelta(days=days)).isoformat()
        except Exception:
            new_at = None
    cur = db.execute(
        "INSERT INTO calendar_items (date, title, filename, caption, hashtags, state, approved, owner, owner_id, "
        "created_at, content_type, platforms, platform_captions, media, media_kind, thumbnail, variants, tz, "
        "publish_at, publish_time, recycle_days, recycled_from, brand_id, yt_title, yt_privacy, auto_publish, "
        "publish_state) VALUES (?,?,?,?,?, 'scheduled', 1, ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 1, 'scheduled')",
        (new_date, row["title"], row["filename"], row["caption"], row["hashtags"], row["owner"], row["owner_id"],
         _now(), row["content_type"], row["platforms"], row["platform_captions"], row["media"], row["media_kind"],
         row["thumbnail"], row["variants"], row["tz"], new_at, row["publish_time"], days, row["id"],
         row["brand_id"], row["yt_title"], row["yt_privacy"]))
    db.execute("UPDATE calendar_items SET recycled_to=? WHERE id=?", (cur.lastrowid, row["id"]))
    db.commit()
    add_notification(db, f'♻️ Evergreen: "{row["title"]}" will be re-shared on {new_date}.', "calendar", "system",
                     link=f"calendar:{cur.lastrowid}", recipients=owner_and_admins(db, row["owner_id"]))


def _file_in_use(db, fname, exclude_id):
    """Recycled items share media files — only delete a file nobody references."""
    like = f'%"{fname}"%'
    r = db.execute("SELECT 1 FROM calendar_items WHERE id<>? AND (filename=? OR thumbnail=? OR media LIKE ? "
                   "OR variants LIKE ?) LIMIT 1", (exclude_id, fname, fname, like, like)).fetchone()
    if r is None:           # the content library, brand kits and bio pages can reference files too
        r = db.execute("SELECT 1 FROM library_items WHERE filename=? LIMIT 1", (fname,)).fetchone() or \
            db.execute("SELECT 1 FROM brand_kits WHERE logo=? LIMIT 1", (fname,)).fetchone() or \
            db.execute("SELECT 1 FROM bio_pages WHERE avatar=? LIMIT 1", (fname,)).fetchone()
    return r is not None


def _purge_calendar_files(db, row):
    files = set(_item_files(row)) | set(_jl(_rget(row, "variants"), {}).values())
    if _rget(row, "thumbnail"):
        files.add(row["thumbnail"])
    for f in files:
        if f and not _file_in_use(db, f, row["id"]):
            try:
                pth = os.path.join(UPLOAD_DIR, f)
                if os.path.exists(pth):
                    os.remove(pth)
            except Exception:
                pass
            _supabase_delete(f)
    if _rget(row, "drive_file_id") and not _rget(row, "recycled_from"):
        orow = db.execute("SELECT * FROM users WHERE id=?", (row["owner_id"],)).fetchone() if row["owner_id"] else None
        if orow:
            _drive_delete_file(dict(orow), row["drive_file_id"])


# ---- alerts: in-app + webhook + email --------------------------------------- #
def _smtp_cfg(db):
    return {"host": os.environ.get("SMTP_HOST") or get_setting(db, "smtp_host"),
            "port": int(os.environ.get("SMTP_PORT") or get_setting(db, "smtp_port") or 587),
            "user": os.environ.get("SMTP_USER") or get_setting(db, "smtp_user"),
            "password": os.environ.get("SMTP_PASS") or get_setting(db, "smtp_pass"),
            "sender": os.environ.get("SMTP_FROM") or get_setting(db, "smtp_from")}


def send_email(db, to, subject, body, attachments=None):
    """Send an email via the configured SMTP server. Returns (ok, message)."""
    import smtplib
    from email.message import EmailMessage
    cfg = _smtp_cfg(db)
    if not (cfg["host"] and to):
        return False, "Email isn't configured (SMTP host missing)."
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, (cfg["sender"] or cfg["user"] or "noreply@localhost"), to
    msg.set_content(body)
    for name, data, mime in (attachments or []):
        maj, _, mnr = mime.partition("/")
        msg.add_attachment(data, maintype=maj, subtype=mnr, filename=name)
    try:
        if cfg["port"] == 465:
            srv = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=30)
        else:
            srv = smtplib.SMTP(cfg["host"], cfg["port"], timeout=30)
            srv.ehlo()
            try:
                srv.starttls()
                srv.ehlo()
            except Exception:
                pass
        if cfg["user"]:
            srv.login(cfg["user"], cfg["password"] or "")
        srv.send_message(msg)
        srv.quit()
        return True, "Sent."
    except Exception as e:  # noqa
        return False, f"Email failed: {e}"


def _post_webhook(url, payload):
    def _go():
        try:
            data = dict(payload)
            data.setdefault("text", payload.get("message", ""))       # Slack / Discord / Teams friendly
            data.setdefault("content", payload.get("message", ""))
            req = urllib.request.Request(url, data=json.dumps(data).encode(), method="POST",
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=15).read()
        except Exception:
            pass
    threading.Thread(target=_go, daemon=True).start()


def send_alert(db, user_ids, title, message, link="", event="alert", payload=None):
    ids = recips(db, user_ids)
    add_notification(db, message, "alert", "system", link=link, recipients=ids)
    for uid in ids:
        hook = (uget_setting(db, uid, "alert_webhook") or "").strip()
        if hook.startswith("http"):
            _post_webhook(hook, dict(payload or {}, event=event, title=title, message=message))
        mail = (uget_setting(db, uid, "alert_email") or "").strip()
        if mail:
            threading.Thread(target=lambda m=mail: _bg_email(m, title, message), daemon=True).start()


def _bg_email(to, subject, body):
    try:
        db = db_connect()
        send_email(db, to, "[Social Platform] " + subject, body)
        db.close()
    except Exception:
        pass


# ---- sentiment (for inbox alerts) -------------------------------------------- #
_NEG_WORDS = {"hate", "worst", "terrible", "awful", "bad", "scam", "fake", "disgusting", "boring", "trash",
              "ugly", "stupid", "refund", "angry", "disappointed", "disappointing", "waste", "horrible",
              "useless", "spam", "fraud", "poor", "sucks", "broken", "liar", "lies", "unfollow", "cringe",
              "rude", "never again", "doesn't work", "not working", "rip off", "ripoff", "misleading"}
_POS_WORDS = {"love", "great", "awesome", "amazing", "best", "nice", "beautiful", "wow", "fire", "perfect",
              "incredible", "thanks", "thank you", "helpful", "cool", "brilliant", "excellent", "good",
              "fantastic", "superb", "saving", "following", "inspiring"}
_NEG_EMOJI = "😡🤬👎🤮😠💩😒🙄"
_POS_EMOJI = "❤😍🔥👏🙌💯😊🥰👍✨🤩"


def _sentiment(text):
    t = (text or "").lower()
    neg = sum(1 for w in _NEG_WORDS if w in t) + sum(t.count(e) for e in _NEG_EMOJI)
    pos = sum(1 for w in _POS_WORDS if w in t) + sum(t.count(e) for e in _POS_EMOJI)
    if neg > pos:
        return "negative"
    if pos > neg:
        return "positive"
    return "neutral"


def _ingest_comments(db, target, item_row, comments):
    """Store new platform comments in the unified inbox; alert on negative ones."""
    new = 0
    for c in comments:
        cid = str(c.get("id") or "")
        if not cid:
            continue
        if db.execute("SELECT 1 FROM inbox_comments WHERE platform=? AND remote_comment_id=?",
                      (target["platform"], cid)).fetchone():
            continue
        sent = _sentiment(c.get("text", ""))
        db.execute("INSERT INTO inbox_comments (item_id, target_id, platform, remote_comment_id, author, text, "
                   "likes, created_at, sentiment, status, parent_remote_id) VALUES (?,?,?,?,?,?,?,?,?, 'new', ?)",
                   (target["item_id"], target["id"], target["platform"], cid, c.get("author", ""),
                    c.get("text", ""), int(c.get("likes") or 0), c.get("created") or _now(), sent,
                    str(c.get("parent") or "")))
        new += 1
        if sent == "negative" and item_row is not None:
            send_alert(db, owner_and_admins(db, item_row["owner_id"]), "Negative comment",
                       f'⚠️ Negative comment on "{item_row["title"]}" ({P.PLATFORMS[target["platform"]]["label"]}) '
                       f'from {c.get("author", "someone")}: "{(c.get("text") or "")[:140]}"',
                       link="inbox:", event="negative_comment",
                       payload={"item_id": target["item_id"], "platform": target["platform"]})
    db.commit()
    return new


# ---- stats refresh + spike alerts -------------------------------------------- #
def _sim_stats(t):
    """Deterministic, growing demo numbers for SIMULATED posts (clearly labelled)."""
    seed = int(hashlib.sha1(f"{t['id']}-{t['platform']}".encode()).hexdigest(), 16)
    try:
        hours = max(0.0, (datetime.utcnow() - datetime.fromisoformat(t["published_at"])).total_seconds() / 3600)
    except Exception:
        hours = 0
    base = 40 + seed % 400
    growth = min(hours, 24 * 14)
    views = int(base + growth * (8 + seed % 30))
    likes = int(views * (0.03 + (seed % 7) / 100))
    return {"views": views, "likes": likes, "comments": int(likes * 0.12), "shares": int(likes * 0.06)}


def refresh_target_stats(db, t, pull_comments=True):
    t = dict(t)
    row = db.execute("SELECT * FROM calendar_items WHERE id=?", (t["item_id"],)).fetchone()
    if t.get("simulated") or not row:
        st = _sim_stats(t)
    else:
        acct = _publish_account(db, row, t["platform"])
        if not acct or acct.get("mode") != "live":
            return None
        try:
            acct = _ensure_fresh(db, acct)
        except Exception:
            return None
        st = P.stats(t["platform"], acct, t["remote_id"])
        if pull_comments:
            _ingest_comments(db, t, row, P.comments(t["platform"], acct, t["remote_id"]))
    prev = db.execute("SELECT * FROM stats_history WHERE target_id=? ORDER BY id DESC LIMIT 1", (t["id"],)).fetchone()
    db.execute("UPDATE post_targets SET views=?, likes=?, comments=?, shares=?, stats_at=? WHERE id=?",
               (st["views"], st["likes"], st["comments"], st["shares"], _now(), t["id"]))
    db.execute("INSERT INTO stats_history (target_id, captured_at, views, likes, comments, shares) VALUES (?,?,?,?,?,?)",
               (t["id"], _now(), st["views"], st["likes"], st["comments"], st["shares"]))
    db.commit()
    if prev and row is not None and not t.get("simulated"):
        dv = st["views"] - (prev["views"] or 0)
        dc = st["comments"] - (prev["comments"] or 0)
        if (dv >= 1000 and dv >= (prev["views"] or 0)) or dc >= 25:
            send_alert(db, owner_and_admins(db, row["owner_id"]), "Engagement spike",
                       f'📈 "{row["title"]}" is taking off on {P.PLATFORMS[t["platform"]]["label"]}: '
                       f'+{dv} views, +{dc} comments since the last check.',
                       link=f"published:{row['id']}", event="spike",
                       payload={"item_id": row["id"], "platform": t["platform"], "views_delta": dv})
    return st


def _refresh_all_stats(limit=40):
    """Posts from the last 3 days refresh every 10 minutes, older posts hourly."""
    try:
        db = db_connect()
        now = datetime.utcnow()
        recent = (now - timedelta(days=3)).isoformat()
        c10 = (now - timedelta(minutes=10)).isoformat()
        c60 = (now - timedelta(minutes=60)).isoformat()
        rows = db.execute(
            "SELECT * FROM post_targets WHERE status='published' AND ("
            " stats_at IS NULL OR (published_at>=? AND stats_at<?) OR stats_at<?) "
            "ORDER BY published_at DESC LIMIT ?", (recent, c10, c60, limit)).fetchall()
        for t in rows:
            try:
                refresh_target_stats(db, t)
            except Exception:
                pass
        db.close()
    except Exception:
        pass


def _check_token_health():
    """Refresh tokens that expire within 3 days; warn (once a day) when one can't be refreshed."""
    try:
        db = db_connect()
        soon = time.time() + 3 * 86400
        rows = db.execute("SELECT * FROM social_accounts WHERE mode='live' AND expires_at IS NOT NULL AND expires_at<?",
                          (soon,)).fetchall()
        for r in rows:
            a = _hydrate_account(db, r)
            label = P.PLATFORMS.get(a["platform"], {}).get("label", a["platform"])
            try:
                upd = P.refresh(a["platform"], a)
            except Exception as e:  # noqa
                upd, err = None, str(e)
            else:
                err = ""
            if upd:
                db.execute("UPDATE social_accounts SET token=?, refresh_token=?, expires_at=?, status='ok', "
                           "last_error='', updated_at=? WHERE id=?",
                           (enc(upd["token"]), enc(upd.get("refresh_token", a.get("refresh_token") or "")),
                            upd.get("expires_at"), _now(), a["id"]))
                db.commit()
                continue
            expired = float(a["expires_at"]) < time.time()
            db.execute("UPDATE social_accounts SET status=?, last_error=? WHERE id=?",
                       ("expired" if expired else "expiring", err, a["id"]))
            db.commit()
            last = a.get("warned_at") or ""
            if last[:10] != datetime.utcnow().strftime("%Y-%m-%d"):
                db.execute("UPDATE social_accounts SET warned_at=? WHERE id=?", (_now(), a["id"]))
                db.commit()
                when = "has expired" if expired else "expires in less than 3 days"
                send_alert(db, [a["user_id"]], f"{label} connection {('expired' if expired else 'expiring')}",
                           f"🔑 Your {label} connection ({a.get('account_name') or ''}) {when}. "
                           f"Reconnect it in Setup so scheduled posts don't fail.",
                           link="setup:", event="token_expiring", payload={"platform": a["platform"]})
        db.close()
    except Exception:
        pass


# ---- format checks + conversion ---------------------------------------------- #
def _ffprobe_bin():
    ff = _ffmpeg_bin()
    if ff and os.path.sep in ff:
        cand = os.path.join(os.path.dirname(ff), "ffprobe" + (".exe" if platform.system() == "Windows" else ""))
        if os.path.exists(cand):
            return cand
    return "ffprobe" if which("ffprobe") else None


def _probe(path):
    fp = _ffprobe_bin()
    info = {"size_mb": round(os.path.getsize(path) / 1048576, 1) if os.path.exists(path) else 0}
    if not fp or not os.path.exists(path):
        return info
    try:
        out = subprocess.run([fp, "-v", "error", "-select_streams", "v:0", "-show_entries",
                              "stream=width,height:format=duration", "-of", "json", path],
                             capture_output=True, timeout=40, text=True)
        d = json.loads(out.stdout or "{}")
        s = (d.get("streams") or [{}])[0]
        info.update(width=int(s.get("width") or 0), height=int(s.get("height") or 0),
                    duration=round(float((d.get("format") or {}).get("duration") or 0), 1))
    except Exception:
        pass
    return info


def _video_limit(platform, post_type):
    v = P.PLATFORMS[platform]["video"]
    if platform == "instagram" and post_type in ("reel", "post", "short"):
        return v.get("reel_max", v["max_duration"])
    if platform == "instagram" and post_type == "story":
        return 60
    if platform == "youtube" and post_type in ("short", "reel", "story"):
        return v.get("short_max", v["max_duration"])
    if platform == "facebook" and post_type in ("reel", "short"):
        return v.get("reel_max", v["max_duration"])
    if platform == "facebook" and post_type == "story":
        return 60
    return v["max_duration"]


def _wants_vertical(platform, post_type):
    return P.PLATFORMS[platform]["video"].get("aspect") == "9:16" or post_type in ("reel", "short", "story")


def format_checks(db, row):
    """Per-platform warnings for the item's media + captions."""
    out = []
    files = _item_files(row)
    kind = _item_kind(row)
    pt = row["content_type"] or "reel"
    variants = _jl(_rget(row, "variants"), {})
    info = None
    if kind == "video" and files:
        info = _probe(_local_upload(files[0]) or os.path.join(UPLOAD_DIR, files[0]))
    kit = kit_for_owner(db, row["owner_id"], _rget(row, "brand_id")) if row["owner_id"] else None
    for p in _item_platforms(row):
        spec, lab = P.PLATFORMS[p], P.PLATFORMS[p]["label"]

        def add(level, msg, fix=""):
            out.append({"platform": p, "level": level, "msg": msg, "fix": fix})

        if kind not in spec["supports"]:
            add("error", f"{lab} doesn't support {kind} posts — it will be skipped or fail.")
            continue
        if pt == "story" and "story" not in spec["supports"]:
            add("error", f"{lab} doesn't support Stories — choose Reel/Post for this platform.")
        if kind == "carousel" and len(files) > spec.get("carousel_max", 10):
            add("error", f"{lab} allows at most {spec.get('carousel_max', 10)} items in a carousel.")
        cap = _caption_for(row, p)
        bad = banned_words_in(cap, kit)
        if bad:
            add("error", f"Caption uses words your brand kit bans: {', '.join(bad)}.")
        if len(cap) > spec["caption_max"]:
            add("error", f"Caption is {len(cap)} characters; {lab} allows {spec['caption_max']}.", "adapt")
        ntags = len([w for w in cap.split() if w.startswith("#")])
        if ntags > spec["hashtag_max"]:
            add("warn", f"{ntags} hashtags — {lab} works best with {spec['hashtag_max']} or fewer.", "adapt")
        if spec.get("needs_public_url") and not _public_media_url(db, files[0] if files else ""):
            if kind != "text":
                add("warn", f"{lab} fetches media from a public HTTPS URL — set Public Base URL or Supabase "
                            "Storage before publishing live.")
        if kind == "video" and info and p not in variants:
            lim = _video_limit(p, pt)
            if info.get("duration") and info["duration"] > lim:
                add("error", f"Video is {info['duration']:.0f}s; {lab} {pt} allows up to {lim}s.", "convert")
            w, h = info.get("width") or 0, info.get("height") or 0
            if w and h and _wants_vertical(p, pt) and abs(w / h - 9 / 16) > 0.04:
                add("warn", f"Video is {w}×{h}; {lab} {pt}s look best at 9:16 (1080×1920).", "convert")
            if info.get("size_mb", 0) > spec["video"]["max_mb"]:
                add("error", f"File is {info['size_mb']} MB; {lab} allows {spec['video']['max_mb']} MB.", "convert")
        if p in variants:
            add("ok", f"Using a converted {lab} version ({variants[p]}).")
    if kind == "video" and not info:
        pass
    elif kind == "video" and info and not info.get("duration"):
        out.append({"platform": "", "level": "warn", "msg": "Install FFmpeg (Setup → Tools) to check video length "
                                                           "and size automatically.", "fix": ""})
    return out, info


CONVERT_JOBS = {}


def _convert_video(cid, platform_key, mode, user_id):
    key = f"{cid}:{platform_key}"
    tid = task_new("convert", f"Converting video for {P.PLATFORMS[platform_key]['label']}", str(user_id))
    CONVERT_JOBS[key] = {"status": "running", "message": "Converting…"}
    try:
        db = db_connect()
        row = db.execute("SELECT * FROM calendar_items WHERE id=?", (cid,)).fetchone()
        files = _item_files(row) if row else []
        ff = _ffmpeg_bin()
        if not (row and files and ff):
            raise RuntimeError("FFmpeg isn't installed (Setup → Tools)." if not ff else "No video to convert.")
        src = _local_upload(files[0]) or os.path.join(UPLOAD_DIR, files[0])
        pt = row["content_type"] or "reel"
        lim = _video_limit(platform_key, pt)
        out_name = f"{secrets.token_hex(4)}_{platform_key}.mp4"
        dst = os.path.join(UPLOAD_DIR, out_name)
        if _wants_vertical(platform_key, pt):
            if mode == "pad":
                vf = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black"
            else:
                vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
        else:
            vf = "scale='min(1920,iw)':-2"
        cmd = [ff, "-y", "-i", src, "-t", str(lim), "-vf", vf + ",format=yuv420p", "-c:v", "libx264",
               "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", dst]
        task_update(tid, percent=30, message="Encoding…")
        r = subprocess.run(cmd, capture_output=True, timeout=1800, text=True)
        if r.returncode != 0 or not os.path.exists(dst):
            raise RuntimeError("FFmpeg failed: " + (r.stderr or "")[-300:])
        if USE_SUPABASE_STORAGE:
            _supabase_upload_path(dst, out_name)
        row = db.execute("SELECT * FROM calendar_items WHERE id=?", (cid,)).fetchone()
        variants = _jl(_rget(row, "variants"), {})
        old = variants.get(platform_key)
        variants[platform_key] = out_name
        db.execute("UPDATE calendar_items SET variants=? WHERE id=?", (json.dumps(variants), cid))
        db.commit()
        if old and not _file_in_use(db, old, cid):
            try:
                os.remove(os.path.join(UPLOAD_DIR, old))
            except Exception:
                pass
        db.close()
        CONVERT_JOBS[key] = {"status": "done", "message": f"Converted for {P.PLATFORMS[platform_key]['label']}."}
        task_done(tid, ok=True, message="Converted.")
    except Exception as e:  # noqa
        CONVERT_JOBS[key] = {"status": "error", "message": str(e)}
        task_done(tid, ok=False, message=str(e))


# ---- AI: per-platform captions + reply suggestions ---------------------------- #
PLATFORM_STYLE = {
    "instagram": "engaging, emojis welcome, short line breaks, 8-15 relevant hashtags at the end",
    "facebook": "conversational and friendly, a question to invite comments, 1-3 hashtags",
    "youtube": "a video DESCRIPTION: hook in the first line, 2-3 informative sentences, 3-5 hashtags",
    "twitter": "punchy, at most 270 characters INCLUDING 1-2 hashtags",
    "linkedin": "professional, value-first, a short insight or takeaway, 3-5 hashtags",
    "threads": "casual and conversational, at most 480 characters, at most 1 hashtag",
    "tiktok": "short hook, playful, 3-6 hashtags including broad trending ones",
    "pinterest": "keyword-rich, descriptive, at most 480 characters, 2-5 hashtags",
}


def _rule_adapt(caption, hashtags, platform):
    tags = [t for t in (hashtags or "").split() if t.startswith("#")]
    spec = P.PLATFORMS[platform]
    n = min(spec["hashtag_max"], {"instagram": 15, "facebook": 3, "linkedin": 5, "twitter": 2,
                                  "threads": 1, "tiktok": 6, "pinterest": 5, "youtube": 5}[platform])
    tag_str = " ".join(tags[:n])
    body = (caption or "").strip()
    room = spec["caption_max"] - (len(tag_str) + 2 if tag_str else 0)
    if len(body) > room:
        body = P.split_text(body, max(20, room))
    return (body + ("\n\n" + tag_str if tag_str else "")).strip()


def adapt_captions(row, plats, kit=None):
    caption, hashtags = (row["caption"] or ""), (row["hashtags"] or "")
    if kit and (kit.get("default_hashtags") or "").strip():
        hashtags = " ".join(_merge_hashtags(kit["default_hashtags"], hashtags, cap=30))
    key, model = _claude_creds()
    result, source = {}, "rules"
    if key and (caption or hashtags):
        spec_lines = "\n".join(f'- "{p}": {PLATFORM_STYLE[p]} (hard limit {P.PLATFORMS[p]["caption_max"]} chars)'
                               for p in plats)
        prompt = (
            "You adapt one social media post for several platforms.\n"
            f"TITLE: {row['title']}\nMASTER CAPTION: {caption}\nHASHTAGS: {hashtags}\n"
            f"DESCRIPTION (use it for YouTube, Facebook, LinkedIn and Pinterest): {_rget(row, 'description') or 'none'}\n"
            f"GUIDELINES FROM THE ACCOUNT OWNER: {_content_guidelines_bg() or 'none'}\n"
            f"{kit_prompt(kit)}\n\n"
            f"Write one caption per platform, following each style note:\n{spec_lines}\n"
            + ('Also write "youtube_title": a click-worthy title under 90 characters.\n' if "youtube" in plats else "")
            + "Keep the facts of the master caption; never invent claims. "
              "Return STRICT JSON only, e.g. {\"instagram\": \"...\", \"twitter\": \"...\"}.")
        try:
            txt = _claude_generate(prompt, key, model)
            m = re.search(r"\{.*\}", txt, re.S)
            obj = json.loads(m.group(0) if m else txt)
            for p in plats:
                v = (obj.get(p) or "").strip()
                if v:
                    result[p] = P.split_text(v, P.PLATFORMS[p]["caption_max"])
            if obj.get("youtube_title"):
                result["_youtube_title"] = str(obj["youtube_title"])[:100]
            source = "ai"
        except Exception:
            result = {}
    for p in plats:
        if p not in result:
            result[p] = _rule_adapt(caption, hashtags, p)
    return result, source


def suggest_replies(comment_text, post_title, platform, kit=None):
    key, model = _claude_creds()
    sent = _sentiment(comment_text)
    if key:
        prompt = (f'You manage a brand\'s {P.PLATFORMS[platform]["label"]} account. A follower commented on the '
                  f'post "{post_title}":\n"{comment_text}"\n\n{kit_prompt(kit)}\nWrite 3 short, warm, on-brand reply options '
                  "(under 200 characters each, no hashtags). If the comment is negative, be empathetic and offer "
                  'help without arguing. Return STRICT JSON: {"replies": ["...", "...", "..."]}')
        try:
            txt = _claude_generate(prompt, key, model)
            m = re.search(r"\{.*\}", txt, re.S)
            reps = [str(x).strip() for x in json.loads(m.group(0) if m else txt).get("replies", []) if str(x).strip()]
            if reps:
                return reps[:3], "ai"
        except Exception:
            pass
    if sent == "negative":
        return (["We're really sorry to hear that — could you DM us the details so we can make it right?",
                 "Thanks for the honest feedback. We hear you and we're looking into it.",
                 "Sorry about your experience! Please message us and we'll help right away."], "templates")
    if sent == "positive":
        return (["Thank you so much! 🙌 Glad you enjoyed it!", "This made our day — thanks for the love! ❤️",
                 "Appreciate you! More coming soon 👀"], "templates")
    return (["Thanks for your comment! 😊", "Great question — we'll share more on this soon!",
             "Thanks for watching! Let us know what you'd like to see next."], "templates")


# ---- best time to post --------------------------------------------------------- #
# General guidance used until your own posts have enough data (dow: Mon=0).
DEFAULT_BEST = {
    "instagram": [(1, 11), (2, 11), (4, 10)], "facebook": [(1, 9), (2, 13), (3, 9)],
    "youtube": [(4, 15), (5, 10), (6, 11)], "twitter": [(1, 9), (2, 9), (3, 10)],
    "linkedin": [(1, 8), (2, 10), (3, 9)], "threads": [(1, 12), (3, 18), (4, 11)],
    "tiktok": [(1, 19), (3, 20), (4, 18)], "pinterest": [(4, 20), (5, 20), (6, 15)],
}


def _tzinfo(tz, offset_min):
    from datetime import timezone
    try:
        from zoneinfo import ZoneInfo
        if tz:
            return ZoneInfo(tz)
    except Exception:
        pass
    return timezone(timedelta(minutes=-int(offset_min or 0)))


def best_times(db, tz, offset, member_ids=None):
    zone = _tzinfo(tz, offset)
    out = {}
    q = ("SELECT t.platform, t.published_at, t.views, t.likes, t.comments, t.shares, t.simulated FROM post_targets t "
         "JOIN calendar_items c ON c.id=t.item_id WHERE t.status='published' AND t.published_at IS NOT NULL")
    args = []
    if member_ids is not None:
        q += f" AND c.owner_id IN ({','.join('?' * len(member_ids))})"
        args = member_ids
    rows = db.execute(q, args).fetchall()
    by = {}
    for r in rows:
        if r["simulated"]:
            continue
        try:
            from datetime import timezone
            dt = datetime.fromisoformat(r["published_at"]).replace(tzinfo=timezone.utc).astimezone(zone)
        except Exception:
            continue
        eng = (r["likes"] or 0) + 2 * (r["comments"] or 0) + 3 * (r["shares"] or 0) + (r["views"] or 0) / 100.0
        by.setdefault(r["platform"], {}).setdefault((dt.weekday(), dt.hour), []).append(eng)
    for p in SOCIAL:
        slots = by.get(p, {})
        if sum(len(v) for v in slots.values()) >= 5:
            ranked = sorted(slots.items(), key=lambda kv: -(sum(kv[1]) / len(kv[1])))[:3]
            out[p] = [{"dow": d, "hour": h, "score": round(sum(v) / len(v), 1), "source": "your data"}
                      for (d, h), v in ranked]
        else:
            out[p] = [{"dow": d, "hour": h, "score": None, "source": "general guidance"} for d, h in DEFAULT_BEST[p]]
    return out


def _next_queue_slot(db, owner_id, tz, offset, brand_id=None):
    """Next free weekly slot (local time) → (local_date, 'HH:MM', utc_iso)."""
    from datetime import timezone
    # (brand filter built in Python — Postgres can't type an untyped "? IS NULL" parameter)
    if brand_id:
        slots = db.execute("SELECT * FROM queue_slots WHERE owner_id=? AND (brand_id IS NULL OR brand_id=?) "
                           "ORDER BY dow, time", (owner_id, brand_id)).fetchall()
    else:
        slots = db.execute("SELECT * FROM queue_slots WHERE owner_id=? ORDER BY dow, time", (owner_id,)).fetchall()
    if not slots:
        return None
    zone = _tzinfo(tz, offset)
    members = [owner_id] + [r["id"] for r in db.execute("SELECT id FROM users WHERE parent_id=?", (owner_id,)).fetchall()]
    taken = {r["publish_at"][:16] for r in db.execute(
        "SELECT publish_at FROM calendar_items WHERE publish_at IS NOT NULL AND state<>'published' "
        f"AND owner_id IN ({','.join('?' * len(members))})", members).fetchall()
        if r["publish_at"]}
    now_local = datetime.now(zone)
    for day in range(0, 70):
        d = (now_local + timedelta(days=day)).date()
        for s in slots:
            if s["dow"] != d.weekday():
                continue
            try:
                hh, mm = [int(x) for x in s["time"].split(":")]
            except Exception:
                continue
            local = datetime(d.year, d.month, d.day, hh, mm, tzinfo=zone)
            if local <= now_local + timedelta(minutes=5):
                continue
            utc = local.astimezone(timezone.utc).replace(tzinfo=None).isoformat()
            if utc[:16] in taken:
                continue
            return d.isoformat(), f"{hh:02d}:{mm:02d}", utc
    return None


def _apply_queue(db, row, u, tz, offset):
    slot = _next_queue_slot(db, billing_user_id(u) or u["id"], tz, offset, _rget(row, "brand_id"))
    if not slot:
        return None
    d, t, utc = slot
    db.execute("UPDATE calendar_items SET date=?, publish_time=?, publish_at=?, tz=?, auto_publish=1 WHERE id=?",
               (d, t, utc, tz or "", row["id"]))
    if row["approved"]:
        db.execute("UPDATE calendar_items SET state='scheduled', publish_state='scheduled' WHERE id=?", (row["id"],))
    db.commit()
    return slot


# ---- analytics ------------------------------------------------------------------ #
def analytics_data(db, days=30, brand_id=None, platform=None, member_ids=None, start=None, end=None):
    """member_ids=None → every workspace (SuperAdmin); else only those owners' posts.
    start/end (ISO dates) override `days` for calendar-month reports."""
    since = start or (datetime.utcnow() - timedelta(days=days)).isoformat()
    q = ("SELECT t.*, c.title, c.brand_id, c.content_type, c.media_kind FROM post_targets t "
         "JOIN calendar_items c ON c.id=t.item_id WHERE t.status='published' AND t.published_at>=?")
    args = [since]
    if end:
        q += " AND t.published_at<?"
        args.append(end)
    if member_ids is not None:
        q += f" AND c.owner_id IN ({','.join('?' * len(member_ids))})"
        args += member_ids
    if brand_id:
        q += " AND c.brand_id=?"
        args.append(brand_id)
    if platform:
        q += " AND t.platform=?"
        args.append(platform)
    rows = [dict(r) for r in db.execute(q, args).fetchall()]
    totals, series, items = {}, {}, {}
    for r in rows:
        p = r["platform"]
        tt = totals.setdefault(p, {"platform": p, "label": P.PLATFORMS[p]["label"], "posts": 0, "views": 0,
                                   "likes": 0, "comments": 0, "shares": 0, "simulated": 0})
        tt["posts"] += 1
        for k in ("views", "likes", "comments", "shares"):
            tt[k] += r[k] or 0
        tt["simulated"] += 1 if r["simulated"] else 0
        day = (r["published_at"] or "")[:10]
        s = series.setdefault(day, {"date": day, "views": 0, "engagement": 0, "posts": 0})
        s["views"] += r["views"] or 0
        s["engagement"] += (r["likes"] or 0) + (r["comments"] or 0) + (r["shares"] or 0)
        s["posts"] += 1
        it = items.setdefault(r["item_id"], {"item_id": r["item_id"], "title": r["title"], "platforms": {},
                                             "views": 0, "engagement": 0, "simulated": False})
        it["platforms"][p] = {k: r[k] or 0 for k in ("views", "likes", "comments", "shares")}
        it["platforms"][p]["permalink"] = r["permalink"] or ""
        it["views"] += r["views"] or 0
        it["engagement"] += (r["likes"] or 0) + (r["comments"] or 0) + (r["shares"] or 0)
        it["simulated"] = it["simulated"] or bool(r["simulated"])
    for tt in totals.values():
        eng = tt["likes"] + tt["comments"] + tt["shares"]
        tt["engagement"] = eng
        tt["engagement_rate"] = round(100.0 * eng / tt["views"], 2) if tt["views"] else 0
    # fill missing days so the chart has a continuous axis
    out_series = []
    start = datetime.utcnow().date() - timedelta(days=days - 1)
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        out_series.append(series.get(d, {"date": d, "views": 0, "engagement": 0, "posts": 0}))
    compare = []
    for it in items.values():
        if len(it["platforms"]) > 1:
            best = max(it["platforms"].items(), key=lambda kv: kv[1]["views"] + 10 * (kv[1]["likes"] + kv[1]["comments"]))
            it["best"] = best[0]
            compare.append(it)
    top = sorted(items.values(), key=lambda x: -(x["engagement"] * 10 + x["views"]))[:10]
    sim = sum(1 for r in rows if r["simulated"])
    return {"days": days, "totals": sorted(totals.values(), key=lambda x: SOCIAL.index(x["platform"])),
            "series": out_series, "top": top, "compare": compare[:20],
            "post_count": len(rows), "simulated_count": sim,
            "sum": {k: sum(t[k] for t in totals.values()) for k in ("views", "likes", "comments", "shares", "posts")}}


def build_report_pdf(data, title):
    from fpdf import FPDF
    reg = os.path.join(_FONT_DIR, "DejaVuSans.ttf")
    bold = os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf")
    pdf = FPDF(format="A4")
    font = "Helvetica"
    if os.path.exists(reg) and os.path.exists(bold):
        try:
            pdf.add_font("DejaVu", "", reg)
            pdf.add_font("DejaVu", "B", bold)
            font = "DejaVu"
        except Exception:
            font = "Helvetica"
    cps = _font_codepoints(reg) if font == "DejaVu" else set()

    def s(t):
        t = str(t if t is not None else "")
        if font != "DejaVu":
            return t.encode("latin-1", "replace").decode("latin-1")
        return "".join(ch for ch in t if ch in " \n" or ord(ch) in cps) if cps else t

    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    pdf.set_font(font, "B", 18)
    pdf.cell(0, 10, s(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(font, "", 10)
    pdf.cell(0, 6, s(f"Last {data['days']} days · generated {datetime.now().strftime('%Y-%m-%d %H:%M')}"),
             new_x="LMARGIN", new_y="NEXT")
    if data.get("simulated_count"):
        pdf.cell(0, 6, s(f"Note: {data['simulated_count']} of {data['post_count']} posts were simulated "
                         "(demo numbers, not real platform data)."), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    sm = data["sum"]
    pdf.set_font(font, "B", 12)
    pdf.cell(0, 8, s(f"Posts {sm['posts']}   Views {sm['views']:,}   Likes {sm['likes']:,}   "
                     f"Comments {sm['comments']:,}   Shares {sm['shares']:,}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    cols = [("Platform", 42), ("Posts", 20), ("Views", 28), ("Likes", 25), ("Comments", 27), ("Shares", 23), ("Eng. %", 20)]
    pdf.set_font(font, "B", 10)
    for name, w in cols:
        pdf.cell(w, 8, s(name), border=1)
    pdf.ln()
    pdf.set_font(font, "", 10)
    for t in data["totals"]:
        vals = [t["label"], t["posts"], f"{t['views']:,}", f"{t['likes']:,}", f"{t['comments']:,}",
                f"{t['shares']:,}", t["engagement_rate"]]
        for (name, w), v in zip(cols, vals):
            pdf.cell(w, 7, s(v), border=1)
        pdf.ln()
    pdf.ln(5)
    pdf.set_font(font, "B", 12)
    pdf.cell(0, 8, s("Top posts"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(font, "", 10)
    for i, it in enumerate(data["top"], 1):
        plats = ", ".join(P.PLATFORMS[p]["label"] for p in it["platforms"])
        line = f"{i}. {it['title'][:60]}  —  {it['views']:,} views, {it['engagement']:,} engagements ({plats})"
        try:
            pdf.multi_cell(0, 6, s(line))
        except Exception:
            pass
    return BytesIO(bytes(pdf.output()))


def _weekly_reports():
    """Monday 09:00 (server time): email each user's weekly PDF if they opted in."""
    try:
        now = datetime.now()
        if now.weekday() != 0 or now.hour < 9:
            return
        db = db_connect()
        if not _smtp_cfg(db)["host"]:
            db.close()
            return
        week = now.strftime("%G-W%V")
        for r in db.execute("SELECT key, value FROM settings WHERE key LIKE 'u%_report_email'").fetchall():
            to = (r["value"] or "").strip()
            m = re.match(r"u(\d+)_report_email", r["key"])
            if not (to and m):
                continue
            uid = int(m.group(1))
            if uget_setting(db, uid, "report_sent_week") == week:
                continue
            urow = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if not urow:
                continue
            data = analytics_data(db, 7, member_ids=ws_member_ids(db, dict(urow)))
            pdf = build_report_pdf(data, "Weekly social report").getvalue()
            ok, _ = send_email(db, to, "Your weekly social media report",
                               f"Attached: performance for the last 7 days — {data['sum']['posts']} posts, "
                               f"{data['sum']['views']:,} views.", [("weekly-report.pdf", pdf, "application/pdf")])
            if ok:
                uset_setting(db, uid, "report_sent_week", week)
        db.close()
    except Exception:
        pass


@app.route("/api/calendar/<int:cid>/publish", methods=["POST"])
def api_calendar_publish(cid):
    """Publish now on the selected platforms (queued; progress shows per platform)."""
    u = require_login()
    db = get_db()
    row = db.execute("SELECT * FROM calendar_items WHERE id=?", (cid,)).fetchone()
    if not row:
        return jsonify({"error": "Not found."}), 404
    if not row["approved"]:
        return jsonify({"error": "This post must be approved before publishing."}), 400
    d = request.get_json(silent=True) or {}
    ct = (d.get("content_type") or row["content_type"] or "reel").lower()
    if ct not in ("reel", "post", "story", "short"):
        return jsonify({"error": "Choose a post type: Reel, Post, Story or Short."}), 400
    plats = [x for x in (d.get("platforms") or []) if x in SOCIAL] or None
    if plats:
        db.execute("UPDATE calendar_items SET platforms=? WHERE id=?", (json.dumps(plats), cid))
        db.commit()
        row = db.execute("SELECT * FROM calendar_items WHERE id=?", (cid,)).fetchone()
    try:
        n = enqueue_publish(db, row, u, plats, ct)
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not n:
        return jsonify({"ok": True, "publishing": False,
                        "message": "Already published (or in progress) on the selected platforms."})
    log_activity(db, u, "publish_now", "item", cid, f"{row['title']} → {', '.join(plats or _item_platforms(row))}")
    return jsonify({"ok": True, "publishing": True,
                    "message": f"Publishing to {n} platform(s)… progress shows on the post."})


@app.route("/api/calendar/<int:cid>/replace", methods=["POST"])
def api_calendar_replace(cid):
    """Replace / change the video for a scheduled item before it's published."""
    u = require_login()
    db = get_db()
    row = db.execute("SELECT * FROM calendar_items WHERE id=?", (cid,)).fetchone()
    if not row:
        return jsonify({"error": "Not found."}), 404
    if row["state"] == "published":
        return jsonify({"error": "This video is already published and can't be replaced."}), 400
    f = request.files.get("file") or (request.files.getlist("files") or [None])[0]
    if not f:
        return jsonify({"error": "Attach a replacement video."}), 400
    # remove the old backing files (unless a recycled copy still uses them)
    try:
        _purge_calendar_files(db, row)
    except Exception:
        pass
    fname = _safe_save(f)
    db.execute("UPDATE calendar_items SET filename=?, media=NULL, media_kind=?, variants=NULL, "
               "drive_file_id=NULL, drive_link=NULL, ig_media_id=NULL, ig_permalink=NULL, "
               "publish_state='scheduled', publish_pct=0 WHERE id=?",
               (fname, _media_kind_for([fname]), cid))
    db.commit()
    gu = _google_user_for(db, u)
    if fname and gu:
        _start_drive_upload_task(gu["id"], cid, os.path.join(UPLOAD_DIR, fname),
                                 f.filename or "video", table="calendar_items")
    add_notification(db, f'🔁 Video replaced for "{row["title"]}" ({row["date"]}) by {u["username"]}.',
                     "upload", u["username"], recipients=owner_and_admins(db, row["owner_id"]))
    return jsonify({"ok": True, "filename": fname})


# --------------------------------------------------------------------------- #
#  API : Published panel + Instagram comment / like tracking
# --------------------------------------------------------------------------- #
@app.route("/api/published")
def api_published():
    require_login()
    db = get_db()
    u = current_user()
    brand = _rget(u, "active_brand_id") if u else None
    wq, wa = ws_sql(db, u)
    rows = db.execute("SELECT * FROM calendar_items WHERE state='published'" + wq +
                      " ORDER BY published_date DESC, id DESC", wa).fetchall()
    if brand:
        rows = [r for r in rows if r["brand_id"] == brand]
    targets = _targets_for(db, [r["id"] for r in rows])
    out = []
    for r in rows:
        comments = db.execute(
            "SELECT commenter, text, like_count, created_at FROM ig_comments "
            "WHERE item_id=? ORDER BY id DESC", (r["id"],)).fetchall()
        d = dict(r)
        d["comments"] = [dict(c) for c in comments]
        d["comment_count"] = len(comments)
        d["targets"] = targets.get(r["id"], [])
        d["media"] = _item_files(r)
        d["media_kind"] = _item_kind(r)
        d["inbox"] = [dict(c) for c in db.execute(
            "SELECT platform, author, text, likes, sentiment, created_at FROM inbox_comments WHERE item_id=? "
            "ORDER BY id DESC LIMIT 30", (r["id"],)).fetchall()]
        out.append(d)
    return jsonify({"published": out})


def _record_comment(db, item_id, title, commenter, text, like_count, ig_comment_id=""):
    db.execute("INSERT INTO ig_comments (item_id, ig_comment_id, commenter, text, "
               "like_count, created_at) VALUES (?,?,?,?,?,?)",
               (item_id, ig_comment_id, commenter, text, like_count,
                datetime.utcnow().isoformat()))
    orow = db.execute("SELECT owner_id FROM calendar_items WHERE id=?", (item_id,)).fetchone()
    owner_id = orow["owner_id"] if orow else None
    add_notification(db, f'💬 {commenter} commented on "{title}": "{text}" '
                         f'({like_count} likes)', "comment", commenter,
                     link=f"published:{item_id}",
                     recipients=owner_and_admins(db, owner_id))
    db.commit()


def _ig_creds_for_item(db, row):
    """Resolve the Instagram token+user for a published item: the ORIGINAL
    owner's connected account first, else the app-level settings."""
    a = _publish_account(db, row, "instagram")
    if a:
        return a["token"], a.get("account_id") or ""
    return "", ""


@app.route("/api/published/<int:cid>/refresh", methods=["POST"])
def api_published_refresh(cid):
    """Pull latest like count + comment count + new comments from Instagram
    (real Graph API), using the account that actually published the post."""
    require_login()
    db = get_db()
    row = db.execute("SELECT * FROM calendar_items WHERE id=?", (cid,)).fetchone()
    if not row:
        return jsonify({"error": "Not found."}), 404
    token, _ = _ig_creds_for_item(db, row)
    media = row["ig_media_id"]
    if not (token and media):
        return jsonify({"ok": False, "message": "This post isn't linked to a live "
                        "Instagram post yet (publish it to Instagram first)."})
    base = IG_GRAPH_BASE

    # 1) Live like + comment COUNTS (media node fields).
    try:
        q = urllib.parse.urlencode({"fields": "like_count,comments_count", "access_token": token})
        with urllib.request.urlopen(f"{base}/{media}?{q}", timeout=30) as r:
            info = json.loads(r.read().decode())
        db.execute("UPDATE calendar_items SET ig_like_count=?, ig_comments_count=? WHERE id=?",
                   (int(info.get("like_count", 0)), int(info.get("comments_count", 0)), cid))
        db.commit()
    except urllib.error.HTTPError as e:  # noqa
        try: body = e.read().decode("utf-8", "replace")[:300]
        except Exception: body = ""
        return jsonify({"ok": False, "message": f"Instagram fetch failed: {e} {body}"}), 502
    except Exception as e:  # noqa
        return jsonify({"ok": False, "message": f"Instagram fetch failed: {e}"}), 502

    # 2) Individual comments (text + author). Needs the manage_comments
    #    permission — if the connected token doesn't have it, keep the counts
    #    and just skip the text rather than failing the whole refresh.
    new_comments = 0
    try:
        q = urllib.parse.urlencode({"fields": "id,username,text,like_count",
                                    "access_token": token})
        with urllib.request.urlopen(f"{base}/{media}/comments?{q}", timeout=30) as r:
            data = json.loads(r.read().decode("utf-8", "replace")).get("data", [])
        for c in data:
            cid_ig = str(c.get("id"))
            exists = db.execute("SELECT 1 FROM ig_comments WHERE ig_comment_id=?", (cid_ig,)).fetchone()
            if not exists:
                _record_comment(db, cid, row["title"], c.get("username", "someone"),
                                c.get("text", ""), int(c.get("like_count", 0)), cid_ig)
                new_comments += 1
        db.commit()
    except urllib.error.HTTPError as e:  # noqa
        try: body = e.read().decode("utf-8", "replace")[:400]
        except Exception: body = ""
        try: app.logger.warning(f"IG comments fetch failed for media {media}: {e} :: {body}")
        except Exception: pass
    except Exception as e:  # noqa
        try: app.logger.warning(f"IG comments fetch error for media {media}: {e}")
        except Exception: pass
    return jsonify({"ok": True, "new_comments": new_comments})


@app.route("/api/published/<int:cid>/simulate-comment", methods=["POST"])
def api_published_simulate(cid):
    """Add a fake IG comment + a like, for testing the notification/popup flow."""
    require_login()
    db = get_db()
    row = db.execute("SELECT * FROM calendar_items WHERE id=?", (cid,)).fetchone()
    if not row:
        return jsonify({"error": "Not found."}), 404
    n = db.execute("SELECT COUNT(*) FROM ig_comments").fetchone()[0]
    samples = [
        ("neha_shots", "This is 🔥🔥 saving it!", 12),
        ("arjun.edits", "How did you make this? Tutorial please 🙏", 5),
        ("the_realtor_life", "Incredible work, sharing to my story!", 23),
        ("mumbai_maker", "Desi jugaad at its best 😍", 8),
        ("content.daily", "Went viral for a reason. Following!", 41),
    ]
    commenter, text, likes = samples[n % len(samples)]
    _record_comment(db, cid, row["title"], commenter, text, likes)
    # bump the post's total like count too
    db.execute("UPDATE calendar_items SET ig_like_count=COALESCE(ig_like_count,0)+? WHERE id=?",
               (likes + 3, cid))
    db.commit()
    return jsonify({"ok": True, "commenter": commenter, "text": text, "like_count": likes})


@app.route("/api/settings/instagram", methods=["GET", "POST"])
def api_ig_settings():
    require_super()
    db = get_db()
    if request.method == "POST":
        d = request.get_json(force=True)
        for k in ("ig_token", "ig_user_id", "public_base_url"):
            if k in d:
                set_setting(db, k, (d.get(k) or "").strip())
        return jsonify({"ok": True})
    # GET — never return the raw token, just whether it's set
    return jsonify({
        "ig_user_id": get_setting(db, "ig_user_id"),
        "public_base_url": get_setting(db, "public_base_url"),
        "token_set": bool(get_setting(db, "ig_token")),
    })


@app.route("/api/settings/model", methods=["GET", "POST"])
def api_model_setting():
    """Get/set the ollama vision model used for video analysis."""
    u = require_login()
    db = get_db()
    if request.method == "POST":
        if not is_super(u):
            return jsonify({"error": "Only the SuperAdmin can change the AI model."}), 403
        d = request.get_json(force=True)
        set_setting(db, "ollama_model", (d.get("model") or "").strip())
        return jsonify({"ok": True})
    return jsonify({"model": get_setting(db, "ollama_model") or OLLAMA_MODEL,
                    "default": OLLAMA_MODEL})


# --------------------------------------------------------------------------- #
#  API : Content Writing  (title -> full content via Ollama OR Claude API)
# --------------------------------------------------------------------------- #
DEFAULT_CLAUDE_MODEL = "claude-opus-5"


def _content_prompt(title, guidelines=""):
    base = (
        f'Write complete, well-structured, engaging content for the title: "{title}".\n'
        "Include a strong hook/introduction, a clear body organised into a few short "
        "sections with subheadings, and a concise conclusion with a call to action. "
        "Write in a warm, professional voice. Use Markdown formatting."
    )
    if (guidelines or "").strip():
        base += ("\n\nFollow these content-writing guidelines strictly (they override "
                 "the defaults where they conflict):\n" + guidelines.strip())
    return base


def _ollama_text(prompt, model):
    """Generate text with a local Ollama model."""
    payload = {"model": model, "prompt": prompt, "stream": False}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(OLLAMA_URL + "/api/generate", data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=240) as r:
        return json.loads(r.read().decode()).get("response", "").strip()


# --------------------------------------------------------------------------- #
#  AI providers (V35): Anthropic Claude, Google Gemini, Groq and OpenRouter.
#  The SuperAdmin picks one in Setup; every AI feature (content writing,
#  video captions, per-platform captions, reply suggestions, hashtags) uses it.
#  Each provider keeps its own key (encrypted: *_api_key) and model.
# --------------------------------------------------------------------------- #
AI_PROVIDERS = {
    "claude":     {"label": "Anthropic Claude", "default": DEFAULT_CLAUDE_MODEL, "env": "CLAUDE_API_KEY"},
    "gemini":     {"label": "Google Gemini", "default": "gemini-2.5-flash", "env": "GEMINI_API_KEY"},
    "groq":       {"label": "Groq", "default": "llama-3.3-70b-versatile", "env": "GROQ_API_KEY"},
    "openrouter": {"label": "OpenRouter", "default": "a free model", "env": "OPENROUTER_API_KEY"},
}
# When no model is set, pick one the key can actually use (free models come and go).
AI_MODEL_PREFS = {
    "gemini":     [r"^gemini-[\d.]+-flash$", r"^gemini-[\d.]+-flash", r"^gemini"],
    "groq":       [r"llama-3\.3-70b-versatile", r"gpt-oss-120b", r"llama", r"qwen"],
    "openrouter": [r"llama.*:free$", r"qwen.*:free$", r"gemma.*:free$", r"deepseek.*:free$", r"mistral.*:free$", r":free$"],
}
_AI_MODEL_CACHE = {}
AI_UA = "SocialPlatform/1.0"


class _AIKey(str):
    """An API key that remembers which provider it belongs to, so the many
    (key, model) call sites keep working whatever provider is chosen."""
    provider = "claude"


def _ai_key(value, provider):
    k = _AIKey(value or "")
    k.provider = provider
    return k


def ai_provider_of(db):
    p = (get_setting(db, "ai_provider") or "claude").strip()
    return p if p in AI_PROVIDERS else "claude"


def ai_creds(db, provider=None):
    """(key, model) for the chosen provider (or the one given)."""
    p = provider if provider in AI_PROVIDERS else ai_provider_of(db)
    key = get_setting(db, f"{p}_api_key") or os.environ.get(AI_PROVIDERS[p]["env"], "").strip()
    model = get_setting(db, f"{p}_model") or ""        # blank = pick automatically (_auto_model)
    return _ai_key(key, p), model


def _ai_error_text(e):
    try:
        raw = e.read().decode("utf-8", "replace")
    except Exception:
        return str(e)
    try:
        j = json.loads(raw)
        if isinstance(j, list) and j:
            j = j[0]
        err = j.get("error") if isinstance(j, dict) else None
        if isinstance(err, dict) and err.get("message"):
            msg = str(err["message"])
            meta = err.get("metadata") if isinstance(err.get("metadata"), dict) else {}
            detail = str(meta.get("raw") or "").strip()
            if detail and detail not in msg:
                msg += f" — {meta.get('provider_name') + ': ' if meta.get('provider_name') else ''}{detail}"
            return msg[:400]
        if isinstance(err, str):
            return err[:400]
    except Exception:
        pass
    return raw[:400]


def _ai_request(url, headers, payload=None, timeout=300):
    hdrs = {"User-Agent": AI_UA, "Accept": "application/json"}
    hdrs.update(headers)
    data = None
    if payload is not None:
        hdrs["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {_ai_error_text(e)}") from None


_AI_LIST_CACHE = {}


def _cached_models(p, key):
    """_list_ai_models, cached for 6 hours (None when the list can't be fetched)."""
    hit = _AI_LIST_CACHE.get(p)
    if hit and time.time() - hit[0] < 6 * 3600:
        return hit[1]
    try:
        models = _list_ai_models(p, key)
    except Exception:
        return None
    _AI_LIST_CACHE[p] = (time.time(), models)
    return models


def _model_sees(p, key, model):
    """True / False when the provider's list says whether `model` reads images, else None."""
    for m in (_cached_models(p, key) or []):
        if m["id"] == model:
            return bool(m["vision"])
    return None


NO_VISION_HELP = ("Pick a model marked “reads images” (Setup → AI provider → Load models), clear the Model box "
                  "to choose one automatically, or switch to Google Gemini, which can watch the whole video.")


def _chat_request(provider, key, url, hdr, body, see):
    """Send an OpenAI-style chat request with the recoveries users actually hit:
    a text-only model given images (switch to one that reads images), low OpenRouter
    credit on a paid model (shorter reply), and busy free models (clear advice)."""
    switched, busy_switches = False, 0
    tried = {body.get("model")} | set(body.get("models") or [])
    for _ in range(9):
        try:
            return _ai_request(url, hdr, body)
        except RuntimeError as e:
            msg = str(e)
            if msg.startswith("HTTP 429") and busy_switches < 5:
                # rate-limited: switch to other models (that read images, for video analysis)
                alts = [m for m in _ranked_models(provider, key, vision=see) if m not in tried
                        and not (provider == "openrouter" and m == AI_PROVIDERS[provider]["default"])]
                if alts:
                    busy_switches += 1
                    body["model"] = alts[0]
                    if provider == "openrouter":
                        body["models"] = alts[:3]
                        tried.update(alts[:3])
                    else:
                        tried.add(alts[0])
                    continue
            if see and not switched and re.match(r"HTTP (400|404)", msg) and re.search(r"image|vision|multimodal", msg, re.I):
                switched = True
                vis = [m for m in _auto_models(provider, key, vision=True)       # ("a free model" is a label, not an id)
                       if m != body.get("model") and not (provider == "openrouter" and m == AI_PROVIDERS[provider]["default"])]
                if vis:
                    body["model"] = vis[0]
                    if provider == "openrouter":
                        body["models"] = vis[:3]
                    continue
                raise RuntimeError(f"{msg}. The chosen model can't read images. {NO_VISION_HELP}") from None
            if see and switched and re.match(r"HTTP (400|404)", msg) and re.search(r"image|vision|multimodal", msg, re.I):
                raise RuntimeError(f"{msg}. No model that reads images answered. {NO_VISION_HELP}") from None
            afford = re.search(r"can only afford (\d+)", msg)
            if provider == "openrouter" and msg.startswith("HTTP 402"):
                # low credit on a paid model: retry with a reply short enough to afford
                if afford and int(afford.group(1)) >= 400 and body.get("max_tokens", 0) > int(afford.group(1)) - 50:
                    body["max_tokens"] = int(afford.group(1)) - 50
                    continue
                raise RuntimeError(f"{msg}. “{body.get('model')}” is a paid model and your OpenRouter credit is too low. "
                                   "Clear the Model box (automatic free models) or pick one ending in “:free”, "
                                   "or add credit on OpenRouter.") from None
            if provider == "openrouter" and msg.startswith("HTTP 429"):
                raise RuntimeError(f"{msg}. All {len(tried)} free models tried were busy. Wait a minute and try again, "
                                   "or use Google Gemini (its free limit is your own). Accounts without credit also get "
                                   "only a small number of free requests per day.") from None
            if provider == "groq" and msg.startswith("HTTP 429"):
                raise RuntimeError(f"{msg}. Groq's free plan has per-minute and per-day limits — wait and try again.") from None
            raise
    raise RuntimeError("The AI request kept failing — please try again in a minute.")


def _ai_complete(provider, key, model, text, images=(), max_tokens=None, video=None):
    """One prompt (plus optional JPEG frames) -> reply text, for any provider.
    `video` = (bytes, mime) sends the whole video, which only Gemini accepts."""
    import base64
    imgs = [base64.b64encode(f).decode() for f in images]
    auto = not (model or "").strip()
    see = bool(imgs or video)
    model = (model or _auto_model(provider, key, vision=see)).strip()
    if provider == "gemini":
        name = model.split("/", 1)[1] if model.startswith("models/") else model
        parts = [{"inline_data": {"mime_type": "image/jpeg", "data": b}} for b in imgs] + [{"text": text}]
        if video:
            parts.insert(0, {"inline_data": {"mime_type": video[1], "data": base64.b64encode(video[0]).decode()}})
        payload = {"contents": [{"role": "user", "parts": parts}],
                   "generationConfig": {"maxOutputTokens": max_tokens or 8192}}
        names, tried = [name], {name}
        while True:
            try:
                resp = _ai_request("https://generativelanguage.googleapis.com/v1beta/models/"
                                   f"{urllib.parse.quote(names[-1], safe='-._')}:generateContent",
                                   {"x-goog-api-key": key}, payload)
                break
            except RuntimeError as e:
                if not str(e).startswith("HTTP 429"):
                    raise
                alts = [m for m in _ranked_models("gemini", key) if m not in tried]
                if len(names) >= 4 or not alts:
                    raise RuntimeError(f"{e}. Gemini's free limit is used up on {len(names)} model(s) — "
                                       "wait a little (limits reset every minute and every day).") from None
                names.append(alts[0])
                tried.add(alts[0])
        cands = resp.get("candidates") or []
        if not cands:
            why = (resp.get("promptFeedback") or {}).get("blockReason")
            raise RuntimeError("Gemini returned no answer" + (f" (blocked: {why})" if why else "") + ".")
        out = "".join(p.get("text", "") for p in (cands[0].get("content") or {}).get("parts", [])
                      if not p.get("thought"))
    elif provider in ("groq", "openrouter"):
        content = text if not imgs else (
            [{"type": "text", "text": text}] +
            [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b}} for b in imgs])
        if see and not auto and _model_sees(provider, key, model) is False:
            model, auto = _auto_model(provider, key, vision=True), True   # the chosen model is text-only
        if provider == "openrouter" and model == AI_PROVIDERS["openrouter"]["default"]:   # label, not a model id
            raise RuntimeError("OpenRouter has no free model " + ("that reads images " if see else "") +
                               "available right now. " + (NO_VISION_HELP if see else "Pick a model in Setup → AI provider."))
        body = {"model": model, "messages": [{"role": "user", "content": content}]}
        if provider == "groq":
            url, hdr = "https://api.groq.com/openai/v1/chat/completions", {}
            body["max_completion_tokens"] = max_tokens or 8000
        else:
            url = "https://openrouter.ai/api/v1/chat/completions"
            hdr = {"HTTP-Referer": os.environ.get("RENDER_EXTERNAL_URL") or "https://github.com/Gowtham-KR6672/SocialPlatform",
                   "X-Title": os.environ.get("COMPANY_NAME") or "SocialPlatform"}
            body["max_tokens"] = max_tokens or 8000
            if auto:                      # free models are often busy: let OpenRouter fall back
                body["models"] = _auto_models("openrouter", key, vision=see)
        hdr["Authorization"] = "Bearer " + key
        resp = _chat_request(provider, key, url, hdr, body, see)
        choices = resp.get("choices") or []
        if not choices:
            raise RuntimeError(((resp.get("error") or {}).get("message")) or "The AI returned no answer.")
        out = (choices[0].get("message") or {}).get("content") or ""
        if isinstance(out, list):
            out = "".join(x.get("text", "") for x in out if isinstance(x, dict))
    else:
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b}} for b in imgs]
        content.append({"type": "text", "text": text})
        resp = _ai_request("https://api.anthropic.com/v1/messages",
                           {"x-api-key": key, "anthropic-version": "2023-06-01"},
                           {"model": model, "max_tokens": max_tokens or 16000,
                            "messages": [{"role": "user", "content": content if imgs else text}]})
        out = "".join(p.get("text", "") for p in resp.get("content", []) if p.get("type") == "text")
    # some open reasoning models put their thinking inline
    return re.sub(r"<think>.*?</think>", "", out or "", flags=re.S).strip()


def _list_ai_models(p, key):
    """Models a provider offers: [{id, name, free, vision}] (OpenRouter's free ones first)."""
    if p == "openrouter":                # public list, no key needed
        j = _ai_request("https://openrouter.ai/api/v1/models", {}, timeout=30)
        out = []
        for m in j.get("data", []):
            pr = m.get("pricing") or {}
            free = all(str(pr.get(k, "1")).strip() in ("0", "0.0", "0.00") for k in ("prompt", "completion"))
            mods = (m.get("architecture") or {}).get("input_modalities") or []
            out.append({"id": m.get("id"), "name": m.get("name") or m.get("id"), "free": free, "vision": "image" in mods})
        return sorted(out, key=lambda x: (not x["free"], x["id"] or ""))
    if not key:
        raise RuntimeError("Enter the API key first.")
    if p == "gemini":
        j = _ai_request("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                        {"x-goog-api-key": key}, timeout=30)
        out = [{"id": m["name"].split("/", 1)[-1], "name": m.get("displayName") or m["name"], "free": None, "vision": True}
               for m in j.get("models", [])
               if "generateContent" in (m.get("supportedGenerationMethods") or [])
               and not re.search(r"embedding|aqa|tts|image|imagen|veo|live", m["name"])]
        return sorted(out, key=lambda x: x["id"], reverse=True)        # newest versions first
    if p == "groq":
        j = _ai_request("https://api.groq.com/openai/v1/models", {"Authorization": "Bearer " + key}, timeout=30)
        return sorted(({"id": m["id"], "name": m["id"], "free": None, "vision": "llama-4" in m["id"]}
                       for m in j.get("data", [])
                       if m.get("active", True) and not re.search(r"whisper|tts|guard|playai|orpheus", m["id"])),
                      key=lambda x: x["id"])
    j = _ai_request("https://api.anthropic.com/v1/models?limit=100",
                    {"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout=30)
    return [{"id": m["id"], "name": m.get("display_name") or m["id"], "free": None, "vision": True}
            for m in j.get("data", [])]


def _auto_model(p, key, vision=False):
    """The model to use when none is set: the usual default if the key offers it,
    otherwise the best match from the provider's live list. Cached for 6 hours.
    With vision=True only models that can read images are considered."""
    if p not in AI_MODEL_PREFS:
        return AI_PROVIDERS.get(p, AI_PROVIDERS["claude"])["default"]
    return _auto_models(p, key, vision)[0]


def _auto_models(p, key, vision=False):
    """Best automatic choices, best first (used as fallbacks on OpenRouter). Cached 6 hours."""
    default = AI_PROVIDERS[p]["default"]
    ck = p + (":vision" if vision else "")
    hit = _AI_MODEL_CACHE.get(ck)
    if hit and time.time() - hit[0] < 6 * 3600:
        return hit[2][:3]
    if vision and p == "groq":
        default = "meta-llama/llama-4-scout-17b-16e-instruct"
    models = _cached_models(p, key)
    if models is None:
        return [default]                  # try again next time
    ids = [m["id"] for m in models
           if m["id"] and (m["free"] or p != "openrouter") and (m["vision"] or not vision)]
    ranked = []
    for rx in AI_MODEL_PREFS[p]:
        ranked += [i for i in ids if re.search(rx, i) and i not in ranked]
    ranked = ([default] if default in ids else []) + [i for i in ranked if i != default]
    ranked += [i for i in ids if i not in ranked]          # everything else, as backups
    picks = ranked or [default]
    _AI_MODEL_CACHE[ck] = (time.time(), picks[0], picks)
    return picks[:3]


def _ranked_models(p, key, vision=False):
    """Every usable model for a provider, best first (vision=True: only ones that read images)."""
    _auto_models(p, key, vision)
    hit = _AI_MODEL_CACHE.get(p + (":vision" if vision else ""))
    return list(hit[2]) if hit else []


def _claude_generate(prompt, api_key, model, provider=None):
    """Generate text with the chosen AI provider (name kept for existing call sites)."""
    return _ai_complete(provider or getattr(api_key, "provider", "claude"), api_key, model, prompt)


def _save_ai_settings(db, d):
    """Store the provider choice and any per-provider key/model that was posted.
    A blank key keeps the saved one."""
    if (d.get("ai_provider") or "") in AI_PROVIDERS:
        set_setting(db, "ai_provider", d["ai_provider"])
    for p in AI_PROVIDERS:
        if f"{p}_model" in d:
            set_setting(db, f"{p}_model", (d.get(f"{p}_model") or "").strip())
        if (d.get(f"{p}_api_key") or "").strip():
            set_setting(db, f"{p}_api_key", d[f"{p}_api_key"].strip())


def ai_settings_payload(db):
    cur = ai_provider_of(db)
    return {"provider": cur, "providers": [
        {"id": p, "label": m["label"], "model": get_setting(db, f"{p}_model") or "",
         "default_model": (_AI_MODEL_CACHE.get(p) or (0, m["default"], []))[1],
         "key_set": bool(get_setting(db, f"{p}_api_key") or os.environ.get(m["env"], "").strip())}
        for p, m in AI_PROVIDERS.items()]}


@app.route("/api/settings/content", methods=["GET", "POST"])
def api_content_settings():
    u = require_login()
    db = get_db()
    if request.method == "POST":
        # Only credential-holders may set the API key / model / guidelines.
        if not can_view_creds(u):
            return jsonify({"error": "Only the SuperAdmin can change AI credentials."}), 403
        d = request.get_json(force=True)
        _save_ai_settings(db, d)
        if "content_guidelines" in d:
            set_setting(db, "content_guidelines", (d.get("content_guidelines") or "").strip())
        return jsonify({"ok": True})
    key, model = ai_creds(db)
    return jsonify({
        "content_provider": key.provider,
        "claude_model": model or "automatic",  # (legacy field names: the ACTIVE provider's model/key)
        "claude_key_set": bool(key),
        "ai_label": AI_PROVIDERS[key.provider]["label"],
        "ai": ai_settings_payload(db) if can_view_creds(u) else None,
        "can_view_creds": can_view_creds(u),
    })


@app.route("/api/settings/content/test", methods=["POST"])
def api_content_test():
    """Check an AI provider's key/model with a tiny request. Credential-holders
    only. A supplied key is used just for this test (not saved). Never returns the key."""
    u = require_login()
    if not can_view_creds(u):
        return jsonify({"ok": False, "message": "Only the SuperAdmin can test AI credentials."}), 403
    db = get_db()
    d = request.get_json(silent=True) or {}
    provider = d.get("provider") or ai_provider_of(db)
    if provider not in AI_PROVIDERS:
        return jsonify({"ok": False, "message": "Unknown AI provider."})
    saved_key, saved_model = ai_creds(db, provider)
    key = (d.get("api_key") or d.get("claude_api_key") or "").strip() or saved_key
    if not key:
        return jsonify({"ok": False, "message": "No API key provided."})
    model = (d.get("model") or d.get("claude_model") or "").strip() or saved_model or _auto_model(provider, key)
    try:
        txt = _ai_complete(provider, key, model, "Reply with the single word: OK", max_tokens=512)
        return jsonify({"ok": True, "message": f"{AI_PROVIDERS[provider]['label']} works with {model}. Reply: {txt[:40]}"})
    except Exception as e:  # noqa
        return jsonify({"ok": False, "message": str(e)})


@app.route("/api/settings/ai/models", methods=["POST"])
def api_ai_models():
    """List the models a provider offers (OpenRouter marks its free ones)."""
    u = require_login()
    if not can_view_creds(u):
        return jsonify({"error": "Only the SuperAdmin can manage AI settings."}), 403
    db = get_db()
    d = request.get_json(silent=True) or {}
    p = d.get("provider") or ai_provider_of(db)
    if p not in AI_PROVIDERS:
        return jsonify({"error": "Unknown AI provider."}), 400
    key = (d.get("api_key") or "").strip() or ai_creds(db, p)[0]
    try:
        out = _list_ai_models(p, key)
    except Exception as e:  # noqa
        return jsonify({"error": str(e)}), 400
    return jsonify({"models": out[:400]})




@app.route("/api/content")
def api_content_list():
    u = require_login()
    db = get_db()
    names = ws_usernames(db, u)
    if names is None:
        rows = db.execute("SELECT * FROM content_items ORDER BY id DESC LIMIT 50").fetchall()
    else:
        rows = db.execute(f"SELECT * FROM content_items WHERE owner IN ({','.join('?' * len(names))}) "
                          "ORDER BY id DESC LIMIT 50", names).fetchall()
    return jsonify({"items": [dict(r) for r in rows]})


@app.route("/api/content/<int:cid>", methods=["DELETE"])
def api_content_delete(cid):
    require_login()
    db = get_db()
    db.execute("DELETE FROM content_items WHERE id=?", (cid,))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/content/<int:cid>", methods=["PATCH"])
def api_content_update(cid):
    """Auto-save edits to a content item (title and/or body)."""
    require_login()
    d = request.get_json(force=True)
    db = get_db()
    row = db.execute("SELECT * FROM content_items WHERE id=?", (cid,)).fetchone()
    if not row:
        return jsonify({"error": "Not found."}), 404
    title = d.get("title", row["title"])
    body = d.get("body", row["body"])
    hashtags = d.get("hashtags", row["hashtags"] if "hashtags" in row.keys() else "")
    db.execute("UPDATE content_items SET title=?, body=?, hashtags=? WHERE id=?",
               (title, body, hashtags, cid))
    db.commit()
    return jsonify({"ok": True, "saved_at": datetime.utcnow().isoformat()})


# ----- content export: Word (.docx) and PDF -------------------------------- #
def _md_blocks(md):
    """Yield (kind, text) blocks: ('h', level, text) | ('li', text) | ('p', text)."""
    for raw in (md or "").split("\n"):
        line = raw.rstrip()
        h = re.match(r"^(#{1,4})\s+(.*)$", line)
        li = re.match(r"^\s*[-*]\s+(.*)$", line)
        if h:
            yield ("h", len(h.group(1)), h.group(2))
        elif li:
            yield ("li", 0, li.group(1))
        elif line.strip():
            yield ("p", 0, line)
        else:
            yield ("blank", 0, "")


def _strip_inline(t):
    return re.sub(r"\*\*(.+?)\*\*", r"\1", re.sub(r"`(.+?)`", r"\1", t or ""))


def _build_docx(title, body):
    from docx import Document          # python-docx
    from docx.shared import Pt
    doc = Document()
    doc.add_heading(title or "Untitled", level=0)
    for kind, lvl, text in _md_blocks(body):
        if kind == "h":
            doc.add_heading(_strip_inline(text), level=min(max(lvl, 1), 4))
        elif kind == "li":
            doc.add_paragraph(_strip_inline(text), style="List Bullet")
        elif kind == "p":
            p = doc.add_paragraph()
            # render **bold** segments as bold runs
            for i, seg in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
                run = p.add_run(seg)
                if i % 2 == 1:
                    run.bold = True
    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf


_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
_PDF_CODEPOINTS = None      # cached set of unicode codepoints the bundled font has


def _font_codepoints(path):
    """Return the set of unicode codepoints the TTF can render (cached).

    Characters the font lacks (e.g. emoji in DejaVuSans) map to a zero-width
    glyph; fpdf2's character-wrapping then loops forever. We strip those chars
    before rendering, so the PDF stays clean and the build never hangs."""
    global _PDF_CODEPOINTS
    if _PDF_CODEPOINTS is not None:
        return _PDF_CODEPOINTS
    cps = set()
    try:
        from fontTools.ttLib import TTFont as _TT
        tt = _TT(path)
        for table in tt["cmap"].tables:
            cps.update(table.cmap.keys())
        tt.close()
    except Exception:
        cps = set()             # empty -> we won't strip (best effort)
    _PDF_CODEPOINTS = cps
    return cps


def _build_pdf(title, body):
    from fpdf import FPDF              # fpdf2

    # Prefer a bundled Unicode font (DejaVu) so the AI's em-dashes, curly quotes,
    # accents, bullets, arrows, etc. render properly instead of turning into "?".
    # Fall back to the built-in Helvetica core font (latin-1) if files are missing.
    _reg = os.path.join(_FONT_DIR, "DejaVuSans.ttf")
    _bold = os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf")
    unicode_ok = os.path.exists(_reg) and os.path.exists(_bold)
    FONT = "DejaVu" if unicode_ok else "Helvetica"
    cps = _font_codepoints(_reg) if unicode_ok else set()

    def s(t):
        t = t or ""
        if not unicode_ok:
            return t.encode("latin-1", "replace").decode("latin-1")
        if cps:
            # keep only glyphs the font actually has (drop emoji etc. so fpdf's
            # character wrap can't loop on a zero-width glyph); keep whitespace.
            return "".join(ch for ch in t if ch in "\n\r\t " or ord(ch) in cps)
        return t

    def _soft_break(t, n=30):
        # fpdf2 raises "Not enough horizontal space to render a single character"
        # when one word (a long URL / #hashtagstring) is wider than the line.
        # Break over-long words so ordinary word-wrap can handle them.
        out = []
        for word in (t or "").split(" "):
            while len(word) > n:
                out.append(word[:n]); word = word[n:]
            out.append(word)
        return " ".join(out)

    def _mc(h, text):
        text = s(_soft_break(text))
        if not text.strip():
            pdf.ln(h); return
        # Ordinary word-wrap (NOT wrapmode="CHAR" — that loops forever on any
        # zero-width glyph). _soft_break already tamed over-long tokens; if a
        # line still won't fit, fall back to fixed-size chunks.
        try:
            pdf.multi_cell(0, h, text)
        except Exception:
            for i in range(0, len(text), 20):
                try: pdf.multi_cell(0, h, text[i:i + 20])
                except Exception: break

    pdf = FPDF(format="A4")
    if unicode_ok:
        try:
            pdf.add_font("DejaVu", "", _reg)
            pdf.add_font("DejaVu", "B", _bold)
        except Exception:
            FONT = "Helvetica"; unicode_ok = False; cps = set()
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    pdf.set_font(FONT, "B", 18)
    _mc(9, title or "Untitled")
    pdf.ln(2)
    for kind, lvl, text in _md_blocks(body):
        if kind == "blank":
            pdf.ln(3); continue
        text = _strip_inline(text)
        if kind == "h":
            size = {1: 15, 2: 14, 3: 13, 4: 12}.get(lvl, 13)
            pdf.set_font(FONT, "B", size); pdf.ln(2)
            _mc(7, text)
        elif kind == "li":
            pdf.set_font(FONT, "", 11)
            _mc(6, "-  " + text)          # no leading spaces (also a trigger)
        else:
            pdf.set_font(FONT, "", 11)
            _mc(6, text)
    out = pdf.output()                 # fpdf2 returns a bytearray
    return BytesIO(bytes(out))


@app.route("/api/content/<int:cid>/download")
def api_content_download(cid):
    require_login()
    fmt = (request.args.get("fmt") or "docx").lower()
    db = get_db()
    row = db.execute("SELECT * FROM content_items WHERE id=?", (cid,)).fetchone()
    if not row:
        return jsonify({"error": "Not found."}), 404
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", (row["title"] or "content"))[:50] or "content"
    try:
        if fmt == "pdf":
            buf = _build_pdf(row["title"], row["body"])
            return send_file(buf, as_attachment=True, download_name=safe + ".pdf",
                             mimetype="application/pdf")
        else:  # docx
            buf = _build_docx(row["title"], row["body"])
            return send_file(
                buf, as_attachment=True, download_name=safe + ".docx",
                mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    except ImportError:
        need = "fpdf2" if fmt == "pdf" else "python-docx"
        return jsonify({"error": f"The '{need}' package isn't installed. Re-run start.bat, "
                                 f"or: pip install -r requirements.txt"}), 500
    except Exception as e:  # noqa
        return jsonify({"error": f"Could not build {fmt.upper()}: {e}"}), 500


# background content-writing jobs {job_id: {status, percent, message, id, title, body}}
CONTENT_JOBS = {}


# --------------------------------------------------------------------------- #
#  Hashtag intelligence (runs in the BACKGROUND — never shown to the user).
#  1) Claude analyses the generated content to identify suitable hashtags.
#  2) Google is checked for currently-relevant / trending phrases.
#  Only the merged, final hashtag list is returned to the caller.
# --------------------------------------------------------------------------- #
_HASHTAG_STOP = {"hashtags", "hashtag", "for", "the", "and", "best", "top",
                 "with", "your", "how", "to", "of", "in", "on", "a", "an",
                 "2023", "2024", "2025", "2026", "2027"}


def _to_hashtag(words):
    words = [w for w in words if w and w.lower() not in _HASHTAG_STOP]
    if not words:
        return ""
    tag = "#" + "".join(w[:1].upper() + w[1:] for w in words[:3])
    return tag if len(tag) > 2 else ""


def _merge_hashtags(*groups, cap=15):
    """De-duplicate + normalise hashtags from several sources, preserving order."""
    seen, out = set(), []
    for g in groups:
        if isinstance(g, str):
            g = g.split()
        for t in (g or []):
            t = (t or "").strip()
            if not t:
                continue
            if not t.startswith("#"):
                t = "#" + re.sub(r"[^A-Za-z0-9]", "", t)
            if len(t) <= 1:
                continue
            k = t.lower()
            if k not in seen:
                seen.add(k)
                out.append(t)
            if len(out) >= cap:
                return out
    return out


def _google_trending_hashtags(terms, limit=8):
    """Check Google (autocomplete/suggest) for currently-relevant phrases around
    the given terms and turn them into hashtags. Best-effort + silent: it runs in
    the background, is never displayed, and never raises."""
    out, seen = [], set()
    for term in [t for t in (terms or []) if t][:3]:
        q = urllib.parse.quote((str(term) + " hashtags").strip())
        url = ("https://suggestqueries.google.com/complete/search"
               "?client=firefox&hl=en&q=" + q)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            suggestions = data[1] if isinstance(data, list) and len(data) > 1 else []
        except Exception:
            suggestions = []
        for s in suggestions:
            words = re.sub(r"[^A-Za-z0-9 ]", " ", str(s)).split()
            tag = _to_hashtag(words)
            if tag and tag.lower() not in seen:
                seen.add(tag.lower())
                out.append(tag)
            if len(out) >= limit:
                return out
    return out[:limit]


def _analyze_content_hashtags(title, body, key, model):
    """Analyse the generated content with the AI to identify (topics, hashtags).
    Silent/background; returns ([title], []) on any failure."""
    prompt = (
        "Analyse the content below. Return STRICT JSON only, no prose:\n"
        '{"topics":["3-5 short search keywords or phrases from the content"],'
        '"hashtags":["8-12 specific, relevant hashtags, each starting with #"]}\n\n'
        f"TITLE: {title}\n\nCONTENT:\n{(body or '')[:4000]}"
    )
    try:
        txt = _claude_generate(prompt, key, model)
        m = re.search(r"\{.*\}", txt, re.S)
        obj = json.loads(m.group(0) if m else txt)
        topics = [str(t).strip() for t in (obj.get("topics") or []) if str(t).strip()]
        tags = [str(h).strip() for h in (obj.get("hashtags") or []) if str(h).strip()]
        return (topics or [title]), tags
    except Exception:
        return [title], []


def _recommend_hashtags(title, body, key, model, base_tags=""):
    """Full background pipeline: analyse content for hashtags + check Google for
    trending/relevant ones, then merge. Returns a single space-separated string."""
    topics, content_tags = _analyze_content_hashtags(title, body, key, model)
    google_tags = _google_trending_hashtags(topics or [title])
    return " ".join(_merge_hashtags(base_tags, content_tags, google_tags, cap=15))


def _run_content_generation(job_id, title, provider, key, model, owner, owner_id, guidelines=""):
    disp = "API"
    tid = task_new("content", f'Writing content: "{title}" ({disp})', str(owner_id))
    CONTENT_JOBS[job_id] = {"status": "running", "percent": 15,
                            "message": f"{disp} is writing…"}
    task_update(tid, percent=15, message=f"{disp} is writing…")
    try:
        if task_cancelled(tid):
            raise _Cancelled()
        prompt = _content_prompt(title, guidelines)
        body = _claude_generate(prompt, key, model)
        # if the user cancelled while the AI was writing, discard the result
        if task_cancelled(tid):
            raise _Cancelled()
        if not body:
            raise RuntimeError("The AI returned empty content.")
        # Background hashtag intelligence: analyse the generated content and
        # cross-check Google for trending, relevant tags. This runs silently —
        # the user only ever sees the final content + recommended hashtags.
        CONTENT_JOBS[job_id] = {"status": "running", "percent": 80,
                                "message": "Finalising…"}
        task_update(tid, percent=80, message="Finalising…")
        try:
            hashtags = _recommend_hashtags(title, body, key, model)
        except Exception:
            hashtags = ""
        if task_cancelled(tid):
            raise _Cancelled()
        db = db_connect()
        cur = db.execute(
            "INSERT INTO content_items (title, body, provider, owner, created_at, hashtags) "
            "VALUES (?,?,?,?,?,?)", (title, body, provider, owner,
                                     datetime.utcnow().isoformat(), hashtags))
        cid = cur.lastrowid
        add_notification(db, f'📝 Content generated for "{title}" ({disp}) by {owner}.',
                         "info", owner, recipients=owner_and_admins(db, owner_id))
        db.commit(); db.close()
        CONTENT_JOBS[job_id] = {"status": "done", "percent": 100,
                                "message": "Content ready.", "id": cid,
                                "title": title, "body": body, "provider": provider,
                                "hashtags": hashtags}
        task_done(tid, ok=True, message="Content ready.")
    except _Cancelled:
        CONTENT_JOBS[job_id] = {"status": "cancelled", "percent": 0, "message": "Cancelled."}
        task_mark_cancelled(tid)
    except Exception as e:  # noqa
        CONTENT_JOBS[job_id] = {"status": "error", "percent": 0,
                                "message": f"Generation failed: {e}"}
        task_done(tid, ok=False, message=f"Generation failed: {e}")


@app.route("/api/content/generate", methods=["POST"])
def api_content_generate():
    u = require_login()
    d = request.get_json(force=True)
    title = (d.get("title") or "").strip()
    if not title:
        return jsonify({"error": "Enter a title."}), 400
    db = get_db()
    # Generation uses the AI provider the SuperAdmin chose in Setup.
    key, model = ai_creds(db)
    if not key:
        return jsonify({"error": "The AI isn't set up yet. Ask your SuperAdmin to choose an AI "
                                 "provider and add its key in Setup → Credentials."}), 400
    guidelines = "\n".join(x for x in (get_setting(db, "content_guidelines") or "",
                                       kit_prompt(kit_for_owner(db, u["id"], _rget(u, "active_brand_id")))) if x)
    job_id = "content_" + secrets.token_hex(4)
    CONTENT_JOBS[job_id] = {"status": "starting", "percent": 0, "message": "Starting…"}
    threading.Thread(target=_run_content_generation,
                     args=(job_id, title, key.provider, key, model, u["username"], u["id"], guidelines),
                     daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/content/genstatus/<job_id>")
def api_content_genstatus(job_id):
    require_login()
    return jsonify(CONTENT_JOBS.get(job_id, {"status": "idle", "percent": 0, "message": ""}))


@app.route("/api/calendar/<int:cid>", methods=["PATCH"])
def api_calendar_edit(cid):
    u = require_login()
    d = request.get_json(force=True)
    db = get_db()
    row = db.execute("SELECT * FROM calendar_items WHERE id=?", (cid,)).fetchone()
    if not row:
        return jsonify({"error": "Not found."}), 404
    # ---- Scheduling: date (+ optional exact time) and auto-publish flag ----
    scheduled = False
    new_date = (d.get("date") or "").strip() if "date" in d else ""
    if new_date and new_date != row["date"]:
        if row["state"] == "published" or row["publish_state"] == "publishing":
            return jsonify({"error": "This video is already published (or publishing) — "
                                     "its date can't be changed."}), 400
        try:
            datetime.strptime(new_date, "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": "Invalid date."}), 400
        if new_date < datetime.now().strftime("%Y-%m-%d"):
            return jsonify({"error": "Pick today or a future date."}), 400
    if "platforms" in d:
        plats = [x for x in (d.get("platforms") or []) if x in SOCIAL]
        if not plats:
            return jsonify({"error": "Select at least one platform."}), 400
        denied = [P.PLATFORMS[x]["label"] for x in plats if x not in _allowed_platforms(u)]
        if denied:
            return jsonify({"error": "You don't have permission to publish to " + ", ".join(denied) + "."}), 403
        db.execute("UPDATE calendar_items SET platforms=? WHERE id=?", (json.dumps(plats), cid))
    if "platform_captions" in d and isinstance(d["platform_captions"], dict):
        pc = {k: (v or "") for k, v in d["platform_captions"].items() if k in SOCIAL}
        db.execute("UPDATE calendar_items SET platform_captions=? WHERE id=?", (json.dumps(pc), cid))
    if "content_type" in d and d["content_type"] in ("reel", "post", "story", "short"):
        db.execute("UPDATE calendar_items SET content_type=? WHERE id=?", (d["content_type"], cid))
    for k in ("yt_title", "yt_privacy", "description"):
        if k in d:
            db.execute(f"UPDATE calendar_items SET {k}=? WHERE id=?", ((d.get(k) or "").strip() or None, cid))
    for k in ("link_url", "link_campaign"):
        if k in d:
            v = (d.get(k) or "").strip()
            if k == "link_url" and v and not re.match(r"^https?://", v):
                return jsonify({"error": "The website link must start with https://"}), 400
            db.execute(f"UPDATE calendar_items SET {k}=? WHERE id=?", (v or None, cid))
    if "recycle_days" in d:
        try:
            rd = int(d.get("recycle_days") or 0)
        except Exception:
            rd = 0
        db.execute("UPDATE calendar_items SET recycle_days=? WHERE id=?", (rd or None, cid))
    if "publish_at" in d:
        db.execute("UPDATE calendar_items SET publish_at=?, tz=? WHERE id=?",
                   ((d.get("publish_at") or None), (d.get("tz") or ""), cid))
    cap = d.get("caption", row["caption"])
    tags = d.get("hashtags", row["hashtags"])
    title = (d.get("title") if d.get("title") is not None else row["title"])
    title = (title or row["title"] or "Untitled").strip() or (row["title"] or "Untitled")
    db.execute("UPDATE calendar_items SET title=?, caption=?, hashtags=? WHERE id=?",
               (title, cap, tags, cid))
    if new_date:
        db.execute("UPDATE calendar_items SET date=? WHERE id=?", (new_date, cid))
        scheduled = True
    if "publish_time" in d:
        pt = (d.get("publish_time") or "").strip()          # 'HH:MM' or '' to clear
        db.execute("UPDATE calendar_items SET publish_time=? WHERE id=?", (pt, cid))
        scheduled = True
    if "auto_publish" in d:
        db.execute("UPDATE calendar_items SET auto_publish=? WHERE id=?",
                   (1 if d.get("auto_publish") else 0, cid))
    if scheduled and row["state"] == "published":
        scheduled = False
    if scheduled and row["approved"]:
        # Only approved content becomes "scheduled"; drafts / items awaiting
        # approval just move to the new date and keep their workflow state.
        db.execute("UPDATE calendar_items SET state='scheduled', publish_state='scheduled' WHERE id=?", (cid,))
        r2 = db.execute("SELECT * FROM calendar_items WHERE id=?", (cid,)).fetchone()
        when = r2["date"] + ((" " + r2["publish_time"]) if r2["publish_time"] else "")
        moved = f' (moved from {row["date"]})' if new_date and new_date != row["date"] else ""
        add_notification(db, f'🗓️ "{title}" is scheduled to publish on {when}{moved}. It will publish '
                             f'automatically when the time arrives.', "calendar",
                         (u["username"]), link=f"calendar:{cid}",
                         recipients=owner_and_admins(db, row["owner_id"]))
        log_activity(db, u, "scheduled", "item", cid, f"{title} → {when}")
    if not scheduled and any(k in d for k in ("title", "caption", "hashtags", "platforms", "platform_captions")):
        log_activity(db, u, "edited", "item", cid, title)
    if scheduled and not row["approved"] and new_date and new_date != row["date"]:
        add_notification(db, f'🗓️ "{title}" moved from {row["date"]} to {new_date} by {u["username"]}.',
                         "calendar", u["username"], link=f"calendar:{cid}",
                         recipients=owner_and_admins(db, row["owner_id"]))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/calendar/<int:cid>", methods=["DELETE"])
def api_calendar_delete(cid):
    u = require_login()
    db = get_db()
    row = db.execute("SELECT * FROM calendar_items WHERE id=?", (cid,)).fetchone()
    if not row:
        return jsonify({"error": "Not found."}), 404
    # Delete backing files from storage (local, Supabase, Drive) unless a recycled copy still uses them.
    _purge_calendar_files(db, row)
    db.execute("DELETE FROM calendar_items WHERE id=?", (cid,))
    db.execute("DELETE FROM post_targets WHERE item_id=?", (cid,))
    db.execute("DELETE FROM inbox_comments WHERE item_id=?", (cid,))
    db.execute("DELETE FROM review_links WHERE item_id=?", (cid,))
    db.commit()
    log_activity(db, u, "deleted", "item", cid, row["title"])
    add_notification(db, f'⚠ Scheduled video "{row["title"]}" ({row["date"]}) removed by {u["username"]}.',
                     "remove", u["username"],
                     recipients=owner_and_admins(db, row["owner_id"]))
    return jsonify({"ok": True})


# --------------------------------------------------------------------------- #
#  Caption + hashtag generation
#  Analyses the ACTUAL video content (multiple sampled frames) with a vision
#  model via ollama, producing a viral title + caption + hashtags.
#  Model defaults to qwen3-vl:8b but can be changed (setting 'ollama_model').
# --------------------------------------------------------------------------- #
def _ffmpeg_bin():
    """Path to ffmpeg — a ZIP-extracted copy we registered, or one on PATH."""
    p = _stored_tool_path("ffmpeg")
    if p:
        return p
    return "ffmpeg" if which("ffmpeg") else None


def _video_duration(video_path, ff):
    """Seconds, via ffprobe next to ffmpeg (best-effort)."""
    probe = os.path.join(os.path.dirname(ff), "ffprobe" + (".exe" if platform.system() == "Windows" else "")) \
            if os.path.sep in ff else "ffprobe"
    for cand in (probe, "ffprobe"):
        try:
            out = subprocess.run([cand, "-v", "error", "-show_entries", "format=duration",
                                  "-of", "csv=p=0", video_path],
                                 capture_output=True, timeout=30, text=True)
            return float(out.stdout.strip())
        except Exception:
            continue
    return None


def _extract_frames(video_path, n=3):
    """Sample up to n JPEG frames spread across the video (for content analysis)."""
    ff = _ffmpeg_bin()
    if not ff:
        return []
    frames = []
    dur = _video_duration(video_path, ff)
    stamps = [max(0.1, dur * f) for f in (0.15, 0.45, 0.75)][:n] if dur and dur > 0 else [None]
    for i, ss in enumerate(stamps):
        out = os.path.join(DOWNLOAD_DIR, f"fr_{secrets.token_hex(3)}_{i}.jpg")
        cmd = [ff, "-y"]
        if ss is not None:
            cmd += ["-ss", str(round(ss, 2))]
        cmd += ["-i", video_path, "-frames:v", "1"]
        if ss is None:
            cmd += ["-vf", "thumbnail"]
        cmd += ["-q:v", "3", out]
        try:
            subprocess.run(cmd, capture_output=True, timeout=60)
            if os.path.exists(out):
                with open(out, "rb") as fh:
                    frames.append(fh.read())
                os.remove(out)
        except Exception:
            pass
    return frames


def _ollama_available():
    try:
        req = urllib.request.Request(OLLAMA_URL + "/api/tags")
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _active_model():
    try:
        db = db_connect()
        m = get_setting(db, "ollama_model")
        db.close()
        return m or OLLAMA_MODEL
    except Exception:
        return OLLAMA_MODEL


def _ollama_list_models():
    """Return the list of model names the local server already has pulled."""
    try:
        req = urllib.request.Request(OLLAMA_URL + "/api/tags")
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    except Exception:
        return []


def _start_ollama_serve():
    """Launch 'ollama serve' in the background if the server isn't up yet."""
    exe = _ollama_exe()
    if not exe:
        return False
    try:
        kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if platform.system() == "Windows":
            # detach so it keeps running after this request/thread ends
            kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_GROUP
        subprocess.Popen([exe, "serve"], **kwargs)
        return True
    except Exception:
        return False


def _set_aimodel(status, percent, message):
    AIMODEL_JOB.update({"status": status, "percent": int(percent), "message": message})


def _ensure_ai_model():
    """
    Make the local AI Model ready in the background, without ever reinstalling
    Ollama:
      1. If the server isn't reachable, start 'ollama serve' and wait for it.
      2. Pick a model — prefer one that is ALREADY pulled (any qwen3-vl, else
         the configured model if present, else the first available one); only
         pull qwen3-vl:8b when nothing usable is installed.
      3. Warm/run the model so it stays resident (keep_alive) — this is the
         "run it in the background once I'm connected" step.
    Safe to call repeatedly; a lock stops overlapping runs.
    """
    if not AIMODEL_LOCK.acquire(blocking=False):
        return
    try:
        if not _ollama_installed():
            _set_aimodel("not_installed", 0,
                         "AI Model is not installed yet — install it from Setup.")
            return

        # 1) make sure the server is up ------------------------------------- #
        if not _ollama_available():
            _set_aimodel("starting", 5, "Starting the AI Model engine…")
            _start_ollama_serve()
            for _ in range(40):                     # wait up to ~20s
                if _ollama_available():
                    break
                time.sleep(0.5)
            if not _ollama_available():
                _set_aimodel("error", 0,
                             "Could not reach the AI Model engine. Please try again.")
                return

        # 2) choose / pull a model ------------------------------------------ #
        want = _active_model()                      # e.g. qwen3-vl:8b
        have = _ollama_list_models()

        def _match(names, needle):
            return next((n for n in names if needle.lower() in n.lower()), "")

        # Captions analyse VIDEO FRAMES, so we need a VISION-capable model.
        # Prefer the configured model if it can see, else any installed vision
        # model; only fall back to a non-vision model if that's all there is.
        chosen = ""
        if want in have and _is_vision_model(want):
            chosen = want
        elif _match(have, "qwen3-vl"):
            chosen = _match(have, "qwen3-vl")
        else:
            chosen = next((m for m in have if _is_vision_model(m)), "")
        if not chosen and want in have:
            chosen = want
        elif not chosen and have:
            chosen = have[0]

        if not chosen:
            # nothing usable installed -> pull the recommended VISION model
            _set_aimodel("pulling", 10, f"Downloading the AI Model ({want})…")
            chosen = want
            try:
                data = json.dumps({"name": want}).encode("utf-8")
                req = urllib.request.Request(
                    OLLAMA_URL + "/api/pull", data=data,
                    headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=None) as resp:
                    for raw in resp:
                        if not raw:
                            continue
                        try:
                            ev = json.loads(raw.decode("utf-8", "replace"))
                        except Exception:
                            continue
                        total = ev.get("total") or 0
                        completed = ev.get("completed") or 0
                        if total:
                            pct = 10 + int(min(85, completed * 85 / total))
                            _set_aimodel("pulling", pct,
                                         f"Downloading the AI Model… {int(completed*100/total)}%")
                        elif ev.get("status"):
                            _set_aimodel("pulling", AIMODEL_JOB.get("percent", 10),
                                         f"AI Model: {ev.get('status')}")
                        if ev.get("error"):
                            _set_aimodel("error", 0, f"AI Model pull failed: {ev['error']}")
                            return
            except Exception as e:
                _set_aimodel("error", 0, f"Could not download the AI Model: {e}")
                return

        # remember the model we settled on so the rest of the app uses it
        try:
            db = db_connect()
            set_setting(db, "ollama_model", chosen)
            db.close()
        except Exception:
            pass

        # 3) warm / run it in the background -------------------------------- #
        _set_aimodel("warming", 96, "Starting the AI Model…")
        try:
            data = json.dumps({
                "model": chosen, "prompt": "OK", "stream": False,
                "keep_alive": "30m",
            }).encode("utf-8")
            req = urllib.request.Request(
                OLLAMA_URL + "/api/generate", data=data,
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=120).read()
        except Exception:
            # even if warming times out, the model is pulled & the server is up
            pass

        _set_aimodel("ready", 100, f"AI Model ready — {chosen} is running.")
    finally:
        AIMODEL_LOCK.release()


@app.route("/api/aimodel/ensure", methods=["POST"])
def api_aimodel_ensure():
    """Kick off (or re-check) the background 'make the AI Model ready' job."""
    require_login()
    if not _ollama_installed():
        AIMODEL_JOB.update({"status": "not_installed", "percent": 0,
                            "message": "AI Model is not installed yet — install it from Setup."})
        return jsonify(dict(AIMODEL_JOB, installed=False))
    if AIMODEL_JOB.get("status") not in ("starting", "pulling", "warming"):
        threading.Thread(target=_ensure_ai_model, daemon=True).start()
    return jsonify(dict(AIMODEL_JOB, installed=True))


@app.route("/api/aimodel/status")
def api_aimodel_status():
    require_login()
    return jsonify(dict(AIMODEL_JOB,
                        installed=_ollama_installed(),
                        available=_ollama_available()))


# model-name hints for image/vision-capable Ollama models
VISION_HINTS = ("qwen3-vl", "qwen2-vl", "qwen2.5-vl", "llava", "llama3.2-vision",
                "llama3.2-vl", "moondream", "bakllava", "minicpm-v", "gemma3", "granite3.2-vision")


def _is_vision_model(name):
    return any(h in (name or "").lower() for h in VISION_HINTS)


def _vision_model():
    """
    Pick a VISION-capable model for analysing video frames. Prefers the
    configured model if it can see images, otherwise the first installed
    vision model, otherwise the default (qwen3-vl:8b). This fixes captions
    all coming out identical because a text-only model was selected and it
    couldn't actually look at the video.
    """
    installed = _ollama_list_models()
    cfg = _active_model()
    if cfg and _is_vision_model(cfg) and any(m == cfg or m.split(":")[0] == cfg.split(":")[0]
                                             for m in installed):
        return cfg
    for m in installed:
        if _is_vision_model(m):
            return m
    return cfg if _is_vision_model(cfg) else OLLAMA_MODEL


def _claude_creds():
    """(key, model) of the chosen AI provider from app settings or env — safe off-request."""
    try:
        db = db_connect()
        key, model = ai_creds(db)
        db.close()
        return key, model
    except Exception:
        return _ai_key(CLAUDE_API_KEY_ENV, "claude"), DEFAULT_CLAUDE_MODEL


VIDEO_MIME = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
              ".mkv": "video/x-matroska", ".avi": "video/x-msvideo", ".3gp": "video/3gpp", ".mpeg": "video/mpeg"}
GEMINI_INLINE_MAX = 14 * 1024 * 1024      # request limit is 20 MB after base64 (+33%)


def ai_analyse_media(frames, guidelines="", video_path=None):
    """Look at a post's media with the chosen AI provider and write its title,
    caption, description and hashtags. Gemini gets the whole video (picture and
    sound) when it's small enough; other providers get frames sampled from it.
    Returns a dict, or raises RuntimeError with the reason."""
    key, model = _claude_creds()
    if not key:
        raise RuntimeError("No AI provider is set up yet (Setup → Credentials → AI provider).")
    video = None
    if key.provider == "gemini" and video_path and os.path.exists(video_path):
        ext = os.path.splitext(video_path)[1].lower()
        if ext in VIDEO_MIME and os.path.getsize(video_path) <= GEMINI_INLINE_MAX:
            with open(video_path, "rb") as fh:
                video = (fh.read(), VIDEO_MIME[ext])
    if not (frames or video):
        raise RuntimeError("Couldn't read pictures from the video. Open it in the Calendar and click the AI "
                           "button again (your browser reads the frames), or install FFmpeg on the server.")
    what = ("This is the video itself — use both what you see and what you hear." if video else
            f"These are {len(frames[:4])} frames sampled in order across ONE video or image post." if len(frames) > 1 else
            "This is the post's image (or one frame from its video).")
    guide = ("\nFollow these guidelines from the account owner (they take priority):\n" + guidelines.strip() + "\n"
             ) if (guidelines or "").strip() else ""
    prompt = (
        f"You are an experienced social media manager. {what}\n"
        "Look carefully at what is actually shown: people, objects, setting, actions, on-screen text and mood. "
        "Then write content for THIS specific post:\n"
        '- "title": a short, catchy title, at most 8 words. Never a file name.\n'
        '- "caption": 1-2 short sentences for Instagram / TikTok: a hook that fits what is shown, '
        "optionally a call to action. Emojis are fine, sparingly.\n"
        '- "description": 2-4 plain sentences describing what happens, for YouTube and Facebook. No hashtags.\n'
        '- "hashtags": 8-12 specific, relevant hashtags (mix niche and popular), space-separated, each starting with #.\n'
        "Never invent facts you can't see or hear (names, prices, places, dates) unless they are shown or said.\n"
        + guide +
        'Return STRICT JSON only: {"title":"...","caption":"...","description":"...","hashtags":"#a #b"}')
    txt = _ai_complete(key.provider, key, model, prompt, [] if video else frames[:4], 4000, video=video)
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        obj = json.loads(m.group(0) if m else txt)
    except Exception:
        raise RuntimeError("The AI's answer wasn't in the expected format. Try again, or choose another model.")
    out = {k: str(obj.get(k) or "").strip() for k in ("title", "caption", "description", "hashtags")}
    if isinstance(obj.get("hashtags"), list):
        out["hashtags"] = " ".join(str(x).strip() for x in obj["hashtags"] if str(x).strip())
    out["hashtags"] = " ".join(t if t.startswith("#") else "#" + t for t in out["hashtags"].replace(",", " ").split())
    if not (out["caption"] or out["title"]):
        raise RuntimeError("The AI returned an empty answer. Try again, or choose another model.")
    try:                                   # add trending, relevant tags from Google (best-effort)
        google_tags = _google_trending_hashtags([t for t in (out["title"], out["caption"]) if t])
        out["hashtags"] = " ".join(_merge_hashtags(out["hashtags"], google_tags, cap=15))
    except Exception:
        pass
    out["via"] = AI_PROVIDERS[key.provider]["label"] + (" (whole video)" if video else "")
    return out


def generate_caption(video_path, original_name, progress=None, kit=None, frames=None):
    """
    Return (title, caption, hashtags, description, note). The chosen AI provider
    looks at the REAL media — frames captured by the browser, frames sampled with
    FFmpeg, or (Gemini) the whole video — and writes content that follows the
    owner's guidelines and brand kit. When the AI can't be used, a per-video
    varied template is returned and `note` says why.
    """
    import time, hashlib
    def rep(p, m):
        if progress:
            try: progress(int(p), m)
            except Exception: pass

    frames = [f for f in (frames or []) if f]
    if not frames:
        rep(8, "Sampling frames from the video…")
        if (video_path or "").lower().endswith(IMG_EXT):
            try:
                with open(video_path, "rb") as fh:
                    frames = [fh.read()]
            except Exception:
                frames = []
        elif video_path and os.path.exists(video_path):
            frames = _extract_frames(video_path, 4)
    guidelines = "\n".join(x for x in (_content_guidelines_bg(), kit_prompt(kit)) if x)
    brand_tags = (kit or {}).get("default_hashtags") or ""

    note = ""
    rep(35, "Analysing the video with AI…")
    try:
        res = ai_analyse_media(frames, guidelines, video_path)
        tags = res["hashtags"]
        if brand_tags:
            tags = " ".join(_merge_hashtags(brand_tags, tags, cap=20))
        rep(100, f"Title, caption, description & hashtags ready ({res['via']}).")
        return (res["title"] or "New post"), res["caption"], tags, res["description"], ""
    except _Cancelled:
        raise
    except Exception as e:  # noqa
        note = str(e)

    # ---- Local fallback — VARIED per video (never identical) -------------- #
    # We can't see the content without a vision model, so we vary the template
    # deterministically by the video's own bytes so two different videos never
    # get the same caption/hashtags.
    try:
        h = hashlib.sha1()
        with open(video_path, "rb") as fh:
            h.update(fh.read(1024 * 512))            # first 512KB is plenty to differ
            h.update(str(os.path.getsize(video_path)).encode())
        seed = int(h.hexdigest(), 16)
    except Exception:
        seed = abs(hash(original_name or "v"))
    TITLES = ["New Reel — ready to review", "Fresh drop 🎬", "Hot off the edit",
              "Watch till the end 👀", "Today's upload", "This one's a vibe",
              "Save this for later", "You'll want to see this"]
    CAPS = ["Make it happen. 🔥", "Small steps, big moves. 🚀", "Pressure makes diamonds. 💎",
            "Consistency is the cheat code. ⚡", "Show up. Level up. 📈", "Good things take reps. 💪",
            "Blink and you'll miss it. 👀", "Another day, another win. 🏆",
            "Trust the process. 🌱", "Let the work talk. 🎯"]
    TAGSETS = [
        "#reels #viral #trending #motivation #contentcreator",
        "#instareels #explore #reelitfeelit #inspiration #dailypost",
        "#reelsinstagram #trendingnow #creator #hustle #growth",
        "#videooftheday #reelsvideo #fyp #mindset #success",
        "#contentcreation #reelkarofeelkaro #viralvideo #focus #goals",
        "#reelsindia #trend #creatorlife #discipline #win",
    ]
    for p, m in [(45, "Composing caption…"), (80, "Selecting hashtags…")]:
        rep(p, m); time.sleep(0.2)
    # use independent regions of the hash so title/caption/hashtags vary
    # separately (two different videos are very unlikely to match on all three)
    title    = TITLES[(seed & 0xFFFF) % len(TITLES)]
    caption  = CAPS[((seed >> 16) & 0xFFFF) % len(CAPS)]
    hashtags = TAGSETS[((seed >> 32) & 0xFFFF) % len(TAGSETS)]
    if brand_tags:
        hashtags = " ".join(_merge_hashtags(brand_tags, hashtags, cap=20))
    rep(100, "Used a basic template — the AI couldn't analyse this video.")
    return title, caption, hashtags, "", note


# =========================================================================== #
#  V14 : Connect (Google Drive + Instagram OAuth), per-user isolation,
#        Drive folders/uploads, presence, and a global running-tasks registry.
# =========================================================================== #

# ---- OAuth constants ------------------------------------------------------ #
GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO  = "https://www.googleapis.com/oauth2/v2/userinfo"
GOOGLE_SCOPES    = ("openid email profile "
                    "https://www.googleapis.com/auth/drive.file")
DRIVE_API        = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_API = "https://www.googleapis.com/upload/drive/v3/files"

# Instagram API with Instagram Login (Business Login for Instagram)
# Meta's current Instagram Login flow authenticates directly on Instagram, not
# through facebook.com/dialog/oauth.
IG_AUTH_URL       = "https://www.instagram.com/oauth/authorize"
IG_TOKEN_URL      = "https://api.instagram.com/oauth/access_token"
IG_GRAPH_BASE     = "https://graph.instagram.com/v26.0"
IG_LONG_TOKEN_URL = "https://graph.instagram.com/access_token"
IG_SCOPES         = ("instagram_business_basic,"
                     "instagram_business_content_publish,"
                     "instagram_business_manage_comments")

PROJECT_FOLDER_NAME = "Social Dashboard Project"


def _oauth_cfg():
    db = get_db()
    return {
        "google_client_id":     get_setting(db, "google_client_id"),
        "google_client_secret": get_setting(db, "google_client_secret"),
        "ig_app_id":            get_setting(db, "ig_app_id"),
        "ig_app_secret":        get_setting(db, "ig_app_secret"),
        "redirect_base":        get_setting(db, "oauth_redirect_base"),
    }


def _redirect_base():
    """Base URL used to build OAuth redirect URIs (configurable; else request host)."""
    base = get_setting(get_db(), "oauth_redirect_base").strip().rstrip("/")
    if base:
        return base
    return request.host_url.rstrip("/")


def _http_json(url, data=None, headers=None, method=None, timeout=30):
    """Small JSON helper over urllib. Returns (ok, parsed_or_text, status)."""
    hdrs = {"Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    body = None
    if data is not None:
        if isinstance(data, (dict, list)):
            body = json.dumps(data).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        elif isinstance(data, bytes):
            body = data
        else:
            body = str(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return True, json.loads(raw), r.status
            except Exception:
                return True, raw, r.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return False, json.loads(raw), e.code
        except Exception:
            return False, raw, e.code
    except Exception as e:
        return False, str(e), 0


# ------------------------------------------------------------------ Google Drive
def _google_access_token(user):
    """Return a usable Google access token for this user (refreshing if needed)."""
    try:
        tok = json.loads(dec(user.get("google_token")) or "{}")
    except Exception:
        tok = {}
    if not tok:
        return ""
    # refresh if we have a refresh_token and the token looks expired
    if tok.get("refresh_token") and tok.get("expires_at", 0) < time.time() + 60:
        cfg = _oauth_cfg()
        ok, res, _ = _http_json(
            GOOGLE_TOKEN_URL,
            data=urllib.parse.urlencode({
                "client_id": cfg["google_client_id"],
                "client_secret": cfg["google_client_secret"],
                "refresh_token": tok["refresh_token"],
                "grant_type": "refresh_token",
            }).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if ok and isinstance(res, dict) and res.get("access_token"):
            tok["access_token"] = res["access_token"]
            tok["expires_at"] = time.time() + int(res.get("expires_in", 3600))
            db = get_db()
            db.execute("UPDATE users SET google_token=? WHERE id=?",
                       (enc(json.dumps(tok)), user["id"]))
            db.commit()
    return tok.get("access_token", "")


def _drive_ensure_folder(user):
    """Create (once) the user's project folder, share it 'anyone with link', return (id, link)."""
    if user.get("drive_folder_id") and user.get("drive_folder_link"):
        return user["drive_folder_id"], user["drive_folder_link"]
    at = _google_access_token(user)
    if not at:
        return "", ""
    hdr = {"Authorization": "Bearer " + at}
    ok, res, _ = _http_json(
        DRIVE_API + "/files",
        data={"name": PROJECT_FOLDER_NAME,
              "mimeType": "application/vnd.google-apps.folder"},
        headers=hdr)
    if not ok or not isinstance(res, dict) or not res.get("id"):
        return "", ""
    fid = res["id"]
    # share: anyone with the link can view/download
    _http_json(f"{DRIVE_API}/files/{fid}/permissions",
               data={"role": "reader", "type": "anyone"}, headers=hdr)
    link = f"https://drive.google.com/drive/folders/{fid}"
    db = get_db()
    db.execute("UPDATE users SET drive_folder_id=?, drive_folder_link=? WHERE id=?",
               (fid, link, user["id"]))
    db.commit()
    return fid, link


def _drive_upload_file(user, local_path, name):
    """Upload a local file into the user's project folder; return (file_id, view_link, download_link)."""
    at = _google_access_token(user)
    fid, _ = _drive_ensure_folder(user)
    if not at or not fid:
        return "", "", ""
    with open(local_path, "rb") as fh:
        content = fh.read()
    # multipart upload (metadata + media)
    boundary = "----sdb" + secrets.token_hex(8)
    meta = json.dumps({"name": name, "parents": [fid]}).encode()
    body = (b"--" + boundary.encode() + b"\r\n"
            b"Content-Type: application/json; charset=UTF-8\r\n\r\n" + meta + b"\r\n"
            b"--" + boundary.encode() + b"\r\n"
            b"Content-Type: application/octet-stream\r\n\r\n" + content + b"\r\n"
            b"--" + boundary.encode() + b"--\r\n")
    req = urllib.request.Request(
        DRIVE_UPLOAD_API + "?uploadType=multipart&fields=id,webViewLink",
        data=body, method="POST",
        headers={"Authorization": "Bearer " + at,
                 "Content-Type": f"multipart/related; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            res = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return "", "", ""
    dfid = res.get("id", "")
    if not dfid:
        return "", "", ""
    # make the file itself viewable/downloadable by anyone with the link
    _http_json(f"{DRIVE_API}/files/{dfid}/permissions",
               data={"role": "reader", "type": "anyone"},
               headers={"Authorization": "Bearer " + at})
    view = res.get("webViewLink") or f"https://drive.google.com/file/d/{dfid}/view"
    download = f"https://drive.google.com/uc?export=download&id={dfid}"
    return dfid, view, download


def _drive_delete_file(user, file_id):
    """Delete a file from the owner's Google Drive (best-effort)."""
    if not file_id:
        return
    at = _google_access_token(user)
    if not at:
        return
    try:
        _http_json(f"{DRIVE_API}/files/{file_id}", method="DELETE",
                   headers={"Authorization": "Bearer " + at})
    except Exception:
        pass


def _purge_item_storage(db, row):
    """When an item is removed from the app, delete its backing video file from
    EVERYWHERE it was stored: the local cache, Supabase Storage, and the owner's
    Google Drive. Best-effort — a failure on one backend never blocks the others."""
    keys = row.keys()
    fname = row["filename"] if ("filename" in keys) else None
    if fname:
        # local cache copy
        try:
            p = os.path.join(UPLOAD_DIR, fname)
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass
        # Supabase Storage copy
        _supabase_delete(fname)
    # Google Drive copy — needs the ORIGINAL owner's token
    dfid = row["drive_file_id"] if ("drive_file_id" in keys) else None
    if dfid:
        oid = row["owner_id"] if ("owner_id" in keys) else None
        orow = db.execute("SELECT * FROM users WHERE id=?", (oid,)).fetchone() if oid else None
        if orow:
            _drive_delete_file(dict(orow), dfid)


# =========================== Running-tasks registry ======================== #
# One global place every long-running job reports into, so the top bar can show
# it on every page. {task_id: {id, kind, label, user, percent, status, message}}
TASKS = {}
TASKS_CANCEL = {}


def task_new(kind, label, user=""):
    tid = kind + "_" + secrets.token_hex(4)
    TASKS[tid] = {"id": tid, "kind": kind, "label": label, "user": user,
                  "percent": 0, "status": "running", "message": "Starting…",
                  "started_at": datetime.utcnow().isoformat()}
    TASKS_CANCEL[tid] = False
    return tid


def task_update(tid, **kw):
    if tid in TASKS:
        TASKS[tid].update(kw)


def task_done(tid, ok=True, message="Completed"):
    if tid in TASKS:
        # if the task was cancelled, keep it marked cancelled (don't overwrite)
        if TASKS[tid].get("status") == "cancelled":
            TASKS[tid]["ended_at"] = datetime.utcnow().isoformat()
            return
        TASKS[tid].update({"status": "completed" if ok else "failed",
                           "percent": 100 if ok else TASKS[tid].get("percent", 0),
                           "message": message,
                           "ended_at": datetime.utcnow().isoformat()})


def task_cancelled(tid):
    """True if this task has been asked to cancel — long jobs poll this to stop."""
    return bool(TASKS_CANCEL.get(tid))


def task_mark_cancelled(tid, message="Cancelled."):
    if tid in TASKS:
        TASKS[tid].update({"status": "cancelled", "message": message,
                           "ended_at": datetime.utcnow().isoformat()})


@app.route("/api/tasks")
def api_tasks():
    u = require_login()
    me = str(u["id"])
    # prune tasks that finished a while ago so the bar doesn't grow forever
    now = datetime.utcnow()
    keep = {}
    for tid, t in TASKS.items():
        if t["status"] == "running":
            keep[tid] = t
        else:
            try:
                ended = datetime.fromisoformat(t.get("ended_at", t["started_at"]))
                if (now - ended).total_seconds() < 20:   # linger 20s after finishing
                    keep[tid] = t
            except Exception:
                keep[tid] = t
    TASKS.clear(); TASKS.update(keep)
    # Running tasks are PRIVATE: a user only sees the tasks THEY started.
    mine = [t for t in TASKS.values() if str(t.get("user") or "") == me]
    running = [t for t in mine if t["status"] == "running"]
    recent  = [t for t in mine if t["status"] != "running"]
    return jsonify({"running": running, "recent": recent,
                    "running_count": len(running)})


@app.route("/api/tasks/<tid>/cancel", methods=["POST"])
def api_task_cancel(tid):
    u = require_login()
    t = TASKS.get(tid)
    # only the task's owner (or an admin) may cancel it
    if t and str(t.get("user") or "") != str(u["id"]) and not is_super(u):
        return jsonify({"error": "You can only cancel your own tasks."}), 403
    TASKS_CANCEL[tid] = True
    task_mark_cancelled(tid, "Cancelled by user.")
    # if this is a download/install, the download loop also watches this flag
    for k in list(INSTALL_CANCEL.keys()):
        pass
    return jsonify({"ok": True})


# ============================= Presence / users ============================ #
def _touch_presence(user_id, activity=None):
    try:
        db = get_db()
        if activity is not None:
            db.execute("UPDATE users SET last_seen=?, current_activity=? WHERE id=?",
                       (datetime.utcnow().isoformat(), activity, user_id))
        else:
            db.execute("UPDATE users SET last_seen=? WHERE id=?",
                       (datetime.utcnow().isoformat(), user_id))
        db.commit()
    except Exception:
        pass


ONLINE_WINDOW = 70  # seconds since last_seen to count a user "online"


def _is_online(last_seen):
    if not last_seen:
        return False
    try:
        return (datetime.utcnow() - datetime.fromisoformat(last_seen)).total_seconds() < ONLINE_WINDOW
    except Exception:
        return False


@app.route("/api/heartbeat", methods=["POST"])
def api_heartbeat():
    u = current_user()
    if not u:
        return jsonify({"ok": False}), 401
    d = request.get_json(silent=True) or {}
    _touch_presence(u["id"], d.get("activity"))
    return jsonify({"ok": True})


@app.route("/api/presence")
def api_presence():
    me = require_login()
    db = get_db()
    ids = ws_member_ids(db, me)
    if ids is None:
        rows = db.execute("SELECT * FROM users ORDER BY username").fetchall()
    else:                         # a client only sees the people in its own workspace
        rows = db.execute(f"SELECT * FROM users WHERE id IN ({','.join('?' * len(ids))}) ORDER BY username",
                          ids).fetchall()
    users, online = [], 0
    can_manage = is_super(me)
    for r in rows:
        r = dict(r)
        on = _is_online(r.get("last_seen"))
        online += 1 if on else 0
        role = r.get("role") or "user"
        users.append({
            "id": r["id"],
            "username": r["username"],
            "display_name": r.get("display_name") or r["username"],
            "avatar": r.get("avatar") or "",
            "online": on,
            "last_seen": r.get("last_seen") or "",
            "activity": r.get("current_activity") or "",
            "google_connected": bool(r.get("google_connected")),
            "instagram_connected": bool(r.get("instagram_connected")),
            "role": role,
            "role_label": role_label(role),
            "name_with_role": name_with_role(r),
        })
    total = len(users)
    return jsonify({
        "total_users": total,
        "online": online,
        "offline": total - online,
        "active": online,     # "active" == currently online for this local app
        "can_manage": can_manage,   # SuperAdmin-only user management controls
        "users": users,
    })


@app.route("/api/users/<int:uid>", methods=["DELETE"])
def api_delete_user(uid):
    """
    Delete a user account (V28 role rules).
      • Only the SuperAdmin may delete another user's account.
      • Any user may delete ONLY their own account.
      • The SuperAdmin account itself can never be deleted (avoids lockout).
    Deleting your own account also logs you out.
    """
    me = require_login()
    is_super_me = is_super(me)
    is_self = (me["id"] == uid)
    if not (is_super_me or is_self):
        return jsonify({"error": "Only the SuperAdmin can manage other users."}), 403
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not target:
        return jsonify({"error": "User not found."}), 404
    # the SuperAdmin account is permanent — never deletable (even by itself)
    if (target["role"] or "user") == "superadmin":
        return jsonify({"error": "The SuperAdmin account can't be deleted."}), 400
    # don't allow removing the last remaining admin
    if (target["role"] or "user") == "admin":
        admins = db.execute(
            "SELECT COUNT(*) c FROM users WHERE role='admin'").fetchone()[0]
        if admins <= 1:
            return jsonify({"error": "Can't delete the last admin account."}), 400
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    db.commit()
    add_notification(db, f'User account "{target["username"]}" was deleted'
                         f'{"" if is_self else " by "+me["username"]}.', "remove", me["username"],
                     recipients=admin_ids(db))
    if is_self:
        session.clear()
    return jsonify({"ok": True, "self_deleted": is_self})


@app.route("/api/users/<int:uid>/password", methods=["POST"])
def api_change_user_password(uid):
    """
    Change / reset a user's password (V28 role rules).
      • The SuperAdmin may reset ANY user's password directly (no current
        password required) — this is the SuperAdmin "reset user password".
      • Any user may change ONLY their own password, and must supply their
        current password to do so.
      • Admins can NOT reset other users' passwords (SuperAdmin manages users).
    """
    me = require_login()
    is_super_me = is_super(me)
    is_self = (me["id"] == uid)
    if not (is_super_me or is_self):
        return jsonify({"error": "Only the SuperAdmin can reset another user's password."}), 403
    d = request.get_json(force=True)
    newpw = d.get("password") or ""
    perr = _validate_password(newpw)
    if perr:
        return jsonify({"error": perr}), 400
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not target:
        return jsonify({"error": "User not found."}), 404
    # a user changing their OWN password must supply the current one; the
    # SuperAdmin resetting someone else's does not.
    if is_self and not is_super_me:
        cur = d.get("current") or ""
        if target["password_hash"] and not verify_pw(target["password_hash"], cur):
            return jsonify({"error": "Your current password is incorrect."}), 400
    db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_pw(newpw), uid))
    db.commit()
    return jsonify({"ok": True})


# ===================== Access control (SuperAdmin only) ==================== #
@app.route("/api/access", methods=["GET", "POST"])
def api_access():
    """SuperAdmin: read/save which tabs Admins & Users can open (role defaults
    + optional per-user overrides)."""
    me = require_super()
    db = get_db()
    if request.method == "POST":
        d = request.get_json(force=True)
        # role defaults
        defaults = d.get("role_defaults") or {}
        for role in ("admin", "user"):
            if role in defaults and isinstance(defaults[role], list):
                clean = [k for k in ALL_TAB_KEYS if k in defaults[role]]
                set_setting(db, "access_role_" + role, json.dumps(clean))
        # per-user overrides: {uid: [tabs] | null}
        overrides = d.get("user_overrides") or {}
        for uid, tabs in overrides.items():
            try:
                uid = int(uid)
            except Exception:
                continue
            if tabs is None:
                db.execute("UPDATE users SET access_tabs=NULL WHERE id=?", (uid,))
            elif isinstance(tabs, list):
                clean = [k for k in ALL_TAB_KEYS if k in tabs]
                db.execute("UPDATE users SET access_tabs=? WHERE id=?",
                           (json.dumps(clean), uid))
        db.commit()
        return jsonify({"ok": True})

    rows = db.execute(
        "SELECT id, username, display_name, role, access_tabs FROM users "
        "WHERE role<>'superadmin' AND role<>'subuser' AND parent_id IS NULL "
        "ORDER BY role, username").fetchall()
    users = []
    for r in rows:
        r = dict(r)
        users.append({
            "id": r["id"], "username": r["username"],
            "display_name": r["display_name"] or r["username"],
            "role": r["role"] or "user",
            "name_with_role": name_with_role(r),
            "override": _user_override_tabs(r),   # None = uses role default
        })
    return jsonify({
        "tabs": [{"key": k, "label": lbl} for k, lbl in CONTROLLABLE_TABS],
        "role_defaults": {
            "admin": _role_default_tabs(db, "admin"),
            "user": _role_default_tabs(db, "user"),
        },
        "users": users,
    })


# ===================== Logins (SuperAdmin only) =========================== #
@app.route("/api/logins")
def api_logins():
    """SuperAdmin: full account details for every created user."""
    require_super()
    db = get_db()
    rows = db.execute("SELECT * FROM users ORDER BY role, username").fetchall()
    out = []
    for r in rows:
        r = dict(r)
        out.append({
            "id": r["id"],
            "username": r["username"],
            "display_name": r.get("display_name") or r["username"],
            "name_with_role": name_with_role(r),
            "role": r.get("role") or "user",
            "role_label": role_label(r.get("role")),
            "email": r.get("email") or "",
            "phone": r.get("phone") or "",
            "created_at": r.get("created_at") or "",
            "last_seen": r.get("last_seen") or "",
            "online": _is_online(r.get("last_seen")),
            "google_connected": bool(r.get("google_connected")),
            "instagram_connected": bool(r.get("instagram_connected")),
            "google_account": r.get("google_email") or r.get("google_account") or "",
            "instagram_account": r.get("ig_username") or r.get("instagram_account") or "",
            "is_permanent": (r.get("role") in ("superadmin",)),
            "parent_id": r.get("parent_id"),
            "totp_enabled": bool(r.get("totp_enabled")),
            # SuperAdmin is always able to view credentials; others only if granted.
            "can_view_credentials": (r.get("role") == "superadmin")
                                    or bool(r.get("can_view_credentials")),
        })
    return jsonify({"users": out})


@app.route("/api/users/<int:uid>/creds-access", methods=["POST"])
def api_set_creds_access(uid):
    """SuperAdmin: grant/revoke a user's permission to VIEW the credentials
    area (OAuth app credentials + Claude API key). Off by default; the
    SuperAdmin always has access and can't be changed here."""
    require_super()
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not target:
        return jsonify({"error": "User not found."}), 404
    if (target["role"] or "user") == "superadmin":
        return jsonify({"error": "The SuperAdmin always has credential access."}), 400
    allow = bool((request.get_json(force=True) or {}).get("allow"))
    db.execute("UPDATE users SET can_view_credentials=? WHERE id=?",
               (1 if allow else 0, uid))
    db.commit()
    return jsonify({"ok": True, "can_view_credentials": allow})


# ============================ Connect endpoints ============================ #
def _superadmin_row(db):
    """The workspace SuperAdmin user row (the account that owns the shared
    Instagram + Google Drive connections)."""
    try:
        return db.execute("SELECT * FROM users WHERE role='superadmin' "
                          "ORDER BY id ASC LIMIT 1").fetchone()
    except Exception:
        return None


def _connections_payload(u):
    """Connection view for the current user.

    • SuperAdmin manages the workspace's own Instagram + Google Drive.
    • Admins and regular users see those SAME (SuperAdmin/workspace) connections
      as status — they don't connect their own accounts. This is why the
      SuperAdmin's IG + Drive show up as 'Connected' in the Admin panel, and why
      Admins have no personal Gmail/Google login.
    """
    view = u                    # everyone sees (and manages) only their own connections
    manage = True
    google = {
        "connected": bool(view.get("google_connected")),
        "account": view.get("google_email") or view.get("google_account") or "",
        "folder_link": view.get("drive_folder_link") or "",
        "mode": "live" if (view.get("google_token")) else ("demo" if view.get("google_connected") else ""),
    }
    instagram = {
        "connected": bool(view.get("instagram_connected")),
        "account": view.get("ig_username") or view.get("instagram_account") or "",
        "mode": "live" if (view.get("ig_token")) else ("demo" if view.get("instagram_connected") else ""),
    }
    return {"google": google, "instagram": instagram, "can_manage": manage}


@app.route("/api/connections")
def api_connections():
    u = require_login()
    return jsonify(_connections_payload(u))


@app.route("/api/connect/<provider>/start", methods=["POST"])
def api_connect_start(provider):
    """
    Begin an official OAuth connect. If real credentials are configured we
    return the official provider auth URL to open; otherwise we complete a
    safe DEMO connection immediately (so the flow is usable now and upgrades
    to real OAuth the moment credentials are added).
    """
    u = require_login()
    if provider in CRED_KEYS:
        return _social_connect_start(u, provider)
    if provider != "google":
        return jsonify({"error": "Unknown provider."}), 400
    cfg = _oauth_cfg()
    db = get_db()

    if provider == "google" and cfg["google_client_id"] and cfg["google_client_secret"]:
        state = secrets.token_urlsafe(16)
        set_setting(db, f"oauth_state_{state}", str(u["id"]))
        params = urllib.parse.urlencode({
            "client_id": cfg["google_client_id"],
            "redirect_uri": _redirect_base() + "/oauth/google/callback",
            "response_type": "code",
            "scope": GOOGLE_SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        })
        return jsonify({"mode": "live", "auth_url": f"{GOOGLE_AUTH_URL}?{params}"})

    # Instagram uses THIS user's OWN app credentials (each user connects their
    # own live account with their own Meta app — never the SuperAdmin's).
    ig_app_id = uget_setting(db, u["id"], "ig_app_id")
    ig_app_secret = uget_setting(db, u["id"], "ig_app_secret")
    if provider == "instagram" and ig_app_id and ig_app_secret:
        state = secrets.token_urlsafe(16)
        set_setting(db, f"oauth_state_{state}", str(u["id"]))
        params = urllib.parse.urlencode({
            "client_id": ig_app_id,
            "redirect_uri": _redirect_base() + "/oauth/instagram/callback",
            "response_type": "code",
            "scope": IG_SCOPES,
            "state": state,
        })
        return jsonify({"mode": "live", "auth_url": f"{IG_AUTH_URL}?{params}"})

    # ---- DEMO connect (no credentials configured yet) --------------------- #
    d = request.get_json(silent=True) or {}
    if provider == "google":
        acct = (d.get("account") or "").strip() or f"{u['username'].lower()}@gmail.com"
        folder = f"https://drive.google.com/drive/folders/demo-{u['id']}-{secrets.token_hex(3)}"
        db.execute("UPDATE users SET google_connected=1, google_account=?, google_email=?, "
                   "drive_folder_link=?, drive_folder_id=? WHERE id=?",
                   (acct, acct, folder, f"demo-{u['id']}", u["id"]))
    else:
        acct = (d.get("account") or "").strip() or f"@{u['username'].lower()}"
        if not acct.startswith("@"):
            acct = "@" + acct
        db.execute("UPDATE users SET instagram_connected=1, instagram_account=?, ig_username=? WHERE id=?",
                   (acct, acct, u["id"]))
    db.commit()
    add_notification(db, f'{u["username"]} connected {provider.title()} '
                         f'({"demo" if provider else ""} mode).', "info", u["username"],
                     recipients=owner_and_admins(db, u["id"]))
    return jsonify({"mode": "demo", "connections": _connections_payload(current_user())})


@app.route("/oauth/google/callback")
def oauth_google_callback():
    code = request.args.get("code", "")
    state = request.args.get("state", "")
    db = get_db()
    uid = get_setting(db, f"oauth_state_{state}")
    if not code or not uid:
        return _oauth_popup_close("Google connection failed. Please try again.")
    cfg = _oauth_cfg()
    ok, res, _ = _http_json(
        GOOGLE_TOKEN_URL,
        data=urllib.parse.urlencode({
            "code": code,
            "client_id": cfg["google_client_id"],
            "client_secret": cfg["google_client_secret"],
            "redirect_uri": _redirect_base() + "/oauth/google/callback",
            "grant_type": "authorization_code",
        }).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    if not ok or not isinstance(res, dict) or not res.get("access_token"):
        return _oauth_popup_close("Could not complete Google sign-in.")
    tok = {"access_token": res["access_token"],
           "refresh_token": res.get("refresh_token", ""),
           "expires_at": time.time() + int(res.get("expires_in", 3600))}
    # who is this
    ok2, info, _ = _http_json(GOOGLE_USERINFO,
                              headers={"Authorization": "Bearer " + tok["access_token"]})
    email = (info or {}).get("email", "") if ok2 else ""
    name  = (info or {}).get("name", "") if ok2 else ""
    db.execute("UPDATE users SET google_connected=1, google_account=?, google_email=?, "
               "google_token=?, avatar=COALESCE(avatar,?) WHERE id=?",
               (email or name, email, enc(json.dumps(tok)),
                (info or {}).get("picture", ""), uid))
    db.commit()
    # provision the Drive project folder now
    row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if row:
        _drive_ensure_folder(dict(row))
    set_setting(db, f"oauth_state_{state}", "")
    return _oauth_popup_close("Google Drive connected — you can close this window.", ok=True)


@app.route("/oauth/instagram/callback")
def oauth_instagram_callback():
    return _social_oauth_callback("instagram")



@app.route("/webhooks/instagram", methods=["GET", "POST"])
@app.route("/webhooks/meta", methods=["GET", "POST"])
def instagram_webhook():
    """Meta webhooks (Instagram + Facebook Page): real-time comments into the Inbox.

    Set INSTAGRAM_WEBHOOK_VERIFY_TOKEN in the environment and enter the same value
    as the "Verify token" in Meta Developers -> Webhooks. Meta only delivers
    webhooks to apps that are Live (published).
    """
    verify_token = (os.environ.get("INSTAGRAM_WEBHOOK_VERIFY_TOKEN") or
                    os.environ.get("META_WEBHOOK_VERIFY_TOKEN") or "").strip()

    if request.method == "GET":
        mode = request.args.get("hub.mode", "")
        token = request.args.get("hub.verify_token", "")
        challenge = request.args.get("hub.challenge", "")
        if verify_token and mode == "subscribe" and secrets.compare_digest(token, verify_token):
            return challenge, 200
        return "Verification failed", 403

    raw = request.get_data() or b""
    db = get_db()
    if not _meta_signature_ok(db, raw, request.headers.get("X-Hub-Signature-256", "")):
        return "Invalid signature", 403
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        payload = {}
    try:
        _handle_meta_webhook(db, payload)
    except Exception as e:  # noqa — never make Meta retry because of our own bug
        try: app.logger.warning(f"webhook processing failed: {e}")
        except Exception: pass
    return "EVENT_RECEIVED", 200


def _meta_app_secrets(db):
    """Every Meta app secret saved by any user (Instagram, Facebook, Threads)."""
    rows = db.execute("SELECT value FROM settings WHERE key LIKE ? OR key LIKE ? OR key LIKE ? OR key LIKE ?",
                      ("u%_ig_app_secret", "u%_fb_app_secret", "u%_th_app_secret", "plat_%_secret")).fetchall()
    out = [dec(r["value"]) for r in rows if r["value"]]
    out += [v for v in (get_setting(db, "ig_app_secret"),) if v]
    return [v for v in out if v]


def _meta_signature_ok(db, raw, header):
    import hmac
    if not header.startswith("sha256="):
        return False
    sig = header.split("=", 1)[1]
    for secret in _meta_app_secrets(db):
        mac = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if hmac.compare_digest(mac, sig):
            return True
    return False


def _target_by_remote(db, platform, remote_id):
    if not remote_id:
        return None
    return db.execute("SELECT * FROM post_targets WHERE platform=? AND status='published' AND "
                      "(remote_id=? OR remote_id LIKE ?)", (platform, remote_id, "%_" + remote_id)).fetchone()


def _handle_meta_webhook(db, payload):
    obj = payload.get("object")
    for entry in payload.get("entry", []) or []:
        for mev in entry.get("messaging", []) or []:
            try:
                _ingest_webhook_dm(db, obj, mev)
            except Exception:
                pass
        for ch in entry.get("changes", []) or []:
            v = ch.get("value") or {}
            if obj == "instagram" and ch.get("field") in ("comments", "live_comments"):
                t = _target_by_remote(db, "instagram", (v.get("media") or {}).get("id"))
                if not t:
                    continue
                frm = v.get("from") or {}
                acct = db.execute("SELECT account_name FROM social_accounts WHERE platform='instagram' "
                                  "AND account_id=?", (str(entry.get("id") or ""),)).fetchone()
                if acct and (frm.get("username") or "").lower() == (acct["account_name"] or "").lstrip("@").lower():
                    continue            # our own reply
                row = _cal_item(db, t["item_id"])
                _ingest_comments(db, t, row, [{"id": v.get("id"), "author": frm.get("username", ""),
                                               "text": v.get("text", ""), "parent": v.get("parent_id", ""),
                                               "created": _now()}])
            elif obj == "page" and ch.get("field") == "feed" and v.get("item") == "comment" and v.get("verb") == "add":
                frm = v.get("from") or {}
                if str(frm.get("id") or "") == str(entry.get("id") or ""):
                    continue            # the Page replying to itself
                t = _target_by_remote(db, "facebook", v.get("post_id")) or \
                    _target_by_remote(db, "facebook", (v.get("post_id") or "").split("_")[-1])
                if not t:
                    continue
                par = v.get("parent_id") or ""
                row = _cal_item(db, t["item_id"])
                _ingest_comments(db, t, row, [{"id": v.get("comment_id"), "author": frm.get("name", "Facebook user"),
                                               "text": v.get("message", ""),
                                               "parent": "" if par == v.get("post_id") else par,
                                               "created": _now()}])


def _ingest_webhook_dm(db, obj, mev):
    """A direct message arriving by webhook (Instagram "messages" / Page "messages")."""
    platform = {"instagram": "instagram", "page": "facebook"}.get(obj)
    msg = mev.get("message") or {}
    if not platform or not (msg.get("text") and msg.get("mid")):
        return
    sender, recipient = str((mev.get("sender") or {}).get("id") or ""), str((mev.get("recipient") or {}).get("id") or "")
    acc = db.execute("SELECT * FROM social_accounts WHERE platform=? AND mode='live' AND account_id IN (?,?)",
                     (platform, sender, recipient)).fetchone()
    if not acc:
        return
    acct = _decrypt_account(acc)
    participant = recipient if sender == str(acct["account_id"]) else sender
    prev = db.execute("SELECT participant_name FROM dm_messages WHERE account_id=? AND participant_id=? "
                      "AND participant_name<>'' LIMIT 1", (acct["id"], participant)).fetchone()
    ts = mev.get("timestamp")
    created = datetime.utcfromtimestamp(int(ts) / 1000).isoformat() if ts else _now()
    _store_dm(db, acct, participant, participant, prev["participant_name"] if prev else participant,
              {"id": msg["mid"], "from_id": sender, "from_name": "", "text": msg["text"], "created": created})
    db.commit()


# ---- Legal pages required by Meta / Google / TikTok app review ----------------
def _legal_ctx():
    base = (os.environ.get("PUBLIC_BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or request.host_url).rstrip("/")
    return {"company": os.environ.get("COMPANY_NAME") or "SocialPlatform",
            "contact": os.environ.get("CONTACT_EMAIL") or "",
            "base": base, "updated": "September 2026"}


_VERIFY_FILE = re.compile(r"^(tiktok|google|pinterest)[A-Za-z0-9_.-]{0,80}\.(txt|html)$")


@app.route("/<fname>")
def site_verification(fname):
    """Platform site-ownership files (TikTok URL properties, Google, Pinterest) at the
    site root. Drop them in static/verify/."""
    vdir = os.path.join(BASE_DIR, "static", "verify")
    if not _VERIFY_FILE.match(fname) or not os.path.isfile(os.path.join(vdir, fname)):
        abort(404)
    return send_from_directory(vdir, fname)


@app.route("/privacy")
def legal_privacy():
    return render_template("legal.html", page="privacy", **_legal_ctx())


@app.route("/terms")
def legal_terms():
    return render_template("legal.html", page="terms", **_legal_ctx())


@app.route("/data-deletion", methods=["GET"])
def legal_data_deletion():
    code = (request.args.get("code") or "").strip()
    status = None
    if code:
        raw = get_setting(get_db(), f"deletion_{code}")
        status = _jl(raw, None)
    return render_template("legal.html", page="deletion", code=code, status=status, **_legal_ctx())


def _parse_signed_request(db, signed):
    """Verify a Meta signed_request against any saved Meta app secret."""
    import base64
    import hmac

    def b64(s):
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    try:
        sig, payload = signed.split(".", 1)
        data = json.loads(b64(payload))
    except Exception:
        return None
    for secret in _meta_app_secrets(db):
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
        if hmac.compare_digest(expected, b64(sig)):
            return data
    return None


@app.route("/data-deletion/callback", methods=["POST"])
@app.route("/deauthorize/callback", methods=["POST"])
def meta_data_deletion_callback():
    """Meta "Data deletion request" + "Deauthorize" callback: removes the
    connection (tokens) for that Meta user and returns a status URL."""
    db = get_db()
    data = _parse_signed_request(db, request.form.get("signed_request", ""))
    if not data or not data.get("user_id"):
        return jsonify({"error": "Invalid signed_request."}), 400
    uid = str(data["user_id"])
    rows = db.execute("SELECT id, user_id, platform FROM social_accounts WHERE account_id=?", (uid,)).fetchall()
    for r in rows:
        db.execute("DELETE FROM social_accounts WHERE id=?", (r["id"],))
        if r["platform"] in LEGACY_COLS:
            c, acol, tcol, icol = LEGACY_COLS[r["platform"]]
            db.execute(f"UPDATE users SET {c}=0, {acol}='', {tcol}='', {icol}='' WHERE id=? AND {icol}=?",
                       (r["user_id"], uid))
    db.commit()
    code = secrets.token_hex(8)
    set_setting(db, f"deletion_{code}", json.dumps({"status": "completed", "removed": len(rows),
                                                   "at": _now()}))
    base = _legal_ctx()["base"]
    return jsonify({"url": f"{base}/data-deletion?code={code}", "confirmation_code": code})


def _oauth_popup_close(message, ok=False):
    color = "#0b8043" if ok else "#c5221f"
    return (f"""<!doctype html><html><head><meta charset="utf-8">
<title>Connection</title></head>
<body style="font-family:Segoe UI,Arial,sans-serif;background:#f4f8fd;
             display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
<div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:28px 34px;
            box-shadow:0 1px 3px rgba(16,24,40,.08);text-align:center;max-width:360px">
  <div style="font-size:15px;color:{color};font-weight:600;margin-bottom:6px">
    {'✓ Connected' if ok else 'Connection problem'}</div>
  <div style="color:#475569;font-size:13px">{message}</div>
</div>
<script>
  try {{ if (window.opener) {{ window.opener.postMessage({{sdb_oauth:true, ok:{str(ok).lower()}}}, "*"); }} }} catch(e) {{}}
  setTimeout(function(){{ window.close(); }}, {1200 if ok else 2600});
</script></body></html>""")


@app.route("/api/connect/<provider>/disconnect", methods=["POST"])
def api_connect_disconnect(provider):
    """Disconnect — only ever affects the CURRENT user's own connection."""
    u = require_login()
    db = get_db()
    if provider == "google":
        db.execute("UPDATE users SET google_connected=0, google_account='', google_email='', "
                   "google_token='', drive_folder_id='', drive_folder_link='' WHERE id=?", (u["id"],))
    elif provider == "instagram":
        db.execute("UPDATE users SET instagram_connected=0, instagram_account='', ig_username='', "
                   "ig_user_id='', ig_token='' WHERE id=?", (u["id"],))
        db.execute("DELETE FROM social_accounts WHERE user_id=? AND platform='instagram'", (u["id"],))
    else:
        return jsonify({"error": "Unknown provider."}), 400
    db.commit()
    return jsonify(_connections_payload(current_user()))


# -------- Credentials area (SuperAdmin sets these once, in the app) -------- #
# This is the single "Credentials" area. It holds the OAuth app credentials
# (Google / Instagram) AND the Claude API key + model + content-writing
# guidelines. It is visible ONLY to the SuperAdmin, or to an admin/user the
# SuperAdmin has explicitly granted "Can view credentials" (can_view_creds).
# Secrets (client secrets, API key) are NEVER echoed back — only a
# "…_set" boolean — and a blank value on save is ignored so the stored secret
# is preserved. Non-secret fields (client IDs, redirect base, model,
# guidelines) ARE returned so they don't appear blank after saving.
@app.route("/api/oauth/config", methods=["GET", "POST"])
def api_oauth_config():
    u = require_login()
    db = get_db()
    allowed = can_view_creds(u)
    if request.method == "POST":
        if not allowed:
            return jsonify({"error": "You don't have permission to change credentials. "
                                     "Ask your SuperAdmin."}), 403
        d = request.get_json(force=True)
        # Non-secret fields: always update to what's posted (may be blank).
        for k in ("google_client_id", "ig_app_id", "oauth_redirect_base",
                  "claude_model", "content_guidelines"):
            if k in d:
                set_setting(db, k, (d.get(k) or "").strip())
        # Secret fields: only overwrite when a non-empty value is provided, so
        # leaving the field blank keeps the previously saved secret.
        for k in ("google_client_secret", "ig_app_secret", "claude_api_key"):
            if k in d:
                v = (d.get(k) or "").strip()
                if v:
                    set_setting(db, k, v)
        _save_ai_settings(db, d)
        return jsonify({"ok": True})
    if not allowed:
        return jsonify({"allowed": False, "is_super": is_super(u),
                        "can_view_creds": False})
    cfg = _oauth_cfg()
    return jsonify({
        "allowed": True,
        "is_super": is_super(u),
        "can_view_creds": True,
        "google_client_id": cfg["google_client_id"],
        "google_secret_set": bool(cfg["google_client_secret"]),
        "ig_app_id": cfg["ig_app_id"],
        "ig_secret_set": bool(cfg["ig_app_secret"]),
        "oauth_redirect_base": cfg["redirect_base"],
        "claude_model": get_setting(db, "claude_model") or DEFAULT_CLAUDE_MODEL,
        "claude_key_set": bool(get_setting(db, "claude_api_key")),
        "ai": ai_settings_payload(db),
        "content_guidelines": get_setting(db, "content_guidelines") or "",
        # kept for older frontends that check is_admin
        "is_admin": True,
    })


# --------------------------------------------------------------------------- #
#  API : notifications
# --------------------------------------------------------------------------- #
def _notif_section(link, kind, message):
    """
    Map each notification to EXACTLY ONE section so its unread badge shows on
    only that sidebar (no duplicate counts). Anything item-specific goes to its
    section; only genuinely general items (chat mentions, access grants, system)
    fall under 'notifications'.
    """
    link = link or ""
    low = (message or "").lower()
    if link.startswith("video:"):
        return "input"
    if link.startswith("published:") or kind == "publish":
        return "published"
    if link.startswith(("openchat:", "chat:")):
        return "notifications"       # chat / @-mentions are general, not a board
    # calendar workflow: submit / approve / schedule / caption+hashtag generation
    if kind == "approval" or "approv" in low or "submitted for upload" in low \
       or "caption" in low or "hashtag" in low or "scheduled" in low:
        return "calendar"
    if "content writing" in low or "content generated" in low:
        return "content"
    if kind in ("upload", "remove"):
        return "input"
    return "notifications"


_IMPORTANT_KINDS = {"upload", "calendar", "approval", "publish",
                    "subscription", "remove", "content", "alert", "comment"}
_IMPORTANT_WORDS = ("publish", "scheduled", "waiting", "caption", "hashtag",
                    "content generat", "content ready", "subscription", "renew",
                    "uploaded", "input", "approved", "invoice", "payment")


def _is_important_notif(kind, message, link):
    """Only important/relevant events reach the Notifications panel (input &
    calendar updates, publishing, content-generation done, subscription/renewal,
    key system updates). Chat @-mentions belong in the messenger, not here."""
    k = (kind or "").lower()
    lnk = (link or "").lower()
    if lnk.startswith(("openchat:", "chat:")):
        return False
    if k in _IMPORTANT_KINDS:
        return True
    low = (message or "").lower()
    return any(w in low for w in _IMPORTANT_WORDS)


@app.route("/api/notifications")
def api_notifications():
    u = require_login()
    db = get_db()
    rows = db.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT 120").fetchall()
    read_ids = set(r[0] for r in db.execute(
        "SELECT notification_id FROM notification_reads WHERE user_id=?", (u["id"],)).fetchall())
    # per-user hidden ("deleted from my list") — never shown to this user again
    hidden_ids = set(r[0] for r in db.execute(
        "SELECT notification_id FROM notification_hidden WHERE user_id=?", (u["id"],)).fetchall())
    reply_counts = {r[0]: r[1] for r in db.execute(
        "SELECT notification_id, COUNT(*) FROM notification_replies GROUP BY notification_id").fetchall()}
    uid_str = str(u["id"])
    items, sections, unread = [], {}, 0
    for r in rows:
        if r["id"] in hidden_ids:
            continue
        # audience gate: NULL/'all' → everyone; else only listed user ids.
        aud = (r["audience"] if "audience" in r.keys() else None) or "all"
        if aud != "all" and uid_str not in set(aud.split(",")):
            continue
        # importance gate: only important/relevant notifications reach the panel
        if not _is_important_notif(r["kind"], r["message"], r["link"]):
            continue
        d = dict(r)
        d["read"] = r["id"] in read_ids
        d["reply_count"] = reply_counts.get(r["id"], 0)
        d["section"] = _notif_section(r["link"], r["kind"], r["message"])
        if not d["read"]:
            unread += 1
            sections[d["section"]] = sections.get(d["section"], 0) + 1
        items.append(d)
    return jsonify({"notifications": items[:80], "unread": unread, "sections": sections})


@app.route("/api/notifications/<int:nid>/hide", methods=["POST"])
def api_notification_hide(nid):
    """Delete a notification from MY list only (doesn't affect other users)."""
    u = require_login()
    db = get_db()
    db.execute("INSERT OR IGNORE INTO notification_hidden (notification_id, user_id) VALUES (?,?)",
               (nid, u["id"]))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/notifications/hide-bulk", methods=["POST"])
def api_notifications_hide_bulk():
    """Delete several notifications from MY list only."""
    u = require_login()
    db = get_db()
    ids = [int(x) for x in (request.get_json(force=True).get("ids") or [])]
    for nid in ids:
        db.execute("INSERT OR IGNORE INTO notification_hidden (notification_id, user_id) VALUES (?,?)",
                   (nid, u["id"]))
    db.commit()
    return jsonify({"ok": True, "hidden": len(ids)})


@app.route("/api/notifications/<int:nid>/read", methods=["POST"])
def api_notification_read(nid):
    u = require_login()
    db = get_db()
    db.execute("INSERT OR IGNORE INTO notification_reads (notification_id, user_id) VALUES (?,?)",
               (nid, u["id"]))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/notifications/read-all", methods=["POST"])
def api_notifications_read_all():
    u = require_login()
    db = get_db()
    db.execute("INSERT OR IGNORE INTO notification_reads (notification_id, user_id) "
               "SELECT id, ? FROM notifications", (u["id"],))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/notifications/<int:nid>/replies")
def api_notification_replies(nid):
    require_login()
    db = get_db()
    rows = db.execute("SELECT * FROM notification_replies WHERE notification_id=? ORDER BY id ASC",
                      (nid,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try: d["files"] = json.loads(r["files"]) if r["files"] else []
        except Exception: d["files"] = []
        out.append(d)
    return jsonify({"replies": out})


def _notify_mentions(db, text, actor, link, u=None):
    """Parse @username mentions and notify each mentioned user (same workspace only)."""
    for uname in set(re.findall(r"@([A-Za-z0-9_.\-]+)", text or "")):
        row = db.execute("SELECT id, username FROM users WHERE lower(username)=lower(?)", (uname,)).fetchone()
        if row and (u is None or in_ws(db, u, row["id"])):
            add_notification(db, f'💬 {actor} mentioned you: "{(text or "")[:80]}"',
                             "comment", actor, link=link, recipients=[row["id"]])


@app.route("/api/notifications/<int:nid>/replies", methods=["POST"])
def api_add_notification_reply(nid):
    u = require_login()
    db = get_db()
    # accept JSON (text only) OR multipart (text + unlimited files/screenshots)
    files = []
    if request.files:
        for f in request.files.getlist("files"):
            if f and f.filename:
                files.append("/uploads/" + _safe_save(f))
        text = (request.form.get("text") or "").strip()
    else:
        d = request.get_json(silent=True) or {}
        text = (d.get("text") or "").strip()
    if not text and not files:
        return jsonify({"error": "Enter a message or attach a file."}), 400
    db.execute("INSERT INTO notification_replies (notification_id, author, author_id, text, files, created_at) "
               "VALUES (?,?,?,?,?,?)",
               (nid, u["username"], u["id"], text, json.dumps(files), datetime.utcnow().isoformat()))
    # a reply is a new update for everyone else — resurface it as unread
    db.execute("DELETE FROM notification_reads WHERE notification_id=? AND user_id<>?", (nid, u["id"]))
    db.commit()
    _notify_mentions(db, text, u["username"], f"chat:{nid}", u)
    return jsonify({"ok": True})


@app.route("/api/notifications/<int:nid>/replies/<int:rid>", methods=["DELETE"])
def api_delete_reply(nid, rid):
    """Delete a chat message — its author or an admin only."""
    u = require_login()
    db = get_db()
    row = db.execute("SELECT * FROM notification_replies WHERE id=? AND notification_id=?",
                     (rid, nid)).fetchone()
    if not row:
        return jsonify({"error": "Not found."}), 404
    if row["author_id"] != u["id"] and not (is_super(u) or (is_primary_user(u) and in_ws(db, u, row["author_id"]))):
        return jsonify({"error": "You can only delete your own messages."}), 403
    db.execute("DELETE FROM notification_replies WHERE id=?", (rid,))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/notifications/<int:nid>", methods=["DELETE"])
def api_delete_notification(nid):
    """Delete a whole chat/notification — admin, or the user who created it."""
    u = require_login()
    db = get_db()
    row = db.execute("SELECT * FROM notifications WHERE id=?", (nid,)).fetchone()
    if not row:
        return jsonify({"error": "Not found."}), 404
    if not is_super(u):
        # clients remove it from their own list; the notification stays for others
        db.execute("INSERT OR IGNORE INTO notification_hidden (notification_id, user_id) VALUES (?,?)",
                   (nid, u["id"]))
        db.commit()
        return jsonify({"ok": True, "hidden": True})
    db.execute("DELETE FROM notifications WHERE id=?", (nid,))
    db.execute("DELETE FROM notification_replies WHERE notification_id=?", (nid,))
    db.execute("DELETE FROM notification_reads WHERE notification_id=?", (nid,))
    db.commit()
    return jsonify({"ok": True})


# ================= Voice / video call signaling (WebRTC) ==================== #
# Simple per-user in-memory mailbox. Peers exchange SDP offers/answers and ICE
# candidates by polling. NOTE: browsers require a SECURE context (HTTPS, or
# localhost) to grant camera/microphone — over plain http on a LAN the call
# UI connects but media may be blocked by the browser.
CALL_MAILBOX = {}       # {user_id: [ {from, from_name, type, data, ts} ]}


@app.route("/api/calls/signal", methods=["POST"])
def api_call_signal():
    u = require_login()
    d = request.get_json(force=True)
    to = int(d.get("to") or 0)
    if not to or not in_ws(get_db(), u, to):
        return jsonify({"error": "Missing target user."}), 400
    CALL_MAILBOX.setdefault(to, []).append({
        "from": u["id"], "from_name": u.get("display_name") or u["username"],
        "type": d.get("type"), "data": d.get("data"),
    })
    return jsonify({"ok": True})


@app.route("/api/calls/poll")
def api_call_poll():
    u = require_login()
    msgs = CALL_MAILBOX.pop(u["id"], [])
    return jsonify({"messages": msgs})


@app.route("/api/notifications/clear", methods=["POST"])
def api_notifications_clear():
    """Mark all of MY notifications as read (per-user). Does not delete others'."""
    u = require_login()
    db = get_db()
    db.execute("INSERT OR IGNORE INTO notification_reads (notification_id, user_id) "
               "SELECT id, ? FROM notifications", (u["id"],))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/notifications/bulk-delete", methods=["POST"])
def api_notifications_bulk_delete():
    """Bulk-delete notifications (their chats too). Admin, or ones you started."""
    u = require_login()
    db = get_db()
    ids = request.get_json(force=True).get("ids") or []
    ids = [int(x) for x in ids]
    if not ids:
        return jsonify({"ok": True, "deleted": 0})
    admin_like = is_super(u)
    deleted = 0
    for nid in ids:
        row = db.execute("SELECT * FROM notifications WHERE id=?", (nid,)).fetchone()
        if not row:
            continue
        if not admin_like:               # clients only hide it from their own list
            db.execute("INSERT OR IGNORE INTO notification_hidden (notification_id, user_id) VALUES (?,?)",
                       (nid, u["id"]))
            deleted += 1
            continue
        if admin_like:
            db.execute("DELETE FROM notifications WHERE id=?", (nid,))
            db.execute("DELETE FROM notification_replies WHERE notification_id=?", (nid,))
            db.execute("DELETE FROM notification_reads WHERE notification_id=?", (nid,))
            deleted += 1
    db.commit()
    return jsonify({"ok": True, "deleted": deleted})


# =========================================================================== #
#  V20 : Messenger-style chat (1:1, group, and video-linked conversations)
# =========================================================================== #
def _conv_summary(db, conv, uid):
    """Build a conversation summary for the current user."""
    members = db.execute(
        "SELECT u.id, u.username, u.display_name, u.role FROM conversation_members m "
        "JOIN users u ON u.id=m.user_id WHERE m.conversation_id=?", (conv["id"],)).fetchall()
    members = [dict(x) for x in members]
    last = db.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT 1",
                      (conv["id"],)).fetchone()
    mrow = db.execute("SELECT last_read_id FROM conversation_members WHERE conversation_id=? AND user_id=?",
                      (conv["id"], uid)).fetchone()
    last_read = mrow["last_read_id"] if mrow else 0
    unread = db.execute("SELECT COUNT(*) FROM messages WHERE conversation_id=? AND id>? AND author_id<>?",
                        (conv["id"], last_read, uid)).fetchone()[0]
    # display title: group -> title; video -> "🎬 <video title>"; 1:1 -> the other person
    if conv["video_id"]:
        vr = db.execute("SELECT title FROM videos WHERE id=?", (conv["video_id"],)).fetchone()
        title = "🎬 " + (vr["title"] if vr else "Video")
    elif conv["is_group"]:
        title = conv["title"] or "Group"
    else:
        others = [m for m in members if m["id"] != uid]
        title = (others[0]["display_name"] or others[0]["username"]) if others else "Chat"
    return {
        "id": conv["id"], "title": title, "is_group": bool(conv["is_group"]),
        "video_id": conv["video_id"], "members": members,
        "last_text": (last["text"] if last else "") or (("📎 attachment" if last and last["files"] and last["files"] != "[]" else "")),
        "last_at": last["created_at"] if last else conv["created_at"],
        "last_author": last["author"] if last else "",
        "unread": unread,
    }


def _my_conversations(db, uid):
    convs = db.execute(
        "SELECT c.* FROM conversations c JOIN conversation_members m ON m.conversation_id=c.id "
        "WHERE m.user_id=? ORDER BY c.id DESC", (uid,)).fetchall()
    out = [_conv_summary(db, c, uid) for c in convs]
    out.sort(key=lambda x: x["last_at"] or "", reverse=True)
    return out


@app.route("/api/chat/conversations")
def api_chat_conversations():
    u = require_login()
    db = get_db()
    convs = _my_conversations(db, u["id"])
    total_unread = sum(c["unread"] for c in convs)
    return jsonify({"conversations": convs, "unread": total_unread})


@app.route("/api/chat/conversations", methods=["POST"])
def api_chat_create():
    u = require_login()
    db = get_db()
    d = request.get_json(force=True)
    member_ids = [int(x) for x in (d.get("member_ids") or []) if in_ws(db, u, int(x))]
    member_ids = list({*member_ids, u["id"]})           # always include me
    is_group = 1 if (d.get("is_group") or len(member_ids) > 2) else 0
    title = (d.get("title") or "").strip()
    if len(member_ids) < 2:
        return jsonify({"error": "Pick at least one person to chat with."}), 400
    # dedupe a 1:1 conversation
    if not is_group and len(member_ids) == 2:
        existing = db.execute(
            "SELECT c.id FROM conversations c "
            "WHERE c.is_group=0 AND c.video_id IS NULL AND "
            "(SELECT COUNT(*) FROM conversation_members m WHERE m.conversation_id=c.id)=2 AND "
            "(SELECT COUNT(*) FROM conversation_members m WHERE m.conversation_id=c.id AND m.user_id IN (?,?))=2",
            tuple(member_ids)).fetchone()
        if existing:
            return jsonify({"id": existing["id"]})
    cur = db.execute("INSERT INTO conversations (title, is_group, created_by, created_at) VALUES (?,?,?,?)",
                     (title, is_group, u["id"], datetime.utcnow().isoformat()))
    cid = cur.lastrowid
    for m in member_ids:
        db.execute("INSERT OR IGNORE INTO conversation_members (conversation_id, user_id) VALUES (?,?)", (cid, m))
    db.commit()
    return jsonify({"id": cid})


def _ensure_video_conversation(db, video_id, uid):
    conv = db.execute("SELECT * FROM conversations WHERE video_id=?", (video_id,)).fetchone()
    if not conv:
        cur = db.execute("INSERT INTO conversations (title, is_group, video_id, created_by, created_at) "
                         "VALUES (?,?,?,?,?)", ("", 1, video_id, uid, datetime.utcnow().isoformat()))
        cid = cur.lastrowid
        # seed members: the video owner + its workspace owner + whoever opened it
        vrow = db.execute("SELECT owner_id FROM videos WHERE id=?", (video_id,)).fetchone()
        seed = set()
        if vrow and vrow["owner_id"]:
            seed.add(vrow["owner_id"])
            ws = ws_owner_id(db, vrow["owner_id"])
            if ws:
                seed.add(ws)
        seed.add(uid)
        for m in seed:
            db.execute("INSERT OR IGNORE INTO conversation_members (conversation_id, user_id) VALUES (?,?)", (cid, m))
        db.commit()
    else:
        cid = conv["id"]
        db.execute("INSERT OR IGNORE INTO conversation_members (conversation_id, user_id) VALUES (?,?)", (cid, uid))
        db.commit()
    return cid


@app.route("/api/chat/video/<int:vid>")
def api_chat_for_video(vid):
    u = require_login()
    db = get_db()
    if not db.execute("SELECT 1 FROM videos WHERE id=?", (vid,)).fetchone():
        return jsonify({"error": "Not found."}), 404
    return jsonify({"id": _ensure_video_conversation(db, vid, u["id"])})


def _is_member(db, cid, uid):
    return db.execute("SELECT 1 FROM conversation_members WHERE conversation_id=? AND user_id=?",
                      (cid, uid)).fetchone() is not None


@app.route("/api/chat/conversations/<int:cid>/messages")
def api_chat_messages(cid):
    u = require_login()
    db = get_db()
    if not _is_member(db, cid, u["id"]):
        return jsonify({"error": "Not a member of this chat."}), 403
    rows = db.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY id ASC", (cid,)).fetchall()
    out = []
    for r in rows:
        m = dict(r)
        try: m["files"] = json.loads(r["files"]) if r["files"] else []
        except Exception: m["files"] = []
        out.append(m)
    # mark read up to the latest message
    if rows:
        db.execute("UPDATE conversation_members SET last_read_id=? WHERE conversation_id=? AND user_id=?",
                   (rows[-1]["id"], cid, u["id"]))
        db.commit()
    conv = db.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
    return jsonify({"messages": out, "conversation": _conv_summary(db, conv, u["id"])})


@app.route("/api/chat/conversations/<int:cid>/messages", methods=["POST"])
def api_chat_send(cid):
    u = require_login()
    db = get_db()
    if not _is_member(db, cid, u["id"]):
        return jsonify({"error": "Not a member of this chat."}), 403
    files = []
    if request.files:
        for f in request.files.getlist("files"):
            if f and f.filename:
                files.append("/uploads/" + _safe_save(f))
        text = (request.form.get("text") or "").strip()
    else:
        text = ((request.get_json(silent=True) or {}).get("text") or "").strip()
    if not text and not files:
        return jsonify({"error": "Type a message or attach a file."}), 400
    now = datetime.utcnow().isoformat()
    cur = db.execute("INSERT INTO messages (conversation_id, author_id, author, text, files, created_at) "
                     "VALUES (?,?,?,?,?,?)", (cid, u["id"], u["username"], text, json.dumps(files), now))
    db.execute("UPDATE conversation_members SET last_read_id=? WHERE conversation_id=? AND user_id=?",
               (cur.lastrowid, cid, u["id"]))
    db.commit()
    # @-mentions -> add them to the chat + notify
    for uname in set(re.findall(r"@([A-Za-z0-9_.\-]+)", text or "")):
        mrow = db.execute("SELECT id, username FROM users WHERE lower(username)=lower(?)", (uname,)).fetchone()
        if mrow and in_ws(db, u, mrow["id"]):          # can't pull other clients into a chat
            db.execute("INSERT OR IGNORE INTO conversation_members (conversation_id, user_id) VALUES (?,?)",
                       (cid, mrow["id"]))
            db.commit()
            add_notification(db, f'💬 {u["username"]} mentioned you in a chat: "{(text or "")[:70]}"',
                             "comment", u["username"], link=f"openchat:{cid}",
                             recipients=[mrow["id"]])
    return jsonify({"ok": True, "id": cur.lastrowid})


@app.route("/api/chat/messages/<int:mid>", methods=["DELETE"])
def api_chat_delete_message(mid):
    u = require_login()
    db = get_db()
    row = db.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
    if not row:
        return jsonify({"error": "Not found."}), 404
    if row["author_id"] != u["id"] and not (is_super(u) or (is_primary_user(u) and in_ws(db, u, row["author_id"]))):
        return jsonify({"error": "You can only delete your own messages."}), 403
    db.execute("DELETE FROM messages WHERE id=?", (mid,))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/chat/inprogress-videos")
def api_chat_inprogress():
    """Videos to offer for #referencing in chat (active = not completed)."""
    u = require_login()
    db = get_db()
    wq, wa = ws_sql(db, u)
    rows = db.execute("SELECT id, title, status FROM videos WHERE status<>'completed'" + wq +
                      " ORDER BY updated_at DESC LIMIT 50", wa).fetchall()
    return jsonify({"videos": [dict(r) for r in rows]})


# =========================================================================== #
#  V31 : API — Setup / connections (all 8 platforms)
# =========================================================================== #
def _guide_url(key):
    gdir = os.path.join(BASE_DIR, "static", "guides")
    return f"/guides/{key}.pdf" if os.path.exists(os.path.join(gdir, f"{key}.pdf")) else ""


def _platform_status(db, u, key):
    brand = _rget(u, "active_brand_id")
    owner = social_owner_id(db, u["id"])
    a = _account_for_user(db, owner, key, brand) or _legacy_account(db, owner, key)
    if not a or a.get("mode") != "live" or not a.get("token"):
        return {"connected": False, "mode": "", "account": "", "status": "", "managed_by_admin": owner != u["id"]}
    extra = _jl(a.get("extra"), {})
    st = a.get("status") or "ok"
    if a.get("mode") == "live" and a.get("expires_at") and float(a["expires_at"]) < time.time():
        st = "expired"
        # short-lived tokens (YouTube 1h, X 2h) renew with the refresh token — only
        # report "expired" when that renewal actually fails
        if a.get("refresh_token") and a.get("id"):
            try:
                h = _ensure_fresh(db, _hydrate_account(db, a))
                if h.get("expires_at") and float(h["expires_at"]) > time.time():
                    st, a["expires_at"], a["last_error"] = "ok", h["expires_at"], ""
            except Exception:  # noqa
                pass
    return {"connected": True, "mode": a.get("mode") or "live", "account": a.get("account_name") or "",
            "status": st, "account_row_id": a.get("id"), "expires_at": a.get("expires_at"),
            "last_error": a.get("last_error") or "",
            "pages": [{"id": x["id"], "name": x.get("name")} for x in extra.get("pages", [])],
            "page_id": a.get("account_id") if key == "facebook" else "",
            "boards": extra.get("boards", []), "board_id": extra.get("board_id", ""),
            "imported_at": a.get("imported_at") or "", "managed_by_admin": owner != u["id"]}


@app.route("/api/platforms")
def api_platforms():
    u = require_login()
    db = get_db()
    out = []
    base = _redirect_base()
    for key in SOCIAL:
        spec = P.PLATFORMS[key]
        ik, sk = CRED_KEYS[key]
        platform_ready = bool(get_setting(db, f"plat_{key}_app_id") and get_setting(db, f"plat_{key}_app_secret"))
        if is_super(u):            # the SuperAdmin edits the platform-wide app for everyone
            app_id = get_setting(db, f"plat_{key}_app_id") or ""
            secret_set = bool(get_setting(db, f"plat_{key}_app_secret"))
        else:                      # a client may optionally bring their own app
            app_id = uget_setting(db, u["id"], ik) or ""
            secret_set = bool(uget_setting(db, u["id"], sk))
        cid, csec, src = app_creds(db, u["id"], key)
        st = _platform_status(db, u, key)
        out.append(dict(st, **{
            "key": key, "label": spec["label"], "id_label": spec["id_label"], "secret_label": spec["secret_label"],
            "app_id": app_id, "secret_set": secret_set, "installed": bool(cid and csec),
            "source": src, "platform_ready": platform_ready, "is_super": is_super(u),
            "redirect_uri": f"{base}/oauth/{key}/callback", "guide": _guide_url(key),
            "supports": spec["supports"], "caption_max": spec["caption_max"],
            "allowed": key in _allowed_platforms(u)}))
    return jsonify({"platforms": out, "can_manage_creds": True, "can_view_creds": can_view_creds(u),
                    "social_mode": ws_social_mode(db, billing_user_id(u)), "social_locked": social_locked(db, u),
                    "is_ws_admin": is_primary_user(u),
                    "redirect_base": get_setting(db, "oauth_redirect_base") or "",
                    "public_base_url": get_setting(db, "public_base_url") or "",
                    "supabase_storage": USE_SUPABASE_STORAGE})


@app.route("/api/platforms/<plat>/creds", methods=["POST"])
def api_platform_creds(plat):
    u = require_login()
    if plat not in CRED_KEYS:
        return jsonify({"error": "Unknown platform."}), 400
    db = get_db()
    if social_locked(db, u):
        return jsonify({"error": LOCKED_MSG}), 403
    d = request.get_json(force=True) or {}
    ik, sk = CRED_KEYS[plat]
    if is_super(u):                # platform-wide app: every client connects through it
        if "app_id" in d:
            set_setting(db, f"plat_{plat}_app_id", (d.get("app_id") or "").strip())
        if d.get("app_secret"):
            set_setting(db, f"plat_{plat}_app_secret", d["app_secret"].strip())
    else:
        if "app_id" in d:
            uset_setting(db, u["id"], ik, (d.get("app_id") or "").strip())
        if d.get("app_secret"):
            uset_setting(db, u["id"], sk, d["app_secret"].strip())
    log_activity(db, u, "credentials_saved", "platform", None, P.PLATFORMS[plat]["label"])
    return jsonify({"ok": True})


@app.route("/api/platforms/<plat>/connect", methods=["POST"])
def api_platform_connect(plat):
    """Accounts connect only through the platform's real sign-in (OAuth)."""
    require_login()
    if plat not in CRED_KEYS:
        return jsonify({"error": "Unknown platform."}), 400
    return jsonify({"error": "Connect through the real sign-in: add the App ID and Secret in Setup, "
                             "then click Connect."}), 400


@app.route("/api/platforms/<plat>/disconnect", methods=["POST"])
def api_platform_disconnect(plat):
    u = require_login()
    if plat not in CRED_KEYS:
        return jsonify({"error": "Unknown platform."}), 400
    db = get_db()
    if social_locked(db, u):
        return jsonify({"error": LOCKED_MSG}), 403
    brand = _rget(u, "active_brand_id")
    if brand:
        db.execute("DELETE FROM social_accounts WHERE user_id=? AND platform=? AND brand_id=?", (u["id"], plat, brand))
    else:
        db.execute("DELETE FROM social_accounts WHERE user_id=? AND platform=? AND brand_id IS NULL", (u["id"], plat))
    if plat in LEGACY_COLS and not brand:
        c, acol, tcol, icol = LEGACY_COLS[plat]
        db.execute(f"UPDATE users SET {c}=0, {acol}='', {tcol}='', {icol}='' WHERE id=?", (u["id"],))
        if plat == "instagram":
            db.execute("UPDATE users SET instagram_account='' WHERE id=?", (u["id"],))
    db.commit()
    log_activity(db, u, "disconnected", "platform", None, P.PLATFORMS[plat]["label"])
    return jsonify({"ok": True, "connected": False})


@app.route("/api/platforms/<plat>/option", methods=["POST"])
def api_platform_option(plat):
    """Pick which Facebook Page / Pinterest board a connection posts to."""
    u = require_login()
    db = get_db()
    if social_locked(db, u):
        return jsonify({"error": LOCKED_MSG}), 403
    a = _account_for_user(db, u["id"], plat, _rget(u, "active_brand_id"))
    if not a:
        return jsonify({"error": "Connect the account first."}), 400
    d = request.get_json(force=True) or {}
    extra = _jl(a.get("extra"), {})
    if plat == "facebook" and d.get("page_id"):
        pg = next((x for x in extra.get("pages", []) if x["id"] == d["page_id"]), None)
        if not pg:
            return jsonify({"error": "Page not found."}), 404
        db.execute("UPDATE social_accounts SET account_id=?, account_name=?, token=? WHERE id=?",
                   (pg["id"], pg.get("name", ""), enc(pg.get("token", "")), a["id"]))
    elif plat == "pinterest" and d.get("board_id"):
        extra["board_id"] = d["board_id"]
        db.execute("UPDATE social_accounts SET extra=? WHERE id=?", (enc(json.dumps(extra)), a["id"]))
    db.commit()
    return jsonify({"ok": True})


def _social_connect_start(u, provider):
    db = get_db()
    if social_locked(db, u):
        return jsonify({"error": LOCKED_MSG}), 403
    cid, secret, _src = app_creds(db, u["id"], provider)
    if cid and secret:
        state = secrets.token_urlsafe(16)
        verifier, challenge = P.pkce_pair()
        set_setting(db, f"oauth_state_{state}", json.dumps({
            "uid": u["id"], "platform": provider, "verifier": verifier, "brand": _rget(u, "active_brand_id")}))
        url = P.oauth_url(provider, cid, f"{_redirect_base()}/oauth/{provider}/callback", state, challenge)
        return jsonify({"mode": "live", "auth_url": url})
    label = P.PLATFORMS[provider]["label"]
    if is_super(u):
        return jsonify({"error": f"Add the {label} App ID and Secret first (see the Guide), then click Connect."}), 400
    return jsonify({"error": f"{label} isn't set up on this workspace yet. Ask your administrator, "
                             f"or add your own {label} app credentials."}), 400


def _social_oauth_callback(platform_key):
    code, state = request.args.get("code", ""), request.args.get("state", "")
    db = get_db()
    raw = get_setting(db, f"oauth_state_{state}") if state else ""
    try:
        st = json.loads(raw) if raw else None
    except Exception:
        st = None
    if not st and raw and raw.isdigit():               # pre-V31 Instagram state format
        st = {"uid": int(raw), "platform": platform_key, "verifier": "", "brand": None}
    label = P.PLATFORMS.get(platform_key, {}).get("label", platform_key.title())
    if request.args.get("error"):
        return _oauth_popup_close(f"{label}: {request.args.get('error_description') or request.args.get('error')}")
    if not code or not st:
        return _oauth_popup_close(f"{label} connection failed (session expired). Please try again.")
    uid = int(st["uid"])
    cid_, sec_, _src = app_creds(db, uid, platform_key)
    try:
        info = P.exchange_code(platform_key, cid_, sec_, code,
                               f"{_redirect_base()}/oauth/{platform_key}/callback", st.get("verifier"))
    except P.PlatformError as e:
        return _oauth_popup_close(f"Could not complete {label} sign-in. {e}")
    except Exception as e:  # noqa
        return _oauth_popup_close(f"Could not complete {label} sign-in. {e}")
    _save_account(db, uid, platform_key, info, mode="live", brand_id=st.get("brand"))
    set_setting(db, f"oauth_state_{state}", "")
    acc = db.execute("SELECT id FROM social_accounts WHERE user_id=? AND platform=? ORDER BY id DESC LIMIT 1",
                     (uid, platform_key)).fetchone()
    if acc:                 # pull in past posts, stats and messages in the background
        threading.Thread(target=_bg_import_and_snapshot, args=(acc["id"],), daemon=True).start()
    urow = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    log_activity(db, dict(urow) if urow else None, "connected", "platform", None,
                 f"{label} ({info.get('account_name', '')})")
    return _oauth_popup_close(f"{label} connected — {info.get('account_name', '')}. You can close this window.", ok=True)


@app.route("/oauth/<platform_key>/callback")
def oauth_social_callback(platform_key):
    if platform_key not in CRED_KEYS:
        abort(404)
    return _social_oauth_callback(platform_key)


# =========================================================================== #
#  V31 : API — calendar item actions
# =========================================================================== #
def _cal_item(db, cid):
    return db.execute("SELECT * FROM calendar_items WHERE id=?", (cid,)).fetchone()


def _targets_for(db, item_ids):
    out = {}
    if not item_ids:
        return out
    q = ",".join("?" * len(item_ids))
    for t in db.execute(f"SELECT * FROM post_targets WHERE item_id IN ({q}) ORDER BY id", list(item_ids)).fetchall():
        d = dict(t)
        d["label"] = P.PLATFORMS.get(d["platform"], {}).get("label", d["platform"])
        out.setdefault(d["item_id"], []).append(d)
    return out


@app.route("/api/calendar/<int:cid>/checks")
def api_calendar_checks(cid):
    require_login()
    db = get_db()
    row = _cal_item(db, cid)
    if not row:
        return jsonify({"error": "Not found."}), 404
    checks, info = format_checks(db, row)
    return jsonify({"checks": checks, "media_info": info or {}, "kind": _item_kind(row),
                    "variants": _jl(_rget(row, "variants"), {})})


@app.route("/api/calendar/<int:cid>/convert", methods=["POST"])
def api_calendar_convert(cid):
    u = require_login()
    db = get_db()
    row = _cal_item(db, cid)
    if not row:
        return jsonify({"error": "Not found."}), 404
    d = request.get_json(force=True) or {}
    plat = d.get("platform")
    if plat not in SOCIAL:
        return jsonify({"error": "Choose a platform."}), 400
    if _item_kind(row) != "video":
        return jsonify({"error": "Only videos can be converted."}), 400
    if not _ffmpeg_bin():
        return jsonify({"error": "FFmpeg isn't installed — add it from the Tools setup first."}), 400
    CONVERT_JOBS[f"{cid}:{plat}"] = {"status": "running", "message": "Starting…"}
    threading.Thread(target=_convert_video, args=(cid, plat, d.get("mode") or "crop", u["id"]), daemon=True).start()
    log_activity(db, u, "convert", "item", cid, P.PLATFORMS[plat]["label"])
    return jsonify({"ok": True})


@app.route("/api/calendar/<int:cid>/convert-status")
def api_calendar_convert_status(cid):
    require_login()
    plat = request.args.get("platform", "")
    return jsonify(CONVERT_JOBS.get(f"{cid}:{plat}", {"status": "idle", "message": ""}))


@app.route("/api/calendar/<int:cid>/variant/<plat>", methods=["DELETE"])
def api_calendar_variant_delete(cid, plat):
    require_login()
    db = get_db()
    row = _cal_item(db, cid)
    if not row:
        return jsonify({"error": "Not found."}), 404
    variants = _jl(_rget(row, "variants"), {})
    old = variants.pop(plat, None)
    db.execute("UPDATE calendar_items SET variants=? WHERE id=?", (json.dumps(variants), cid))
    db.commit()
    if old and not _file_in_use(db, old, cid):
        try:
            os.remove(os.path.join(UPLOAD_DIR, old))
        except Exception:
            pass
    return jsonify({"ok": True})


@app.route("/api/calendar/<int:cid>/thumbnail", methods=["POST", "DELETE"])
def api_calendar_thumbnail(cid):
    u = require_login()
    db = get_db()
    row = _cal_item(db, cid)
    if not row:
        return jsonify({"error": "Not found."}), 404
    if request.method == "DELETE":
        db.execute("UPDATE calendar_items SET thumbnail=NULL WHERE id=?", (cid,))
        db.commit()
        return jsonify({"ok": True})
    f = request.files.get("file")
    if f and f.filename:
        if not _is_image(f.filename):
            return jsonify({"error": "Upload a JPG or PNG image."}), 400
        fname = _safe_save(f)
    else:
        d = request.get_json(silent=True) or {}
        files = _item_files(row)
        ff = _ffmpeg_bin()
        if not (files and ff) or _is_image(files[0]):
            return jsonify({"error": "Picking a frame needs a video and FFmpeg installed."}), 400
        at = max(0.0, float(d.get("at") or 1))
        fname = f"{secrets.token_hex(4)}_thumb.jpg"
        subprocess.run([ff, "-y", "-ss", str(at), "-i", _local_upload(files[0]) or os.path.join(UPLOAD_DIR, files[0]), "-frames:v", "1",
                        "-q:v", "2", os.path.join(UPLOAD_DIR, fname)], capture_output=True, timeout=60)
        if not os.path.exists(os.path.join(UPLOAD_DIR, fname)):
            return jsonify({"error": "Couldn't grab that frame — try another time."}), 400
        if USE_SUPABASE_STORAGE:
            _supabase_upload_path(os.path.join(UPLOAD_DIR, fname), fname)
    db.execute("UPDATE calendar_items SET thumbnail=? WHERE id=?", (fname, cid))
    db.commit()
    log_activity(db, u, "thumbnail", "item", cid, fname)
    return jsonify({"ok": True, "thumbnail": fname})


@app.route("/api/calendar/<int:cid>/adapt", methods=["POST"])
def api_calendar_adapt(cid):
    u = require_login()
    db = get_db()
    row = _cal_item(db, cid)
    if not row:
        return jsonify({"error": "Not found."}), 404
    d = request.get_json(silent=True) or {}
    plats = [p for p in (d.get("platforms") or _item_platforms(row)) if p in SOCIAL]
    if not ((row["caption"] or "").strip() or (row["hashtags"] or "").strip()):
        return jsonify({"error": "Write (or generate) the master caption first."}), 400
    result, source = adapt_captions(row, plats, kit_for_owner(db, row["owner_id"], row["brand_id"]))
    yt_title = result.pop("_youtube_title", None)
    pc = _jl(_rget(row, "platform_captions"), {})
    pc.update(result)
    db.execute("UPDATE calendar_items SET platform_captions=? WHERE id=?", (json.dumps(pc), cid))
    if yt_title and not _rget(row, "yt_title"):
        db.execute("UPDATE calendar_items SET yt_title=? WHERE id=?", (yt_title, cid))
    db.commit()
    log_activity(db, u, "captions_adapted", "item", cid, f"{', '.join(plats)} via {source}")
    return jsonify({"ok": True, "captions": pc, "source": source, "yt_title": yt_title})


@app.route("/api/targets/<int:tid>/retry", methods=["POST"])
def api_target_retry(tid):
    u = require_login()
    db = get_db()
    t = db.execute("SELECT * FROM post_targets WHERE id=?", (tid,)).fetchone()
    if not t:
        return jsonify({"error": "Not found."}), 404
    if t["status"] != "failed":
        return jsonify({"error": "Only failed platforms can be retried."}), 400
    row = _cal_item(db, t["item_id"])
    try:
        n = enqueue_publish(db, row, u, platforms=[t["platform"]])
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    log_activity(db, u, "retry", "item", t["item_id"], P.PLATFORMS[t["platform"]]["label"])
    return jsonify({"ok": True, "queued": n})


@app.route("/api/calendar/<int:cid>/queue", methods=["POST"])
def api_calendar_queue(cid):
    u = require_login()
    db = get_db()
    row = _cal_item(db, cid)
    if not row:
        return jsonify({"error": "Not found."}), 404
    if row["state"] == "published":
        return jsonify({"error": "Already published."}), 400
    d = request.get_json(silent=True) or {}
    slot = _apply_queue(db, row, u, d.get("tz"), d.get("offset"))
    if not slot:
        return jsonify({"error": "No free queue slot — add weekly time slots on the Queue page first."}), 400
    log_activity(db, u, "queued", "item", cid, f"{slot[0]} {slot[1]}")
    return jsonify({"ok": True, "date": slot[0], "time": slot[1], "publish_at": slot[2],
                    "note": "" if row["approved"] else "It will publish at that slot once it's approved."})


@app.route("/api/queue/fill", methods=["POST"])
def api_queue_fill():
    u = require_login()
    db = get_db()
    d = request.get_json(silent=True) or {}
    wq, wa = ws_sql(db, u)
    rows = db.execute("SELECT * FROM calendar_items WHERE approved=1 AND state='approved' "
                      "AND (publish_at IS NULL OR publish_at='')" + wq + " ORDER BY id", wa).fetchall()
    placed = []
    for r in rows:
        slot = _apply_queue(db, r, u, d.get("tz"), d.get("offset"))
        if not slot:
            break
        placed.append({"id": r["id"], "title": r["title"], "date": slot[0], "time": slot[1]})
    log_activity(db, u, "queue_fill", "", None, f"{len(placed)} posts")
    return jsonify({"ok": True, "placed": placed, "remaining": len(rows) - len(placed)})


@app.route("/api/queue/slots", methods=["GET", "POST"])
def api_queue_slots():
    u = require_login()
    db = get_db()
    owner = billing_user_id(u) or u["id"]
    if request.method == "POST":
        d = request.get_json(force=True) or {}
        try:
            dow = int(d.get("dow"))
            hh, mm = [int(x) for x in (d.get("time") or "").split(":")]
            assert 0 <= dow <= 6 and 0 <= hh < 24 and 0 <= mm < 60
        except Exception:
            return jsonify({"error": "Choose a day and a time."}), 400
        db.execute("INSERT INTO queue_slots (owner_id, brand_id, dow, time, created_at) VALUES (?,?,?,?,?)",
                   (owner, d.get("brand_id") or None, dow, f"{hh:02d}:{mm:02d}", _now()))
        db.commit()
        log_activity(db, u, "queue_slot_added", "", None, f"{dow} {hh:02d}:{mm:02d}")
    rows = db.execute("SELECT * FROM queue_slots WHERE owner_id=? ORDER BY dow, time", (owner,)).fetchall()
    return jsonify({"slots": [dict(r) for r in rows]})


@app.route("/api/queue/slots/<int:sid>", methods=["DELETE"])
def api_queue_slot_delete(sid):
    u = require_login()
    db = get_db()
    db.execute("DELETE FROM queue_slots WHERE id=? AND owner_id=?", (sid, billing_user_id(u) or u["id"]))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/schedule/best-times")
def api_best_times():
    u = require_login()
    db = get_db()
    return jsonify({"best": best_times(db, request.args.get("tz"), request.args.get("offset"),
                                       ws_member_ids(db, u))})


def _local_to_utc(date_s, time_s, tz, offset):
    from datetime import timezone
    try:
        hh, mm = [int(x) for x in (time_s or "09:00").split(":")]
        y, mo, dd = [int(x) for x in date_s.split("-")]
        local = datetime(y, mo, dd, hh, mm, tzinfo=_tzinfo(tz, offset))
        return local.astimezone(timezone.utc).replace(tzinfo=None).isoformat()
    except Exception:
        return None


@app.route("/api/calendar/bulk", methods=["POST"])
def api_calendar_bulk():
    """Bulk upload: many files (+ optional CSV of titles/captions/dates), spread across the calendar."""
    u = require_login()
    db = get_db()
    files = [f for f in request.files.getlist("files") if f and f.filename]
    csv_file = request.files.get("csv")
    rows_meta = []
    if csv_file and csv_file.filename:
        import csv
        import io
        text = csv_file.read().decode("utf-8-sig", "replace")
        rows_meta = [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
                     for r in csv.DictReader(io.StringIO(text))]
    if not files and not rows_meta:
        return jsonify({"error": "Add media files and/or a CSV."}), 400
    f = request.form
    try:
        start = datetime.strptime(f.get("start_date") or datetime.now().strftime("%Y-%m-%d"), "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "Invalid start date."}), 400
    every = max(1, int(f.get("every_days") or 1))
    at_time = (f.get("time") or "").strip()
    tz, offset = f.get("tz"), f.get("offset")
    plats = [p for p in _jl(f.get("platforms"), []) if p in SOCIAL] or ["instagram"]
    denied = [p for p in plats if p not in _allowed_platforms(u)]
    if denied:
        return jsonify({"error": "No permission for: " + ", ".join(denied)}), 403
    queue_mode = f.get("mode") == "queue"
    by_name = {m.get("filename", ""): m for m in rows_meta if m.get("filename")}
    saved = {fo.filename: _safe_save(fo) for fo in files}
    entries = []
    if rows_meta:
        for m in rows_meta:
            entries.append((m, saved.get(m.get("filename", ""))))
        for name, fn in saved.items():
            if name not in by_name:
                entries.append(({}, fn))
    else:
        entries = [({}, fn) for fn in saved.values()]
    created = []
    for i, (m, fname) in enumerate(entries):
        date_s = m.get("date") or (start + timedelta(days=i * every)).strftime("%Y-%m-%d")
        time_s = m.get("time") or at_time
        mplats = [p.strip() for p in (m.get("platforms") or "").replace(";", ",").split(",") if p.strip() in SOCIAL] or plats
        title = m.get("title") or (os.path.splitext(fname.split("_", 1)[-1])[0] if fname else "Text post")
        kind = _media_kind_for([fname] if fname else [])
        pub_at = _local_to_utc(date_s, time_s, tz, offset) if (time_s and not queue_mode) else None
        cur = db.execute(
            "INSERT INTO calendar_items (date, title, filename, caption, hashtags, state, approved, owner, owner_id, "
            "created_at, platforms, media_kind, publish_time, publish_at, tz, brand_id, queue_on_approve) "
            "VALUES (?,?,?,?,?, 'uploaded', 0, ?,?,?,?,?,?,?,?,?,?)",
            (date_s, title, fname, m.get("caption", ""), m.get("hashtags", ""), u["username"], u["id"], _now(),
             json.dumps(mplats), kind, time_s if not queue_mode else "", pub_at, tz or "",
             _rget(u, "active_brand_id"), 1 if queue_mode else 0))
        created.append(cur.lastrowid)
    db.commit()
    log_activity(db, u, "bulk_upload", "", None, f"{len(created)} items")
    add_notification(db, f"📦 Bulk upload: {len(created)} post(s) added to the calendar by {u['username']}.",
                     "upload", u["username"], recipients=owner_and_admins(db, u["id"]))
    return jsonify({"ok": True, "ids": created})


@app.route("/api/calendar/text", methods=["POST"])
def api_calendar_text():
    u = require_login()
    d = request.get_json(force=True) or {}
    date_s = (d.get("date") or "").strip()
    if not date_s:
        return jsonify({"error": "A date is required."}), 400
    db = get_db()
    plats = [p for p in d.get("platforms") or [] if p in SOCIAL] or ["facebook", "twitter", "linkedin", "threads"]
    cur = db.execute("INSERT INTO calendar_items (date, title, caption, hashtags, state, approved, owner, owner_id, "
                     "created_at, platforms, media_kind, content_type, brand_id) "
                     "VALUES (?,?,?,?, 'uploaded', 0, ?,?,?,?, 'text', 'post', ?)",
                     (date_s, (d.get("title") or "Text post").strip(), d.get("caption", ""), d.get("hashtags", ""),
                      u["username"], u["id"], _now(), json.dumps(plats), _rget(u, "active_brand_id")))
    db.commit()
    log_activity(db, u, "created", "item", cur.lastrowid, "text post")
    return jsonify({"ok": True, "id": cur.lastrowid})


# ---- client approval links ---------------------------------------------------- #
@app.route("/api/calendar/<int:cid>/review-link", methods=["GET", "POST"])
def api_review_link(cid):
    u = require_login()
    db = get_db()
    row = _cal_item(db, cid)
    if not row:
        return jsonify({"error": "Not found."}), 404
    if request.method == "POST":
        ex = db.execute("SELECT * FROM review_links WHERE item_id=? AND status='pending' ORDER BY id DESC LIMIT 1",
                        (cid,)).fetchone()
        token = ex["token"] if ex else secrets.token_urlsafe(18)
        if not ex:
            db.execute("INSERT INTO review_links (item_id, token, created_by, status, created_at) "
                       "VALUES (?,?,?, 'pending', ?)", (cid, token, u["id"], _now()))
            db.commit()
            log_activity(db, u, "review_link", "item", cid, row["title"])
        return jsonify({"ok": True, "url": f"{_redirect_base()}/review/{token}"})
    links = [dict(r) for r in db.execute("SELECT * FROM review_links WHERE item_id=? ORDER BY id DESC", (cid,)).fetchall()]
    for lk in links:
        lk["url"] = f"{_redirect_base()}/review/{lk['token']}"
    return jsonify({"links": links})


@app.route("/review/<token>", methods=["GET", "POST"])
def client_review(token):
    """Public page: a client approves or requests changes — no login needed."""
    db = get_db()
    lk = db.execute("SELECT * FROM review_links WHERE token=?", (token,)).fetchone()
    row = _cal_item(db, lk["item_id"]) if lk else None
    if not (lk and row):
        return render_template("review.html", missing=True), 404
    message = ""
    if request.method == "POST" and lk["status"] == "pending":
        decision = request.form.get("decision")
        name = (request.form.get("name") or "Client").strip()[:80]
        note = (request.form.get("note") or "").strip()[:2000]
        if decision in ("approve", "changes"):
            db.execute("UPDATE review_links SET status=?, client_name=?, client_note=?, decided_at=? WHERE id=?",
                       ("approved" if decision == "approve" else "changes", name, note, _now(), lk["id"]))
            if decision == "approve":
                if row["state"] in ("uploaded", "submitted"):
                    db.execute("UPDATE calendar_items SET approved=1, state=?, review_note=? WHERE id=?",
                               ("scheduled" if row["publish_at"] else "approved",
                                f"Approved by {name}" + (f": {note}" if note else ""), row["id"]))
                msg = f'👍 Client {name} APPROVED "{row["title"]}"' + (f': "{note[:120]}"' if note else ".")
            else:
                if row["state"] != "published":
                    db.execute("UPDATE calendar_items SET state='uploaded', approved=0, review_note=? WHERE id=?",
                               (f"Changes requested by {name}: {note}", row["id"]))
                msg = f'✏️ Client {name} requested changes on "{row["title"]}": "{note[:160]}"'
            db.commit()
            add_notification(db, msg, "approval", name, link=f"calendar:{row['id']}",
                             recipients=owner_and_admins(db, row["owner_id"]))
            db.execute("INSERT INTO activity_log (user_id, username, action, target_type, target_id, detail, created_at) "
                       "VALUES (NULL, ?, ?, 'item', ?, ?, ?)",
                       (f"client:{name}", "client_" + decision, row["id"], note[:300], _now()))
            db.commit()
            lk = db.execute("SELECT * FROM review_links WHERE id=?", (lk["id"],)).fetchone()
            message = "Thanks — your response has been sent to the team."
    files = _item_files(row)
    media = [{"url": "/uploads/" + urllib.parse.quote(f), "image": _is_image(f)} for f in files]
    caps = [{"label": P.PLATFORMS[p]["label"], "text": _caption_for(row, p)} for p in _item_platforms(row)]
    return render_template("review.html", missing=False, item=dict(row), media=media, captions=caps,
                           link=dict(lk), message=message)


# =========================================================================== #
#  V31 : API — analytics, reports, inbox
# =========================================================================== #
@app.route("/api/analytics")
def api_analytics():
    u = require_login()
    db = get_db()
    days = max(1, min(365, int(request.args.get("days") or 30)))
    brand = request.args.get("brand_id") or _rget(u, "active_brand_id")
    return jsonify(analytics_data(db, days, int(brand) if brand else None, request.args.get("platform") or None,
                                  member_ids=ws_member_ids(db, u)))


@app.route("/api/analytics/refresh", methods=["POST"])
def api_analytics_refresh():
    u = require_login()
    db = get_db()
    wq, wa = ws_sql(db, u, "c.owner_id")
    rows = db.execute("SELECT t.* FROM post_targets t JOIN calendar_items c ON c.id=t.item_id "
                      "WHERE t.status='published'" + wq + " ORDER BY t.id DESC LIMIT 60", wa).fetchall()
    n = 0
    for t in rows:
        try:
            if refresh_target_stats(db, t) is not None:
                n += 1
        except Exception:
            pass
    return jsonify({"ok": True, "refreshed": n})


@app.route("/api/analytics/report.pdf")
def api_analytics_report():
    u = require_login()
    db = get_db()
    days = max(1, min(365, int(request.args.get("days") or 7)))
    brand = _rget(u, "active_brand_id")
    buf = build_report_pdf(analytics_data(db, days, brand, member_ids=ws_member_ids(db, u)),
                           f"Social media report — last {days} days")
    return send_file(buf, as_attachment=True, download_name=f"social-report-{days}d.pdf", mimetype="application/pdf")


@app.route("/api/analytics/report/email", methods=["POST"])
def api_analytics_report_email():
    u = require_login()
    db = get_db()
    d = request.get_json(force=True) or {}
    to = (d.get("to") or uget_setting(db, u["id"], "report_email") or u.get("email") or "").strip()
    if not to:
        return jsonify({"error": "Enter an email address."}), 400
    days = max(1, min(365, int(d.get("days") or 7)))
    data = analytics_data(db, days, _rget(u, "active_brand_id"), member_ids=ws_member_ids(db, u))
    pdf = build_report_pdf(data, f"Social media report — last {days} days").getvalue()
    ok, msg = send_email(db, to, f"Social media report — last {days} days",
                         f"{data['sum']['posts']} posts · {data['sum']['views']:,} views · "
                         f"{data['sum']['likes']:,} likes. Full report attached.",
                         [(f"social-report-{days}d.pdf", pdf, "application/pdf")])
    if not ok:
        return jsonify({"error": msg}), 400
    log_activity(db, u, "report_emailed", "", None, to)
    return jsonify({"ok": True})


@app.route("/api/inbox")
def api_inbox():
    u = require_login()
    db = get_db()
    wq, wa = ws_sql(db, u, "c.owner_id")
    q = ("SELECT i.*, c.title AS post_title, t.permalink FROM inbox_comments i "
         "LEFT JOIN calendar_items c ON c.id=i.item_id LEFT JOIN post_targets t ON t.id=i.target_id WHERE 1=1" + wq)
    args = list(wa)
    if request.args.get("status"):
        q += " AND i.status=?"
        args.append(request.args["status"])
    if request.args.get("platform"):
        q += " AND i.platform=?"
        args.append(request.args["platform"])
    if request.args.get("sentiment"):
        q += " AND i.sentiment=?"
        args.append(request.args["sentiment"])
    q += " ORDER BY i.id DESC LIMIT 300"
    rows = [dict(r) for r in db.execute(q, args).fetchall()]
    counts = {r["status"]: r["n"] for r in db.execute(
        "SELECT i.status, COUNT(*) AS n FROM inbox_comments i JOIN calendar_items c ON c.id=i.item_id "
        "WHERE 1=1" + wq + " GROUP BY i.status", wa).fetchall()}
    neg = db.execute("SELECT COUNT(*) FROM inbox_comments i JOIN calendar_items c ON c.id=i.item_id "
                     "WHERE i.sentiment='negative' AND i.status='new'" + wq, wa).fetchone()[0]
    # Comments the platform counts but won't return to the app (e.g. Meta apps in
    # Development mode only expose comments written by app testers).
    hidden = {}
    for t in db.execute("SELECT t.id, t.platform, t.comments, "
                        "(SELECT COUNT(*) FROM inbox_comments i WHERE i.target_id=t.id) AS got "
                        "FROM post_targets t JOIN calendar_items c ON c.id=t.item_id "
                        "WHERE t.status='published' AND t.simulated=0" + wq, wa).fetchall():
        gap = (t["comments"] or 0) - (t["got"] or 0)
        if gap > 0:
            hidden[t["platform"]] = hidden.get(t["platform"], 0) + gap
    return jsonify({"comments": rows, "counts": counts, "negative_new": neg, "hidden": hidden})


@app.route("/api/inbox/sync", methods=["POST"])
def api_inbox_sync():
    u = require_login()
    db = get_db()
    new = 0
    wq, wa = ws_sql(db, u, "c.owner_id")
    for t in db.execute("SELECT t.* FROM post_targets t JOIN calendar_items c ON c.id=t.item_id "
                        "WHERE t.status='published' AND t.simulated=0" + wq + " ORDER BY t.id DESC LIMIT 300",
                        wa).fetchall():
        row = _cal_item(db, t["item_id"])
        acct = _publish_account(db, row, t["platform"]) if row else None
        if not acct or acct.get("mode") != "live":
            continue
        before = db.execute("SELECT COUNT(*) FROM inbox_comments WHERE target_id=?", (t["id"],)).fetchone()[0]
        try:
            refresh_target_stats(db, t)          # updates counts AND pulls the comments
        except Exception:
            pass
        new += db.execute("SELECT COUNT(*) FROM inbox_comments WHERE target_id=?", (t["id"],)).fetchone()[0] - before
    return jsonify({"ok": True, "new": new})


@app.route("/api/inbox/<int:iid>/suggest", methods=["POST"])
def api_inbox_suggest(iid):
    require_login()
    db = get_db()
    c = db.execute("SELECT i.*, c.title AS post_title, c.owner_id, c.brand_id FROM inbox_comments i "
                   "LEFT JOIN calendar_items c ON c.id=i.item_id WHERE i.id=?", (iid,)).fetchone()
    if not c:
        return jsonify({"error": "Not found."}), 404
    reps, source = suggest_replies(c["text"], c["post_title"] or "", c["platform"],
                                   kit_for_owner(db, c["owner_id"], c["brand_id"]) if c["owner_id"] else None)
    return jsonify({"replies": reps, "source": source})


@app.route("/api/inbox/<int:iid>/reply", methods=["POST"])
def api_inbox_reply(iid):
    u = require_login()
    db = get_db()
    c = db.execute("SELECT * FROM inbox_comments WHERE id=?", (iid,)).fetchone()
    if not c:
        return jsonify({"error": "Not found."}), 404
    text = ((request.get_json(force=True) or {}).get("text") or "").strip()
    if not text:
        return jsonify({"error": "Write a reply."}), 400
    t = db.execute("SELECT * FROM post_targets WHERE id=?", (c["target_id"],)).fetchone()
    ok, msg, simulated = True, "Reply saved.", True
    if t and not t["simulated"] and not (c["remote_comment_id"] or "").startswith("sim_"):
        row = _cal_item(db, t["item_id"])
        acct = _publish_account(db, row, t["platform"]) if row else None
        if acct and acct.get("mode") == "live":
            simulated = False
            try:
                acct = _ensure_fresh(db, acct)
                ok, msg = P.reply(t["platform"], acct, t["remote_id"], c["remote_comment_id"], text)
            except Exception as e:  # noqa
                ok, msg = False, str(e)
    if not ok:
        db.execute("UPDATE inbox_comments SET reply_error=? WHERE id=?", (msg, iid))
        db.commit()
        return jsonify({"error": f"Couldn't post the reply: {msg}"}), 400
    db.execute("UPDATE inbox_comments SET status='replied', reply_text=?, replied_at=?, replied_by=?, reply_error='' "
               "WHERE id=?", (text, _now(), u["username"], iid))
    db.commit()
    log_activity(db, u, "replied", "comment", iid, text[:120])
    return jsonify({"ok": True, "simulated": simulated, "message": msg})


@app.route("/api/inbox/<int:iid>/status", methods=["POST"])
def api_inbox_status(iid):
    require_login()
    st = ((request.get_json(force=True) or {}).get("status") or "")
    if st not in ("new", "replied", "done", "hidden"):
        return jsonify({"error": "Invalid status."}), 400
    db = get_db()
    db.execute("UPDATE inbox_comments SET status=? WHERE id=?", (st, iid))
    db.commit()
    return jsonify({"ok": True})


# =========================================================================== #
#  V31 : API — team: brands, per-platform roles, activity, alerts/report settings
# =========================================================================== #
@app.route("/api/brands", methods=["GET", "POST"])
def api_brands():
    u = require_login()
    db = get_db()
    owner = billing_user_id(u) or u["id"]
    if request.method == "POST":
        if is_subuser(u):
            return jsonify({"error": "Only the primary account can create brands."}), 403
        d = request.get_json(force=True) or {}
        name = (d.get("name") or "").strip()
        if not name:
            return jsonify({"error": "Enter a brand name."}), 400
        cur = db.execute("INSERT INTO brands (owner_id, name, color, created_at) VALUES (?,?,?,?)",
                         (owner, name[:60], (d.get("color") or "#2f7bff")[:9], _now()))
        db.commit()
        log_activity(db, u, "brand_created", "brand", cur.lastrowid, name)
    q = "SELECT * FROM brands" + ("" if is_super(u) else " WHERE owner_id=?") + " ORDER BY name"
    rows = db.execute(q, () if is_super(u) else (owner,)).fetchall()
    return jsonify({"brands": [dict(r) for r in rows], "active_brand_id": _rget(u, "active_brand_id")})


@app.route("/api/brands/<int:bid>", methods=["PATCH", "DELETE"])
def api_brand_edit(bid):
    u = require_login()
    db = get_db()
    b = db.execute("SELECT * FROM brands WHERE id=?", (bid,)).fetchone()
    if not b or (not is_super(u) and b["owner_id"] != (billing_user_id(u) or u["id"])) or is_subuser(u):
        return jsonify({"error": "Not allowed."}), 403
    if request.method == "DELETE":
        db.execute("DELETE FROM brands WHERE id=?", (bid,))
        db.execute("UPDATE calendar_items SET brand_id=NULL WHERE brand_id=?", (bid,))
        db.execute("UPDATE users SET active_brand_id=NULL WHERE active_brand_id=?", (bid,))
        db.commit()
        log_activity(db, u, "brand_deleted", "brand", bid, b["name"])
        return jsonify({"ok": True})
    d = request.get_json(force=True) or {}
    db.execute("UPDATE brands SET name=COALESCE(?, name), color=COALESCE(?, color) WHERE id=?",
               ((d.get("name") or "").strip() or None, d.get("color") or None, bid))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/brands/active", methods=["POST"])
def api_brand_active():
    u = require_login()
    db = get_db()
    bid = (request.get_json(force=True) or {}).get("brand_id")
    if bid:
        b = db.execute("SELECT owner_id FROM brands WHERE id=?", (int(bid),)).fetchone()
        if not b or not (is_super(u) or b["owner_id"] == billing_user_id(u)):
            return jsonify({"error": "Brand not found."}), 404
    db.execute("UPDATE users SET active_brand_id=? WHERE id=?", (int(bid) if bid else None, u["id"]))
    db.commit()
    return jsonify({"ok": True, "active_brand_id": int(bid) if bid else None})


@app.route("/api/team/permissions", methods=["GET", "POST"])
def api_team_permissions():
    u = require_login()
    db = get_db()
    if not is_admin(u):
        return jsonify({"error": "Only account owners can manage publishing permissions."}), 403
    if request.method == "POST":
        d = request.get_json(force=True) or {}
        tid = int(d.get("user_id") or 0)
        tgt = db.execute("SELECT * FROM users WHERE id=?", (tid,)).fetchone()
        if not tgt or (not is_super(u) and tgt["parent_id"] != u["id"]):
            return jsonify({"error": "You can only manage your own Sub-Users."}), 403
        plats = d.get("platforms")
        val = None if plats is None else json.dumps([p for p in plats if p in SOCIAL])
        db.execute("UPDATE users SET publish_platforms=? WHERE id=?", (val, tid))
        db.commit()
        log_activity(db, u, "permissions_changed", "user", tid, val or "all platforms")
        return jsonify({"ok": True})
    rows = db.execute("SELECT * FROM users ORDER BY username").fetchall() if is_super(u) else \
        db.execute("SELECT * FROM users WHERE parent_id=? ORDER BY username", (u["id"],)).fetchall()
    users = [{"id": r["id"], "username": r["username"], "name_with_role": name_with_role(r),
              "role": role_of(r), "platforms": _jl(r["publish_platforms"], None)}
             for r in rows if r["id"] != u["id"] and role_of(r) != "superadmin"]
    return jsonify({"users": users, "platforms": [{"key": k, "label": P.PLATFORMS[k]["label"]} for k in SOCIAL]})


@app.route("/api/activity")
def api_activity():
    u = require_login()
    db = get_db()
    q, args = "SELECT * FROM activity_log WHERE 1=1", []
    if not is_super(u):
        ids = [u["id"]] + ([r["id"] for r in db.execute("SELECT id FROM users WHERE parent_id=?", (u["id"],)).fetchall()]
                           if is_primary_user(u) else [])
        q += f" AND (user_id IN ({','.join('?' * len(ids))}) OR user_id IS NULL)"
        args += ids
    if request.args.get("action"):
        q += " AND action=?"
        args.append(request.args["action"])
    if request.args.get("q"):
        q += " AND (lower(detail) LIKE ? OR lower(username) LIKE ?)"
        like = "%" + request.args["q"].lower() + "%"
        args += [like, like]
    q += " ORDER BY id DESC LIMIT ?"
    args.append(max(1, min(1000, int(request.args.get("limit") or 300))))
    return jsonify({"activity": [dict(r) for r in db.execute(q, args).fetchall()]})


@app.route("/api/settings/alerts", methods=["GET", "POST"])
def api_alert_settings():
    u = require_login()
    db = get_db()
    keys = ("alert_webhook", "alert_email", "report_email")
    if request.method == "POST":
        d = request.get_json(force=True) or {}
        for k in keys:
            if k in d:
                uset_setting(db, u["id"], k, (d.get(k) or "").strip())
        if can_view_creds(u):
            for k in ("smtp_host", "smtp_port", "smtp_user", "smtp_from", "public_base_url"):
                if k in d:
                    set_setting(db, k, (d.get(k) or "").strip())
            if d.get("smtp_pass"):
                set_setting(db, "smtp_pass", d["smtp_pass"].strip())
        return jsonify({"ok": True})
    out = {k: uget_setting(db, u["id"], k) for k in keys}
    cfg = _smtp_cfg(db)
    out.update({"smtp_configured": bool(cfg["host"]), "can_edit_smtp": can_view_creds(u),
                "public_base_url": get_setting(db, "public_base_url") or ""})
    if can_view_creds(u):
        out.update({"smtp_host": get_setting(db, "smtp_host"), "smtp_port": get_setting(db, "smtp_port"),
                    "smtp_user": get_setting(db, "smtp_user"), "smtp_from": get_setting(db, "smtp_from"),
                    "smtp_pass_set": bool(get_setting(db, "smtp_pass"))})
    return jsonify(out)


@app.route("/api/settings/alerts/test", methods=["POST"])
def api_alert_test():
    u = require_login()
    db = get_db()
    send_alert(db, [u["id"]], "Test alert", "🔔 Test alert from Social Platform — your alerts are working.",
               event="test")
    return jsonify({"ok": True})


@app.route("/api/jobs")
def api_jobs():
    u = require_login()
    if not is_super(u):
        return jsonify({"error": "Not allowed."}), 403
    db = get_db()
    rows = db.execute("SELECT id, kind, status, attempts, max_attempts, run_at, last_error, updated_at FROM jobs "
                      "ORDER BY id DESC LIMIT 100").fetchall()
    return jsonify({"jobs": [dict(r) for r in rows]})


# =========================================================================== #
#  V32 : PLATFORM-WIDE APP CREDENTIALS
#  The SuperAdmin registers ONE developer app per platform; every client just
#  clicks Connect. A client may still "bring their own app" (their own ID +
#  secret), which then takes precedence for that client.
# =========================================================================== #
def app_creds(db, uid, platform):
    """(client_id, client_secret, source) — source is "own", "platform" or ""."""
    ik, sk = CRED_KEYS[platform]
    own_id, own_sec = uget_setting(db, uid, ik), uget_setting(db, uid, sk)
    if own_id and own_sec:
        return own_id, own_sec, "own"
    g_id, g_sec = get_setting(db, f"plat_{platform}_app_id"), get_setting(db, f"plat_{platform}_app_secret")
    if g_id and g_sec:
        return g_id, g_sec, "platform"
    return own_id, own_sec, ""


def _promote_superadmin_creds(db):
    """First run of V32: the SuperAdmin's own app credentials become the platform-wide ones."""
    try:
        sa = db.execute("SELECT id FROM users WHERE role='superadmin' ORDER BY id LIMIT 1").fetchone()
        if not sa:
            return
        for p, (ik, sk) in CRED_KEYS.items():
            if get_setting(db, f"plat_{p}_app_id"):
                continue
            i, s_ = uget_setting(db, sa["id"], ik), uget_setting(db, sa["id"], sk)
            if i and s_:
                set_setting(db, f"plat_{p}_app_id", i)
                set_setting(db, f"plat_{p}_app_secret", s_)
    except Exception:
        pass


def _public_base(db):
    """Public https address of the app — usable from background threads (no request)."""
    from flask import has_request_context
    return ((get_setting(db, "oauth_redirect_base") or os.environ.get("PUBLIC_BASE_URL")
             or os.environ.get("RENDER_EXTERNAL_URL")
             or (request.host_url if has_request_context() else "") or "http://127.0.0.1:5000").strip().rstrip("/"))


def _ws_accounts(db, u, platform=None):
    """Live connected accounts in the login's workspace (all for the SuperAdmin).
    In central mode only the workspace admin's accounts count."""
    ids = ws_member_ids(db, u)
    if ids is not None and ws_social_mode(db, billing_user_id(u)) == "central":
        ids = [billing_user_id(u)]
    q, args = "SELECT * FROM social_accounts WHERE mode='live'", []
    if ids is not None:
        q += f" AND user_id IN ({','.join('?' * len(ids))})"
        args += ids
    if platform:
        q += " AND platform=?"
        args.append(platform)
    return [_hydrate_account(db, r) for r in db.execute(q + " ORDER BY platform, id", args).fetchall()]


def _iso_utc(s):
    """Platform timestamps → naive UTC ISO string."""
    if not s:
        return _now()
    try:
        from datetime import timezone
        t = s.replace("Z", "+00:00")
        if re.search(r"[+-]\d{4}$", t):
            t = t[:-2] + ":" + t[-2:]
        d = datetime.fromisoformat(t)
        if d.tzinfo:
            d = d.astimezone(timezone.utc).replace(tzinfo=None)
        return d.isoformat()
    except Exception:
        return _now()


# =========================================================================== #
#  V32 : IMPORT EXISTING POSTS
# =========================================================================== #
def import_account_posts(db, acct, limit=50):
    """Pull an account's recent posts into the dashboard (as published items with a
    post target), so their comments and stats are tracked like dashboard posts."""
    posts = P.list_posts(acct["platform"], acct, limit)
    urow = db.execute("SELECT username FROM users WHERE id=?", (acct["user_id"],)).fetchone()
    owner = urow["username"] if urow else ""
    new_targets = []
    for p in posts:
        if db.execute("SELECT 1 FROM post_targets WHERE platform=? AND remote_id=?",
                      (acct["platform"], p["id"])).fetchone():
            continue
        created = _iso_utc(p["created"])
        mt = p["media_type"]
        kind = "video" if ("video" in mt or "reel" in mt) else ("carousel" if "carousel" in mt or "album" in mt
                                                                 else ("text" if mt in ("text", "") and not p["thumb"] else "image"))
        cap = (p["caption"] or "").strip()
        title = (cap.split("\n")[0][:70] or f"Imported {P.PLATFORMS[acct['platform']]['label']} post")
        cur = db.execute(
            "INSERT INTO calendar_items (date, title, caption, hashtags, state, approved, owner, owner_id, created_at, "
            "platforms, media_kind, content_type, published_date, publish_state, publish_pct, source, external_thumb, "
            "external_url, brand_id) VALUES (?,?,?, '', 'published', 1, ?,?,?,?,?,?,?, 'published', 100, 'imported', ?,?,?)",
            (created[:10], title, cap, owner, acct["user_id"], _now(), json.dumps([acct["platform"]]), kind,
             "reel" if kind == "video" else "post", created[:10], p["thumb"], p["permalink"], acct.get("brand_id")))
        tcur = db.execute("INSERT INTO post_targets (item_id, platform, status, remote_id, permalink, message, "
                          "attempts, simulated, published_at, created_at) VALUES (?,?, 'published', ?,?, "
                          "'Imported from the platform', 0, 0, ?, ?)",
                          (cur.lastrowid, acct["platform"], p["id"], p["permalink"], created, _now()))
        new_targets.append(tcur.lastrowid)
    if acct.get("id"):
        db.execute("UPDATE social_accounts SET imported_at=? WHERE id=?", (_now(), acct["id"]))
    db.commit()
    return len(new_targets), len(posts)


def _bg_import_and_snapshot(account_row_id):
    """After connecting: import past posts, first account snapshot, stats+comments, DMs."""
    try:
        db = db_connect()
        r = db.execute("SELECT * FROM social_accounts WHERE id=?", (account_row_id,)).fetchone()
        if not r:
            db.close()
            return
        acct = _hydrate_account(db, r)
        try:
            import_account_posts(db, acct)
        except Exception:
            pass
        try:
            snapshot_account(db, acct)
        except Exception:
            pass
        for t in db.execute("SELECT t.* FROM post_targets t JOIN calendar_items c ON c.id=t.item_id "
                            "WHERE t.platform=? AND t.status='published' AND c.owner_id=? "
                            "ORDER BY t.published_at DESC LIMIT 20", (acct["platform"], acct["user_id"])).fetchall():
            try:
                refresh_target_stats(db, t)
            except Exception:
                pass
        if acct["platform"] in P.DM_PLATFORMS:
            try:
                sync_dms(db, acct)
            except Exception:
                pass
        db.close()
    except Exception:
        pass


# =========================================================================== #
#  V32 : ACCOUNT-LEVEL ANALYTICS (followers, reach, profile views over time)
# =========================================================================== #
def snapshot_account(db, acct):
    st = P.account_stats(acct["platform"], acct)
    day = datetime.utcnow().strftime("%Y-%m-%d")
    ex = db.execute("SELECT id FROM account_stats WHERE account_id=? AND day=?", (acct["id"], day)).fetchone()
    vals = (st["followers"], st["reach"], st["impressions"], st["profile_views"], st["media_count"], _now())
    if ex:
        db.execute("UPDATE account_stats SET followers=?, reach=?, impressions=?, profile_views=?, media_count=?, "
                   "captured_at=? WHERE id=?", vals + (ex["id"],))
    else:
        db.execute("INSERT INTO account_stats (followers, reach, impressions, profile_views, media_count, captured_at, "
                   "account_id, user_id, platform, day) VALUES (?,?,?,?,?,?,?,?,?,?)",
                   vals + (acct["id"], acct["user_id"], acct["platform"], day))
    db.commit()
    return st


def _snapshot_all_accounts():
    try:
        db = db_connect()
        for r in db.execute("SELECT * FROM social_accounts WHERE mode='live'").fetchall():
            try:
                snapshot_account(db, _ensure_fresh(db, _hydrate_account(db, r)))
            except Exception:
                pass
        db.close()
    except Exception:
        pass


def account_analytics(db, u, days=30):
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    out = []
    for a in _ws_accounts(db, u):
        rows = [dict(r) for r in db.execute("SELECT day, followers, reach, impressions, profile_views, media_count "
                                            "FROM account_stats WHERE account_id=? AND day>=? ORDER BY day",
                                            (a["id"], since)).fetchall()]
        first = rows[0] if rows else None
        last = rows[-1] if rows else None
        out.append({"id": a["id"], "platform": a["platform"], "label": P.PLATFORMS[a["platform"]]["label"],
                    "account": a.get("account_name") or "", "series": rows,
                    "followers": last["followers"] if last else 0,
                    "growth": (last["followers"] - first["followers"]) if (first and last) else 0,
                    "reach": sum(r["reach"] or 0 for r in rows), "profile_views": sum(r["profile_views"] or 0 for r in rows),
                    "impressions": last["impressions"] if last else 0, "days_tracked": len(rows)})
    return out


# =========================================================================== #
#  V32 : DIRECT MESSAGES (Instagram + Facebook Page)
# =========================================================================== #
def _store_dm(db, acct, conv_id, participant_id, participant_name, m):
    if not m.get("id") or db.execute("SELECT 1 FROM dm_messages WHERE platform=? AND remote_id=?",
                                     (acct["platform"], str(m["id"]))).fetchone():
        return False
    own = str(acct.get("account_id") or "")
    out_dir = str(m.get("from_id") or "") == own
    db.execute("INSERT INTO dm_messages (account_id, user_id, platform, conversation_id, participant_id, "
               "participant_name, remote_id, from_id, from_name, text, created_at, direction, status) "
               "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (acct["id"], acct["user_id"], acct["platform"], participant_id or conv_id, participant_id,
                participant_name, str(m["id"]), str(m.get("from_id") or ""), m.get("from_name") or "",
                m.get("text") or "", _iso_utc(m.get("created")), "out" if out_dir else "in",
                "read" if out_dir else "new"))
    return True


def sync_dms(db, acct):
    new = 0
    for th in P.dm_threads(acct["platform"], acct):
        for m in th["messages"]:
            if _store_dm(db, acct, th["conversation_id"], th["participant_id"], th["participant_name"], m):
                new += 1
    db.commit()
    return new


def _sync_all_dms():
    try:
        db = db_connect()
        for r in db.execute("SELECT * FROM social_accounts WHERE mode='live' AND platform IN ('instagram','facebook')").fetchall():
            try:
                sync_dms(db, _ensure_fresh(db, _hydrate_account(db, r)))
            except Exception:
                pass
        db.close()
    except Exception:
        pass


def _account_in_ws(db, u, account_id):
    r = db.execute("SELECT * FROM social_accounts WHERE id=?", (account_id,)).fetchone()
    if not r or not in_ws(db, u, r["user_id"]):
        return None
    return r


@app.route("/api/dms")
def api_dms():
    u = require_login()
    db = get_db()
    ids = ws_member_ids(db, u)
    q = ("SELECT d.account_id, d.platform, d.conversation_id, d.participant_id, MAX(d.participant_name) AS name, "
         "MAX(d.created_at) AS last_at, SUM(CASE WHEN d.status='new' THEN 1 ELSE 0 END) AS unread, COUNT(*) AS n "
         "FROM dm_messages d WHERE 1=1")
    args = []
    if ids is not None:
        q += f" AND d.user_id IN ({','.join('?' * len(ids))})"
        args += ids
    q += " GROUP BY d.account_id, d.platform, d.conversation_id, d.participant_id ORDER BY last_at DESC LIMIT 200"
    convs = []
    for c in db.execute(q, args).fetchall():
        c = dict(c)
        last = db.execute("SELECT text, direction FROM dm_messages WHERE account_id=? AND conversation_id=? "
                          "ORDER BY created_at DESC, id DESC LIMIT 1", (c["account_id"], c["conversation_id"])).fetchone()
        acc = db.execute("SELECT account_name FROM social_accounts WHERE id=?", (c["account_id"],)).fetchone()
        c["last_text"] = last["text"] if last else ""
        c["last_dir"] = last["direction"] if last else ""
        c["account"] = acc["account_name"] if acc else ""
        convs.append(c)
    have = [a["platform"] for a in _ws_accounts(db, u) if a["platform"] in P.DM_PLATFORMS]
    return jsonify({"conversations": convs, "unread": sum(c["unread"] or 0 for c in convs),
                    "dm_accounts": sorted(set(have))})


@app.route("/api/dms/<int:account_id>/<path:conv_id>", methods=["GET", "POST"])
def api_dm_thread(account_id, conv_id):
    u = require_login()
    db = get_db()
    r = _account_in_ws(db, u, account_id)
    if not r:
        return jsonify({"error": "Not found."}), 404
    if request.method == "POST":
        text = ((request.get_json(force=True) or {}).get("text") or "").strip()
        if not text:
            return jsonify({"error": "Write a message."}), 400
        part = db.execute("SELECT participant_id, participant_name FROM dm_messages WHERE account_id=? AND "
                          "conversation_id=? LIMIT 1", (account_id, conv_id)).fetchone()
        if not part:
            return jsonify({"error": "Conversation not found."}), 404
        acct = _ensure_fresh(db, _hydrate_account(db, r))
        ok, msg, mid = P.dm_send(acct["platform"], acct, part["participant_id"], text)
        if not ok:
            return jsonify({"error": msg}), 400
        _store_dm(db, acct, conv_id, part["participant_id"], part["participant_name"],
                  {"id": mid or ("out_" + secrets.token_hex(6)), "from_id": acct.get("account_id"),
                   "from_name": acct.get("account_name"), "text": text, "created": _now()})
        db.execute("UPDATE dm_messages SET sent_by=? WHERE remote_id=?", (u["username"], mid or ""))
        db.commit()
        log_activity(db, u, "dm_replied", "dm", account_id, text[:120])
    msgs = [dict(m) for m in db.execute("SELECT * FROM dm_messages WHERE account_id=? AND conversation_id=? "
                                        "ORDER BY created_at, id", (account_id, conv_id)).fetchall()]
    db.execute("UPDATE dm_messages SET status='read' WHERE account_id=? AND conversation_id=? AND status='new'",
               (account_id, conv_id))
    db.commit()
    return jsonify({"messages": msgs, "platform": r["platform"], "account": r["account_name"]})


@app.route("/api/dms/sync", methods=["POST"])
def api_dms_sync():
    u = require_login()
    db = get_db()
    new, errors = 0, []
    for a in _ws_accounts(db, u):
        if a["platform"] not in P.DM_PLATFORMS:
            continue
        try:
            new += sync_dms(db, _ensure_fresh(db, a))
        except Exception as e:  # noqa
            errors.append({"platform": a["platform"], "account": a.get("account_name") or "",
                           "error": str(e)[:300], "fix": _dm_fix(a["platform"], str(e))})
    return jsonify({"ok": True, "new": new, "errors": errors})


def _dm_fix(platform, err):
    """Plain-language next step for a direct-message sync error."""
    e = (err or "").lower()
    if platform == "instagram":
        if "capability" in e or "(#3)" in e:
            return ("Your Meta app doesn't have the Instagram messaging permission yet. In Meta Developers → your app → "
                    "Use cases → Instagram API → Permissions, add instagram_business_manage_messages, then Disconnect "
                    "and Connect Instagram again in Setup.")
        if "permission" in e or "scope" in e or "(#10)" in e or "(#200)" in e or "oauth" in e:
            return ("Instagram didn't grant message access. Disconnect and Connect Instagram again in Setup and allow "
                    "\"Manage messages\". Also in the Instagram app: Settings → Messages and story replies → "
                    "Message controls → Connected tools → turn on \"Allow access to messages\".")
        return ("Check that Instagram is connected with message access, and in the Instagram app turn on "
                "Settings → Messages and story replies → Message controls → Connected tools → \"Allow access to messages\".")
    if "capability" in e or "permission" in e or "(#10)" in e or "(#200)" in e:
        return ("Your Meta app needs the pages_messaging permission. Add it to the app, then Disconnect and Connect "
                "the Facebook Page again in Setup.")
    return "Try Disconnect and Connect again in Setup, then Sync."


# =========================================================================== #
#  V32 : BRAND KIT (per workspace, optionally per brand)
# =========================================================================== #
def _kit_row(db, ws, brand_id=None):
    if brand_id:
        r = db.execute("SELECT * FROM brand_kits WHERE workspace_id=? AND brand_id=?", (ws, brand_id)).fetchone()
        if r:
            return dict(r)
    r = db.execute("SELECT * FROM brand_kits WHERE workspace_id=? AND brand_id IS NULL", (ws,)).fetchone()
    return dict(r) if r else None


def kit_for_owner(db, owner_id, brand_id=None):
    ws = ws_owner_id(db, owner_id)
    return _kit_row(db, ws, brand_id) if ws else None


def kit_prompt(kit):
    """Brand-kit rules as prompt text for the AI."""
    if not kit:
        return ""
    parts = []
    if (kit.get("tone") or "").strip():
        parts.append("Brand voice / tone: " + kit["tone"].strip())
    if (kit.get("banned_words") or "").strip():
        parts.append("NEVER use these words or phrases: " + kit["banned_words"].strip())
    if (kit.get("default_hashtags") or "").strip():
        parts.append("Always include these brand hashtags: " + kit["default_hashtags"].strip())
    return "\n".join(parts)


def banned_words_in(text, kit):
    if not kit or not (kit.get("banned_words") or "").strip():
        return []
    low = (text or "").lower()
    words = [w.strip() for w in re.split(r"[,\n]", kit["banned_words"]) if w.strip()]
    return [w for w in words if w.lower() in low]


@app.route("/api/brandkit", methods=["GET", "POST"])
def api_brandkit():
    u = require_login()
    db = get_db()
    ws = billing_user_id(u)
    body = (request.get_json(silent=True) or {}) if request.method == "POST" else {}
    bid = request.args.get("brand_id") or body.get("brand_id")
    bid = int(bid) if bid else None
    if bid:
        b = db.execute("SELECT owner_id FROM brands WHERE id=?", (bid,)).fetchone()
        if not b or b["owner_id"] != ws:
            return jsonify({"error": "Brand not found."}), 404
    if request.method == "POST":
        if is_subuser(u) and not _rget(u, "can_edit", 1):
            return jsonify({"error": "You don't have permission to edit the brand kit."}), 403
        d = request.get_json(force=True) or {}
        fields = {k: (d.get(k) or "").strip() for k in ("color_primary", "color_secondary", "tone",
                                                          "default_hashtags", "banned_words", "website")}
        ex = db.execute("SELECT id FROM brand_kits WHERE workspace_id=? AND COALESCE(brand_id,0)=?",
                        (ws, bid or 0)).fetchone()
        if ex:
            db.execute("UPDATE brand_kits SET color_primary=?, color_secondary=?, tone=?, default_hashtags=?, "
                       "banned_words=?, website=?, updated_at=? WHERE id=?",
                       tuple(fields.values()) + (_now(), ex["id"]))
        else:
            db.execute("INSERT INTO brand_kits (color_primary, color_secondary, tone, default_hashtags, banned_words, "
                       "website, updated_at, workspace_id, brand_id) VALUES (?,?,?,?,?,?,?,?,?)",
                       tuple(fields.values()) + (_now(), ws, bid))
        db.commit()
        log_activity(db, u, "brandkit_saved", "brand", bid, "")
    kit = _kit_row(db, ws, bid) or {}
    if bid and kit.get("brand_id") != bid:
        kit = {"inherited": True, **kit}
    return jsonify({"kit": kit, "brand_id": bid})


@app.route("/api/brandkit/logo", methods=["POST", "DELETE"])
def api_brandkit_logo():
    u = require_login()
    db = get_db()
    ws = billing_user_id(u)
    bid = request.args.get("brand_id")
    bid = int(bid) if bid else None
    ex = db.execute("SELECT id FROM brand_kits WHERE workspace_id=? AND COALESCE(brand_id,0)=?", (ws, bid or 0)).fetchone()
    if not ex:
        cur = db.execute("INSERT INTO brand_kits (workspace_id, brand_id, updated_at) VALUES (?,?,?)", (ws, bid, _now()))
        kid = cur.lastrowid
    else:
        kid = ex["id"]
    if request.method == "DELETE":
        db.execute("UPDATE brand_kits SET logo=NULL WHERE id=?", (kid,))
        db.commit()
        return jsonify({"ok": True})
    f = request.files.get("file")
    if not (f and f.filename and f.filename.lower().endswith((".png", ".jpg", ".jpeg"))):
        return jsonify({"error": "Upload a PNG or JPG logo."}), 400
    fname = _safe_save(f)
    db.execute("UPDATE brand_kits SET logo=?, updated_at=? WHERE id=?", (fname, _now(), kid))
    db.commit()
    return jsonify({"ok": True, "logo": fname})


# =========================================================================== #
#  V32 : CONTENT LIBRARY (media, caption templates, hashtag groups)
# =========================================================================== #
@app.route("/api/library", methods=["GET", "POST"])
def api_library():
    u = require_login()
    db = get_db()
    ws = billing_user_id(u)
    if request.method == "POST":
        if request.files:
            f = request.files.get("file")
            if not (f and f.filename):
                return jsonify({"error": "Choose a file."}), 400
            fname = _safe_save(f)
            title = (request.form.get("title") or f.filename)[:120]
            cur = db.execute("INSERT INTO library_items (workspace_id, brand_id, kind, title, body, filename, created_by, "
                             "created_at) VALUES (?,?, 'media', ?, ?, ?, ?, ?)",
                             (ws, _rget(u, "active_brand_id"), title, request.form.get("body") or "", fname,
                              u["username"], _now()))
        else:
            d = request.get_json(force=True) or {}
            kind = d.get("kind")
            if kind not in ("caption", "hashtags"):
                return jsonify({"error": "Invalid item type."}), 400
            if not (d.get("body") or "").strip():
                return jsonify({"error": "Write the text first."}), 400
            cur = db.execute("INSERT INTO library_items (workspace_id, brand_id, kind, title, body, created_by, created_at) "
                             "VALUES (?,?,?,?,?,?,?)", (ws, _rget(u, "active_brand_id"), kind,
                                                        (d.get("title") or "Untitled")[:120], d["body"].strip(),
                                                        u["username"], _now()))
        db.commit()
        log_activity(db, u, "library_added", "library", cur.lastrowid, "")
    q, args = "SELECT * FROM library_items WHERE 1=1", []
    if not is_super(u):
        q += " AND workspace_id=?"
        args.append(ws)
    if request.args.get("kind"):
        q += " AND kind=?"
        args.append(request.args["kind"])
    return jsonify({"items": [dict(r) for r in db.execute(q + " ORDER BY id DESC LIMIT 500", args).fetchall()]})


def _library_item(db, u, lid):
    r = db.execute("SELECT * FROM library_items WHERE id=?", (lid,)).fetchone()
    if not r or not (is_super(u) or r["workspace_id"] == billing_user_id(u)):
        return None
    return r


@app.route("/api/library/<int:lid>", methods=["PATCH", "DELETE"])
def api_library_item(lid):
    u = require_login()
    db = get_db()
    r = _library_item(db, u, lid)
    if not r:
        return jsonify({"error": "Not found."}), 404
    if request.method == "DELETE":
        db.execute("DELETE FROM library_items WHERE id=?", (lid,))
        db.commit()
        if r["filename"] and not _file_in_use(db, r["filename"], -1):
            try:
                os.remove(os.path.join(UPLOAD_DIR, r["filename"]))
            except Exception:
                pass
            _supabase_delete(r["filename"])
        return jsonify({"ok": True})
    d = request.get_json(force=True) or {}
    db.execute("UPDATE library_items SET title=COALESCE(?, title), body=COALESCE(?, body) WHERE id=?",
               ((d.get("title") or "").strip() or None, d.get("body"), lid))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/library/<int:lid>/use", methods=["POST"])
def api_library_use(lid):
    """Create a draft post from a library media file."""
    u = require_login()
    db = get_db()
    r = _library_item(db, u, lid)
    if not r or r["kind"] != "media":
        return jsonify({"error": "Not found."}), 404
    d = request.get_json(force=True) or {}
    date_s = (d.get("date") or datetime.now().strftime("%Y-%m-%d")).strip()
    plats = [p for p in (d.get("platforms") or []) if p in SOCIAL] or ["instagram"]
    kind = _media_kind_for([r["filename"]])
    cur = db.execute("INSERT INTO calendar_items (date, title, filename, caption, hashtags, state, approved, owner, owner_id, "
                     "created_at, platforms, media_kind, content_type, brand_id) "
                     "VALUES (?,?,?,?, '', 'uploaded', 0, ?,?,?,?,?,?,?)",
                     (date_s, r["title"], r["filename"], r["body"] or "", u["username"], u["id"], _now(),
                      json.dumps(plats), kind, "reel" if kind == "video" else "post", _rget(u, "active_brand_id")))
    db.commit()
    log_activity(db, u, "created", "item", cur.lastrowid, f"from library: {r['title']}")
    return jsonify({"ok": True, "id": cur.lastrowid, "date": date_s})


# =========================================================================== #
#  V32 : LINK IN BIO + UTM TRACKED LINKS
# =========================================================================== #
def _slugify(t):
    return re.sub(r"[^a-z0-9]+", "-", (t or "").lower()).strip("-")[:40] or "page"


def _utm_url(url, source, medium, campaign, content):
    parts = urllib.parse.urlsplit(url)
    q = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    have = {k for k, _ in q}
    for k, v in (("utm_source", source), ("utm_medium", medium), ("utm_campaign", campaign), ("utm_content", content)):
        if v and k not in have:
            q.append((k, v))
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(q)))


def create_short_link(db, ws, url, label="", item_id=None, platform="", source="", medium="", campaign="", content=""):
    code = secrets.token_urlsafe(5).replace("-", "x").replace("_", "y")[:7]
    cur = db.execute("INSERT INTO short_links (workspace_id, code, url, label, item_id, platform, utm_source, utm_medium, "
                     "utm_campaign, utm_content, clicks, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,0,?)",
                     (ws, code, url, label, item_id, platform, source, medium, campaign, content, _now()))
    db.commit()
    return code, cur.lastrowid


def post_link(db, row, platform):
    """Tracked short link for a post on one platform (created once, then reused)."""
    if not (_rget(row, "link_url") or "").strip():
        return ""
    ex = db.execute("SELECT code FROM short_links WHERE item_id=? AND platform=?", (row["id"], platform)).fetchone()
    if ex:
        code = ex["code"]
    else:
        ws = ws_owner_id(db, row["owner_id"])
        camp = _slugify(_rget(row, "link_campaign") or row["title"])
        code, _ = create_short_link(db, ws, row["link_url"].strip(), row["title"], row["id"], platform,
                                    platform, "social", camp, f"post{row['id']}")
    return f"{_public_base(db)}/r/{code}"


@app.route("/r/<code>")
def short_redirect(code):
    db = get_db()
    r = db.execute("SELECT * FROM short_links WHERE code=?", (code,)).fetchone()
    if not r:
        abort(404)
    db.execute("UPDATE short_links SET clicks=COALESCE(clicks,0)+1 WHERE id=?", (r["id"],))
    ref = (request.referrer or "")[:200]
    db.execute("INSERT INTO link_clicks (link_id, workspace_id, at, day, referrer) VALUES (?,?,?,?,?)",
               (r["id"], r["workspace_id"], _now(), datetime.utcnow().strftime("%Y-%m-%d"), ref))
    db.commit()
    return redirect(_utm_url(r["url"], r["utm_source"], r["utm_medium"], r["utm_campaign"], r["utm_content"]), 302)


@app.route("/api/links", methods=["GET", "POST"])
def api_links():
    u = require_login()
    db = get_db()
    ws = billing_user_id(u)
    if request.method == "POST":
        d = request.get_json(force=True) or {}
        url = (d.get("url") or "").strip()
        if not re.match(r"^https?://", url):
            return jsonify({"error": "Enter a full link starting with https://"}), 400
        code, lid = create_short_link(db, ws, url, (d.get("label") or "")[:120], None, "",
                                      (d.get("utm_source") or "").strip(), (d.get("utm_medium") or "").strip(),
                                      (d.get("utm_campaign") or "").strip(), (d.get("utm_content") or "").strip())
        log_activity(db, u, "link_created", "link", lid, url)
    q, args = "SELECT * FROM short_links WHERE 1=1", []
    if not is_super(u):
        q += " AND workspace_id=?"
        args.append(ws)
    rows = [dict(r) for r in db.execute(q + " ORDER BY id DESC LIMIT 500", args).fetchall()]
    base = _public_base(db)
    for r in rows:
        r["short_url"] = f"{base}/r/{r['code']}"
    return jsonify({"links": rows})


@app.route("/api/links/<int:lid>", methods=["DELETE"])
def api_link_delete(lid):
    u = require_login()
    db = get_db()
    r = db.execute("SELECT * FROM short_links WHERE id=?", (lid,)).fetchone()
    if not r or not (is_super(u) or r["workspace_id"] == billing_user_id(u)):
        return jsonify({"error": "Not found."}), 404
    db.execute("DELETE FROM short_links WHERE id=?", (lid,))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/links/stats")
def api_link_stats():
    u = require_login()
    db = get_db()
    days = max(1, min(365, int(request.args.get("days") or 30)))
    since = (datetime.utcnow() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    q, args = "SELECT c.day, l.platform, l.id AS link_id FROM link_clicks c JOIN short_links l ON l.id=c.link_id WHERE c.day>=?", [since]
    if not is_super(u):
        q += " AND l.workspace_id=?"
        args.append(billing_user_id(u))
    rows = db.execute(q, args).fetchall()
    by_day, by_platform, by_link = {}, {}, {}
    for r in rows:
        by_day[r["day"]] = by_day.get(r["day"], 0) + 1
        k = r["platform"] or "bio / other"
        by_platform[k] = by_platform.get(k, 0) + 1
        by_link[r["link_id"]] = by_link.get(r["link_id"], 0) + 1
    start = datetime.utcnow().date() - timedelta(days=days - 1)
    series = [{"date": (start + timedelta(days=i)).isoformat(),
               "clicks": by_day.get((start + timedelta(days=i)).isoformat(), 0)} for i in range(days)]
    return jsonify({"series": series, "by_platform": by_platform, "by_link": by_link, "total": len(rows)})


@app.route("/api/bio", methods=["GET", "POST"])
def api_bio():
    u = require_login()
    db = get_db()
    ws = billing_user_id(u)
    brand = _rget(u, "active_brand_id")
    page = db.execute("SELECT * FROM bio_pages WHERE workspace_id=? AND COALESCE(brand_id,0)=?",
                      (ws, brand or 0)).fetchone()
    if request.method == "POST":
        d = request.get_json(force=True) or {}
        slug = _slugify(d.get("slug") or d.get("title") or u["username"])
        clash = db.execute("SELECT id FROM bio_pages WHERE slug=?", (slug,)).fetchone()
        if clash and (not page or clash["id"] != page["id"]):
            return jsonify({"error": "That page address is taken — choose another."}), 400
        links_in = [lk for lk in (d.get("links") or []) if re.match(r"^https?://", (lk.get("url") or "").strip())]
        old = {lk.get("url"): lk.get("code") for lk in _jl(page["links"], [])} if page else {}
        links = []
        for lk in links_in[:30]:
            url = lk["url"].strip()
            code = old.get(url)
            if not code:
                code, _ = create_short_link(db, ws, url, (lk.get("label") or url)[:120], None, "bio",
                                            "linkinbio", "social", "bio", _slugify(lk.get("label") or "link"))
            links.append({"label": (lk.get("label") or url)[:120], "url": url, "code": code})
        vals = (slug, (d.get("title") or "")[:120], (d.get("bio") or "")[:500], (d.get("theme") or "#2f7bff")[:9],
                json.dumps(links), 1 if d.get("show_posts", True) else 0, _now())
        if page:
            db.execute("UPDATE bio_pages SET slug=?, title=?, bio=?, theme=?, links=?, show_posts=?, updated_at=? "
                       "WHERE id=?", vals + (page["id"],))
        else:
            db.execute("INSERT INTO bio_pages (slug, title, bio, theme, links, show_posts, updated_at, workspace_id, "
                       "brand_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", vals + (ws, brand, _now()))
        db.commit()
        log_activity(db, u, "bio_saved", "bio", None, slug)
        page = db.execute("SELECT * FROM bio_pages WHERE workspace_id=? AND COALESCE(brand_id,0)=?",
                          (ws, brand or 0)).fetchone()
    out = dict(page) if page else None
    if out:
        out["links"] = _jl(out["links"], [])
        out["url"] = f"{_public_base(db)}/l/{out['slug']}"
    return jsonify({"page": out})


@app.route("/api/bio/avatar", methods=["POST"])
def api_bio_avatar():
    u = require_login()
    db = get_db()
    page = db.execute("SELECT id FROM bio_pages WHERE workspace_id=? AND COALESCE(brand_id,0)=?",
                      (billing_user_id(u), _rget(u, "active_brand_id") or 0)).fetchone()
    if not page:
        return jsonify({"error": "Save the page first."}), 400
    f = request.files.get("file")
    if not (f and f.filename and _is_image(f.filename)):
        return jsonify({"error": "Upload an image."}), 400
    fname = _safe_save(f)
    db.execute("UPDATE bio_pages SET avatar=? WHERE id=?", (fname, page["id"]))
    db.commit()
    return jsonify({"ok": True, "avatar": fname})


@app.route("/l/<slug>")
def bio_public(slug):
    db = get_db()
    page = db.execute("SELECT * FROM bio_pages WHERE slug=?", (slug,)).fetchone()
    if not page:
        abort(404)
    posts = []
    if page["show_posts"]:
        members = [page["workspace_id"]] + [r["id"] for r in db.execute("SELECT id FROM users WHERE parent_id=?",
                                                                          (page["workspace_id"],)).fetchall()]
        q = (f"SELECT c.*, t.permalink AS tlink FROM calendar_items c JOIN post_targets t ON t.item_id=c.id "
             f"WHERE t.status='published' AND t.simulated=0 AND c.owner_id IN ({','.join('?' * len(members))})")
        args = list(members)
        if page["brand_id"]:
            q += " AND c.brand_id=?"
            args.append(page["brand_id"])
        seen = set()
        for r in db.execute(q + " ORDER BY t.published_at DESC LIMIT 40", args).fetchall():
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            files = _item_files(r)
            thumb = (f"/uploads/{urllib.parse.quote(r['thumbnail'] or files[0])}"
                     if (r["thumbnail"] or (files and _is_image(files[0]))) else (r["external_thumb"] or ""))
            if thumb:
                posts.append({"thumb": thumb, "link": r["tlink"] or r["external_url"] or "", "title": r["title"]})
            if len(posts) >= 12:
                break
    kit = _kit_row(db, page["workspace_id"], page["brand_id"]) or {}
    return render_template("bio.html", page=dict(page), links=_jl(page["links"], []), posts=posts,
                           logo=kit.get("logo"), company=os.environ.get("COMPANY_NAME") or "SocialPlatform")


# =========================================================================== #
#  V32 : ACCOUNT ANALYTICS + IMPORT + BRANDED MONTHLY REPORT — API
# =========================================================================== #
@app.route("/api/analytics/accounts")
def api_analytics_accounts():
    u = require_login()
    db = get_db()
    days = max(7, min(365, int(request.args.get("days") or 30)))
    return jsonify({"accounts": account_analytics(db, u, days), "days": days})


@app.route("/api/analytics/accounts/refresh", methods=["POST"])
def api_analytics_accounts_refresh():
    u = require_login()
    db = get_db()
    n = 0
    for a in _ws_accounts(db, u):
        try:
            snapshot_account(db, _ensure_fresh(db, a))
            n += 1
        except Exception:
            pass
    return jsonify({"ok": True, "refreshed": n})


@app.route("/api/platforms/<plat>/import", methods=["POST"])
def api_platform_import(plat):
    u = require_login()
    db = get_db()
    if social_locked(db, u):
        return jsonify({"error": LOCKED_MSG}), 403
    accts = [a for a in _ws_accounts(db, u, plat) if a["user_id"] == u["id"]] or _ws_accounts(db, u, plat)
    if not accts:
        return jsonify({"error": "Connect this platform first."}), 400
    total_new = total_seen = 0
    for a in accts:
        try:
            n, seen = import_account_posts(db, _ensure_fresh(db, a))
            total_new += n
            total_seen += seen
        except Exception as e:  # noqa
            return jsonify({"error": f"Import failed: {e}"}), 400
    log_activity(db, u, "imported", "platform", None, f"{P.PLATFORMS[plat]['label']}: {total_new} new posts")
    threading.Thread(target=_bg_import_and_snapshot, args=(accts[0]["id"],), daemon=True).start()
    return jsonify({"ok": True, "imported": total_new, "found": total_seen})


def _month_range(month):
    y, m = [int(x) for x in month.split("-")]
    start = datetime(y, m, 1)
    end = datetime(y + (m == 12), (m % 12) + 1, 1)
    return start, end


def monthly_report_data(db, member_ids, month, ws, brand_id=None):
    start, end = _month_range(month)
    pstart = (start - timedelta(days=1)).replace(day=1)
    cur = analytics_data(db, 31, brand_id, member_ids=member_ids, start=start.isoformat(), end=end.isoformat())
    prev = analytics_data(db, 31, brand_id, member_ids=member_ids, start=pstart.isoformat(), end=start.isoformat())
    accts = []
    q = "SELECT * FROM social_accounts WHERE mode='live'"
    args = []
    if member_ids is not None:
        q += f" AND user_id IN ({','.join('?' * len(member_ids))})"
        args = member_ids
    for a in db.execute(q, args).fetchall():
        s0 = db.execute("SELECT followers FROM account_stats WHERE account_id=? AND day>=? AND day<? ORDER BY day LIMIT 1",
                        (a["id"], start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))).fetchone()
        s1 = db.execute("SELECT followers FROM account_stats WHERE account_id=? AND day>=? AND day<? ORDER BY day DESC LIMIT 1",
                        (a["id"], start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))).fetchone()
        accts.append({"label": P.PLATFORMS[a["platform"]]["label"], "account": a["account_name"] or "",
                      "start": s0["followers"] if s0 else None, "end": s1["followers"] if s1 else None})
    kit = _kit_row(db, ws, brand_id) if ws else None
    return cur, prev, accts, kit, start


def build_monthly_pdf(cur, prev, accts, kit, start, company):
    from fpdf import FPDF
    reg = os.path.join(_FONT_DIR, "DejaVuSans.ttf")
    bold = os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf")
    pdf = FPDF(format="A4")
    font = "Helvetica"
    if os.path.exists(reg) and os.path.exists(bold):
        try:
            pdf.add_font("DejaVu", "", reg)
            pdf.add_font("DejaVu", "B", bold)
            font = "DejaVu"
        except Exception:
            font = "Helvetica"
    cps = _font_codepoints(reg) if font == "DejaVu" else set()

    def s(t):
        t = str(t if t is not None else "")
        if font != "DejaVu":
            return t.encode("latin-1", "replace").decode("latin-1")
        return "".join(ch for ch in t if ch in " \n" or ord(ch) in cps) if cps else t

    def rgb(hexv, fallback=(47, 123, 255)):
        try:
            h = (hexv or "").lstrip("#")
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if len(h) == 6 else fallback
        except Exception:
            return fallback

    primary = rgb((kit or {}).get("color_primary"))
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    pdf.set_fill_color(*primary)
    pdf.rect(0, 0, 210, 34, "F")
    x_text = 12
    logo = (kit or {}).get("logo")
    logo_path = _local_upload(logo) if logo else ""
    if logo_path:
        try:
            pdf.image(logo_path, x=12, y=6, h=22)
            x_text = 42
        except Exception:
            pass
    pdf.set_text_color(255, 255, 255)
    pdf.set_xy(x_text, 9)
    pdf.set_font(font, "B", 17)
    pdf.cell(0, 8, s(f"{company} — monthly social report"))
    pdf.set_xy(x_text, 19)
    pdf.set_font(font, "", 11)
    pdf.cell(0, 6, s(start.strftime("%B %Y")))
    pdf.set_text_color(18, 49, 90)
    pdf.set_xy(12, 42)

    def pct(a, b):
        if not b:
            return "new" if a else "—"
        d = 100.0 * (a - b) / b
        return f"{'+' if d >= 0 else ''}{d:.0f}%"
    sc, sp = cur["sum"], prev["sum"]
    er = lambda x: round(100.0 * (x["likes"] + x["comments"] + x["shares"]) / x["views"], 2) if x["views"] else 0
    pdf.set_font(font, "B", 13)
    pdf.cell(0, 8, s("This month vs last month"), new_x="LMARGIN", new_y="NEXT")
    cols = [("Metric", 60), ("This month", 40), ("Last month", 40), ("Change", 40)]
    pdf.set_font(font, "B", 10)
    pdf.set_fill_color(235, 242, 252)
    for n, w in cols:
        pdf.cell(w, 8, s(n), border=1, fill=True)
    pdf.ln()
    pdf.set_font(font, "", 10)
    for label, key in (("Posts", "posts"), ("Views", "views"), ("Likes", "likes"), ("Comments", "comments"), ("Shares", "shares")):
        for (n, w), v in zip(cols, (label, f"{sc[key]:,}", f"{sp[key]:,}", pct(sc[key], sp[key]))):
            pdf.cell(w, 7, s(v), border=1)
        pdf.ln()
    for (n, w), v in zip(cols, ("Engagement rate", f"{er(sc)}%", f"{er(sp)}%", pct(er(sc), er(sp)))):
        pdf.cell(w, 7, s(v), border=1)
    pdf.ln()
    if accts:
        pdf.ln(5)
        pdf.set_font(font, "B", 13)
        pdf.cell(0, 8, s("Followers"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(font, "B", 10)
        acols = [("Account", 80), ("Start of month", 35), ("End of month", 35), ("Growth", 30)]
        for n, w in acols:
            pdf.cell(w, 8, s(n), border=1, fill=True)
        pdf.ln()
        pdf.set_font(font, "", 10)
        for a in accts:
            g = (a["end"] - a["start"]) if (a["start"] is not None and a["end"] is not None) else None
            vals = (f"{a['label']} {a['account']}", "—" if a["start"] is None else f"{a['start']:,}",
                    "—" if a["end"] is None else f"{a['end']:,}", "—" if g is None else f"{'+' if g >= 0 else ''}{g:,}")
            for (n, w), v in zip(acols, vals):
                pdf.cell(w, 7, s(v), border=1)
            pdf.ln()
    pdf.ln(5)
    pdf.set_font(font, "B", 13)
    pdf.cell(0, 8, s("By platform (this month)"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(font, "", 10)
    for t in cur["totals"]:
        pdf.cell(0, 6, s(f"{t['label']}: {t['posts']} posts · {t['views']:,} views · {t['engagement']:,} engagements "
                         f"· {t['engagement_rate']}% rate"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font(font, "B", 13)
    pdf.cell(0, 8, s("Top posts"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(font, "", 10)
    for i, it in enumerate(cur["top"][:8], 1):
        try:
            pdf.multi_cell(0, 6, s(f"{i}. {it['title'][:70]} — {it['views']:,} views, {it['engagement']:,} engagements"))
        except Exception:
            pass
    return BytesIO(bytes(pdf.output()))


@app.route("/api/analytics/monthly-report.pdf")
def api_monthly_report():
    u = require_login()
    db = get_db()
    month = request.args.get("month") or datetime.utcnow().strftime("%Y-%m")
    if not re.match(r"^\d{4}-\d{2}$", month):
        return jsonify({"error": "Month must look like 2026-09."}), 400
    brand = _rget(u, "active_brand_id")
    cur, prev, accts, kit, start = monthly_report_data(db, ws_member_ids(db, u), month, billing_user_id(u), brand)
    company = (db.execute("SELECT name FROM brands WHERE id=?", (brand,)).fetchone() or {"name": None})["name"] if brand else None
    buf = build_monthly_pdf(cur, prev, accts, kit, start, company or os.environ.get("COMPANY_NAME") or "SocialPlatform")
    return send_file(buf, as_attachment=True, download_name=f"monthly-report-{month}.pdf", mimetype="application/pdf")


@app.route("/api/analytics/monthly-report/email", methods=["POST"])
def api_monthly_report_email():
    u = require_login()
    db = get_db()
    d = request.get_json(force=True) or {}
    month = d.get("month") or datetime.utcnow().strftime("%Y-%m")
    to = (d.get("to") or uget_setting(db, u["id"], "report_email") or u.get("email") or "").strip()
    if not to:
        return jsonify({"error": "Enter an email address."}), 400
    cur, prev, accts, kit, start = monthly_report_data(db, ws_member_ids(db, u), month, billing_user_id(u),
                                                       _rget(u, "active_brand_id"))
    pdf = build_monthly_pdf(cur, prev, accts, kit, start, os.environ.get("COMPANY_NAME") or "SocialPlatform").getvalue()
    ok, msg = send_email(db, to, f"Monthly social media report — {start.strftime('%B %Y')}",
                         f"Attached: your social media performance for {start.strftime('%B %Y')}.",
                         [(f"monthly-report-{month}.pdf", pdf, "application/pdf")])
    if not ok:
        return jsonify({"error": msg}), 400
    log_activity(db, u, "report_emailed", "", None, f"monthly {month} → {to}")
    return jsonify({"ok": True})


def _monthly_reports():
    """1st of the month, 09:00+: email last month's branded report to every workspace
    that set a report email in Setup → Alerts & reports."""
    try:
        now = datetime.now()
        if now.day != 1 or now.hour < 9:
            return
        db = db_connect()
        if not _smtp_cfg(db)["host"]:
            db.close()
            return
        last = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        for r in db.execute("SELECT key, value FROM settings WHERE key LIKE 'u%_report_email'").fetchall():
            to = (r["value"] or "").strip()
            m = re.match(r"u(\d+)_report_email", r["key"])
            if not (to and m):
                continue
            uid = int(m.group(1))
            if uget_setting(db, uid, "monthly_sent") == last:
                continue
            urow = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if not urow:
                continue
            ud = dict(urow)
            cur, prev, accts, kit, start = monthly_report_data(db, ws_member_ids(db, ud), last, billing_user_id(ud))
            pdf = build_monthly_pdf(cur, prev, accts, kit, start, os.environ.get("COMPANY_NAME") or "SocialPlatform").getvalue()
            ok, _ = send_email(db, to, f"Monthly social media report — {start.strftime('%B %Y')}",
                               f"Attached: your social media performance for {start.strftime('%B %Y')}.",
                               [(f"monthly-report-{last}.pdf", pdf, "application/pdf")])
            if ok:
                uset_setting(db, uid, "monthly_sent", last)
        db.close()
    except Exception:
        pass


@app.route("/api/signup-open")
def api_signup_open():
    """Public: lets the login page hide "Create account" when sign-up is closed."""
    return jsonify({"allow": (get_setting(get_db(), "allow_signup") or "1") != "0"})


@app.route("/api/settings/signup", methods=["GET", "POST"])
def api_signup_setting():
    u = require_login()
    db = get_db()
    if request.method == "POST":
        if not is_super(u):
            return jsonify({"error": "Only the SuperAdmin can change this."}), 403
        set_setting(db, "allow_signup", "1" if (request.get_json(force=True) or {}).get("allow") else "0")
    return jsonify({"allow": (get_setting(db, "allow_signup") or "1") != "0"})


# --------------------------------------------------------------------------- #
#  Background scheduler — auto-publishes due calendar items and posts
#  subscription-renewal reminders.
# --------------------------------------------------------------------------- #
_SCHED_STARTED = False


def _is_due(r, today, hm, utc_now):
    pa = (r["publish_at"] or "").strip() if "publish_at" in r.keys() else ""
    if pa:
        return pa[:19] <= utc_now[:19]          # exact UTC instant (timezone-safe)
    dt = (r["date"] or "")
    if not dt:
        return False
    if dt < today:
        return True
    if dt == today:
        t = (r["publish_time"] or "").strip()
        return (not t) or (t <= hm)
    return False


def _scheduler_loop():
    last_sub_check = ""
    last_stats = last_tokens = last_report = last_accounts = last_dms = 0
    while True:
        try:
            db = db_connect()
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            hm = now.strftime("%H:%M")
            utc_now = datetime.utcnow().isoformat()
            # (a) queue approved + scheduled items whose date/time has arrived
            rows = db.execute(
                "SELECT * FROM calendar_items WHERE approved=1 "
                "AND state IN ('approved','scheduled') "
                "AND (auto_publish IS NULL OR auto_publish=1) "
                "AND (publish_state IS NULL OR publish_state NOT IN ('publishing','published','partial','failed'))"
            ).fetchall()
            for r in rows:
                if _is_due(r, today, hm, utc_now):
                    try:
                        enqueue_publish(db, r, None, actor_name="scheduler")
                    except Exception as e:  # noqa
                        db.execute("UPDATE calendar_items SET publish_state='failed' WHERE id=?", (r["id"],))
                        db.commit()
                        send_alert(db, owner_and_admins(db, r["owner_id"]), "Scheduled post failed",
                                   f'❌ "{r["title"]}" could not be queued: {e}', link=f"calendar:{r['id']}",
                                   event="publish_failed", payload={"item_id": r["id"]})
            # (b) subscription reminders — evaluated once per calendar day
            if last_sub_check != today:
                last_sub_check = today
                try:
                    subs = db.execute(
                        "SELECT id, subscription_expiry FROM users "
                        "WHERE subscription_expiry IS NOT NULL AND subscription_expiry<>''"
                    ).fetchall()
                    for s in subs:
                        dleft = _days_left(s["subscription_expiry"])
                        if dleft is None:
                            continue
                        if 0 <= dleft <= SUB_RENEWAL_WARN_DAYS:
                            add_notification(db, f"⏳ Subscription renews in {dleft} day(s). "
                                                 f"Renew in Subscription & Billing to avoid interruption.",
                                             "subscription", "system", recipients=[s["id"]])
                        elif dleft < 0:
                            add_notification(db, "🔒 Subscription expired — creating, editing & "
                                                 "publishing are disabled until you renew.",
                                             "subscription", "system", recipients=[s["id"]])
                except Exception:
                    pass
            db.close()
        except Exception:
            pass
        # (c) background maintenance, each in its own thread so publishing never waits
        t = time.time()
        if t - last_stats > 600:
            last_stats = t
            threading.Thread(target=_refresh_all_stats, daemon=True).start()
        if t - last_tokens > 3600:
            last_tokens = t
            threading.Thread(target=_check_token_health, daemon=True).start()
        if t - last_report > 1800:
            last_report = t
            threading.Thread(target=_weekly_reports, daemon=True).start()
            threading.Thread(target=_monthly_reports, daemon=True).start()
        if t - last_accounts > 6 * 3600:
            last_accounts = t
            threading.Thread(target=_snapshot_all_accounts, daemon=True).start()
        if t - last_dms > 600:
            last_dms = t
            threading.Thread(target=_sync_all_dms, daemon=True).start()
        time.sleep(30)


def _start_scheduler():
    global _SCHED_STARTED
    if _SCHED_STARTED:
        return
    _SCHED_STARTED = True
    threading.Thread(target=_scheduler_loop, daemon=True).start()
    threading.Thread(target=_job_worker_loop, daemon=True).start()


def _seed_public_base_url():
    """Once deployed, fix the "Redirect Base URL" (and public media base) to the
    live deployment URL for ALL users — automatically, no per-user setup.

    Order of preference: PUBLIC_BASE_URL env → RENDER_EXTERNAL_URL (set by Render
    automatically). Only fills the value when it isn't already set, so a manual
    override in the app is never clobbered. Applies globally via app settings."""
    url = (os.environ.get("PUBLIC_BASE_URL")
           or os.environ.get("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")
    if not url:
        return
    try:
        db = db_connect()
        for key in ("oauth_redirect_base", "public_base_url"):
            if not (get_setting(db, key) or "").strip():
                set_setting(db, key, url)
        db.close()
    except Exception:
        pass


# --------------------------------------------------------------------------- #
#  Boot
# --------------------------------------------------------------------------- #
# Initialise the DB at import time too, so WSGI servers (gunicorn) work.
init_db()
_seed_public_base_url()
_start_scheduler()

if __name__ == "__main__":
    print("\n  Social Media Production Dashboard — Version 26")
    print("  ---------------------------------------------")
    print("  Open:  http://127.0.0.1:5000\n")
    # 0.0.0.0 so it also works inside a container / VM for the demo
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    # threaded=True: serve multiple requests at once so a long-running job (e.g.
    # content generation) in one panel never blocks loading or updating another.
    app.run(host=host, port=port, debug=False, threaded=True)
