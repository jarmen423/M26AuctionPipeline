import asyncio
import ast
import json
from pathlib import Path
from typing import Iterable

import httpx

from companion_collect.config import get_settings
from companion_collect.auth.token_manager import TokenManager
from companion_collect.auth.session_manager import SessionManager


SESSION_CONTEXT_PATH = Path("auction_data/current_session_context.json")
ENDPOINT_SUMMARY_PATH = Path("endpointCheckSummary.md")

# Candidate path suffixes to probe against each host
PATH_CANDIDATES = (
    "wal/mca/Process",
    "wal/mca21/Process",
)

# Minimal body – the collector fills this with full auth data, but this is enough
# to reveal whether the route exists.
MINIMAL_BODY = {"apiVersion": 2, "clientDevice": 3, "requestInfo": "{}"}


async def load_session_ticket(settings) -> str:
    """Load existing session ticket from context; mint new one if missing."""
    if SESSION_CONTEXT_PATH.exists():
        try:
            data = json.loads(SESSION_CONTEXT_PATH.read_text())
            ticket = data.get("session_ticket")
            if isinstance(ticket, str) and ticket:
                return ticket
        except json.JSONDecodeError:
            pass  # fall through to minting a fresh ticket

    token_mgr = TokenManager.from_file(settings.tokens_path)
    session_mgr = SessionManager(token_mgr)
    return await session_mgr.get_session_ticket()


def load_candidate_hosts() -> Iterable[str]:
    """Parse endpointCheckSummary.md and return the resolved hosts list."""
    if not ENDPOINT_SUMMARY_PATH.exists():
        return ()

    text = ENDPOINT_SUMMARY_PATH.read_text()
    start = text.find("[")
    end = text.find("]", start)
    if start == -1 or end == -1:
        return ()
    try:
        hosts = ast.literal_eval(text[start : end + 1])
    except (SyntaxError, ValueError):
        return ()
    return [host.strip() for host in hosts if isinstance(host, str) and host.strip()]


async def probe_host(client: httpx.AsyncClient, host: str, ticket: str, headers: dict) -> None:
    for suffix in PATH_CANDIDATES:
        url = f"https://{host}/{suffix}/{ticket}"
        try:
            resp = await client.post(url, headers=headers, json=MINIMAL_BODY)
            snippet = resp.text.strip()[:200].replace("\n", " ")
            print(f"{host}/{suffix} -> {resp.status_code} | {snippet}")
        except Exception as exc:
            print(f"{host}/{suffix} -> ERROR {exc}")


async def main():
    settings = get_settings()
    ticket = await load_session_ticket(settings)
    print(f"Using session ticket: {ticket}")

    headers = {
        "Accept-Charset": "UTF-8",
        "Accept": "application/json",
        "X-BLAZE-ID": settings.m26_blaze_id,
        "X-BLAZE-VOID-RESP": "XML",
        "X-Application-Key": "MADDEN-MCA",
        "Content-Type": "application/json",
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 13; Android SDK built for x86_64 Build/TE1A.220922.034)",
    }

    hosts = list(load_candidate_hosts())
    if not hosts:
        print("No hosts found in endpointCheckSummary.md; probing default wal2 host only.")
        hosts = ["wal2.tools.gos.bio-iad.ea.com"]

    async with httpx.AsyncClient(timeout=20.0, verify=False) as client:
        for host in hosts:
            await probe_host(client, host, ticket, headers)


if __name__ == "__main__":
    asyncio.run(main())
