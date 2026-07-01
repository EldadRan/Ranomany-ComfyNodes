"""
Server route for the "Cloudflare Access Identity" node.

  GET /ranomany/cf-identity
    -> { "email": "...", "authenticated": true|false, "headers": { "Cf-...": "..." } }

Cloudflare Access injects the authenticated user's identity as request headers (e.g.
Cf-Access-Authenticated-User-Email) into every request it forwards to the origin. Node
execution can't see request headers (ComfyUI hands nodes only the /prompt body's
extra_data), so this route reads the headers here and the JS extension (web/cf_identity.js)
pulls the result into the node's widgets.

SECURITY: the email header is plaintext and is only trustworthy because the origin is
reachable solely through Cloudflare. Use it for attribution/metadata, NOT authorization —
anyone able to hit the origin directly could spoof it. For real authz, verify the signed
Cf-Access-Jwt-Assertion against your team's certs.

Self-contained on purpose: the repo loads each node file as a standalone module (no package
context), so it cannot relative-import node.py.
"""

from aiohttp import web
from server import PromptServer


async def handle_cf_identity(request):
    email = request.headers.get("Cf-Access-Authenticated-User-Email", "")
    headers = {k: v for k, v in request.headers.items() if k.lower().startswith("cf-")}
    authenticated = bool(email) or "Cf-Access-Jwt-Assertion" in request.headers
    return web.json_response({
        "email": email,
        "authenticated": authenticated,
        "headers": headers,
    })


r = PromptServer.instance.routes
r.get("/ranomany/cf-identity")(handle_cf_identity)
