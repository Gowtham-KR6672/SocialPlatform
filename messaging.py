"""
Loan reminders — message channels and payment schedules (V38).

Channels (each workspace brings its own provider account):
  SMS       Twilio · Telnyx · Plivo · Vonage · any HTTP API ("custom")
  WhatsApp  Meta WhatsApp Cloud API · Twilio WhatsApp
  Email     SMTP · SendGrid

Every sender returns (ok: bool, info: str) — info is the provider's message id
on success, or a plain-language error. Nothing here touches the database.
"""
import base64
import json
import re
import smtplib
import urllib.error
import urllib.parse
import urllib.request
from calendar import monthrange
from datetime import date, datetime, timedelta
from email.message import EmailMessage

# --------------------------------------------------------------------------- #
#  Provider catalogue — drives the Setup forms. Field keys ending in "_secret"
#  are encrypted at rest by the app (see _is_secret_setting).
# --------------------------------------------------------------------------- #
PROVIDERS = {
    "sms": {
        "twilio": {"label": "Twilio", "fields": [
            ("account_sid", "Account SID", "ACxxxxxxxx…"),
            ("auth_secret", "Auth Token", ""),
            ("from_number", "From number (E.164) or Messaging Service SID", "+15551234567 or MGxxxxxxxx…")]},
        "telnyx": {"label": "Telnyx", "fields": [
            ("api_secret", "API key", "KEYxxxxxxxx…"),
            ("from_number", "From number (E.164)", "+15551234567"),
            ("profile_id", "Messaging profile ID (optional)", "")]},
        "plivo": {"label": "Plivo", "fields": [
            ("auth_id", "Auth ID", "MAxxxxxxxx…"),
            ("auth_secret", "Auth Token", ""),
            ("from_number", "From number (E.164)", "+15551234567")]},
        "vonage": {"label": "Vonage (Nexmo)", "fields": [
            ("api_key", "API key", ""),
            ("api_secret", "API secret", ""),
            ("from_number", "From number (E.164)", "+15551234567")]},
        "custom": {"label": "Other provider (HTTP API)", "fields": [
            ("url", "API URL (POST)", "https://api.provider.com/send"),
            ("auth_header_secret", "Authorization header value (optional)", "Bearer abc123"),
            ("body_template", "JSON body — use {to}, {from}, {message}",
             '{"to": "{to}", "from": "{from}", "text": "{message}"}'),
            ("from_number", "From number (optional)", "+15551234567")]},
    },
    "whatsapp": {
        "meta": {"label": "Meta WhatsApp Cloud API", "fields": [
            ("phone_number_id", "Phone number ID", "1234567890"),
            ("token_secret", "Permanent access token", "EAAG…"),
            ("template_name", "Approved template for reminders (optional)", "payment_reminder"),
            ("template_lang", "Template language code", "en_US"),
            ("template_params", "Template body parameters, in order", "name,amount,due_date")]},
        "twilio": {"label": "Twilio WhatsApp", "fields": [
            ("account_sid", "Account SID", "ACxxxxxxxx…"),
            ("auth_secret", "Auth Token", ""),
            ("from_number", "WhatsApp sender number (E.164)", "+14155238886"),
            ("content_sid", "Approved template Content SID for reminders (optional)", "HXxxxxxxxx…"),
            ("template_params", "Template variables, in order", "name,amount,due_date")]},
    },
    "email": {
        "smtp": {"label": "SMTP server", "fields": [
            ("host", "SMTP host", "smtp.gmail.com"),
            ("port", "Port", "587"),
            ("user", "Username", ""),
            ("pass_secret", "Password", ""),
            ("from_addr", "From address", "Acme Loans <billing@acme.com>")]},
        "sendgrid": {"label": "SendGrid", "fields": [
            ("api_secret", "API key", "SG.xxxxxxxx…"),
            ("from_addr", "Verified sender email", "billing@acme.com"),
            ("from_name", "Sender name (optional)", "Acme Loans")]},
    },
}
CHANNELS = ("sms", "whatsapp", "email")
CHANNEL_LABEL = {"sms": "SMS", "whatsapp": "WhatsApp", "email": "Email"}


# --------------------------------------------------------------------------- #
#  HTTP + small helpers
# --------------------------------------------------------------------------- #
def _http(url, data=None, headers=None, method="POST", timeout=30):
    hdrs = {"Accept": "application/json", "User-Agent": "SocialPlatform-Reminders/1.0"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            status = r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read().decode("utf-8", "replace"), e.code
    except Exception as e:  # noqa — network problems
        return 0, {"error": str(e)}
    try:
        body = json.loads(raw) if raw else {}
    except Exception:
        body = {"raw": raw[:300]}
    return status, body


def _basic(a, b):
    return "Basic " + base64.b64encode(f"{a}:{b}".encode()).decode()


def _err(status, body, who):
    """Pull a readable message out of a provider's error response."""
    msg = ""
    if isinstance(body, dict):
        e = body.get("error")
        if isinstance(e, dict):
            msg = e.get("message") or e.get("error_user_msg") or json.dumps(e)[:200]
        elif isinstance(e, str):
            msg = e
        msg = msg or body.get("message") or body.get("error_message") or ""
        if not msg and isinstance(body.get("errors"), list) and body["errors"]:
            x = body["errors"][0]
            msg = (x.get("detail") or x.get("title") or x.get("message") or str(x)) if isinstance(x, dict) else str(x)
        msg = msg or body.get("raw") or ""
    return f"{who} error ({status or 'network'}): {msg or 'request failed'}"[:400]


def us_phone(raw):
    """Normalise a US/Canada phone number to E.164 (+1XXXXXXXXXX). Numbers that
    already start with + are kept (international). Returns "" if unusable."""
    s = (raw or "").strip()
    if not s:
        return ""
    if s.startswith("+"):
        d = re.sub(r"\D", "", s)
        return "+" + d if 8 <= len(d) <= 15 else ""
    d = re.sub(r"\D", "", s)
    if len(d) == 10:
        return "+1" + d
    if len(d) == 11 and d.startswith("1"):
        return "+" + d
    return ""


def valid_email(s):
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", (s or "").strip()))


# --------------------------------------------------------------------------- #
#  SMS
# --------------------------------------------------------------------------- #
def send_sms(cfg, to, text):
    p = (cfg or {}).get("provider")
    to = us_phone(to)
    if not to:
        return False, "No valid mobile number."
    text = (text or "").strip()
    if not text:
        return False, "Empty message."
    frm = (cfg.get("from_number") or "").strip()
    if p == "twilio":
        sid, tok = cfg.get("account_sid", "").strip(), cfg.get("auth_secret", "").strip()
        if not (sid and tok and frm):
            return False, "Twilio isn't set up (Account SID, Auth Token and From number are needed)."
        form = {"To": to, "Body": text}
        form["MessagingServiceSid" if frm.startswith("MG") else "From"] = frm
        st, b = _http(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                      urllib.parse.urlencode(form).encode(),
                      {"Authorization": _basic(sid, tok), "Content-Type": "application/x-www-form-urlencoded"})
        return (True, b.get("sid", "")) if st in (200, 201) else (False, _err(st, b, "Twilio"))
    if p == "telnyx":
        key = cfg.get("api_secret", "").strip()
        if not (key and frm):
            return False, "Telnyx isn't set up (API key and From number are needed)."
        body = {"from": frm, "to": to, "text": text}
        if cfg.get("profile_id"):
            body["messaging_profile_id"] = cfg["profile_id"].strip()
        st, b = _http("https://api.telnyx.com/v2/messages", json.dumps(body).encode(),
                      {"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        return (True, ((b.get("data") or {}).get("id", ""))) if st in (200, 201) else (False, _err(st, b, "Telnyx"))
    if p == "plivo":
        aid, tok = cfg.get("auth_id", "").strip(), cfg.get("auth_secret", "").strip()
        if not (aid and tok and frm):
            return False, "Plivo isn't set up (Auth ID, Auth Token and From number are needed)."
        st, b = _http(f"https://api.plivo.com/v1/Account/{aid}/Message/",
                      json.dumps({"src": frm, "dst": to, "text": text}).encode(),
                      {"Authorization": _basic(aid, tok), "Content-Type": "application/json"})
        ok = st in (200, 202)
        return (True, ",".join(b.get("message_uuid", []) or [])) if ok else (False, _err(st, b, "Plivo"))
    if p == "vonage":
        k, s = cfg.get("api_key", "").strip(), cfg.get("api_secret", "").strip()
        if not (k and s and frm):
            return False, "Vonage isn't set up (API key, secret and From number are needed)."
        st, b = _http("https://rest.nexmo.com/sms/json",
                      urllib.parse.urlencode({"api_key": k, "api_secret": s, "from": frm.lstrip("+"),
                                              "to": to.lstrip("+"), "text": text}).encode(),
                      {"Content-Type": "application/x-www-form-urlencoded"})
        m = (b.get("messages") or [{}])[0] if isinstance(b, dict) else {}
        if st == 200 and str(m.get("status")) == "0":
            return True, m.get("message-id", "")
        return False, f"Vonage error: {m.get('error-text') or _err(st, b, 'Vonage')}"
    if p == "custom":
        url = (cfg.get("url") or "").strip()
        if not url.startswith("http"):
            return False, "The custom SMS provider needs an API URL."
        tpl = cfg.get("body_template") or '{"to": "{to}", "from": "{from}", "text": "{message}"}'
        esc = lambda v: json.dumps(v)[1:-1]                  # JSON-escape inside the quotes
        payload = tpl.replace("{to}", esc(to)).replace("{from}", esc(frm)).replace("{message}", esc(text))
        try:
            json.loads(payload)
        except Exception:
            return False, "The custom provider's JSON body isn't valid JSON after filling it in."
        hdr = {"Content-Type": "application/json"}
        if cfg.get("auth_header_secret"):
            hdr["Authorization"] = cfg["auth_header_secret"].strip()
        st, b = _http(url, payload.encode(), hdr)
        return (True, str((b or {}).get("id", "") if isinstance(b, dict) else "")) if 200 <= st < 300 \
            else (False, _err(st, b, "SMS provider"))
    return False, "No SMS provider is set up. Add one in Setup → Messaging channels."


# --------------------------------------------------------------------------- #
#  WhatsApp
# --------------------------------------------------------------------------- #
def _template_values(cfg, values):
    keys = [k.strip() for k in (cfg.get("template_params") or "").split(",") if k.strip()]
    return [str(values.get(k, "")) for k in keys]


def send_whatsapp(cfg, to, text, values=None, use_template=False):
    """use_template: send the approved template (needed for business-initiated
    messages such as reminders) instead of free text."""
    p = (cfg or {}).get("provider")
    to = us_phone(to)
    if not to:
        return False, "No valid WhatsApp number."
    values = values or {}
    if p == "meta":
        pid, tok = cfg.get("phone_number_id", "").strip(), cfg.get("token_secret", "").strip()
        if not (pid and tok):
            return False, "WhatsApp Cloud API isn't set up (Phone number ID and access token are needed)."
        if use_template and cfg.get("template_name"):
            params = [{"type": "text", "text": v or "-"} for v in _template_values(cfg, values)]
            msg = {"messaging_product": "whatsapp", "to": to.lstrip("+"), "type": "template",
                   "template": {"name": cfg["template_name"].strip(),
                                "language": {"code": (cfg.get("template_lang") or "en_US").strip()},
                                "components": [{"type": "body", "parameters": params}] if params else []}}
        else:
            msg = {"messaging_product": "whatsapp", "to": to.lstrip("+"), "type": "text",
                   "text": {"body": (text or "").strip(), "preview_url": False}}
        st, b = _http(f"https://graph.facebook.com/v21.0/{pid}/messages", json.dumps(msg).encode(),
                      {"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
        if st == 200:
            return True, ((b.get("messages") or [{}])[0]).get("id", "")
        err = _err(st, b, "WhatsApp")
        if "131047" in json.dumps(b) or "re-engagement" in err.lower():
            err += " — WhatsApp only allows free text within 24 hours of the customer's last message; " \
                   "set an approved template in Setup for reminders."
        return False, err
    if p == "twilio":
        sid, tok = cfg.get("account_sid", "").strip(), cfg.get("auth_secret", "").strip()
        frm = (cfg.get("from_number") or "").strip()
        if not (sid and tok and frm):
            return False, "Twilio WhatsApp isn't set up (Account SID, Auth Token and sender number are needed)."
        form = {"To": "whatsapp:" + to, "From": "whatsapp:" + (us_phone(frm) or frm)}
        if use_template and cfg.get("content_sid"):
            form["ContentSid"] = cfg["content_sid"].strip()
            form["ContentVariables"] = json.dumps({str(i + 1): v for i, v in enumerate(_template_values(cfg, values))})
        else:
            form["Body"] = (text or "").strip()
        st, b = _http(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                      urllib.parse.urlencode(form).encode(),
                      {"Authorization": _basic(sid, tok), "Content-Type": "application/x-www-form-urlencoded"})
        return (True, b.get("sid", "")) if st in (200, 201) else (False, _err(st, b, "Twilio WhatsApp"))
    return False, "No WhatsApp provider is set up. Add one in Setup → Messaging channels."


# --------------------------------------------------------------------------- #
#  Email
# --------------------------------------------------------------------------- #
def send_mail(cfg, to, subject, text):
    p = (cfg or {}).get("provider")
    to = (to or "").strip()
    if not valid_email(to):
        return False, "No valid email address."
    subject = (subject or "Payment reminder").strip()
    if p == "sendgrid":
        key, frm = cfg.get("api_secret", "").strip(), (cfg.get("from_addr") or "").strip()
        if not (key and frm):
            return False, "SendGrid isn't set up (API key and verified sender are needed)."
        sender = {"email": frm}
        if cfg.get("from_name"):
            sender["name"] = cfg["from_name"].strip()
        body = {"personalizations": [{"to": [{"email": to}]}], "from": sender, "subject": subject,
                "content": [{"type": "text/plain", "value": text or ""}]}
        st, b = _http("https://api.sendgrid.com/v3/mail/send", json.dumps(body).encode(),
                      {"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        return (True, "") if st in (200, 202) else (False, _err(st, b, "SendGrid"))
    if p == "smtp":
        host = (cfg.get("host") or "").strip()
        if not host:
            return False, "SMTP isn't set up (host is needed)."
        port = int(cfg.get("port") or 587)
        msg = EmailMessage()
        msg["Subject"], msg["To"] = subject, to
        msg["From"] = (cfg.get("from_addr") or cfg.get("user") or "noreply@localhost").strip()
        msg.set_content(text or "")
        try:
            srv = smtplib.SMTP_SSL(host, port, timeout=30) if port == 465 else smtplib.SMTP(host, port, timeout=30)
            if port != 465:
                srv.ehlo()
                try:
                    srv.starttls()
                    srv.ehlo()
                except Exception:
                    pass
            if cfg.get("user"):
                srv.login(cfg["user"].strip(), cfg.get("pass_secret") or "")
            srv.send_message(msg)
            srv.quit()
            return True, ""
        except Exception as e:  # noqa
            return False, f"Email failed: {e}"[:400]
    return False, "No email provider is set up. Add one in Setup → Messaging channels."


# --------------------------------------------------------------------------- #
#  Message templates
# --------------------------------------------------------------------------- #
PLACEHOLDERS = [
    ("name", "Customer's full name"), ("first_name", "First name"), ("amount", "Installment amount, e.g. $250.00"),
    ("due_date", "Due date, e.g. Oct 5, 2026"), ("loan_ref", "Loan number"), ("installment", "e.g. 3 of 12"),
    ("days_left", "Days until the due date"), ("days_overdue", "Days past the due date"),
    ("balance", "Total still unpaid on the loan"), ("company", "Your company name"),
]


def money(v):
    try:
        return "${:,.2f}".format(float(v or 0))
    except Exception:
        return str(v)


def nice_date(iso):
    try:
        return date.fromisoformat(str(iso)[:10]).strftime("%b %d, %Y").replace(" 0", " ")   # Oct 5, 2026
    except Exception:
        return str(iso or "")


def render(text, values):
    """Fill {placeholders}; unknown ones are left as they are."""
    def sub(m):
        k = m.group(1)
        return str(values[k]) if k in values and values[k] is not None else m.group(0)
    return re.sub(r"\{([a-z_]+)\}", sub, text or "")


# --------------------------------------------------------------------------- #
#  Payment schedules
# --------------------------------------------------------------------------- #
PLAN_TYPES = [
    ("monthly", "Monthly installments (EMI)"),
    ("biweekly", "Every 2 weeks"),
    ("weekly", "Weekly"),
    ("interest_only", "Interest only, principal at the end"),
    ("one_time", "One payment on a due date"),
    ("custom", "Custom schedule (enter each payment)"),
]
PERIODS_PER_YEAR = {"monthly": 12, "biweekly": 26, "weekly": 52, "interest_only": 12}


def _add_months(d, n, day):
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(day, monthrange(y, m)[1]))


def _cents(x):
    return round(float(x) + 1e-9, 2)


def build_schedule(plan, principal=0, annual_rate=0, count=1, first_due=None, amount=None, custom=None):
    """List of {"seq", "due_date" (ISO), "amount", "kind"} for a loan.

    monthly / biweekly / weekly — equal payments; `amount` if given, else an
        amortised payment from principal + annual_rate over `count` periods.
    interest_only — monthly interest (principal × rate / 12); the last payment
        adds the principal.
    one_time — a single payment of `amount` (or principal + simple interest).
    custom — `custom` = [{"due_date", "amount"}…] as entered."""
    plan = plan if plan in dict(PLAN_TYPES) else "monthly"
    if plan == "custom":
        rows = []
        for i, c in enumerate(sorted(custom or [], key=lambda r: str(r.get("due_date", "")))):
            d = str(c.get("due_date", ""))[:10]
            date.fromisoformat(d)                              # raises on a bad date
            rows.append({"seq": i + 1, "due_date": d, "amount": _cents(c.get("amount") or 0), "kind": "payment"})
        if not rows:
            raise ValueError("Add at least one payment to the custom schedule.")
        return rows
    first = date.fromisoformat(str(first_due)[:10]) if first_due else None
    if not first:
        raise ValueError("Pick the first due date.")
    principal, rate = float(principal or 0), float(annual_rate or 0)
    count = max(1, min(int(count or 1), 600))
    if plan == "one_time":
        amt = float(amount) if amount not in (None, "") else principal * (1 + rate / 100.0)
        return [{"seq": 1, "due_date": first.isoformat(), "amount": _cents(amt), "kind": "payment"}]
    dates = []
    for i in range(count):
        if plan in ("monthly", "interest_only"):
            dates.append(_add_months(first, i, first.day))
        else:
            dates.append(first + timedelta(days=(14 if plan == "biweekly" else 7) * i))
    if plan == "interest_only":
        if principal <= 0:
            raise ValueError("Interest-only loans need the principal amount.")
        interest = _cents(principal * rate / 100.0 / 12.0) if amount in (None, "") else _cents(amount)
        rows = [{"seq": i + 1, "due_date": d.isoformat(), "amount": interest, "kind": "interest"}
                for i, d in enumerate(dates)]
        rows[-1]["amount"] = _cents(rows[-1]["amount"] + principal)
        rows[-1]["kind"] = "final"
        return rows
    if amount not in (None, ""):
        pay = _cents(amount)
        return [{"seq": i + 1, "due_date": d.isoformat(), "amount": pay, "kind": "payment"} for i, d in enumerate(dates)]
    if principal <= 0:
        raise ValueError("Enter the installment amount, or the principal so it can be calculated.")
    r = rate / 100.0 / PERIODS_PER_YEAR[plan]
    pay = principal / count if r == 0 else principal * r / (1 - (1 + r) ** -count)
    pay = _cents(pay)
    total = _cents(pay * count) if r == 0 else None
    rows = [{"seq": i + 1, "due_date": d.isoformat(), "amount": pay, "kind": "payment"} for i, d in enumerate(dates)]
    if r == 0 and total != _cents(principal):                  # absorb rounding in the last payment
        rows[-1]["amount"] = _cents(pay + (principal - total))
    return rows
