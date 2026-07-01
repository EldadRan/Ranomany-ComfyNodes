"""
Server route for the "Cloudflare Access Identity" node.

  GET /ranomany/cf-identity
    -> { "email": "...", "authenticated": true|false, "simulated": bool,
         "headers": { "Cf-...": "..." } }

Cloudflare Access injects the authenticated user's identity as request headers (e.g.
Cf-Access-Authenticated-User-Email) into every request it forwards to the origin. Node
execution can't see request headers (ComfyUI hands nodes only the /prompt body's
extra_data), so this route reads the headers here and the JS extension (web/cf_identity.js)
pulls the result into the node's widgets.

LOCAL SIMULATION: when no real Cf-Access header is present (i.e. you're not behind
Cloudflare), the route falls back to a simulated email from RANOMANY_CF_SIMULATED_EMAIL
(env var, or a line in .env next to the API keys). This lets you test the whole node /
workflow / metadata chain locally before deploying. The real header always takes precedence,
so leaving the var unset in production changes nothing.

SECURITY: the email header is plaintext and is only trustworthy because the origin is
reachable solely through Cloudflare. Use it for attribution/metadata, NOT authorization —
anyone able to hit the origin directly could spoof it. For real authz, verify the signed
Cf-Access-Jwt-Assertion against your team's certs.

Self-contained on purpose: the repo loads each node file as a standalone module (no package
context), so it cannot relative-import node.py.
"""

import os
from pathlib import Path

from aiohttp import web
from server import PromptServer

_REPO = Path(__file__).resolve().parent.parent.parent  # Ranomany-ComfyNodes root


def _simulated_email() -> str:
    """Dev-only fallback identity: env var, then RANOMANY_CF_SIMULATED_EMAIL in a .env file."""
    val = os.environ.get("RANOMANY_CF_SIMULATED_EMAIL", "").strip()
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
                if k.strip() == "RANOMANY_CF_SIMULATED_EMAIL":
                    return v.strip().strip('"').strip("'")
        except OSError:
            pass
    return ""


async def handle_cf_identity(request):
    email = request.headers.get("Cf-Access-Authenticated-User-Email", "")
    headers = {k: v for k, v in request.headers.items() if k.lower().startswith("cf-")}

    # Local simulation: only when no real Access identity is on the request.
    simulated = False
    if not email and "Cf-Access-Jwt-Assertion" not in request.headers:
        sim = _simulated_email()
        if sim:
            email = sim
            simulated = True

    authenticated = bool(email) or "Cf-Access-Jwt-Assertion" in request.headers
    return web.json_response({
        "email": email,
        "authenticated": authenticated,
        "simulated": simulated,
        "headers": headers,
    })


r = PromptServer.instance.routes
r.get("/ranomany/cf-identity")(handle_cf_identity)
