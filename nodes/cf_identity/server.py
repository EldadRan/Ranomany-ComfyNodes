"""
Server route for the "Cloudflare Access Identity" node.

  GET /ranomany/cf-identity
    -> { "email": str, "authenticated": bool, "simulated": bool,
         "headers": { "Cf-...": "..." },   # the Cf-* request headers CF adds
         "claims":  { ... } }              # identity claims decoded from the Access JWT

Cloudflare Access identity comes in two buckets:
  1. Request HEADERS CF injects  — Cf-Access-Authenticated-User-Email, Cf-Ipcountry,
     Cf-Connecting-Ip, Cf-Ray, and the signed token Cf-Access-Jwt-Assertion.
  2. Rich CLAIMS (name, sub/user-uuid, groups, idp, custom claims) — these live *inside*
     the JWT, not as headers. We base64-decode the JWT payload to surface them.

Node execution can't see request headers (ComfyUI hands nodes only the /prompt body), so
this route reads them and the JS extension (web/cf_identity.js) pulls the result into the
node's widgets.

LOCAL SIMULATION (test before deploying): when no real Cf-Access header/JWT is present, the
route falls back to a simulated identity, from either env var or .env (next to the API keys):
  - RANOMANY_CF_SIMULATED_EMAIL=you@example.com                 # email only, shorthand
  - RANOMANY_CF_SIMULATED_IDENTITY={"email":"you@example.com",  # full bundle (one line)
        "headers":{"Cf-Ipcountry":"IL"}, "claims":{"name":"You","sub":"uuid","groups":["admin"]}}
The real header/JWT always takes precedence, so leaving these unset in production is a no-op.

SECURITY: the email header (and an unverified JWT decode) are only trustworthy because the
origin is reachable solely through Cloudflare. Use for attribution/metadata, NOT authorization
— for real authz, verify the JWT signature against your team's certs.

Self-contained on purpose: the repo loads each node file as a standalone module (no package
context), so it cannot relative-import node.py.
"""

import base64
import json
import os
from pathlib import Path

from aiohttp import web
from server import PromptServer

_REPO = Path(__file__).resolve().parent.parent.parent  # Ranomany-ComfyNodes root


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


def _ci_get(d: dict, key: str) -> str:
    """Case-insensitive dict lookup (header names are case-insensitive)."""
    kl = key.lower()
    for k, v in d.items():
        if k.lower() == kl:
            return v
    return ""


def _decode_jwt_claims(token: str) -> dict:
    """Base64url-decode the JWT payload (UNVERIFIED — presence already proves Access authed)."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)  # restore padding
        return json.loads(base64.urlsafe_b64decode(payload.encode()))
    except Exception:
        return {}


def _simulated():
    """Return (headers, claims) to fake a CF identity locally, or (None, None) if unset."""
    raw = _env_value("RANOMANY_CF_SIMULATED_IDENTITY")
    if raw:
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            obj = {}
        headers = dict(obj.get("headers") or {})
        claims = dict(obj.get("claims") or {})
        email = obj.get("email") or claims.get("email") or ""
        if email:
            if not _ci_get(headers, "Cf-Access-Authenticated-User-Email"):
                headers["Cf-Access-Authenticated-User-Email"] = email
            claims.setdefault("email", email)
        return headers, claims
    email = _env_value("RANOMANY_CF_SIMULATED_EMAIL")
    if email:
        return {"Cf-Access-Authenticated-User-Email": email}, {"email": email}
    return None, None


async def handle_cf_identity(request):
    headers = {k: v for k, v in request.headers.items() if k.lower().startswith("cf-")}
    email = request.headers.get("Cf-Access-Authenticated-User-Email", "")
    jwt = request.headers.get("Cf-Access-Jwt-Assertion", "")

    claims: dict = {}
    simulated = False

    if email or jwt:
        # Real Cloudflare identity — decode the JWT for the rich claims.
        if jwt:
            claims = _decode_jwt_claims(jwt)
        if not email:
            email = claims.get("email", "")
    else:
        # No real identity — fall back to the local simulation, if configured.
        sim_headers, sim_claims = _simulated()
        if sim_headers is not None:
            headers = {k: str(v) for k, v in sim_headers.items()}
            claims = sim_claims or {}
            email = _ci_get(headers, "Cf-Access-Authenticated-User-Email") or claims.get("email", "")
            simulated = True

    authenticated = bool(email) or bool(jwt) or simulated
    return web.json_response({
        "email": email,
        "authenticated": authenticated,
        "simulated": simulated,
        "headers": headers,
        "claims": claims,
    })


r = PromptServer.instance.routes
r.get("/ranomany/cf-identity")(handle_cf_identity)
