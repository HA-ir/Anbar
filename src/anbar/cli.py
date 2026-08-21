"""anbarctl — operational CLI: auth on/off, link minting, object listing.

Talks to a running anbar server over HTTP. The admin key comes from the
ANBAR_ADMIN_KEY env var (or --admin-key); the base URL from ANBAR_BASE_URL
(or --base-url, default http://127.0.0.1:8317).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def _http(method: str, url: str, admin_key: str | None,
          body: dict | None = None) -> tuple[int, dict]:
    """Issue an admin request; return (status_code, parsed_json)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if admin_key:
        req.add_header("Authorization", f"Bearer {admin_key}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")  # type: ignore[no-any-return]
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")  # type: ignore[no-any-return]
        except (ValueError, UnicodeDecodeError):
            return e.code, {"detail": str(e)}
    except urllib.error.URLError as e:
        print(f"error: cannot reach {url} ({e.reason})", file=sys.stderr)
        raise SystemExit(2) from None


def _cmd_auth(args: argparse.Namespace) -> int:
    """Set auth on/off. Reads current state, toggles only if different."""
    status, body = _http("GET", f"{args.base_url}/api/v1/admin/status", args.admin_key)
    if status != 200:
        print(f"error: status check failed: HTTP {status} {body}", file=sys.stderr)
        return 1
    current = body.get("auth_enabled", False)
    desired = args.state != "off"
    if current == desired:
        print(f"auth already {'on' if desired else 'off'}")
        return 0
    code, body = _http("POST", f"{args.base_url}/api/v1/admin/auth/toggle", args.admin_key)
    if code != 200:
        print(f"error: toggle failed: HTTP {code} {body}", file=sys.stderr)
        return 1
    print(f"auth is now {'ON' if body.get('auth_enabled') else 'OFF'}")
    return 0


def _cmd_link(args: argparse.Namespace) -> int:
    code, body = _http("POST", f"{args.base_url}/f/{args.object_id}/link?ttl={args.ttl}",
                       args.admin_key)
    if code != 200:
        print(f"error: link mint failed: HTTP {code} {body}", file=sys.stderr)
        return 1
    print(body["url"])
    return 0


def _cmd_objects(args: argparse.Namespace) -> int:
    code, body = _http("GET", f"{args.base_url}/api/v1/admin/objects?limit={args.limit}",
                       args.admin_key)
    if code != 200:
        print(f"error: listing failed: HTTP {code} {body}", file=sys.stderr)
        return 1
    rows = body.get("objects", [])
    if not rows:
        print("(no objects)")
        return 0
    print(f"{'id':<14} {'size':>12}  {'chunks':>6}  filename")
    for r in rows:
        chunks = r.get("chunks", "?")
        print(f"{r['id']:<14} {r['size']:>12}  {chunks:>6}  {r['filename']}")
    return 0


def _cmd_rotate(args: argparse.Namespace) -> int:
    code, body = _http("POST", f"{args.base_url}/api/v1/admin/auth/rotate-secret",
                       args.admin_key)
    if code != 200:
        print(f"error: rotation failed: HTTP {code} {body}", file=sys.stderr)
        return 1
    print(body["hmac_secret"])
    print("note: previously minted links are now invalid", file=sys.stderr)
    return 0


def _cmd_login(args: argparse.Namespace) -> int:
    """One-time interactive MTProto login (phone + code, optional 2FA).

    Writes the session file that the server (backend=mtproto) reuses on
    startup. Telethon itself prompts for the login code and 2FA password
    on stdin, so this must be run from a real TTY (e.g. `docker exec -it`).
    """
    import asyncio

    from telethon import TelegramClient

    if not args.api_id or not args.api_hash:
        print("error: need --api-id/--api-hash or $ANBAR_API_ID/$ANBAR_API_HASH "
              "(get them from my.telegram.org)", file=sys.stderr)
        return 1
    if not args.phone:
        print("error: need --phone or $ANBAR_LOGIN_PHONE", file=sys.stderr)
        return 1

    client = TelegramClient(args.session, int(args.api_id), args.api_hash)

    async def _run() -> None:
        await client.start(phone=args.phone)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("cancelled", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 - Telethon raises many auth errors
        print(f"login failed: {e}", file=sys.stderr)
        return 1
    finally:
        client.disconnect()
    print(f"logged in — session saved to {args.session}")
    print("start the server with ANBAR_BACKEND=mtproto pointing at this file")
    return 0


def _cmd_install(args: argparse.Namespace) -> int:
    """Write a systemd unit (non-Docker hosts). Does NOT enable the service."""
    unit_path = os.path.expanduser(args.unit)
    env_file = os.path.expanduser(args.env_file)
    if not os.path.isfile(env_file):
        print(f"error: env file not found: {env_file} (copy your .env there first)",
              file=sys.stderr)
        return 1

    # find uvicorn: prefer the venv in --workdir, then the running interpreter's
    # site-packages (the anbarctl you are running is a good signal of the env)
    candidates = [
        os.path.join(os.path.expanduser(args.workdir), ".venv/bin/uvicorn"),
    ]
    import importlib.util

    spec = importlib.util.find_spec("uvicorn")
    if spec is not None and spec.origin:
        uvicorn_py = os.path.dirname(os.path.dirname(spec.origin))
        candidates.append(os.path.join(uvicorn_py, "uvicorn"))
    uvicorn_bin = next((c for c in candidates if os.path.exists(c)), None)
    if uvicorn_bin is None:
        print("error: could not locate an `uvicorn` executable "
              f"(looked at: {', '.join(candidates)})", file=sys.stderr)
        return 1

    host = "127.0.0.1" if args.loopback else "0.0.0.0"
    unit = f"""# Generated by `anbarctl install` — edit freely, then:
#   systemctl daemon-reload && systemctl enable --now anbar
[Unit]
Description=anbar — Telegram-based object storage (zero-retention)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={args.user}
WorkingDirectory={os.path.expanduser(args.workdir)}
EnvironmentFile={env_file}
ExecStart={uvicorn_bin} anbar.main:create_app --factory --host {host} --port {args.port}
Restart=on-failure
RestartSec=3
# hardening
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true

[Install]
WantedBy=multi-user.target
"""
    unit_dir = os.path.dirname(unit_path)
    if unit_dir and not os.path.isdir(unit_dir):
        print(f"error: {unit_dir} does not exist (run as root, or pass a user-unit path)",
              file=sys.stderr)
        return 1
    with open(unit_path, "w") as f:
        f.write(unit)
    os.chmod(unit_path, 0o644)
    print(f"wrote {unit_path}")
    print("next steps:")
    print("  sudo systemctl daemon-reload")
    print("  sudo systemctl enable --now anbar")
    print(f"  curl -s http://{host}:{args.port}/healthz")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="anbarctl", description=__doc__)
    parser.add_argument("--base-url",
                        default=os.environ.get("ANBAR_BASE_URL", "http://127.0.0.1:8317"),
                        help="anbar server base URL (default: $ANBAR_BASE_URL)")
    parser.add_argument("--admin-key", default=os.environ.get("ANBAR_ADMIN_KEY"),
                        help="admin API key (default: $ANBAR_ADMIN_KEY)")

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("version", help="print version")

    p_auth = sub.add_parser("auth", help="turn auth on or off (runtime, no restart)")
    p_auth.add_argument("state", choices=["on", "off"])
    p_auth.set_defaults(func=_cmd_auth)

    p_link = sub.add_parser("link", help="mint a signed download link")
    p_link.add_argument("object_id")
    p_link.add_argument("--ttl", type=int, default=3600,
                        help="validity in seconds (default 3600, clamped 60..604800)")
    p_link.set_defaults(func=_cmd_link)

    p_obj = sub.add_parser("objects", help="list stored objects (newest first)")
    p_obj.add_argument("--limit", type=int, default=50)
    p_obj.set_defaults(func=_cmd_objects)

    p_rot = sub.add_parser("rotate-secret", help="rotate the HMAC signing secret")
    p_rot.set_defaults(func=_cmd_rotate)

    p_login = sub.add_parser(
        "login",
        help="one-time MTProto account login (creates the session file; needs a TTY)",
    )
    p_login.add_argument("--api-id", type=int,
                         default=os.environ.get("ANBAR_API_ID"),
                         help="api_id from my.telegram.org (default: $ANBAR_API_ID)")
    p_login.add_argument("--api-hash", default=os.environ.get("ANBAR_API_HASH"),
                         help="api_hash (default: $ANBAR_API_HASH)")
    p_login.add_argument("--phone", default=os.environ.get("ANBAR_LOGIN_PHONE"),
                         help="account phone, e.g. +98... (default: $ANBAR_LOGIN_PHONE)")
    p_login.add_argument("--session",
                         default=os.environ.get("ANBAR_SESSION_FILE", "secrets/session.session"),
                         help="where to save the session (default: $ANBAR_SESSION_FILE)")
    p_login.set_defaults(func=_cmd_login)

    p_inst = sub.add_parser(
        "install",
        help="write a systemd unit for non-Docker hosts (does not enable it)",
    )
    p_inst.add_argument("--unit", default="/etc/systemd/system/anbar.service",
                        help="where to write the unit (user units also work)")
    p_inst.add_argument("--env-file", default="/etc/anbar/.env",
                        help="the .env file the service should load")
    p_inst.add_argument("--user", default="anbar", help="system user to run as")
    p_inst.add_argument("--workdir", default=".", help="project root (finds .venv)")
    p_inst.add_argument("--port", type=int, default=8000)
    p_inst.add_argument("--loopback", action="store_true",
                        help="bind 127.0.0.1 instead of 0.0.0.0")
    p_inst.set_defaults(func=_cmd_install)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    args.base_url = args.base_url.rstrip("/")

    if getattr(args, "command", None) == "version":
        from . import __version__

        print(f"anbar {__version__}")
        return 0

    if not getattr(args, "func", None):
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())