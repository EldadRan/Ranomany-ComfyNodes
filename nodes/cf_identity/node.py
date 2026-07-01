"""
CloudflareIdentity ("Cloudflare Access Identity") — Phase 1 of the identity/metadata toolset.

Surfaces the Cloudflare Access identity of the current user into the workflow, so downstream
nodes (e.g. the Phase-2 EXIF / video-metadata writers) can stamp "who generated this" into
output files.

Node execution can't read HTTP request headers, so a companion server route
(nodes/cf_identity/server.py, GET /ranomany/cf-identity) reads the Cf-Access-* headers and the
JS extension (web/cf_identity.js) fetches them into this node's widgets. The node then just
echoes those widget values as outputs.

See server.py for the security caveat: this identity is for attribution/metadata, not authz.
"""

import logging

log = logging.getLogger("CFIdentity")


class CloudflareIdentity:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # Populated by web/cf_identity.js from GET /ranomany/cf-identity.
                "email":         ("STRING",  {"default": ""}),
                "authenticated": ("BOOLEAN", {"default": False}),
                "identity_json": ("STRING",  {"default": "", "multiline": True}),
            }
        }

    RETURN_TYPES = ("STRING", "BOOLEAN", "STRING")
    RETURN_NAMES = ("email", "authenticated", "identity_json")
    FUNCTION     = "identity"
    CATEGORY     = "Ranomany/Utils"

    @classmethod
    def IS_CHANGED(cls, email, authenticated, identity_json):
        # Re-run downstream when the identity changes; stay cached otherwise.
        return f"{email}:{authenticated}"

    def identity(self, email: str, authenticated: bool, identity_json: str):
        return (email, bool(authenticated), identity_json)


NODE_CLASS_MAPPINGS = {
    "RanomanyCFIdentity": CloudflareIdentity,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RanomanyCFIdentity": "Cloudflare Access Identity",
}
