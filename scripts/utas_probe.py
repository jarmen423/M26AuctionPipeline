#!/usr/bin/env python3
"""Standalone UTAS probe without touching the pipeline.

Usage examples:
    python scripts/utas_probe.py --endpoint user/profile
    python scripts/utas_probe.py --endpoint auctionhouse
    python scripts/utas_probe.py --route m26
    python scripts/utas_probe.py --route m25
    python scripts/utas_probe.py --endpoint binder/GetHubData --method POST --body-file binder_payload.json
"""
import argparse
import asyncio
import json
import ssl
from pathlib import Path

import httpx

from companion_collect.config import get_settings
from companion_collect.logging import get_logger
from companion_collect.auth.token_manager import TokenManager
from companion_collect.auth.session_manager import SessionManager

logger = get_logger(__name__)


def _tls_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _header_variants(session_key: str, route: str, *, user_agent: str = "", has_body: bool = False):
    base = {
        "Accept": "application/json",
        "Accept-Charset": "UTF-8",
        "User-Agent": user_agent or "Dalvik/2.1.0 (Linux; U; Android 13; Android SDK built for x86_64 Build/TE1A.220922.034)",
        "X-UT-Route": route,
    }
    if has_body:
        base |= {"Content-Type": "application/json"}
    return [
        ("EA-ACCESS-TOKEN+X-UT-SID", base | {"Authorization": f"EA-ACCESS-TOKEN {session_key}", "X-UT-SID": session_key}),
        ("Bearer+X-UT-SID",         base | {"Authorization": f"Bearer {session_key}",          "X-UT-SID": session_key}),
        ("X-UT-SID-only",           base | {"X-UT-SID": session_key}),
    ]


async def utas_request(
    path: str,
    route: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    sid: str | None = None,
    from_context: bool = False,
) -> None:
    settings = get_settings()

    resolved_sid: str | None = None
    if sid:
        resolved_sid = sid.strip()
    elif from_context:
        ctx_path = Path(settings.session_context_path)
        if not ctx_path.exists():
            print(f"Context file not found: {ctx_path}")
            return
        try:
            with ctx_path.open(encoding="utf-8") as handle:
                ctx_data = json.load(handle)
            candidate = ctx_data.get("session_ticket")
            if isinstance(candidate, str) and candidate.strip():
                resolved_sid = candidate.strip()
        except Exception as exc:
            print(f"Failed to load session context: {exc}")
            return
        if not resolved_sid:
            print(f"session_ticket missing in {ctx_path}")
            return
    else:
        tokens_path = Path(getattr(settings, "tokens_path"))
        token_mgr = TokenManager.from_file(tokens_path)
        session_mgr = SessionManager(token_mgr)
        ticket = await session_mgr.get_session_ticket()
        resolved_sid = getattr(ticket, "session_ticket", None) or str(ticket)

    if not resolved_sid:
        print("Session ticket unavailable; aborting UTAS probe")
        return

    base = getattr(settings, "utas_base_url", "https://utas.mob.v2.madden.ea.com").rstrip("/")
    url = f"{base}/mut/{route.strip('/')}/{path.lstrip('/')}"

    logger.info("utas_probe_start", url=url, method=method)

    tls = _tls_ctx()
    async with httpx.AsyncClient(verify=tls, http2=False, timeout=20) as client:
        for label, headers in _header_variants(resolved_sid, route, has_body=body is not None):
            try:
                res = await client.request(method.upper(), url, headers=headers, content=body)
                snippet = res.text[:1000] if res.text else ""
                logger.info("utas_probe_result", header_mode=label, status=res.status_code)
                print(f"[{route}:{label}:{method.upper()}] {res.status_code}")
                if snippet:
                    print(snippet)
                if res.status_code == 200:
                    logger.info("utas_probe_success", header_mode=label)
                    return
            except Exception as e:
                logger.error("utas_probe_error", header_mode=label, error=str(e))

    logger.warning("utas_probe_done_no_success", url=url)


def main():
    ap = argparse.ArgumentParser(description="UTAS probe for Madden MUT endpoints")
    ap.add_argument("--endpoint", default="user/profile", help="Endpoint under /mut/<route>/..., e.g., user/profile or auctionhouse")
    ap.add_argument("--route", default="m26", help="UTAS route, e.g., m26 or m25")
    ap.add_argument("--sid", default=None, help="Use an explicit session ticket (skip WAL)")
    ap.add_argument("--from-context", action="store_true", help="Load session_ticket from session_context")
    ap.add_argument("--method", default="GET", choices=["GET", "POST"], help="HTTP method to use (default: GET)")
    ap.add_argument("--body", default=None, help="Inline JSON string to send as the request body")
    ap.add_argument("--body-file", default=None, help="Path to JSON file to send as the request body")
    args = ap.parse_args()

    if args.sid and args.from_context:
        print("--sid and --from-context are mutually exclusive")
        return

    if args.body and args.body_file:
        print("--body and --body-file are mutually exclusive")
        return

    body_data: bytes | None = None
    if args.body_file:
        body_path = Path(args.body_file)
        if not body_path.exists():
            print(f"Body file not found: {body_path}")
            return
        body_data = body_path.read_bytes()
    elif args.body:
        body_data = args.body.encode("utf-8")

    asyncio.run(
        utas_request(
            args.endpoint,
            args.route,
            method=args.method,
            body=body_data,
            sid=args.sid,
            from_context=args.from_context,
        )
    )


if __name__ == "__main__":
    main()
