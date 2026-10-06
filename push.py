"""
Push notifications (V39).

  * Web Push for browsers (Chrome, Edge, Firefox, Android Chrome, Safari 16.4+):
    payloads are encrypted per RFC 8291 (aes128gcm) and signed with VAPID (RFC 8292).
  * Firebase Cloud Messaging (HTTP v1) for the Android / iOS app, using a
    Firebase service account.

Only the `cryptography` package is needed (already a dependency). No secrets are
logged. Every send returns (ok, gone, detail): `gone` means the subscription or
token no longer exists and should be deleted.
"""
import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

TIMEOUT = 15


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64u_dec(s):
    s = (s or "").strip()
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# --------------------------------------------------------------------------- #
#  VAPID keys
# --------------------------------------------------------------------------- #
def new_vapid_keys():
    """A fresh P-256 key pair: (private key, public key), both base64url."""
    k = ec.generate_private_key(ec.SECP256R1())
    priv = b64u(k.private_numbers().private_value.to_bytes(32, "big"))
    pub = b64u(k.public_key().public_bytes(serialization.Encoding.X962,
                                           serialization.PublicFormat.UncompressedPoint))
    return priv, pub


def _vapid_header(endpoint, priv, pub, contact):
    u = urllib.parse.urlparse(endpoint)
    head = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = b64u(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 12 * 3600,
                              "sub": contact}, separators=(",", ":")).encode())
    key = ec.derive_private_key(int.from_bytes(b64u_dec(priv), "big"), ec.SECP256R1())
    r, s = decode_dss_signature(key.sign(f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256())))
    sig = b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={head}.{claims}.{sig}, k={pub}"


# --------------------------------------------------------------------------- #
#  RFC 8291 payload encryption (single aes128gcm record)
# --------------------------------------------------------------------------- #
def encrypt_payload(p256dh, auth, payload):
    ua_pub = b64u_dec(p256dh)
    auth_secret = b64u_dec(auth)
    as_key = ec.generate_private_key(ec.SECP256R1())
    as_pub = as_key.public_key().public_bytes(serialization.Encoding.X962,
                                              serialization.PublicFormat.UncompressedPoint)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub)
    shared = as_key.exchange(ec.ECDH(), ua_key)
    ikm = HKDF(hashes.SHA256(), 32, salt=auth_secret,
               info=b"WebPush: info\x00" + ua_pub + as_pub).derive(shared)
    salt = os.urandom(16)
    cek = HKDF(hashes.SHA256(), 16, salt=salt, info=b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt=salt, info=b"Content-Encoding: nonce\x00").derive(ikm)
    body = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)     # 0x02 = last (only) record
    return salt + (4096).to_bytes(4, "big") + bytes([len(as_pub)]) + as_pub + body


def send_web(sub, data, priv, pub, contact, ttl=86400):
    """sub: {endpoint, p256dh, auth}. data: dict shown by the service worker."""
    try:
        body = encrypt_payload(sub["p256dh"], sub["auth"], json.dumps(data).encode("utf-8"))
        req = urllib.request.Request(sub["endpoint"], data=body, method="POST", headers={
            "TTL": str(ttl), "Urgency": "high", "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "Authorization": _vapid_header(sub["endpoint"], priv, pub, contact)})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return True, False, str(r.status)
    except urllib.error.HTTPError as e:
        return False, e.code in (404, 410), f"HTTP {e.code}"
    except Exception as e:  # noqa
        return False, False, type(e).__name__


# --------------------------------------------------------------------------- #
#  Firebase Cloud Messaging (HTTP v1)
# --------------------------------------------------------------------------- #
_FCM_TOKEN = {"key": None, "token": None, "exp": 0}


def parse_service_account(text):
    """Validate a Firebase service-account JSON. Returns the dict or raises ValueError."""
    try:
        sa = json.loads(text)
    except Exception:
        raise ValueError("That isn't a valid JSON file.")
    need = ("project_id", "client_email", "private_key")
    if sa.get("type") != "service_account" or not all(sa.get(k) for k in need):
        raise ValueError("Use the Firebase service-account key (Project settings → Service accounts → "
                         "Generate new private key).")
    try:
        serialization.load_pem_private_key(sa["private_key"].encode(), None)
    except Exception:
        raise ValueError("The private key in that file can't be read.")
    return sa


def _fcm_access_token(sa):
    now = int(time.time())
    if _FCM_TOKEN["key"] == sa["client_email"] and _FCM_TOKEN["token"] and _FCM_TOKEN["exp"] > now + 120:
        return _FCM_TOKEN["token"]
    token_uri = sa.get("token_uri") or "https://oauth2.googleapis.com/token"
    head = b64u(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = b64u(json.dumps({"iss": sa["client_email"], "aud": token_uri, "iat": now, "exp": now + 3600,
                              "scope": "https://www.googleapis.com/auth/firebase.messaging"}).encode())
    key = serialization.load_pem_private_key(sa["private_key"].encode(), None)
    sig = b64u(key.sign(f"{head}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256()))
    form = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                   "assertion": f"{head}.{claims}.{sig}"}).encode()
    req = urllib.request.Request(token_uri, data=form, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        d = json.loads(r.read().decode())
    _FCM_TOKEN.update(key=sa["client_email"], token=d["access_token"], exp=now + int(d.get("expires_in", 3600)))
    return _FCM_TOKEN["token"]


def send_fcm(sa, token, data):
    """data: {title, body, link, tag, url}."""
    try:
        access = _fcm_access_token(sa)
        msg = {"message": {
            "token": token,
            "notification": {"title": data.get("title", ""), "body": data.get("body", "")},
            "data": {k: str(data.get(k, "")) for k in ("link", "url", "tag")},
            "android": {"priority": "HIGH",
                        "notification": {"tag": data.get("tag") or "sp", "default_sound": True}},
            "apns": {"payload": {"aps": {"sound": "default", "thread-id": data.get("tag") or "sp"}}},
        }}
        req = urllib.request.Request(
            f"https://fcm.googleapis.com/v1/projects/{sa['project_id']}/messages:send",
            data=json.dumps(msg).encode(), method="POST",
            headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return True, False, str(r.status)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode()[:300]
        except Exception:
            pass
        gone = e.code == 404 or "UNREGISTERED" in detail or ("INVALID_ARGUMENT" in detail and "token" in detail.lower())
        return False, gone, f"HTTP {e.code}"
    except Exception as e:  # noqa
        return False, False, type(e).__name__
