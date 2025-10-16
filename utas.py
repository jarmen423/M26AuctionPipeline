import asyncio
import ssl
import json
import argparse
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

def _header_variants(session_key: str, user_agent: str = ""):
    base = {
        "Accept": "application/json",
        "Accept-Charset": "UTF-8",
        "User-Agent": user_agent or "Dalvik/2.1.0 (Linux; U; Android 13; Android SDK built for x86_64 Build/TE1A.220922.034)",
    }
    variants = []
    # Variant A: EA-ACCESS-TOKEN + X-UT-SID
    h1 = base | {"Authorization": f"EA-ACCESS-TOKEN {session_key}", "X-UT-SID": session_key, "X-UT-Route": "m26"}
    variants.append(("EA-ACCESS-TOKEN+X-UT-SID", h1))
    # Variant B: Bearer + X-UT-SID
    h2 = base | {"Authorization": f"Bearer {session_key}", "X-UT-SID": session_key, "X-UT-Route": "m26"}
    variants.append(("Bearer+X-UT-SID", h2))
    # Variant C: X-UT-SID only
    h3 = base | {"X-UT-SID": session_key, "X-UT-Route": "m26"}
    variants.append(("X-UT-SID-only", h3))
    return variants

async def utas_get(path: str) -> None:
    settings = get_settings()
    token_mgr = TokenManager()
    session_mgr = SessionManager(token_mgr)
    ticket = await session_mgr.get_session_ticket()
    session_key = ticket.session_ticket

    base = settings.utas_base_url.rstrip("/")
    route = settings.utas_route.strip("/")
    url = f"{base}/mut/{route}/{path.lstrip('/')}"

    logger.info("utas_probe_start", url=url)

    tls = _tls_ctx()
    async with httpx.AsyncClient(verify=tls, http2=False, timeout=20) as client:
        for label, headers in _header_variants(session_key):
            try:
                res = await client.get(url, headers=headers)
                snippet = res.text[:1000] if res.text else ""
                logger.info("utas_probe_result", header_mode=label, status=res.status_code)
                print(f"[{label}] {res.status_code}")
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
    args = ap.parse_args()
    asyncio.run(utas_get(args.endpoint))

if __name__ == "__main__":
    main()