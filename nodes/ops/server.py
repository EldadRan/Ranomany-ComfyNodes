"""
Ranomany Ops — aiohttp routes registered on ComfyUI's server.

Routes:
  POST /ranomany/restart       — restart ComfyUI (no auth)
  POST /ranomany/update        — git pull + pip install + restart (password)
  GET  /ranomany/rollback-tags — list last 5 pre-update-* tags (no auth)
  POST /ranomany/rollback      — git checkout <tag> + restart (password)
  GET  /ranomany/ops-log       — last 20 lines of ops log (no auth)

Password: set RANOMANY_ADMIN_PASSWORD in .env alongside API keys.
Restart: os._exit(0) — relies on systemd Restart=always to bring ComfyUI back.
"""

import asyncio
import hmac
import os
import signal
import sys
import time
from pathlib import Path

from aiohttp import web
from server import PromptServer

_HERE = Path(__file__).parent   # nodes/ops/
_REPO = _HERE.parent.parent     # Ranomany-ComfyNodes root (the git repo)
_LOG  = _REPO / "ranomany_ops.log"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _cf_email(request) -> str:
    return request.headers.get("Cf-Access-Authenticated-User-Email", "unknown")


def _log(action: str, email: str, extra: str = "") -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} | {action} | {email}"
    if extra:
        line += f" | {extra}"
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _read_admin_password() -> str:
    """Read RANOMANY_ADMIN_PASSWORD from env var or .env file (same search as other nodes)."""
    val = os.environ.get("RANOMANY_ADMIN_PASSWORD", "").strip()
    if val:
        return val
    for search_dir in [_REPO, _REPO.parent, _REPO.parent.parent]:
        env_path = search_dir / ".env"
        if not env_path.is_file():
            continue
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == "RANOMANY_ADMIN_PASSWORD":
                    return v.strip().strip('"').strip("'")
        except OSError:
            pass
    return ""


def _check_password(body: dict) -> bool:
    expected = _read_admin_password()
    given = body.get("password", "")
    if not expected:
        return False
    return hmac.compare_digest(expected.encode(), given.encode())


def _schedule_exit() -> None:
    asyncio.get_event_loop().call_later(1.0, lambda: os.kill(os.getpid(), signal.SIGTERM))


async def _run_git(*args) -> tuple:
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=str(_REPO),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    return proc.returncode, out.decode("utf-8", errors="replace")


async def _run_pip_install() -> tuple:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "pip", "install", "-r", "requirements.txt",
        cwd=str(_REPO),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    return proc.returncode, out.decode("utf-8", errors="replace")


# ── Route handlers ─────────────────────────────────────────────────────────────

async def handle_restart(request):
    _log("restart", _cf_email(request))
    _schedule_exit()
    return web.json_response({"status": "restarting"})


async def handle_update(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)

    if not _check_password(body):
        return web.json_response({"error": "forbidden"}, status=403)

    tag = f"pre-update-{int(time.time())}"
    await _run_git("tag", tag)

    rc, pull_out = await _run_git("pull")
    if rc != 0:
        return web.json_response({"error": "git pull failed", "output": pull_out}, status=500)

    rc, pip_out = await _run_pip_install()
    if rc != 0:
        return web.json_response({"error": "pip install failed", "output": pip_out}, status=500)

    _log("update", _cf_email(request), f"tag={tag}")
    _schedule_exit()
    return web.json_response({
        "status": "updated",
        "rollback_tag": tag,
        "output": pull_out,
    })


async def handle_rollback_tags(request):
    _, out = await _run_git("tag", "--sort=-version:refname", "-l", "pre-update-*")
    tags = [t for t in out.strip().splitlines() if t][:5]
    return web.json_response({"tags": tags})


async def handle_rollback(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)

    if not _check_password(body):
        return web.json_response({"error": "forbidden"}, status=403)

    tag = body.get("tag", "")
    if not tag.startswith("pre-update-"):
        return web.json_response({"error": "invalid tag"}, status=400)

    rc, out = await _run_git("checkout", tag)
    if rc != 0:
        return web.json_response({"error": "git checkout failed", "output": out}, status=500)

    _log("rollback", _cf_email(request), f"tag={tag}")
    _schedule_exit()
    return web.json_response({"status": "rolling back", "tag": tag})


async def handle_ops_log(request):
    if not _LOG.exists():
        return web.json_response({"lines": []})
    lines = _LOG.read_text(encoding="utf-8").splitlines()[-20:]
    return web.json_response({"lines": lines})


# ── Register routes ────────────────────────────────────────────────────────────

r = PromptServer.instance.routes
r.post("/ranomany/restart")(handle_restart)
r.post("/ranomany/update")(handle_update)
r.get("/ranomany/rollback-tags")(handle_rollback_tags)
r.post("/ranomany/rollback")(handle_rollback)
r.get("/ranomany/ops-log")(handle_ops_log)
