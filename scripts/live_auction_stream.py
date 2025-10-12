#!/usr/bin/env python3
"""Live auction streaming with automatic token refresh and session management.

This script demonstrates continuous auction polling using the TokenManager and
SessionManager for automatic JWT refresh and session ticket management.

Features:
- Automatic JWT refresh every ~4 hours
- Reusable session tickets (2-3 ticket pool)
- Automatic failover on session errors
- Continuous polling with configurable interval
- Graceful error handling and recovery

Usage:
    python scripts/live_auction_stream.py [--interval SECONDS]

Before running:
    1. python scripts/extract_tokens.py  # Extract tokens from login capture
    2. Ensure tokens.json is valid and not expired
"""

import asyncio
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

import httpx

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from companion_collect.auth.token_manager import TokenManager
from companion_collect.auth.session_manager import SessionManager


# API endpoint and configuration
API_BASE_URL = "https://wal2.tools.gos.bio-iad.ea.com/wal/mca/Process"
DEVICE_ID = "android_emulator_test_001"  # Could be randomized


async def search_auctions(session_ticket: str, count: int = 20) -> dict:
    """Make a Mobile_SearchAuctions API call.
    
    Args:
        session_ticket: Session ticket for authentication
        count: Number of auction results to return
        
    Returns:
        API response data
        
    Raises:
        httpx.HTTPError: If API call fails
    """
    url = f"{API_BASE_URL}/{session_ticket}"
    
    # Build request payload
    # Note: messageAuthData can be dummy values since session ticket handles auth
    payload = {
        "apiVersion": "1.0",
        "clientDevice": "ANDROID",
        "requestInfo": json.dumps({
            "messageExpirationTime": int(datetime.now().timestamp()) + 300,  # 5 min from now
            "deviceId": DEVICE_ID,
            "commandName": "Mobile_SearchAuctions",
            "componentId": 2,
            "commandId": 123,
            "ipAddress": "127.0.0.1",
            "requestPayload": json.dumps({
                "count": count,
                "start": 0,
                "searchCriteria": {}  # Empty = all auctions
            }),
            "componentName": "MCA",
            "messageAuthData": {
                "authCode": "dummy",
                "authData": "dummy",
                "authType": 2
            }
        })
    }
    
    headers = {
        "Accept-Charset": "UTF-8",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 13; Android SDK built for x86_64 Build/TE1A.220922.034)",
        "X-BLAZE-ID": "madden-2025-xbsx-gen5",
        "X-Application-Key": "MADDEN-MCA",
        "X-BLAZE-VOID-RESP": "XML",
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()


async def process_auction_data(data: dict) -> int:
    """Process auction API response and extract auction count.
    
    Args:
        data: API response data
        
    Returns:
        Number of auctions found
    """
    try:
        if "responseInfo" in data:
            response_info = json.loads(data["responseInfo"])
            if "responsePayload" in response_info:
                response_payload = json.loads(response_info["responsePayload"])
                if "auctionInfo" in response_payload:
                    auctions = response_payload["auctionInfo"]
                    return len(auctions)
        return 0
    except Exception as e:
        print(f"      ⚠️  Error parsing auction data: {e}")
        return 0


async def live_stream(interval: int = 10):
    """Continuously poll auction API with automatic token/session management.
    
    Args:
        interval: Seconds between polls
    """
    print("=" * 80)
    print("LIVE AUCTION STREAMING")
    print("=" * 80)
    print()
    
    # Initialize token manager
    tokens_path = Path(__file__).parent.parent / "research" / "captures" / "tokens.json"
    
    if not tokens_path.exists():
        print("❌ Tokens file not found!")
        print()
        print("Run this first:")
        print("  python scripts/extract_tokens.py")
        return 1
    
    print("[1/3] Loading TokenManager...")
    try:
        token_manager = TokenManager.from_file(tokens_path)
        token_status = token_manager.get_status()
        print(f"      ✅ JWT expires in: {token_status['time_remaining']}")
    except Exception as e:
        print(f"      ❌ Failed to load tokens: {e}")
        return 1
    
    print()
    
    # Initialize session manager
    print("[2/3] Initializing SessionManager...")
    session_manager = SessionManager(token_manager, max_backups=2)
    
    # Pre-generate primary ticket
    try:
        ticket = await session_manager.get_session_ticket()
        print(f"      ✅ Primary session ticket ready: {ticket[:50]}...")
    except Exception as e:
        print(f"      ❌ Failed to generate session ticket: {e}")
        return 1
    
    print()
    
    # Generate backup tickets (do this in background to not delay startup)
    print("[3/3] Starting backup generation (runs in background)...")
    print(f"      Primary ticket is ready, starting stream now!")
    
    # We'll generate backups during the polling loop
    
    print()
    print("=" * 80)
    print(f"🚀 LIVE STREAMING STARTED (polling every {interval}s)")
    print("=" * 80)
    print()
    print("Press Ctrl+C to stop")
    print()
    
    # Statistics
    total_polls = 0
    successful_polls = 0
    failed_polls = 0
    total_auctions_seen = 0
    
    try:
        while True:
            total_polls += 1
            timestamp = datetime.now().strftime("%H:%M:%S")
            
            try:
                # Get current session ticket (reusable!)
                ticket = await session_manager.get_session_ticket()
                
                # Make API call
                data = await search_auctions(ticket, count=20)
                
                # Process results
                auction_count = await process_auction_data(data)
                total_auctions_seen += auction_count
                successful_polls += 1
                
                print(f"[{timestamp}] ✅ Poll #{total_polls}: {auction_count} auctions found")
                
            except httpx.HTTPStatusError as e:
                failed_polls += 1
                print(f"[{timestamp}] ❌ Poll #{total_polls} failed: HTTP {e.response.status_code}")
                
                # Mark ticket as failed and try to get backup
                if e.response.status_code in (401, 403, 404):
                    print(f"           Session error, marking ticket as failed...")
                    await session_manager.mark_failed(ticket)
                
            except Exception as e:
                failed_polls += 1
                print(f"[{timestamp}] ❌ Poll #{total_polls} failed: {e}")
            
            # Wait before next poll
            await asyncio.sleep(interval)
            
            # Periodically ensure backups and show status
            if total_polls % 10 == 0:
                print()
                print(f"📊 Status after {total_polls} polls:")
                print(f"   Success: {successful_polls} ({100*successful_polls/total_polls:.1f}%)")
                print(f"   Failed: {failed_polls} ({100*failed_polls/total_polls:.1f}%)")
                print(f"   Total auctions seen: {total_auctions_seen}")
                
                # Show token status
                token_status = token_manager.get_status()
                print(f"   JWT expires in: {token_status['time_remaining']}")
                
                # Ensure backups are maintained (async, non-blocking)
                session_status = session_manager.get_status()
                print(f"   Session tickets: 1 primary + {session_status['backup_count']} backups")
                
                if session_status['backup_count'] < 2:
                    print(f"   🔄 Will generate more backups in background...")
                    asyncio.create_task(session_manager.ensure_backups())
                
                print()
    
    except KeyboardInterrupt:
        print()
        print()
        print("=" * 80)
        print("🛑 STREAMING STOPPED")
        print("=" * 80)
        print()
        print("Final Statistics:")
        print(f"  Total polls: {total_polls}")
        print(f"  Successful: {successful_polls} ({100*successful_polls/total_polls:.1f}%)")
        print(f"  Failed: {failed_polls} ({100*failed_polls/total_polls:.1f}%)")
        print(f"  Total auctions seen: {total_auctions_seen}")
        print()
        return 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Live auction streaming with automatic token management"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Polling interval in seconds (default: 10)"
    )
    
    args = parser.parse_args()
    
    return asyncio.run(live_stream(args.interval))


if __name__ == "__main__":
    sys.exit(main())
