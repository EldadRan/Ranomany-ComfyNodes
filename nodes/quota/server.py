"""
Ranomany Usage tracking — per-user generation counts, "last seen" presence, weekly email digest.

The app runs behind Cloudflare Access, which injects the caller's email as the
`Cf-Access-Authenticated-User-Email` request header. Node execution can't read request headers,
so this is a server module (aiohttp middleware + routes), the same pattern as
nodes/ops/server.py and nodes/cf_identity/server.py.

What it does (TRACK ONLY — never blocks a generation):
  - middleware records `presence.last_seen` for any authenticated request (throttled), and
    increments a per-user, per-month generation `count` on each successful POST /prompt.
  - GET  /ranomany/usage        -> the caller's own month/total/last-seen.
  - GET  /ranomany/usage/all    -> everyone's stats (gated by the RANOMANY_VIEWERS allowlist).
  - POST /ranomany/quota-report -> send the weekly digest email now (gated by the admin
                                   password); this is what a host cron / systemd timer calls.

Storage: SQLite at RANOMANY_QUOTA_DB (default <repo>/ranomany_usage.db).
Email:   Resend's SMTP relay via stdlib smtplib — no new dependency; creds are a Resend API
         key + verified sending domain (RANOMANY_SMTP_*), not a personal account.

SECURITY: the CF email is trustworthy only because the origin is reachable solely through
Cloudflare. This is for attribution/visibility, not authorization.

Self-contained on purpose: the repo loads each server file as a standalone module (no package
context), so it cannot relative-import sibling helpers.
"""

import hmac
import json
import logging
import os
import smtplib
import sqlite3
import threading
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from aiohttp import web
from server import PromptServer

_REPO = Path(__file__).resolve().parent.parent.parent  # Ranomany-ComfyNodes root

log = logging.getLogger("RanomanyUsage")

_PRESENCE_THROTTLE_S = 60          # min seconds between presence DB writes per email
_presence_cache: dict[str, float] = {}
_db_lock = threading.Lock()

# A submitted /prompt graph is scanned and every node whose class_type appears in the mapping
# bumps its kind's counter (count-per-node). Nodes NOT in the mapping are never counted.
#
# The mapping is DATA, not code: it lives in a JSON file (see _categories_path) that is
# auto-created with these defaults on first run, git-ignored, and re-read whenever it changes —
# so you add nodes as the pack grows by editing that file, no code edit and no restart.
KINDS = ("image", "video", "utils")
_DEFAULT_CATEGORIES = {
    "image": ["GeminiImage", "GeminiImageMultiRef", "OpenAIImage", "OpenAIImageMultiRef", "WanImage"],
    "video": ["GeminiVeo", "WanVideo", "WanVideoEdit"],
    "utils": ["RanomanyExtractVideoFrames", "RanomanyTrimVideoFrames",
              "RanomanyConvertVideoFPS"],
}
_kind_index_cache = {"mtime": None, "index": {}}


# ── env / .env ───────────────────────────────────────────────────────────────────

def _env_value(key: str) -> str:
    """Read a value from an env var, then from a .env file (repo root and two parents)."""
    val = os.environ.get(key, "").strip()
    if val:
        return val
    for search_dir in (_REPO, _REPO.parent, _REPO.parent.parent):
        env_path = search_dir / ".env"
        if not env_path.is_file():
            continue
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == key:
                    return v.strip().strip('"').strip("'")
        except OSError:
            pass
    return ""


def _env_list(key: str) -> list:
    """Comma-separated env value -> list of trimmed, lowercased, non-empty items."""
    return [x.strip().lower() for x in _env_value(key).split(",") if x.strip()]


def _request_email(request) -> str:
    """CF Access email, or the local-simulation email, or '' (anonymous)."""
    email = request.headers.get("Cf-Access-Authenticated-User-Email", "").strip()
    if email:
        return email
    return _env_value("RANOMANY_CF_SIMULATED_EMAIL")


def _check_password(body: dict) -> bool:
    expected = _env_value("RANOMANY_ADMIN_PASSWORD")
    given = body.get("password", "") if isinstance(body, dict) else ""
    if not expected:
        return False
    return hmac.compare_digest(expected.encode(), given.encode())


# ── time helpers ───────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _period(dt: datetime = None) -> str:
    return (dt or _now()).strftime("%Y-%m")


def _iso(dt: datetime = None) -> str:
    return (dt or _now()).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── category mapping (data-driven, live-reloaded) ───────────────────────────────────

def _categories_path() -> Path:
    override = _env_value("RANOMANY_USAGE_CATEGORIES")
    return Path(override) if override else (_REPO / "ranomany_usage_categories.json")


def _ensure_categories_file() -> None:
    """Seed the categories JSON with the built-in defaults on first run (never overwrites)."""
    path = _categories_path()
    if path.exists():
        return
    try:
        path.write_text(json.dumps(_DEFAULT_CATEGORIES, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def _kind_index() -> dict:
    """{class_type: kind} from the categories file, re-read on change; falls back to defaults."""
    path = _categories_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    if _kind_index_cache["index"] and _kind_index_cache["mtime"] == mtime:
        return _kind_index_cache["index"]

    data = _DEFAULT_CATEGORIES
    if mtime is not None:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError):
            data = _DEFAULT_CATEGORIES

    index: dict = {}
    for kind, classes in data.items():
        if kind not in KINDS or not isinstance(classes, list):
            continue  # only the known kinds (image/video/utils) are tallied
        for c in classes:
            index[str(c)] = kind
    _kind_index_cache["mtime"] = mtime
    _kind_index_cache["index"] = index
    return index


# ── SQLite ─────────────────────────────────────────────────────────────────────────

def _db_path() -> Path:
    override = _env_value("RANOMANY_QUOTA_DB")
    return Path(override) if override else (_REPO / "ranomany_usage.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    with _db_lock, _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usage (
                email       TEXT NOT NULL,
                period      TEXT NOT NULL,
                kind        TEXT NOT NULL,
                count       INTEGER NOT NULL DEFAULT 0,
                last_action TEXT,
                PRIMARY KEY (email, period, kind)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS presence (
                email     TEXT PRIMARY KEY,
                last_seen TEXT
            )
        """)


def _count_kinds(prompt: dict) -> dict:
    """Tally generation nodes in a /prompt graph, per kind (count per matching node)."""
    counts: dict = {}
    if not isinstance(prompt, dict):
        return counts
    index = _kind_index()
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        kind = index.get(node.get("class_type"))
        if kind:
            counts[kind] = counts.get(kind, 0) + 1
    return counts


def _record_generations(email: str, counts: dict) -> None:
    if not counts:
        return
    now = _iso()
    period = _period()
    with _db_lock, _connect() as conn:
        for kind, n in counts.items():
            conn.execute(
                """
                INSERT INTO usage (email, period, kind, count, last_action)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(email, period, kind) DO UPDATE SET
                    count = count + excluded.count,
                    last_action = excluded.last_action
                """,
                (email, period, kind, n, now),
            )


def _touch_presence(email: str) -> None:
    """Update last_seen, throttled to one DB write per _PRESENCE_THROTTLE_S per email."""
    now = time.time()
    if now - _presence_cache.get(email, 0.0) < _PRESENCE_THROTTLE_S:
        return
    _presence_cache[email] = now
    with _db_lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO presence (email, last_seen) VALUES (?, ?)
            ON CONFLICT(email) DO UPDATE SET last_seen = excluded.last_seen
            """,
            (email, _iso()),
        )


def _user_usage(email: str) -> dict:
    period = _period()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT kind, count, last_action FROM usage WHERE email = ? AND period = ?",
            (email, period),
        ).fetchall()
        total = conn.execute(
            "SELECT COALESCE(SUM(count), 0) AS t FROM usage WHERE email = ?", (email,)
        ).fetchone()["t"]
        pres = conn.execute(
            "SELECT last_seen FROM presence WHERE email = ?", (email,)
        ).fetchone()
    kinds = {k: 0 for k in KINDS}
    last_action = None
    for r in rows:
        if r["kind"] in kinds:
            kinds[r["kind"]] = r["count"]
        if r["last_action"] and (last_action is None or r["last_action"] > last_action):
            last_action = r["last_action"]
    return {
        "email": email,
        "period": period,
        **kinds,
        "month": sum(kinds.values()),
        "total": total,
        "last_action": last_action,
        "last_seen": pres["last_seen"] if pres else None,
    }


def _all_usage() -> list:
    """Per-user per-kind stats for the current period, sorted by this-month total desc."""
    period = _period()
    with _connect() as conn:
        cur = conn.execute(
            "SELECT email, kind, count, last_action FROM usage WHERE period = ?", (period,)
        ).fetchall()
        totals = {r["email"]: r["t"] for r in conn.execute(
            "SELECT email, SUM(count) AS t FROM usage GROUP BY email"
        )}
        seen = {r["email"]: r["last_seen"] for r in conn.execute(
            "SELECT email, last_seen FROM presence"
        )}
    per: dict = {}
    for r in cur:
        d = per.setdefault(r["email"], {**{k: 0 for k in KINDS}, "last_action": None})
        if r["kind"] in KINDS:
            d[r["kind"]] = r["count"]
        if r["last_action"] and (d["last_action"] is None or r["last_action"] > d["last_action"]):
            d["last_action"] = r["last_action"]
    emails = set(per) | set(totals) | set(seen)
    rows = []
    for e in emails:
        d = per.get(e, {**{k: 0 for k in KINDS}, "last_action": None})
        month = sum(d[k] for k in KINDS)
        rows.append({
            "email": e,
            **{k: d[k] for k in KINDS},
            "month": month,
            "total": totals.get(e, 0),
            "last_action": d["last_action"],
            "last_seen": seen.get(e),
        })
    rows.sort(key=lambda r: (r["month"], r["total"]), reverse=True)
    return rows


# ── email digest ───────────────────────────────────────────────────────────────────

def _send_report() -> dict:
    host = _env_value("RANOMANY_SMTP_HOST")
    from_addr = _env_value("RANOMANY_SMTP_FROM")
    recipients = _env_list("RANOMANY_REPORT_TO")
    if not host or not from_addr or not recipients:
        return {"sent": False, "error": "missing RANOMANY_SMTP_HOST / _FROM / RANOMANY_REPORT_TO"}

    port = int(_env_value("RANOMANY_SMTP_PORT") or "587")
    user = _env_value("RANOMANY_SMTP_USER")
    password = _env_value("RANOMANY_SMTP_PASS")

    period = _period()
    rows = _all_usage()
    subject = f"Ranomany usage — week of {_now().strftime('%Y-%m-%d')}"

    def _cell(v):
        return "—" if v in (None, "") else str(v)

    text_lines = [f"Ranomany usage report — {period}", ""]
    for r in rows:
        text_lines.append(
            f"  {r['email']}: {r['image']} image / {r['video']} video / {r['utils']} utils"
            f" = {r['month']} this month ({r['total']} lifetime)"
            f" · last action {_cell(r['last_action'])} · last seen {_cell(r['last_seen'])}"
        )
    if not rows:
        text_lines.append("  (no activity recorded yet)")
    text = "\n".join(text_lines) + "\n"

    trs = "".join(
        f"<tr><td>{r['email']}</td>"
        f"<td align='right'>{r['image']}</td><td align='right'>{r['video']}</td>"
        f"<td align='right'>{r['utils']}</td><td align='right'>{r['month']}</td>"
        f"<td align='right'>{r['total']}</td><td>{_cell(r['last_action'])}</td>"
        f"<td>{_cell(r['last_seen'])}</td></tr>"
        for r in rows
    ) or "<tr><td colspan='8'>(no activity recorded yet)</td></tr>"
    html = (
        f"<h3>Ranomany usage report — {period}</h3>"
        "<table border='1' cellpadding='6' cellspacing='0' "
        "style='border-collapse:collapse;font-family:sans-serif;font-size:13px'>"
        "<tr><th>User</th><th>Image</th><th>Video</th><th>Utils</th>"
        "<th>Month</th><th>Lifetime</th><th>Last action</th><th>Last seen</th></tr>"
        f"{trs}</table>"
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls()
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg)
    except Exception as exc:  # noqa: BLE001 — surface any SMTP failure to the caller
        return {"sent": False, "error": f"{type(exc).__name__}: {exc}", "recipients": recipients}

    return {"sent": True, "recipients": recipients, "period": period, "users": len(rows)}


# ── middleware ─────────────────────────────────────────────────────────────────────

def _is_prompt_submit(request) -> bool:
    # The frontend posts to /prompt or (with the /api base) /api/prompt — accept both.
    return request.method == "POST" and request.path.rstrip("/").endswith("/prompt")


@web.middleware
async def usage_middleware(request, handler):
    # Buffer the prompt graph BEFORE the handler runs. aiohttp caches request.read(), so the
    # handler's own request.json() still works — but reading it only *after* the handler can
    # fail once the payload is consumed/released, which would silently drop the count. Reading
    # first guarantees we have the graph regardless.
    is_submit = _is_prompt_submit(request)
    prompt_graph = None
    if is_submit:
        try:
            body = await request.json()
            if isinstance(body, dict):
                prompt_graph = body.get("prompt")
        except Exception as exc:  # noqa: BLE001
            log.warning("[usage] could not read prompt body at %s: %s", request.path, exc)

    resp = await handler(request)

    try:
        email = _request_email(request)
        if email:
            _touch_presence(email)
            if is_submit and getattr(resp, "status", None) == 200:
                counts = _count_kinds(prompt_graph or {})
                if counts:
                    _record_generations(email, counts)
                    log.info("[usage] recorded for %s at %s: %s", email, request.path, counts)
                else:
                    log.info("[usage] %s submitted %s but no countable nodes in graph",
                             email, request.path)
    except Exception:  # noqa: BLE001 — tracking must never break the request pipeline
        log.exception("[usage] failed to record usage")
    return resp


# ── route handlers ─────────────────────────────────────────────────────────────────

async def handle_usage(request):
    email = _request_email(request)
    if not email:
        return web.json_response({"email": "", "image": 0, "video": 0, "utils": 0,
                                  "month": 0, "total": 0, "last_seen": None,
                                  "authenticated": False})
    data = _user_usage(email)
    data["authenticated"] = True
    return web.json_response(data)


async def handle_usage_all(request):
    viewers = _env_list("RANOMANY_VIEWERS")
    email = _request_email(request).lower()
    if not email or email not in viewers:
        return web.json_response({"error": "forbidden"}, status=403)
    return web.json_response({"period": _period(), "users": _all_usage()})


async def handle_quota_report(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not _check_password(body):
        return web.json_response({"error": "forbidden"}, status=403)
    result = _send_report()
    return web.json_response(result, status=200 if result.get("sent") else 500)


# ── register ───────────────────────────────────────────────────────────────────────

_ensure_categories_file()
_init_db()

PromptServer.instance.app.middlewares.append(usage_middleware)

r = PromptServer.instance.routes
r.get("/ranomany/usage")(handle_usage)
r.get("/ranomany/usage/all")(handle_usage_all)
r.post("/ranomany/quota-report")(handle_quota_report)
