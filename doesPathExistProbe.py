import asyncio, httpx, json
from companion_collect.config import get_settings
from companion_collect.auth.token_manager import TokenManager
from companion_collect.auth.session_manager import SessionManager

async def main():
    settings = get_settings()
    token_mgr = TokenManager.from_file(settings.tokens_path)
    session_mgr = SessionManager(token_mgr)

    # Mint a fresh WAL session ticket (same as run_auction_pipeline does)
    ticket = await session_mgr.get_session_ticket()
    print(f"Session ticket: {ticket}")

    headers = {
        "Accept-Charset": "UTF-8",
        "Accept": "application/json",
        "X-BLAZE-ID": settings.m26_blaze_id,
        "X-BLAZE-VOID-RESP": "XML",
        "X-Application-Key": "MADDEN-MCA",
        "Content-Type": "application/json",
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 13; Android SDK built for x86_64 Build/TE1A.220922.034)",
    }

    # Minimal body – the real collector fills requestInfo with auth data,
    # this is just to see if the endpoint itself resolves.
    payload = {"apiVersion": 2, "clientDevice": 3, "requestInfo": "{}"}

    async with httpx.AsyncClient(timeout=20.0, verify=False) as client:
        for path in ("wal/mca/Process", "wal/mca21/Process"):
            url = f"https://wal2.tools.gos.bio-iad.ea.com/{path}/{ticket}"
            resp = await client.post(url, headers=headers, json=payload)
            print(path, resp.status_code)
            print(resp.text[:200])

asyncio.run(main())
