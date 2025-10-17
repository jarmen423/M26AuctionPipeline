import sys
sys.path.append('..')  # Add parent directory to path for local imports

import asyncio
import aiohttp
import uuid
import time
import json
from datetime import datetime

from session_manager import ensure_primary_ticket
from companion_collect.adapters.auth import compute_message_auth

# ---- SESSION SETUP ----
context = ensure_primary_ticket(force=True)
ticket = context.ticket
persona_id = context.persona_id

# Compute auth blob
auth_bundle = compute_message_auth(context)
auth_blob = auth_bundle.to_blob()

# ---- CONFIGURATION ----
REGION = "FRA"
SHARD = "mut-companion"
WAL_HOST = "https://wal2.tools.gos.bio-iad.ea.com"
PROCESS_PATH = f"/wal/mca/Process/{ticket}"
FULL_URL = f"{WAL_HOST}{PROCESS_PATH}"

COMMAND_ID_RANGE = range(9100, 9201)
COMPONENT_ID_RANGE = range(2040, 2101)
CONCURRENT_LIMIT = 10

HEADERS = {
    "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 14; Pixel 8 Build/UPB1.230309.017)",
    "Content-Type": "application/json",
    "X-BLAZE-ID": "madden-2026-xbsx-gen5",
    "X-Application-Key": "MADDEN-MCA",
    "productName": "madden-2026-xbsx-mca",
    "X-BLAZE-ROUTE": f"routingPersona={persona_id};region={REGION};shard={SHARD}"
    # Add "Cookie" header here if needed from context.cookie
}

# ---- FUZZER ----

sem = asyncio.Semaphore(CONCURRENT_LIMIT)
results = []

async def fuzz_one(session, command_id, component_id):
    async with sem:
        payload = {
            "apiVersion": 2,
            "clientDevice": 3,
            "requestInfo": {
                "commandName": f"FuzzCmd_{command_id}",
                "componentId": component_id,
                "commandId": command_id,
                "componentName": "AuctionComponent",
                "deviceId": str(uuid.uuid4()),
                "ipAddress": "127.0.0.1",
                "messageExpirationTime": int(time.time()) + 600,
                "messageAuthData": auth_blob,
                "requestPayload": {}
            }
        }

        try:
            async with session.post(FULL_URL, json=payload, headers=HEADERS, timeout=20) as resp:
                try:
                    body = await resp.json()
                    error = body.get("error", "")
                except:
                    body = await resp.text()
                    error = "non-JSON"
                results.append({
                    "commandId": command_id,
                    "componentId": component_id,
                    "status": resp.status,
                    "error": error,
                    "snippet": str(body)[:250]
                })
        except Exception as e:
            results.append({
                "commandId": command_id,
                "componentId": component_id,
                "status": "EXCEPTION",
                "error": str(e),
                "snippet": ""
            })

async def main():
    async with aiohttp.ClientSession() as session:
        tasks = [
            fuzz_one(session, cid, compid)
            for compid in COMPONENT_ID_RANGE
            for cid in COMMAND_ID_RANGE
        ]
        await asyncio.gather(*tasks)

    timestamp = datetime.utcnow().isoformat().replace(":", "_")
    with open(f"fuzz_results_{timestamp}.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nDone. Saved {len(results)} results.")

if __name__ == "__main__":
    asyncio.run(main())
