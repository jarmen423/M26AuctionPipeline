#!/usr/bin/env python3
"""Generate a fresh session ticket via WAL login."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import ssl

import httpx

from companion_collect.auth.session_manager import SessionManager
from companion_collect.auth.token_manager import TokenManager
from companion_collect.config import get_settings

def _tls_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def _header_variants(session_key: str, route: str, user_agent: str = ""):
    base = {
        "Accept": "application/json",
        "Accept-Charset": "UTF-8",
        "User-Agent": user_agent or "Dalvik/2.1.0 (Linux; U; Android 13; Android SDK built for x86_64 Build/TE1A.220922.034)",
        "X-UT-Route": route,
    }
    return [
        ("EA-ACCESS-TOKEN+X-UT-SID", base | {"Authorization": f"EA-ACCESS-TOKEN {session_key}", "X-UT-SID": session_key}),
        ("Bearer+X-UT-SID",         base | {"Authorization": f"Bearer {session_key}",          "X-UT-SID": session_key}),
        ("X-UT-SID-only",           base | {"X-UT-SID": session_key}),
    ]

async def _probe_utas(sid: str, base_url: str, route: str) -> tuple[bool, str, int, str]:
    """
    Try a simple UTAS read endpoint with multiple header variants.
    Returns: (ok, header_mode, status_code, route_used)
    """
    url = f"{base_url.rstrip('/')}/mut/{route.strip('/')}/user/profile"
    tls = _tls_ctx()
    async with httpx.AsyncClient(verify=tls, http2=False, timeout=20) as client:
        for label, headers in _header_variants(sid, route):
            try:
                r = await client.get(url, headers=headers)
                print(f"[{route}:{label}] {r.status_code}")
                if r.status_code == 200:
                    return True, label, r.status_code, route
            except Exception as e:
                print(f"[{route}:{label}] error: {e}")
    return False, "", 0, route

def _resolve_year_token(route: str, wal_year: str | None) -> str:
    token = (wal_year or route).lower().strip()
    if token.startswith("m"):
        token = token[1:]
    if token.startswith("20") and len(token) == 4 and token.isdigit():
        return token
    if len(token) == 2 and token.isdigit():
        return f"20{token}"
    if token.isdigit() and len(token) == 4:
        return token
    return "2026"


def _platform_candidates(year: str, platform: str) -> list[tuple[str, str]]:
    """Return likely (product, blaze) pairs for the given year/platform."""
    match platform:
        case "pc":
            return [
                (f"madden-{year}-pc-mca", f"madden-{year}-pc-gen5"),
                (f"madden-{year}-win32-mca", f"madden-{year}-win32-gen5"),
            ]
        case "ps5":
            return [(f"madden-{year}-ps5-mca", f"madden-{year}-ps5-gen5")]
        case "xbsx":
            return [(f"madden-{year}-xbsx-mca", f"madden-{year}-xbsx-gen5")]
    return []


def _explicit_candidates(product: str | None, blaze: str | None) -> list[tuple[str, str]]:
    if product and blaze:
        return [(product, blaze)]
    if product or blaze:
        raise ValueError("Both --wal-product and --wal-blaze must be supplied together")
    return []


def _normalized_wal_hosts(choice: str | None) -> list[str]:
    if not choice or choice == "auto":
        return ["https://wal2.tools.gos.bio-iad.ea.com"]
    return [choice]


async def main():
    """Generate fresh session ticket from WAL."""
    parser = argparse.ArgumentParser(description="Mint WAL session ticket and validate against UTAS")
    parser.add_argument(
        "--platform",
        choices=["pc", "xbsx", "ps5"],
        default=None,
        help="Override WAL product/blaze identifiers for the given platform",
    )
    parser.add_argument(
        "--route",
        choices=["m26", "m25"],
        default=None,
        help="UTAS route to validate (defaults to config utas_route)",
    )
    parser.add_argument(
        "--wal-host",
        default="auto",
        help="Override WAL base host. Defaults to wal2.tools.gos.bio-iad.ea.com",
    )
    parser.add_argument(
        "--wal-year",
        default=None,
        help="Force WAL Madden year (e.g., 2025, 2026, m25, m26).",
    )
    parser.add_argument(
        "--wal-product",
        default=None,
        help="Explicit WAL product name override (requires --wal-blaze).",
    )
    parser.add_argument(
        "--wal-blaze",
        default=None,
        help="Explicit WAL blaze id override (requires --wal-product).",
    )
    args = parser.parse_args()

    print("=" * 80)
    print("GENERATING FRESH SESSION TICKET FROM WAL")
    print("=" * 80)
    
    settings = get_settings()

    #Ensure tokens are fresh
    tokens_path = Path(settings.tokens_path)
    if not tokens_path.exists():
        print(f"Tokens file not found: {tokens_path}")
        return 1
    
    token_manager = TokenManager.from_file(tokens_path)
    print("\nEnsuring valid JWT token...")
    jwt = await token_manager.get_valid_jwt()
    print(f"JWT ready: {jwt[:20]}...")

    # Generate session ticket via WAL
    print("\nGenerating session ticket from WAL...")

    ticket = None
    last_error: Exception | None = None

    chosen_route = (args.route or getattr(settings, "utas_route", None) or "m26").lower()

    wal_year = _resolve_year_token(chosen_route, args.wal_year)

    if args.platform:
        candidates: list[tuple[str, str]] = []
        try:
            explicit = _explicit_candidates(args.wal_product, args.wal_blaze)
        except ValueError as exc:
            print(str(exc))
            return 1
        if explicit:
            candidates = explicit
        else:
            candidates = _platform_candidates(wal_year, args.platform)
        wal_hosts = _normalized_wal_hosts(args.wal_host)

        for wal_host in wal_hosts:
            for product, blaze in candidates:
                print(f"\nTrying WAL login: host={wal_host}, product={product}, blaze_id={blaze}")
                session_manager = SessionManager(
                    token_manager,
                    product_override=product,
                    blaze_id_override=blaze,
                    wal_base_url_override=wal_host,
                )
                try:
                    ticket = await session_manager.get_session_ticket()
                    print("WAL login success.")
                    break
                except Exception as exc:  # noqa: PERF203 - keep for diagnostics
                    last_error = exc
                    print(f"WAL login failed: {exc}")
            if ticket:
                break
    else:
        wal_host_override = None if args.wal_host in (None, "auto") else args.wal_host
        session_manager = SessionManager(
            token_manager,
            product_override=args.wal_product,
            blaze_id_override=args.wal_blaze,
            wal_base_url_override=wal_host_override,
        )
        try:
            ticket = await session_manager.get_session_ticket()
        except Exception as exc:
            last_error = exc

    if not ticket:
        print("\nAll WAL login attempts failed; cannot mint session ticket.")
        if last_error:
            print(f"Last error: {last_error}")
        return 1

    try:
        # Extract the raw session key string (sid)
        sid = getattr(ticket, "session_ticket", None) or str(ticket)
        if not isinstance(sid, str) or len(sid) < 10:
            raise RuntimeError("Invalid session ticket format")

        print(f"\nSession ticket minted (sid): {sid[:10]}...")

        # Probe UTAS (chosen route first, then optional fallback)
        utas_base = getattr(settings, "utas_base_url", "https://utas.mob.v2.madden.ea.com")
        primary_route = chosen_route

        print(f"\nProbing UTAS ({primary_route})...")
        ok, header_mode, status, route_used = await _probe_utas(sid, utas_base, primary_route)

        if not ok and primary_route != "m25":
            print("\nNo 200 on selected route; retrying on m25...")
            ok, header_mode, status, route_used = await _probe_utas(sid, utas_base, "m25")

        if not ok:
            print("\nUTAS probe failed on all variants. Ticket not persisted.")
            return 1

        print(f"\nUTAS probe success: route={route_used}, header_mode={header_mode}, status={status}")

        # Update context file 
        context_path = Path(settings.session_context_path)

        existing_context: dict[str, str] = {}
        if context_path.exists():
            with open(context_path) as f:
                existing_context = json.load(f)

        new_context: dict[str, str] = {}
        cookie_val = existing_context.get('ak_bmsc_cookie')
        if cookie_val:
            new_context['ak_bmsc_cookie'] = cookie_val
        # persist the validated session ticket and UTAS hints
        new_context['session_ticket'] = sid
        new_context['utas_route'] = route_used
        new_context['utas_header_mode'] = header_mode

        with open(context_path, 'w') as f:
            json.dump(new_context, f, indent=2)
        print(f"\nUpdated {context_path}")
        print("\nReady for pipeline (200-confirmed UTAS ticket).")
        return 0

    except Exception as exc:
        print(f"\nError: {exc}")
        import traceback
        traceback.print_exc()
        return 1
if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
    