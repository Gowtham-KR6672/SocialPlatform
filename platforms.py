"""
Platform adapters — real API integrations for every supported social network.

Each adapter is a set of plain functions (no Flask, no DB) so they can run from
an HTTP request OR the background job worker:

    oauth_url(platform, client_id, redirect_uri, state, code_challenge)
    exchange_code(platform, client_id, client_secret, code, redirect_uri, verifier)
    refresh(platform, account)          -> updated token fields or None
    publish(platform, account, media, text, opts)
    stats(platform, account, remote_id)
    comments(platform, account, remote_id)
    reply(platform, account, remote_id, comment_id, text)

`account` is a dict:  token, refresh_token, expires_at, account_id,
                      account_name, extra (dict), app_id, app_secret
`media` is a dict:    kind (video|image|carousel|text), items [{path, url, mime,
                      is_video}], thumb_path, thumb_url
`opts` is a dict:     post_type (reel|post|story|short), title, privacy, tags

Every network call is best-effort and returns / raises PlatformError with a
readable message — the job worker turns that into a retry or a failed status.
"""
import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

META_VERSION = "v26.0"
FB_GRAPH = f"https://graph.facebook.com/{META_VERSION}"
FB_GRAPH_VIDEO = f"https://graph-video.facebook.com/{META_VERSION}"
IG_GRAPH = f"https://graph.instagram.com/{META_VERSION}"
THREADS_GRAPH = "https://graph.threads.net/v1.0"
YT_API = "https://www.googleapis.com/youtube/v3"
YT_UPLOAD = "https://www.googleapis.com/upload/youtube/v3"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
X_API = "https://api.x.com/2"
LI_API = "https://api.linkedin.com"
TT_API = "https://open.tiktokapis.com/v2"
PIN_API = "https://api.pinterest.com/v5"

CHUNK = 8 * 1024 * 1024          # 8 MB upload chunks


class PlatformError(Exception):
    """A readable, user-facing publishing/API error. `retry` marks transient
    failures (network, rate limit, server error) that are worth retrying."""

    def __init__(self, msg, retry=False):
        super().__init__(msg)
        self.retry = retry


# --------------------------------------------------------------------------- #
#  Platform catalogue: labels, credential names, limits and capabilities
# --------------------------------------------------------------------------- #
PLATFORMS = {
    "instagram": {"label": "Instagram", "id_label": "Instagram App ID", "secret_label": "Instagram App Secret",
                  "caption_max": 2200, "hashtag_max": 30,
                  "supports": ["video", "image", "carousel", "story"],
                  "video": {"max_duration": 900, "reel_max": 180, "aspect": "9:16", "max_mb": 1024},
                  "needs_public_url": True},
    "facebook":  {"label": "Facebook Page", "id_label": "Facebook App ID", "secret_label": "Facebook App Secret",
                  "caption_max": 63206, "hashtag_max": 30,
                  "supports": ["video", "image", "carousel", "story", "text"],
                  "video": {"max_duration": 14400, "reel_max": 90, "aspect": "any", "max_mb": 4096}},
    "youtube":   {"label": "YouTube", "id_label": "Google OAuth Client ID", "secret_label": "Google OAuth Client Secret",
                  "caption_max": 5000, "title_max": 100, "hashtag_max": 15,
                  "supports": ["video"],
                  "video": {"max_duration": 43200, "short_max": 180, "aspect": "any", "max_mb": 131072}},
    "twitter":   {"label": "X (Twitter)", "id_label": "OAuth 2.0 Client ID", "secret_label": "OAuth 2.0 Client Secret",
                  "caption_max": 280, "hashtag_max": 3,
                  "supports": ["video", "image", "carousel", "text"], "carousel_max": 4,
                  "video": {"max_duration": 140, "aspect": "any", "max_mb": 512}},
    "linkedin":  {"label": "LinkedIn", "id_label": "LinkedIn Client ID", "secret_label": "LinkedIn Client Secret",
                  "caption_max": 3000, "hashtag_max": 5,
                  "supports": ["video", "image", "carousel", "text"], "carousel_max": 20,
                  "video": {"max_duration": 1800, "aspect": "any", "max_mb": 5120}},
    "threads":   {"label": "Threads", "id_label": "Threads App ID", "secret_label": "Threads App Secret",
                  "caption_max": 500, "hashtag_max": 1,
                  "supports": ["video", "image", "carousel", "text"], "carousel_max": 20,
                  "video": {"max_duration": 300, "aspect": "any", "max_mb": 1024},
                  "needs_public_url": True},
    "tiktok":    {"label": "TikTok", "id_label": "TikTok Client Key", "secret_label": "TikTok Client Secret",
                  "caption_max": 2200, "hashtag_max": 10,
                  "supports": ["video"],
                  "video": {"max_duration": 600, "aspect": "9:16", "max_mb": 4096}},
    "pinterest": {"label": "Pinterest", "id_label": "Pinterest App ID", "secret_label": "Pinterest App Secret",
                  "caption_max": 500, "title_max": 100, "hashtag_max": 5,
                  "supports": ["video", "image", "carousel"], "carousel_max": 5,
                  "video": {"max_duration": 900, "aspect": "any", "max_mb": 2048}},
}
ORDER = ["instagram", "facebook", "youtube", "twitter", "linkedin", "threads", "tiktok", "pinterest"]

OAUTH = {
    "instagram": {"auth": "https://www.instagram.com/oauth/authorize", "sep": ",",
                  "scopes": ["instagram_business_basic", "instagram_business_content_publish",
                             "instagram_business_manage_comments", "instagram_business_manage_insights",
                             "instagram_business_manage_messages"]},
    "facebook":  {"auth": f"https://www.facebook.com/{META_VERSION}/dialog/oauth", "sep": ",",
                  "scopes": ["pages_show_list", "pages_read_engagement", "pages_manage_posts",
                             "pages_read_user_content", "pages_manage_engagement", "read_insights",
                             "pages_messaging"]},
    "youtube":   {"auth": "https://accounts.google.com/o/oauth2/v2/auth", "sep": " ",
                  "scopes": ["https://www.googleapis.com/auth/youtube.upload",
                             "https://www.googleapis.com/auth/youtube.force-ssl",
                             "https://www.googleapis.com/auth/youtube.readonly"],
                  "extra": {"access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"}},
    "twitter":   {"auth": "https://x.com/i/oauth2/authorize", "sep": " ", "pkce": True,
                  "scopes": ["tweet.read", "tweet.write", "users.read", "offline.access", "media.write"]},
    "linkedin":  {"auth": "https://www.linkedin.com/oauth/v2/authorization", "sep": " ",
                  "scopes": ["openid", "profile", "w_member_social"]},
    "threads":   {"auth": "https://threads.net/oauth/authorize", "sep": ",",
                  "scopes": ["threads_basic", "threads_content_publish", "threads_manage_replies",
                             "threads_read_replies", "threads_manage_insights"]},
    "tiktok":    {"auth": "https://www.tiktok.com/v2/auth/authorize/", "sep": ",", "client_param": "client_key",
                  # video.list needs the Display API product, which TikTok no longer offers to new
                  # apps; without it per-video stats and "Import past posts" simply come back empty
                  "scopes": ["user.info.basic", "user.info.stats", "video.publish", "video.upload"]},
    "pinterest": {"auth": "https://www.pinterest.com/oauth/", "sep": ",",
                  "scopes": ["boards:read", "pins:read", "pins:write", "user_accounts:read"]},
}


# --------------------------------------------------------------------------- #
#  HTTP helpers
# --------------------------------------------------------------------------- #
class R:
    def __init__(self, ok, status, data, headers):
        self.ok, self.status, self.data, self.headers = ok, status, data, headers or {}

    def err(self):
        d = self.data
        if isinstance(d, dict):
            e = d.get("error")
            if isinstance(e, dict):
                return e.get("message") or e.get("error_user_msg") or json.dumps(e)[:300]
            return (d.get("error_description") or d.get("message") or d.get("detail")
                    or (e if isinstance(e, str) else "") or json.dumps(d)[:300])
        return str(d)[:300]


def _req(url, data=None, headers=None, method=None, form=None, json_body=None, timeout=90):
    hdrs = {"Accept": "application/json", "User-Agent": "SocialPlatform/1.0"}
    if headers:
        hdrs.update(headers)
    body = None
    if json_body is not None:
        body = json.dumps(json_body).encode()
        hdrs["Content-Type"] = "application/json"
    elif form is not None:
        body = urllib.parse.urlencode(form).encode()
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    elif data is not None:
        body = data
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            hd = {k.lower(): v for k, v in r.headers.items()}
            try:
                return R(True, r.status, json.loads(raw) if raw else {}, hd)
            except Exception:
                return R(True, r.status, raw, hd)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        hd = {k.lower(): v for k, v in (e.headers or {}).items()}
        try:
            return R(False, e.code, json.loads(raw), hd)
        except Exception:
            return R(False, e.code, raw, hd)
    except Exception as e:  # network / timeout
        return R(False, 0, str(e), {})


def _must(r, what):
    if not r.ok:
        raise PlatformError(f"{what} failed ({r.status or 'network error'}): {r.err()}",
                            retry=(r.status == 0 or r.status == 429 or r.status >= 500))
    return r.data


def _multipart(fields, files):
    """fields: dict; files: list of (field, filename, bytes, mime)."""
    b = "----sp" + secrets.token_hex(12)
    out = []
    for k, v in (fields or {}).items():
        out.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for name, fn, content, mime in (files or []):
        out.append(f'--{b}\r\nContent-Disposition: form-data; name="{name}"; filename="{fn}"\r\n'
                   f'Content-Type: {mime}\r\n\r\n'.encode() + content + b"\r\n")
    out.append(f"--{b}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={b}"


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


def _basic(cid, secret):
    return "Basic " + base64.b64encode(f"{cid}:{secret}".encode()).decode()


def _exp(expires_in):
    try:
        return time.time() + int(expires_in) if expires_in else None
    except Exception:
        return None


def pkce_pair():
    verifier = secrets.token_urlsafe(48)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def split_text(text, limit):
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _videos(media):
    return [i for i in media.get("items", []) if i.get("is_video")]


def _images(media):
    return [i for i in media.get("items", []) if not i.get("is_video")]


def _need_url(item, platform):
    if not item.get("url"):
        raise PlatformError(f"{PLATFORMS[platform]['label']} downloads media from a public HTTPS URL. "
                            "Set a Public Base URL (Setup) or enable Supabase Storage, then retry.")
    return item["url"]


# --------------------------------------------------------------------------- #
#  OAuth
# --------------------------------------------------------------------------- #
def oauth_url(platform, client_id, redirect_uri, state, code_challenge=None):
    cfg = OAUTH[platform]
    params = {cfg.get("client_param", "client_id"): client_id, "redirect_uri": redirect_uri,
              "response_type": "code", "scope": cfg["sep"].join(cfg["scopes"]), "state": state}
    params.update(cfg.get("extra", {}))
    if cfg.get("pkce") and code_challenge:
        params.update({"code_challenge": code_challenge, "code_challenge_method": "S256"})
    return cfg["auth"] + "?" + urllib.parse.urlencode(params)


def exchange_code(platform, cid, secret, code, redirect_uri, verifier=None):
    """Returns dict: token, refresh_token, expires_at, account_id, account_name, extra."""
    fn = globals().get(f"_{platform}_exchange")
    if not fn:
        raise PlatformError("Unsupported platform.")
    return fn(cid, secret, code, redirect_uri, verifier)


def _instagram_exchange(cid, secret, code, redirect, _v):
    d = _must(_req("https://api.instagram.com/oauth/access_token", method="POST", form={
        "client_id": cid, "client_secret": secret, "grant_type": "authorization_code",
        "redirect_uri": redirect, "code": code}), "Instagram token exchange")
    token, uid, expires = d.get("access_token"), str(d.get("user_id") or ""), None
    lr = _req("https://graph.instagram.com/access_token?" + urllib.parse.urlencode({
        "grant_type": "ig_exchange_token", "client_secret": secret, "access_token": token}))
    if lr.ok and isinstance(lr.data, dict) and lr.data.get("access_token"):
        token, expires = lr.data["access_token"], _exp(lr.data.get("expires_in"))
    else:
        raise PlatformError("Instagram signed you in, but Meta refused the long-lived (60-day) sign-in "
                            f"({lr.err()}). Without it the connection stops working within an hour. This "
                            "usually means Meta is limiting the account — check the Instagram app for a "
                            "warning or 'confirm it's you' prompt, then click Connect again.")
    me = _req(f"{IG_GRAPH}/me?" + urllib.parse.urlencode({"fields": "user_id,username", "access_token": token}))
    name = ""
    if me.ok and isinstance(me.data, dict):
        uid = str(me.data.get("user_id") or me.data.get("id") or uid)
        name = "@" + me.data["username"] if me.data.get("username") else ""
    return {"token": token, "refresh_token": "", "expires_at": expires,
            "account_id": uid, "account_name": name or uid, "extra": {}}


def _facebook_exchange(cid, secret, code, redirect, _v):
    d = _must(_req(f"{FB_GRAPH}/oauth/access_token?" + urllib.parse.urlencode({
        "client_id": cid, "client_secret": secret, "redirect_uri": redirect, "code": code})),
        "Facebook token exchange")
    user_token = d["access_token"]
    lr = _req(f"{FB_GRAPH}/oauth/access_token?" + urllib.parse.urlencode({
        "grant_type": "fb_exchange_token", "client_id": cid, "client_secret": secret,
        "fb_exchange_token": user_token}))
    if lr.ok and isinstance(lr.data, dict) and lr.data.get("access_token"):
        user_token = lr.data["access_token"]
    pages = _must(_req(f"{FB_GRAPH}/me/accounts?" + urllib.parse.urlencode({
        "fields": "id,name,access_token", "access_token": user_token})), "Listing Facebook Pages").get("data", [])
    if not pages:
        raise PlatformError("No Facebook Pages found. Posting requires a Page you manage.")
    p = pages[0]
    # Page tokens obtained from a long-lived user token do not expire.
    return {"token": p["access_token"], "refresh_token": "", "expires_at": None,
            "account_id": p["id"], "account_name": p.get("name", p["id"]),
            "extra": {"pages": [{"id": x["id"], "name": x.get("name"), "token": x.get("access_token")}
                                for x in pages]}}


def _youtube_exchange(cid, secret, code, redirect, _v):
    d = _must(_req(GOOGLE_TOKEN, method="POST", form={
        "code": code, "client_id": cid, "client_secret": secret,
        "redirect_uri": redirect, "grant_type": "authorization_code"}), "Google token exchange")
    token = d["access_token"]
    ch = _req(f"{YT_API}/channels?part=snippet&mine=true", headers={"Authorization": "Bearer " + token})
    items = (ch.data or {}).get("items", []) if ch.ok and isinstance(ch.data, dict) else []
    if not items:
        raise PlatformError("This Google account has no YouTube channel.")
    return {"token": token, "refresh_token": d.get("refresh_token", ""), "expires_at": _exp(d.get("expires_in")),
            "account_id": items[0]["id"], "account_name": items[0]["snippet"].get("title", ""), "extra": {}}


def _twitter_exchange(cid, secret, code, redirect, verifier):
    hdr = {"Authorization": _basic(cid, secret)} if secret else {}
    d = _must(_req(f"{X_API}/oauth2/token", method="POST", headers=hdr, form={
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect,
        "code_verifier": verifier or "", "client_id": cid}), "X token exchange")
    token = d["access_token"]
    me = _must(_req(f"{X_API}/users/me", headers={"Authorization": "Bearer " + token}), "X profile").get("data", {})
    return {"token": token, "refresh_token": d.get("refresh_token", ""), "expires_at": _exp(d.get("expires_in")),
            "account_id": me.get("id", ""), "account_name": "@" + me.get("username", ""), "extra": {}}


def _linkedin_exchange(cid, secret, code, redirect, _v):
    d = _must(_req("https://www.linkedin.com/oauth/v2/accessToken", method="POST", form={
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect,
        "client_id": cid, "client_secret": secret}), "LinkedIn token exchange")
    token = d["access_token"]
    me = _must(_req(f"{LI_API}/v2/userinfo", headers={"Authorization": "Bearer " + token}), "LinkedIn profile")
    return {"token": token, "refresh_token": d.get("refresh_token", ""), "expires_at": _exp(d.get("expires_in")),
            "account_id": "urn:li:person:" + me.get("sub", ""), "account_name": me.get("name", ""), "extra": {}}


def _threads_exchange(cid, secret, code, redirect, _v):
    d = _must(_req("https://graph.threads.net/oauth/access_token", method="POST", form={
        "client_id": cid, "client_secret": secret, "grant_type": "authorization_code",
        "redirect_uri": redirect, "code": code}), "Threads token exchange")
    token, uid, expires = d["access_token"], str(d.get("user_id", "")), None
    lr = _req("https://graph.threads.net/access_token?" + urllib.parse.urlencode({
        "grant_type": "th_exchange_token", "client_secret": secret, "access_token": token}))
    if lr.ok and isinstance(lr.data, dict) and lr.data.get("access_token"):
        token, expires = lr.data["access_token"], _exp(lr.data.get("expires_in"))
    else:
        raise PlatformError("Threads signed you in, but Meta refused the long-lived (60-day) sign-in "
                            f"({lr.err()}). Without it the connection stops working within an hour. This "
                            "usually means Meta is limiting the account — check the Threads app for a "
                            "warning or 'confirm it's you' prompt, then click Connect again.")
    me = _req(f"{THREADS_GRAPH}/me?" + urllib.parse.urlencode({"fields": "id,username", "access_token": token}))
    name = ""
    if me.ok and isinstance(me.data, dict):
        uid = str(me.data.get("id") or uid)
        name = "@" + me.data.get("username", "")
    return {"token": token, "refresh_token": "", "expires_at": expires,
            "account_id": uid, "account_name": name or uid, "extra": {}}


def _tiktok_exchange(cid, secret, code, redirect, _v):
    d = _must(_req(f"{TT_API}/oauth/token/", method="POST", form={
        "client_key": cid, "client_secret": secret, "code": code,
        "grant_type": "authorization_code", "redirect_uri": redirect}), "TikTok token exchange")
    if d.get("error"):
        raise PlatformError(f"TikTok: {d.get('error_description') or d.get('error')}")
    token = d["access_token"]
    info = _req(f"{TT_API}/user/info/?fields=open_id,display_name", headers={"Authorization": "Bearer " + token})
    user = ((info.data or {}).get("data") or {}).get("user", {}) if info.ok and isinstance(info.data, dict) else {}
    return {"token": token, "refresh_token": d.get("refresh_token", ""), "expires_at": _exp(d.get("expires_in")),
            "account_id": d.get("open_id") or user.get("open_id", ""),
            "account_name": user.get("display_name", "TikTok account"), "extra": {}}


def _pinterest_exchange(cid, secret, code, redirect, _v):
    d = _must(_req(f"{PIN_API}/oauth/token", method="POST", headers={"Authorization": _basic(cid, secret)},
                   form={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect}),
              "Pinterest token exchange")
    token = d["access_token"]
    hdr = {"Authorization": "Bearer " + token}
    me = _req(f"{PIN_API}/user_account", headers=hdr)
    boards = _req(f"{PIN_API}/boards?page_size=50", headers=hdr)
    blist = (boards.data or {}).get("items", []) if boards.ok and isinstance(boards.data, dict) else []
    uname = (me.data or {}).get("username", "") if me.ok and isinstance(me.data, dict) else ""
    return {"token": token, "refresh_token": d.get("refresh_token", ""), "expires_at": _exp(d.get("expires_in")),
            "account_id": uname, "account_name": "@" + uname if uname else "Pinterest",
            "extra": {"boards": [{"id": b["id"], "name": b.get("name")} for b in blist],
                      "board_id": blist[0]["id"] if blist else ""}}


# --------------------------------------------------------------------------- #
#  Token refresh — returns dict of updated fields, or None if not refreshable
# --------------------------------------------------------------------------- #
def refresh(platform, a):
    cid, secret, rt, tok = a.get("app_id"), a.get("app_secret"), a.get("refresh_token"), a.get("token")
    if platform == "instagram" and tok:
        r = _req("https://graph.instagram.com/refresh_access_token?" + urllib.parse.urlencode({
            "grant_type": "ig_refresh_token", "access_token": tok}))
        d = _must(r, "Instagram token refresh")
        return {"token": d["access_token"], "expires_at": _exp(d.get("expires_in"))}
    if platform == "threads" and tok:
        r = _req("https://graph.threads.net/refresh_access_token?" + urllib.parse.urlencode({
            "grant_type": "th_refresh_token", "access_token": tok}))
        d = _must(r, "Threads token refresh")
        return {"token": d["access_token"], "expires_at": _exp(d.get("expires_in"))}
    if not rt:
        return None
    if platform == "youtube":
        d = _must(_req(GOOGLE_TOKEN, method="POST", form={
            "client_id": cid, "client_secret": secret, "refresh_token": rt, "grant_type": "refresh_token"}),
            "Google token refresh")
        return {"token": d["access_token"], "expires_at": _exp(d.get("expires_in"))}
    if platform == "twitter":
        hdr = {"Authorization": _basic(cid, secret)} if secret else {}
        d = _must(_req(f"{X_API}/oauth2/token", method="POST", headers=hdr, form={
            "grant_type": "refresh_token", "refresh_token": rt, "client_id": cid}), "X token refresh")
        return {"token": d["access_token"], "refresh_token": d.get("refresh_token", rt),
                "expires_at": _exp(d.get("expires_in"))}
    if platform == "linkedin":
        d = _must(_req("https://www.linkedin.com/oauth/v2/accessToken", method="POST", form={
            "grant_type": "refresh_token", "refresh_token": rt, "client_id": cid, "client_secret": secret}),
            "LinkedIn token refresh")
        return {"token": d["access_token"], "refresh_token": d.get("refresh_token", rt),
                "expires_at": _exp(d.get("expires_in"))}
    if platform == "tiktok":
        d = _must(_req(f"{TT_API}/oauth/token/", method="POST", form={
            "client_key": cid, "client_secret": secret, "grant_type": "refresh_token", "refresh_token": rt}),
            "TikTok token refresh")
        return {"token": d["access_token"], "refresh_token": d.get("refresh_token", rt),
                "expires_at": _exp(d.get("expires_in"))}
    if platform == "pinterest":
        d = _must(_req(f"{PIN_API}/oauth/token", method="POST", headers={"Authorization": _basic(cid, secret)},
                       form={"grant_type": "refresh_token", "refresh_token": rt}), "Pinterest token refresh")
        return {"token": d["access_token"], "refresh_token": d.get("refresh_token", rt),
                "expires_at": _exp(d.get("expires_in"))}
    return None


# --------------------------------------------------------------------------- #
#  Publishing
# --------------------------------------------------------------------------- #
def publish(platform, account, media, text, opts):
    """Returns {"remote_id", "permalink", "message"}; raises PlatformError."""
    spec = PLATFORMS[platform]
    kind = media.get("kind", "video")
    if opts.get("post_type") == "story" and "story" not in spec["supports"]:
        raise PlatformError(f"{spec['label']} doesn't support Stories.")
    if kind not in spec["supports"] and not (kind == "text" and "text" in spec["supports"]):
        raise PlatformError(f"{spec['label']} doesn't support {kind} posts.")
    fn = globals()[f"_{platform}_publish"]
    return fn(account, media, split_text(text, spec["caption_max"]), opts)


# ---- Instagram ------------------------------------------------------------ #
def _ig_wait(cid, token, tries=40):
    for _ in range(tries):
        r = _req(f"{IG_GRAPH}/{cid}?" + urllib.parse.urlencode({"fields": "status_code,status", "access_token": token}))
        st = (r.data or {}).get("status_code") if isinstance(r.data, dict) else None
        if st == "FINISHED":
            return
        if st in ("ERROR", "EXPIRED"):
            raise PlatformError(f"Instagram couldn't process the media: {(r.data or {}).get('status', st)}")
        time.sleep(4)
    raise PlatformError("Instagram media processing timed out.", retry=True)


def _instagram_publish(a, media, text, opts):
    tok, uid = a["token"], a["account_id"]

    def container(params):
        params["access_token"] = tok
        return _must(_req(f"{IG_GRAPH}/{uid}/media", method="POST", form=params), "Instagram container")["id"]

    items, story = media["items"], opts.get("post_type") == "story"
    if media["kind"] == "carousel":
        children = []
        for it in items[:10]:
            p = {"is_carousel_item": "true"}
            if it["is_video"]:
                p.update({"media_type": "VIDEO", "video_url": _need_url(it, "instagram")})
            else:
                p["image_url"] = _need_url(it, "instagram")
            c = container(p)
            _ig_wait(c, tok)
            children.append(c)
        cid = container({"media_type": "CAROUSEL", "children": ",".join(children), "caption": text})
    else:
        it = items[0]
        if it["is_video"]:
            p = {"media_type": "STORIES" if story else "REELS", "video_url": _need_url(it, "instagram")}
            if not story:
                p.update({"caption": text, "share_to_feed": "true"})
                if media.get("thumb_url"):
                    p["cover_url"] = media["thumb_url"]
        else:
            p = {"image_url": _need_url(it, "instagram")}
            if story:
                p["media_type"] = "STORIES"
            else:
                p["caption"] = text
        cid = container(p)
    _ig_wait(cid, tok)
    mid = _must(_req(f"{IG_GRAPH}/{uid}/media_publish", method="POST",
                     form={"creation_id": cid, "access_token": tok}), "Instagram publish")["id"]
    pl = _req(f"{IG_GRAPH}/{mid}?" + urllib.parse.urlencode({"fields": "permalink", "access_token": tok}))
    link = (pl.data or {}).get("permalink", "") if pl.ok and isinstance(pl.data, dict) else ""
    return {"remote_id": mid, "permalink": link, "message": "Published to Instagram."}


# ---- Facebook Page -------------------------------------------------------- #
def _fb_rupload(a, edge, path, finish_extra):
    """Reels / video stories: start → upload binary to rupload → finish."""
    tok, page = a["token"], a["account_id"]
    start = _must(_req(f"{FB_GRAPH}/{page}/{edge}", method="POST",
                       form={"upload_phase": "start", "access_token": tok}), "Facebook upload start")
    vid = start["video_id"]
    url = start.get("upload_url") or f"https://rupload.facebook.com/video-upload/{META_VERSION}/{vid}"
    size = os.path.getsize(path)
    _must(_req(url, data=_read(path), method="POST", timeout=900, headers={
        "Authorization": "OAuth " + tok, "offset": "0", "file_size": str(size),
        "Content-Type": "application/octet-stream"}), "Facebook video upload")
    form = {"upload_phase": "finish", "video_id": vid, "access_token": tok}
    form.update(finish_extra)
    fin = _must(_req(f"{FB_GRAPH}/{page}/{edge}", method="POST", form=form), "Facebook upload finish")
    return vid, fin


def _fb_photo(a, it, published=True, caption=""):
    fields = {"access_token": a["token"], "published": "true" if published else "false"}
    if caption:
        fields["message"] = caption
    if it.get("url"):
        fields["url"] = it["url"]
        return _must(_req(f"{FB_GRAPH}/{a['account_id']}/photos", method="POST", form=fields), "Facebook photo")
    body, ct = _multipart(fields, [("source", os.path.basename(it["path"]), _read(it["path"]), it["mime"])])
    return _must(_req(f"{FB_GRAPH}/{a['account_id']}/photos", data=body, method="POST",
                      headers={"Content-Type": ct}, timeout=300), "Facebook photo")


def _facebook_publish(a, media, text, opts):
    tok, page, kind, pt = a["token"], a["account_id"], media["kind"], opts.get("post_type")
    items = media.get("items", [])
    if kind == "text":
        d = _must(_req(f"{FB_GRAPH}/{page}/feed", method="POST", form={"message": text, "access_token": tok}),
                  "Facebook post")
        return {"remote_id": d["id"], "permalink": f"https://www.facebook.com/{d['id']}", "message": "Posted."}
    if kind == "carousel":
        if _videos(media):
            raise PlatformError("Facebook multi-photo posts can't include videos.")
        ids = [_fb_photo(a, it, published=False)["id"] for it in items[:30]]
        form = {"message": text, "access_token": tok}
        for i, pid in enumerate(ids):
            form[f"attached_media[{i}]"] = json.dumps({"media_fbid": pid})
        d = _must(_req(f"{FB_GRAPH}/{page}/feed", method="POST", form=form), "Facebook multi-photo post")
        return {"remote_id": d["id"], "permalink": f"https://www.facebook.com/{d['id']}", "message": "Posted."}
    it = items[0]
    if not it["is_video"]:
        if pt == "story":
            ph = _fb_photo(a, it, published=False)
            d = _must(_req(f"{FB_GRAPH}/{page}/photo_stories", method="POST",
                           form={"photo_id": ph["id"], "access_token": tok}), "Facebook photo story")
            return {"remote_id": d.get("post_id", ph["id"]), "permalink": "", "message": "Story posted."}
        d = _fb_photo(a, it, caption=text)
        pid = d.get("post_id") or d["id"]
        return {"remote_id": pid, "permalink": f"https://www.facebook.com/{pid}", "message": "Photo posted."}
    if pt == "story":
        vid, fin = _fb_rupload(a, "video_stories", it["path"], {})
        return {"remote_id": fin.get("post_id", vid), "permalink": "", "message": "Video story posted."}
    if pt in ("reel", "short"):
        vid, _ = _fb_rupload(a, "video_reels", it["path"], {"video_state": "PUBLISHED", "description": text})
        return {"remote_id": vid, "permalink": f"https://www.facebook.com/reel/{vid}", "message": "Reel published."}
    fields = {"description": text, "access_token": tok}
    if opts.get("title"):
        fields["title"] = opts["title"][:255]
    files = [("source", os.path.basename(it["path"]), _read(it["path"]), it["mime"])]
    if media.get("thumb_path"):
        files.append(("thumb", "thumb.jpg", _read(media["thumb_path"]), "image/jpeg"))
    body, ct = _multipart(fields, files)
    d = _must(_req(f"{FB_GRAPH_VIDEO}/{page}/videos", data=body, method="POST",
                   headers={"Content-Type": ct}, timeout=1800), "Facebook video upload")
    return {"remote_id": d["id"], "permalink": f"https://www.facebook.com/{page}/videos/{d['id']}",
            "message": "Video published."}


# ---- YouTube -------------------------------------------------------------- #
def _youtube_publish(a, media, text, opts):
    vids = _videos(media)
    if not vids:
        raise PlatformError("YouTube only accepts videos.")
    it, tok = vids[0], a["token"]
    short = opts.get("post_type") in ("short", "reel", "story")
    title = (opts.get("title") or text.split("\n")[0] or "New video").strip()
    if short and "#shorts" not in (title + text).lower():
        title = (title[:90] + " #Shorts")
    meta = {"snippet": {"title": title[:100], "description": text[:5000],
                        "tags": [t.lstrip("#") for t in (opts.get("tags") or [])][:30], "categoryId": "22"},
            "status": {"privacyStatus": opts.get("privacy") or "public", "selfDeclaredMadeForKids": False}}
    size = os.path.getsize(it["path"])
    init = _req(f"{YT_UPLOAD}/videos?uploadType=resumable&part=snippet,status", method="POST", json_body=meta,
                headers={"Authorization": "Bearer " + tok, "X-Upload-Content-Type": it["mime"],
                         "X-Upload-Content-Length": str(size)})
    _must(init, "YouTube upload start")
    loc = init.headers.get("location")
    if not loc:
        raise PlatformError("YouTube did not return an upload URL.")
    up = _req(loc, data=_read(it["path"]), method="PUT", timeout=3600,
              headers={"Authorization": "Bearer " + tok, "Content-Type": it["mime"]})
    vid = _must(up, "YouTube upload")["id"]
    msg = "Uploaded to YouTube."
    if media.get("thumb_path"):
        tr = _req(f"{YT_UPLOAD}/thumbnails/set?videoId={vid}", data=_read(media["thumb_path"]), method="POST",
                  headers={"Authorization": "Bearer " + tok, "Content-Type": "image/jpeg"})
        if not tr.ok:
            msg += f" (Thumbnail not set: {tr.err()})"
    link = f"https://youtube.com/shorts/{vid}" if short else f"https://www.youtube.com/watch?v={vid}"
    return {"remote_id": vid, "permalink": link, "message": msg}


# ---- X (Twitter) ---------------------------------------------------------- #
def _x_upload(tok, it):
    hdr = {"Authorization": "Bearer " + tok}
    data = _read(it["path"])
    if not it["is_video"] and len(data) < 5 * 1024 * 1024:
        body, ct = _multipart({"media_category": "tweet_image"},
                              [("media", os.path.basename(it["path"]), data, it["mime"])])
        d = _must(_req(f"{X_API}/media/upload", data=body, method="POST",
                       headers=dict(hdr, **{"Content-Type": ct})), "X image upload")
        return (d.get("data") or d).get("id")
    cat = "tweet_video" if it["is_video"] else "tweet_image"
    init = _must(_req(f"{X_API}/media/upload/initialize", method="POST", headers=hdr, json_body={
        "media_type": it["mime"], "total_bytes": len(data), "media_category": cat}), "X upload start")
    mid = (init.get("data") or init)["id"]
    for i in range(0, len(data), CHUNK):
        body, ct = _multipart({"segment_index": str(i // CHUNK)}, [("media", "chunk", data[i:i + CHUNK],
                                                                   "application/octet-stream")])
        _must(_req(f"{X_API}/media/upload/{mid}/append", data=body, method="POST", timeout=600,
                   headers=dict(hdr, **{"Content-Type": ct})), "X upload chunk")
    fin = _must(_req(f"{X_API}/media/upload/{mid}/finalize", method="POST", headers=hdr), "X upload finish")
    info = (fin.get("data") or {}).get("processing_info")
    for _ in range(60):
        if not info or info.get("state") == "succeeded":
            break
        if info.get("state") == "failed":
            raise PlatformError(f"X couldn't process the media: {info.get('error', {}).get('message', '')}")
        time.sleep(int(info.get("check_after_secs", 3)))
        st = _req(f"{X_API}/media/upload?" + urllib.parse.urlencode({"command": "STATUS", "media_id": mid}),
                  headers=hdr)
        info = ((st.data or {}).get("data") or {}).get("processing_info") if isinstance(st.data, dict) else None
    return mid


def _twitter_publish(a, media, text, opts):
    tok = a["token"]
    body = {"text": text}
    if media["kind"] != "text":
        items = media["items"]
        if _videos(media):
            items = _videos(media)[:1]
        body["media"] = {"media_ids": [_x_upload(tok, it) for it in items[:4]]}
    d = _must(_req(f"{X_API}/tweets", method="POST", json_body=body,
                   headers={"Authorization": "Bearer " + tok}), "Posting to X")["data"]
    return {"remote_id": d["id"], "permalink": f"https://x.com/i/web/status/{d['id']}", "message": "Posted to X."}


# ---- LinkedIn ------------------------------------------------------------- #
def _li_version():
    d = datetime.utcnow().replace(day=1) - timedelta(days=45)   # a released, still-supported version
    return d.strftime("%Y%m")


def _li_hdr(tok):
    return {"Authorization": "Bearer " + tok, "LinkedIn-Version": _li_version(),
            "X-Restli-Protocol-Version": "2.0.0"}


def _li_image(a, it):
    tok, owner = a["token"], a["account_id"]
    init = _must(_req(f"{LI_API}/rest/images?action=initializeUpload", method="POST", headers=_li_hdr(tok),
                      json_body={"initializeUploadRequest": {"owner": owner}}), "LinkedIn image init")["value"]
    # without a Content-Type the upload host rejects the bytes with an HTML 400 page
    _must(_req(init["uploadUrl"], data=_read(it["path"]), method="PUT", timeout=300,
               headers={"Authorization": "Bearer " + tok,
                        "Content-Type": it.get("mime") or "application/octet-stream"}), "LinkedIn image upload")
    return init["image"]


def _li_video(a, it):
    tok, owner = a["token"], a["account_id"]
    size = os.path.getsize(it["path"])
    init = _must(_req(f"{LI_API}/rest/videos?action=initializeUpload", method="POST", headers=_li_hdr(tok),
                      json_body={"initializeUploadRequest": {"owner": owner, "fileSizeBytes": size,
                                                             "uploadCaptions": False, "uploadThumbnail": False}}),
                 "LinkedIn video init")["value"]
    etags = []
    with open(it["path"], "rb") as fh:
        for ins in init["uploadInstructions"]:
            fh.seek(ins["firstByte"])
            part = fh.read(ins["lastByte"] - ins["firstByte"] + 1)
            r = _req(ins["uploadUrl"], data=part, method="PUT", timeout=600,
                     headers={"Content-Type": "application/octet-stream"})
            _must(r, "LinkedIn video upload")
            etags.append(r.headers.get("etag", "").strip('"'))
    _must(_req(f"{LI_API}/rest/videos?action=finalizeUpload", method="POST", headers=_li_hdr(tok),
               json_body={"finalizeUploadRequest": {"video": init["video"], "uploadToken": init.get("uploadToken", ""),
                                                    "uploadedPartIds": etags}}), "LinkedIn video finalize")
    return init["video"]


def _linkedin_publish(a, media, text, opts):
    tok = a["token"]
    post = {"author": a["account_id"], "commentary": text, "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [],
                             "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False}
    kind = media["kind"]
    if kind == "carousel":
        imgs = _images(media)
        if len(imgs) < 2:
            raise PlatformError("LinkedIn multi-image posts need 2+ images (no videos).")
        post["content"] = {"multiImage": {"images": [{"id": _li_image(a, it)} for it in imgs[:20]]}}
    elif kind in ("video", "image"):
        it = media["items"][0]
        urn = _li_video(a, it) if it["is_video"] else _li_image(a, it)
        post["content"] = {"media": {"id": urn, "title": (opts.get("title") or "")[:200]}}
    r = _req(f"{LI_API}/rest/posts", method="POST", headers=_li_hdr(tok), json_body=post)
    _must(r, "LinkedIn post")
    pid = r.headers.get("x-restli-id") or (r.data.get("id", "") if isinstance(r.data, dict) else "")
    return {"remote_id": pid, "permalink": f"https://www.linkedin.com/feed/update/{pid}" if pid else "",
            "message": "Posted to LinkedIn."}


# ---- Threads -------------------------------------------------------------- #
def _th_wait(cid, tok, tries=40):
    for _ in range(tries):
        r = _req(f"{THREADS_GRAPH}/{cid}?" + urllib.parse.urlencode({"fields": "status,error_message",
                                                                      "access_token": tok}))
        st = (r.data or {}).get("status") if isinstance(r.data, dict) else None
        if st in ("FINISHED", "PUBLISHED"):
            return
        if st in ("ERROR", "EXPIRED"):
            raise PlatformError(f"Threads couldn't process the media: {(r.data or {}).get('error_message', st)}")
        time.sleep(3)
    raise PlatformError("Threads media processing timed out.", retry=True)


def _threads_publish(a, media, text, opts, reply_to=None):
    tok, uid = a["token"], a["account_id"]

    def container(p):
        p["access_token"] = tok
        return _must(_req(f"{THREADS_GRAPH}/{uid}/threads", method="POST", form=p), "Threads container")["id"]

    kind = media["kind"]
    if kind == "text":
        p = {"media_type": "TEXT", "text": text}
        if reply_to:
            p["reply_to_id"] = reply_to
        cid = container(p)
    elif kind == "carousel":
        kids = []
        for it in media["items"][:20]:
            p = {"is_carousel_item": "true"}
            if it["is_video"]:
                p.update({"media_type": "VIDEO", "video_url": _need_url(it, "threads")})
            else:
                p.update({"media_type": "IMAGE", "image_url": _need_url(it, "threads")})
            k = container(p)
            _th_wait(k, tok)
            kids.append(k)
        cid = container({"media_type": "CAROUSEL", "children": ",".join(kids), "text": text})
    else:
        it = media["items"][0]
        if it["is_video"]:
            cid = container({"media_type": "VIDEO", "video_url": _need_url(it, "threads"), "text": text})
        else:
            cid = container({"media_type": "IMAGE", "image_url": _need_url(it, "threads"), "text": text})
    _th_wait(cid, tok)
    mid = _must(_req(f"{THREADS_GRAPH}/{uid}/threads_publish", method="POST",
                     form={"creation_id": cid, "access_token": tok}), "Threads publish")["id"]
    pl = _req(f"{THREADS_GRAPH}/{mid}?" + urllib.parse.urlencode({"fields": "permalink", "access_token": tok}))
    link = (pl.data or {}).get("permalink", "") if pl.ok and isinstance(pl.data, dict) else ""
    return {"remote_id": mid, "permalink": link, "message": "Posted to Threads."}


# ---- TikTok --------------------------------------------------------------- #
def _tiktok_publish(a, media, text, opts):
    vids = _videos(media)
    if not vids:
        raise PlatformError("TikTok publishing here supports videos only.")
    it, tok = vids[0], a["token"]
    hdr = {"Authorization": "Bearer " + tok}
    ci = _req(f"{TT_API}/post/publish/creator_info/query/", method="POST", headers=hdr, json_body={})
    opts_list = ((ci.data or {}).get("data") or {}).get("privacy_level_options", []) if isinstance(ci.data, dict) else []
    privacy = "PUBLIC_TO_EVERYONE" if "PUBLIC_TO_EVERYONE" in opts_list else (opts_list[0] if opts_list else "SELF_ONLY")
    size = os.path.getsize(it["path"])
    chunk = size if size < 64 * 1024 * 1024 else 10 * 1024 * 1024
    count = max(1, size // chunk)
    def _init(level):
        return _req(f"{TT_API}/post/publish/video/init/", method="POST", headers=hdr, json_body={
            "post_info": {"title": text[:2200], "privacy_level": level, "disable_comment": False,
                          "disable_duet": False, "disable_stitch": False},
            "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk,
                            "total_chunk_count": count}})
    r = _init(privacy)
    if r.status == 403 and privacy != "SELF_ONLY":
        # unaudited apps (sandbox / before TikTok's audit) may only post private videos
        privacy = "SELF_ONLY"
        r = _init(privacy)
    code = (((r.data or {}).get("error") or {}).get("code", "") if isinstance(r.data, dict) else "")
    if code == "unaudited_client_can_only_post_to_private_accounts":
        raise PlatformError("TikTok only lets unaudited apps post to private accounts. In the TikTok app open "
                            "Profile → ☰ → Settings and privacy → Privacy and turn on Private account, then Retry. "
                            "After TikTok audits the app you can switch it back.")
    init = _must(r, "TikTok publish init")
    if (init.get("error") or {}).get("code") not in (None, "ok"):
        raise PlatformError("TikTok: " + init["error"].get("message", "init failed"))
    d = init["data"]
    with open(it["path"], "rb") as fh:
        for i in range(count):
            start = i * chunk
            end = size - 1 if i == count - 1 else start + chunk - 1
            fh.seek(start)
            part = fh.read(end - start + 1)
            _must(_req(d["upload_url"], data=part, method="PUT", timeout=900, headers={
                "Content-Type": it["mime"], "Content-Range": f"bytes {start}-{end}/{size}"}), "TikTok upload")
    pid, post_id = d["publish_id"], ""
    for _ in range(40):
        st = _req(f"{TT_API}/post/publish/status/fetch/", method="POST", headers=hdr, json_body={"publish_id": pid})
        sd = (st.data or {}).get("data", {}) if isinstance(st.data, dict) else {}
        if sd.get("status") == "PUBLISH_COMPLETE":
            ids = sd.get("publicaly_available_post_id") or sd.get("publicly_available_post_id") or []
            post_id = str(ids[0]) if ids else ""
            break
        if sd.get("status") == "FAILED":
            raise PlatformError("TikTok publishing failed: " + str(sd.get("fail_reason", "")))
        time.sleep(4)
    note = "" if privacy == "PUBLIC_TO_EVERYONE" else " (posted as private — TikTok requires app audit for public posts)"
    return {"remote_id": post_id or pid, "permalink": "", "message": "Sent to TikTok." + note}


# ---- Pinterest ------------------------------------------------------------ #
def _pinterest_publish(a, media, text, opts):
    tok = a["token"]
    hdr = {"Authorization": "Bearer " + tok}
    board = (a.get("extra") or {}).get("board_id")
    if not board:
        # none saved (e.g. the account had no boards when it was connected): use the first board now
        r = _req(f"{PIN_API}/boards?page_size=25", headers=hdr)
        items = (r.data or {}).get("items", []) if r.ok and isinstance(r.data, dict) else []
        board = items[0]["id"] if items else ""
    if not board:
        raise PlatformError("Your Pinterest account has no boards. Create a board on pinterest.com, "
                            "then pick it on the Pinterest tile in Setup and Retry.")
    title = (opts.get("title") or text.split("\n")[0])[:100]
    pin = {"board_id": board, "title": title, "description": text[:500]}
    vids = _videos(media)
    if vids:
        it = vids[0]
        reg = _must(_req(f"{PIN_API}/media", method="POST", headers=hdr, json_body={"media_type": "video"}),
                    "Pinterest media register")
        body, ct = _multipart(reg.get("upload_parameters", {}),
                              [("file", os.path.basename(it["path"]), _read(it["path"]), it["mime"])])
        up = _req(reg["upload_url"], data=body, method="POST", headers={"Content-Type": ct}, timeout=1800)
        if not up.ok and up.status not in (204,):
            raise PlatformError(f"Pinterest video upload failed ({up.status}).")
        for _ in range(60):
            st = _req(f"{PIN_API}/media/{reg['media_id']}", headers=hdr)
            s = (st.data or {}).get("status") if isinstance(st.data, dict) else None
            if s == "succeeded":
                break
            if s == "failed":
                raise PlatformError("Pinterest couldn't process the video.")
            time.sleep(4)
        src = {"source_type": "video_id", "media_id": reg["media_id"]}
        if media.get("thumb_url"):
            src["cover_image_url"] = media["thumb_url"]
        else:
            src["cover_image_key_frame_time"] = 1
        pin["media_source"] = src
    else:
        imgs = _images(media)
        enc = [{"content_type": it["mime"], "data": base64.b64encode(_read(it["path"])).decode()} for it in imgs[:5]]
        if len(enc) > 1:
            pin["media_source"] = {"source_type": "multiple_image_base64", "items": enc}
        else:
            pin["media_source"] = dict({"source_type": "image_base64"}, **enc[0])
    d = _must(_req(f"{PIN_API}/pins", method="POST", headers=hdr, json_body=pin), "Creating the Pin")
    return {"remote_id": d["id"], "permalink": f"https://www.pinterest.com/pin/{d['id']}/", "message": "Pin created."}


# --------------------------------------------------------------------------- #
#  Stats  → {"views", "likes", "comments", "shares"} (missing metrics = 0)
# --------------------------------------------------------------------------- #
def _token_dead(r):
    """True when a platform says the access token itself is no longer valid."""
    if r.ok:
        return False
    e = (r.data or {}).get("error") if isinstance(r.data, dict) else None
    if isinstance(e, dict) and e.get("code") in (190, 102):          # Meta: expired / invalidated session
        return True
    return r.status == 401                                           # Bearer platforms: token rejected


def stats(platform, a, rid):
    out = {"views": 0, "likes": 0, "comments": 0, "shares": 0}
    tok = a.get("token")
    if not (tok and rid):
        return out
    def G(*args, **kw):
        r = _req(*args, **kw)
        if _token_dead(r):
            raise PlatformError(f"{PLATFORMS[platform]['label']} sign-in has expired or was revoked "
                                f"({r.err()}). Reconnect it in Setup.")
        return r
    try:
        if platform == "instagram":
            r = G(f"{IG_GRAPH}/{rid}?" + urllib.parse.urlencode({"fields": "like_count,comments_count",
                                                                     "access_token": tok}))
            if r.ok:
                out["likes"], out["comments"] = int(r.data.get("like_count", 0)), int(r.data.get("comments_count", 0))
            ins = G(f"{IG_GRAPH}/{rid}/insights?" + urllib.parse.urlencode({"metric": "views,shares",
                                                                                "access_token": tok}))
            for m in ((ins.data or {}).get("data", []) if ins.ok else []):
                v = (m.get("values") or [{}])[0].get("value", 0)
                if m.get("name") in ("views", "shares"):
                    out[m["name"]] = int(v or 0)
        elif platform == "facebook":
            r = G(f"{FB_GRAPH}/{rid}?" + urllib.parse.urlencode({
                "fields": "reactions.summary(total_count).limit(0),comments.summary(total_count).limit(0),shares",
                "access_token": tok}))
            if r.ok and isinstance(r.data, dict):
                out["likes"] = int(((r.data.get("reactions") or {}).get("summary") or {}).get("total_count", 0))
                out["comments"] = int(((r.data.get("comments") or {}).get("summary") or {}).get("total_count", 0))
                out["shares"] = int((r.data.get("shares") or {}).get("count", 0))
            v = G(f"{FB_GRAPH}/{rid}/video_insights?" + urllib.parse.urlencode({
                "metric": "total_video_views", "access_token": tok}))
            if v.ok and isinstance(v.data, dict) and v.data.get("data"):
                out["views"] = int(((v.data["data"][0].get("values") or [{}])[0]).get("value", 0) or 0)
        elif platform == "youtube":
            r = G(f"{YT_API}/videos?part=statistics&id={rid}", headers={"Authorization": "Bearer " + tok})
            items = (r.data or {}).get("items", []) if r.ok else []
            if items:
                s = items[0]["statistics"]
                out.update(views=int(s.get("viewCount", 0)), likes=int(s.get("likeCount", 0)),
                           comments=int(s.get("commentCount", 0)))
        elif platform == "twitter":
            r = G(f"{X_API}/tweets/{rid}?tweet.fields=public_metrics", headers={"Authorization": "Bearer " + tok})
            m = ((r.data or {}).get("data") or {}).get("public_metrics", {}) if r.ok else {}
            out.update(views=int(m.get("impression_count", 0)), likes=int(m.get("like_count", 0)),
                       comments=int(m.get("reply_count", 0)),
                       shares=int(m.get("retweet_count", 0)) + int(m.get("quote_count", 0)))
        elif platform == "linkedin":
            r = G(f"{LI_API}/rest/socialMetadata/{urllib.parse.quote(rid, safe='')}", headers=_li_hdr(tok))
            if r.ok and isinstance(r.data, dict):
                out["likes"] = sum(int(v.get("count", 0)) for v in (r.data.get("reactionSummaries") or {}).values())
                out["comments"] = int((r.data.get("commentSummary") or {}).get("count", 0))
        elif platform == "threads":
            r = G(f"{THREADS_GRAPH}/{rid}/insights?" + urllib.parse.urlencode({
                "metric": "views,likes,replies,reposts,quotes,shares", "access_token": tok}))
            for m in ((r.data or {}).get("data", []) if r.ok else []):
                v = int((m.get("values") or [{}])[0].get("value", 0) or 0)
                key = {"views": "views", "likes": "likes", "replies": "comments"}.get(m.get("name"))
                if key:
                    out[key] = v
                elif m.get("name") in ("reposts", "quotes", "shares"):
                    out["shares"] += v
        elif platform == "tiktok":
            r = G(f"{TT_API}/video/query/?fields=id,view_count,like_count,comment_count,share_count",
                     method="POST", headers={"Authorization": "Bearer " + tok},
                     json_body={"filters": {"video_ids": [rid]}})
            vids = (((r.data or {}).get("data") or {}).get("videos") or []) if r.ok else []
            if vids:
                v = vids[0]
                out.update(views=int(v.get("view_count", 0)), likes=int(v.get("like_count", 0)),
                           comments=int(v.get("comment_count", 0)), shares=int(v.get("share_count", 0)))
        elif platform == "pinterest":
            end = datetime.utcnow().date()
            r = G(f"{PIN_API}/pins/{rid}/analytics?" + urllib.parse.urlencode({
                "start_date": (end - timedelta(days=89)).isoformat(), "end_date": end.isoformat(),
                "metric_types": "IMPRESSION,SAVE,PIN_CLICK"}), headers={"Authorization": "Bearer " + tok})
            lm = ((r.data or {}).get("all") or {}).get("lifetime_metrics", {}) if r.ok and isinstance(r.data, dict) else {}
            out.update(views=int(lm.get("IMPRESSION", 0)), likes=int(lm.get("SAVE", 0)))
    except PlatformError:
        raise
    except Exception:
        pass
    return out


# --------------------------------------------------------------------------- #
#  Comments (inbox) → [{"id","author","text","likes","created","parent"}]
#  Follows every page of results and includes threaded replies ("parent" is the
#  id of the comment being replied to, "" for top-level). Comments written by
#  the connected account itself (e.g. replies sent from the dashboard) are
#  skipped so they don't show up in the inbox as new comments.
# --------------------------------------------------------------------------- #
MAX_COMMENTS = 1000


def _pages(first_url, headers=None, next_of=None):
    """Yield result pages, following the platform's paging cursor."""
    url, seen = first_url, 0
    while url and seen < 40:
        r = _req(url, headers=headers)
        if not r.ok or not isinstance(r.data, dict):
            return
        yield r.data
        seen += 1
        url = next_of(r.data) if next_of else ((r.data.get("paging") or {}).get("next"))


def comments(platform, a, rid):
    tok = a.get("token")
    if not (tok and rid):
        return []
    own_name = (a.get("account_name") or "").lstrip("@").lower()
    own_id = str(a.get("account_id") or "")
    out = []

    def add(cid, author, text, likes=0, created="", parent="", author_id=""):
        if not cid:
            return
        if (own_name and (author or "").lstrip("@").lower() == own_name) or (own_id and str(author_id) == own_id):
            return
        out.append({"id": str(cid), "author": author or "", "text": text or "", "likes": int(likes or 0),
                    "created": created or "", "parent": str(parent or "")})

    try:
        if platform == "instagram":
            fields = ("id,username,text,like_count,timestamp,"
                      "replies{id,username,text,like_count,timestamp}")
            url = f"{IG_GRAPH}/{rid}/comments?" + urllib.parse.urlencode(
                {"fields": fields, "limit": 50, "access_token": tok})
            for page in _pages(url):
                for c in page.get("data", []):
                    add(c.get("id"), c.get("username"), c.get("text"), c.get("like_count"), c.get("timestamp"))
                    for rp in ((c.get("replies") or {}).get("data") or []):
                        add(rp.get("id"), rp.get("username"), rp.get("text"), rp.get("like_count"),
                            rp.get("timestamp"), parent=c.get("id"))
                if len(out) >= MAX_COMMENTS:
                    break
        elif platform == "facebook":
            # filter=stream returns top-level comments AND replies in one chronological list
            url = f"{FB_GRAPH}/{rid}/comments?" + urllib.parse.urlencode({
                "filter": "stream", "limit": 100, "access_token": tok,
                "fields": "id,from,message,created_time,like_count,parent{id}"})
            for page in _pages(url):
                for c in page.get("data", []):
                    frm = c.get("from") or {}
                    add(c.get("id"), frm.get("name", "Facebook user"), c.get("message"), c.get("like_count"),
                        c.get("created_time"), parent=(c.get("parent") or {}).get("id", ""), author_id=frm.get("id", ""))
                if len(out) >= MAX_COMMENTS:
                    break
        elif platform == "youtube":
            hdr = {"Authorization": "Bearer " + tok}
            base = f"{YT_API}/commentThreads?part=snippet,replies&maxResults=100&videoId={rid}"
            nxt = lambda d: (base + "&pageToken=" + d["nextPageToken"]) if d.get("nextPageToken") else None
            for page in _pages(base, headers=hdr, next_of=nxt):
                for t in page.get("items", []):
                    top = t["snippet"]["topLevelComment"]
                    s = top["snippet"]
                    add(top["id"], s.get("authorDisplayName"), s.get("textOriginal") or s.get("textDisplay"),
                        s.get("likeCount"), s.get("publishedAt"),
                        author_id=(s.get("authorChannelId") or {}).get("value", ""))
                    for rp in ((t.get("replies") or {}).get("comments") or []):
                        rs = rp["snippet"]
                        add(rp["id"], rs.get("authorDisplayName"), rs.get("textOriginal") or rs.get("textDisplay"),
                            rs.get("likeCount"), rs.get("publishedAt"), parent=top["id"],
                            author_id=(rs.get("authorChannelId") or {}).get("value", ""))
                if len(out) >= MAX_COMMENTS:
                    break
        elif platform == "twitter":
            hdr = {"Authorization": "Bearer " + tok}
            q = {"query": f"conversation_id:{rid}", "tweet.fields": "author_id,created_at,public_metrics,in_reply_to_user_id,referenced_tweets",
                 "expansions": "author_id", "user.fields": "username", "max_results": 100}
            base = f"{X_API}/tweets/search/recent?" + urllib.parse.urlencode(q)
            nxt = lambda d: (base + "&next_token=" + (d.get("meta") or {})["next_token"]) \
                if (d.get("meta") or {}).get("next_token") else None
            for page in _pages(base, headers=hdr, next_of=nxt):
                users = {u["id"]: u.get("username", "") for u in (page.get("includes") or {}).get("users", [])}
                for c in page.get("data", []):
                    ref = next((r_["id"] for r_ in (c.get("referenced_tweets") or []) if r_.get("type") == "replied_to"), "")
                    add(c["id"], "@" + users.get(c.get("author_id"), ""), c.get("text"),
                        (c.get("public_metrics") or {}).get("like_count", 0), c.get("created_at"),
                        parent="" if ref == rid else ref, author_id=c.get("author_id", ""))
        elif platform == "threads":
            # /conversation returns every reply in the thread, at any depth
            url = f"{THREADS_GRAPH}/{rid}/conversation?" + urllib.parse.urlencode({
                "fields": "id,text,username,timestamp,replied_to{id}", "reverse": "false", "access_token": tok})
            for page in _pages(url):
                for c in page.get("data", []):
                    par = (c.get("replied_to") or {}).get("id", "")
                    add(c.get("id"), "@" + (c.get("username") or ""), c.get("text"), 0, c.get("timestamp"),
                        parent="" if par == rid else par)
        elif platform == "linkedin":
            r = _req(f"{LI_API}/rest/socialActions/{urllib.parse.quote(rid, safe='')}/comments?count=100",
                     headers=_li_hdr(tok))
            for c in ((r.data or {}).get("elements", []) if r.ok and isinstance(r.data, dict) else []):
                add(c.get("$URN") or c.get("commentUrn") or c.get("id", ""), "LinkedIn member",
                    (c.get("message") or {}).get("text", ""), author_id=c.get("actor", ""))
    except Exception:
        pass
    return out[:MAX_COMMENTS]


def reply(platform, a, rid, comment_id, text):
    """Reply to a comment on the platform. Returns (ok, message)."""
    tok = a.get("token")
    try:
        if platform == "instagram":
            r = _req(f"{IG_GRAPH}/{comment_id}/replies", method="POST", form={"message": text, "access_token": tok})
        elif platform == "facebook":
            r = _req(f"{FB_GRAPH}/{comment_id}/comments", method="POST", form={"message": text, "access_token": tok})
        elif platform == "youtube":
            r = _req(f"{YT_API}/comments?part=snippet", method="POST", headers={"Authorization": "Bearer " + tok},
                     json_body={"snippet": {"parentId": comment_id, "textOriginal": text}})
        elif platform == "twitter":
            r = _req(f"{X_API}/tweets", method="POST", headers={"Authorization": "Bearer " + tok},
                     json_body={"text": text[:280], "reply": {"in_reply_to_tweet_id": comment_id}})
        elif platform == "threads":
            _threads_publish(a, {"kind": "text", "items": []}, text[:500], {}, reply_to=comment_id)
            return True, "Reply posted."
        elif platform == "linkedin":
            r = _req(f"{LI_API}/rest/socialActions/{urllib.parse.quote(rid, safe='')}/comments", method="POST",
                     headers=_li_hdr(tok), json_body={"actor": a["account_id"], "object": rid,
                                                      "parentComment": comment_id, "message": {"text": text}})
        else:
            return False, f"{PLATFORMS[platform]['label']} doesn't allow replying through its API."
        return (True, "Reply posted.") if r.ok else (False, r.err())
    except PlatformError as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)


# --------------------------------------------------------------------------- #
#  Existing posts (import) → [{"id","caption","permalink","created","media_type","thumb"}]
# --------------------------------------------------------------------------- #
def list_posts(platform, a, limit=50):
    tok = a.get("token")
    if not tok:
        return []
    out = []

    def add(pid, caption, link, created, mtype, thumb):
        if pid:
            out.append({"id": str(pid), "caption": caption or "", "permalink": link or "", "created": created or "",
                        "media_type": (mtype or "").lower(), "thumb": thumb or ""})

    try:
        if platform == "instagram":
            url = f"{IG_GRAPH}/{a.get('account_id') or 'me'}/media?" + urllib.parse.urlencode({
                "fields": "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp",
                "limit": min(limit, 50), "access_token": tok})
            for page in _pages(url):
                for m in page.get("data", []):
                    add(m.get("id"), m.get("caption"), m.get("permalink"), m.get("timestamp"), m.get("media_type"),
                        m.get("thumbnail_url") or (m.get("media_url") if m.get("media_type") != "VIDEO" else ""))
                if len(out) >= limit:
                    break
        elif platform == "facebook":
            url = f"{FB_GRAPH}/{a['account_id']}/published_posts?" + urllib.parse.urlencode({
                "fields": "id,message,permalink_url,created_time,full_picture,status_type",
                "limit": min(limit, 50), "access_token": tok})
            for page in _pages(url):
                for m in page.get("data", []):
                    st = (m.get("status_type") or "")
                    add(m.get("id"), m.get("message"), m.get("permalink_url"), m.get("created_time"),
                        "video" if "video" in st else ("image" if m.get("full_picture") else "text"), m.get("full_picture"))
                if len(out) >= limit:
                    break
        elif platform == "youtube":
            hdr = {"Authorization": "Bearer " + tok}
            ch = _req(f"{YT_API}/channels?part=contentDetails&mine=true", headers=hdr)
            items = (ch.data or {}).get("items", []) if ch.ok and isinstance(ch.data, dict) else []
            uploads = ((items[0].get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads") if items else ""
            if uploads:
                base = f"{YT_API}/playlistItems?part=snippet&maxResults=50&playlistId={uploads}"
                nxt = lambda d: (base + "&pageToken=" + d["nextPageToken"]) if d.get("nextPageToken") else None
                for page in _pages(base, headers=hdr, next_of=nxt):
                    for it in page.get("items", []):
                        sn = it.get("snippet") or {}
                        vid = (sn.get("resourceId") or {}).get("videoId")
                        th = ((sn.get("thumbnails") or {}).get("medium") or {}).get("url", "")
                        add(vid, (sn.get("title", "") + "\n\n" + sn.get("description", "")).strip(),
                            f"https://www.youtube.com/watch?v={vid}", sn.get("publishedAt"), "video", th)
                    if len(out) >= limit:
                        break
        elif platform == "twitter":
            r = _req(f"{X_API}/users/{a['account_id']}/tweets?max_results={max(5, min(limit, 100))}"
                     "&tweet.fields=created_at&exclude=replies,retweets", headers={"Authorization": "Bearer " + tok})
            for t in ((r.data or {}).get("data", []) if r.ok and isinstance(r.data, dict) else []):
                add(t.get("id"), t.get("text"), f"https://x.com/i/web/status/{t.get('id')}", t.get("created_at"), "text", "")
        elif platform == "threads":
            url = f"{THREADS_GRAPH}/me/threads?" + urllib.parse.urlencode({
                "fields": "id,text,permalink,timestamp,media_type,thumbnail_url,media_url",
                "limit": min(limit, 50), "access_token": tok})
            for page in _pages(url):
                for m in page.get("data", []):
                    add(m.get("id"), m.get("text"), m.get("permalink"), m.get("timestamp"), m.get("media_type"),
                        m.get("thumbnail_url") or (m.get("media_url") if (m.get("media_type") or "") == "IMAGE" else ""))
                if len(out) >= limit:
                    break
        elif platform == "tiktok":
            r = _req(f"{TT_API}/video/list/?fields=id,title,video_description,create_time,share_url,cover_image_url",
                     method="POST", headers={"Authorization": "Bearer " + tok}, json_body={"max_count": 20})
            for v in (((r.data or {}).get("data") or {}).get("videos", []) if r.ok and isinstance(r.data, dict) else []):
                ts = v.get("create_time")
                created = datetime.utcfromtimestamp(int(ts)).isoformat() if ts else ""
                add(v.get("id"), v.get("video_description") or v.get("title"), v.get("share_url"), created, "video",
                    v.get("cover_image_url"))
        elif platform == "pinterest":
            r = _req(f"{PIN_API}/pins?page_size={min(limit, 100)}", headers={"Authorization": "Bearer " + tok})
            for p in ((r.data or {}).get("items", []) if r.ok and isinstance(r.data, dict) else []):
                imgs = ((p.get("media") or {}).get("images") or {})
                th = (imgs.get("600x") or imgs.get("400x300") or {}).get("url", "")
                add(p.get("id"), ((p.get("title") or "") + "\n\n" + (p.get("description") or "")).strip(),
                    f"https://www.pinterest.com/pin/{p.get('id')}/", p.get("created_at"),
                    (p.get("media") or {}).get("media_type", "image"), th)
    except Exception:
        pass
    return out[:limit]


# --------------------------------------------------------------------------- #
#  Account-level stats → {"followers","reach","impressions","profile_views","media_count"}
# --------------------------------------------------------------------------- #
def account_stats(platform, a):
    out = {"followers": 0, "reach": 0, "impressions": 0, "profile_views": 0, "media_count": 0}
    tok = a.get("token")
    if not tok:
        return out
    now = int(time.time())
    try:
        if platform == "instagram":
            uid = a.get("account_id") or "me"
            r = _req(f"{IG_GRAPH}/{uid}?" + urllib.parse.urlencode({"fields": "followers_count,media_count",
                                                                     "access_token": tok}))
            if r.ok and isinstance(r.data, dict):
                out["followers"] = int(r.data.get("followers_count", 0) or 0)
                out["media_count"] = int(r.data.get("media_count", 0) or 0)
            ins = _req(f"{IG_GRAPH}/{uid}/insights?" + urllib.parse.urlencode({
                "metric": "reach,profile_views,views", "period": "day", "metric_type": "total_value",
                "since": now - 86400, "until": now, "access_token": tok}))
            for m in ((ins.data or {}).get("data", []) if ins.ok and isinstance(ins.data, dict) else []):
                v = int(((m.get("total_value") or {}).get("value")) or 0)
                key = {"reach": "reach", "profile_views": "profile_views", "views": "impressions"}.get(m.get("name"))
                if key:
                    out[key] = v
        elif platform == "facebook":
            r = _req(f"{FB_GRAPH}/{a['account_id']}?" + urllib.parse.urlencode({
                "fields": "followers_count,fan_count", "access_token": tok}))
            if r.ok and isinstance(r.data, dict):
                out["followers"] = int(r.data.get("followers_count") or r.data.get("fan_count") or 0)
            ins = _req(f"{FB_GRAPH}/{a['account_id']}/insights?" + urllib.parse.urlencode({
                "metric": "page_impressions_unique,page_views_total,page_impressions", "period": "day",
                "access_token": tok}))
            for m in ((ins.data or {}).get("data", []) if ins.ok and isinstance(ins.data, dict) else []):
                vals = m.get("values") or [{}]
                v = int((vals[-1] or {}).get("value", 0) or 0)
                key = {"page_impressions_unique": "reach", "page_views_total": "profile_views",
                       "page_impressions": "impressions"}.get(m.get("name"))
                if key:
                    out[key] = v
        elif platform == "youtube":
            r = _req(f"{YT_API}/channels?part=statistics&mine=true", headers={"Authorization": "Bearer " + tok})
            items = (r.data or {}).get("items", []) if r.ok and isinstance(r.data, dict) else []
            if items:
                st = items[0].get("statistics") or {}
                out.update(followers=int(st.get("subscriberCount", 0) or 0), impressions=int(st.get("viewCount", 0) or 0),
                           media_count=int(st.get("videoCount", 0) or 0))
        elif platform == "twitter":
            r = _req(f"{X_API}/users/me?user.fields=public_metrics", headers={"Authorization": "Bearer " + tok})
            pm = ((r.data or {}).get("data") or {}).get("public_metrics", {}) if r.ok and isinstance(r.data, dict) else {}
            out.update(followers=int(pm.get("followers_count", 0) or 0), media_count=int(pm.get("tweet_count", 0) or 0))
        elif platform == "threads":
            r = _req(f"{THREADS_GRAPH}/me/threads_insights?" + urllib.parse.urlencode({
                "metric": "views,followers_count", "since": now - 86400, "until": now, "access_token": tok}))
            for m in ((r.data or {}).get("data", []) if r.ok and isinstance(r.data, dict) else []):
                if m.get("name") == "followers_count":
                    out["followers"] = int(((m.get("total_value") or {}).get("value")) or 0)
                elif m.get("name") == "views":
                    out["impressions"] = sum(int(x.get("value", 0) or 0) for x in (m.get("values") or []))
        elif platform == "tiktok":
            r = _req(f"{TT_API}/user/info/?fields=follower_count,likes_count,video_count",
                     headers={"Authorization": "Bearer " + tok})
            us = (((r.data or {}).get("data") or {}).get("user") or {}) if r.ok and isinstance(r.data, dict) else {}
            out.update(followers=int(us.get("follower_count", 0) or 0), media_count=int(us.get("video_count", 0) or 0))
        elif platform == "pinterest":
            r = _req(f"{PIN_API}/user_account", headers={"Authorization": "Bearer " + tok})
            if r.ok and isinstance(r.data, dict):
                out.update(followers=int(r.data.get("follower_count", 0) or 0),
                           impressions=int(r.data.get("monthly_views", 0) or 0),
                           media_count=int(r.data.get("pin_count", 0) or 0))
    except Exception:
        pass
    return out


# --------------------------------------------------------------------------- #
#  Direct messages (Instagram + Facebook Page)
#  dm_threads → [{"conversation_id","participant_id","participant_name",
#                 "messages":[{"id","from_id","from_name","text","created"}]}]
# --------------------------------------------------------------------------- #
DM_PLATFORMS = ("instagram", "facebook")


def dm_threads(platform, a, limit=25):
    tok = a.get("token")
    own = str(a.get("account_id") or "")
    if platform not in DM_PLATFORMS or not tok:
        return []
    out = []
    try:
        if platform == "instagram":
            base, conv_url = IG_GRAPH, f"{IG_GRAPH}/me/conversations?"
            params = {"platform": "instagram", "fields": "id,updated_time,participants,"
                      "messages.limit(20){id,created_time,from,to,message}", "limit": limit, "access_token": tok}
        else:
            base, conv_url = FB_GRAPH, f"{FB_GRAPH}/{own}/conversations?"
            params = {"platform": "messenger", "fields": "id,updated_time,participants,"
                      "messages.limit(20){id,created_time,from,to,message}", "limit": limit, "access_token": tok}
        r = _req(conv_url + urllib.parse.urlencode(params))
        if not r.ok:
            raise PlatformError(r.err())
        convs = (r.data or {}).get("data", []) if isinstance(r.data, dict) else []
        for c in convs:
            parts = ((c.get("participants") or {}).get("data") or [])
            other = next((p for p in parts if str(p.get("id")) != own), (parts[0] if parts else {}))
            msgs = []
            for m in ((c.get("messages") or {}).get("data") or []):
                frm = m.get("from") or {}
                msgs.append({"id": m.get("id"), "from_id": str(frm.get("id") or ""),
                             "from_name": frm.get("username") or frm.get("name") or "",
                             "text": m.get("message") or "", "created": m.get("created_time") or ""})
            out.append({"conversation_id": c.get("id"), "participant_id": str(other.get("id") or ""),
                        "participant_name": other.get("username") or other.get("name") or "Unknown",
                        "messages": msgs})
    except PlatformError:
        raise
    except Exception as e:
        raise PlatformError(str(e))
    return out


def dm_send(platform, a, recipient_id, text):
    """Reply to a direct message. Returns (ok, message, remote_message_id)."""
    tok = a.get("token")
    try:
        if platform == "instagram":
            r = _req(f"{IG_GRAPH}/me/messages", method="POST", headers={"Authorization": "Bearer " + tok},
                     json_body={"recipient": {"id": recipient_id}, "message": {"text": text[:1000]}})
        elif platform == "facebook":
            r = _req(f"{FB_GRAPH}/{a['account_id']}/messages?access_token={urllib.parse.quote(tok)}", method="POST",
                     json_body={"recipient": {"id": recipient_id}, "messaging_type": "RESPONSE",
                                "message": {"text": text[:2000]}})
        else:
            return False, "Direct messages aren't available for this platform.", ""
        if r.ok:
            return True, "Sent.", (r.data or {}).get("message_id", "") if isinstance(r.data, dict) else ""
        err = r.err()
        if "outside of allowed window" in err.lower() or "24" in err and "hour" in err.lower():
            err = "You can only reply within 24 hours of the person's last message (platform rule)."
        return False, err, ""
    except Exception as e:
        return False, str(e), ""
