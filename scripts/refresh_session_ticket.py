"""Auto-refresh session ticket from fresh mitmproxy captures.

This script watches for new Mobile_SearchAuctions requests in mitmproxy flow files
and automatically extracts the session ticket to update current_session_context.json.

Usage:
    # Watch fresh_capture.mitm for new captures
    python scripts/refresh_session_ticket.py
    
    # Watch a specific flow file
    python scripts/refresh_session_ticket.py --flow-file path/to/capture.mitm
    
    # One-time extraction (no watching)
    python scripts/refresh_session_ticket.py --once

Workflow:
    1. Start mitmproxy: mitmdump -p 8888 -w companion_collect/savedFlows/fresh_capture.mitm
    2. Run this script in another terminal
    3. Open EA app and search auctions once
    4. Script detects new capture and updates session ticket
    5. Your streaming script now has fresh auth!
"""

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from mitmproxy import io as mitmio
from mitmproxy.http import HTTPFlow

from companion_collect.logging import get_logger

logger = get_logger(__name__)


def extract_session_ticket_from_flow(flow: HTTPFlow) -> dict[str, Any] | None:
    """Extract session ticket and headers from a Mobile_SearchAuctions flow.
    
    Args:
        flow: mitmproxy HTTPFlow object
        
    Returns:
        Dict with session_ticket, user_agent, blaze_id, Cookie, or None if not applicable
    """
    # Check if this is a Process request (all Blaze protocol requests go through /wal/mca/Process)
    if "wal/mca/Process" not in flow.request.pretty_url:
        return None
    
    # Check if the request body contains Mobile_SearchAuctions
    if flow.request.content:
        try:
            body_text = flow.request.content.decode("utf-8", errors="ignore")
            if "Mobile_SearchAuctions" not in body_text:
                return None
        except Exception:
            return None
    else:
        return None
    
    # Extract session ticket from URL path
    # URL format: https://.../wal/mca/Process/{session_ticket}
    url_parts = flow.request.path.split("/")
    if len(url_parts) < 5 or url_parts[3] != "Process":
        return None
    
    session_ticket = url_parts[4]
    
    # Extract headers
    headers = dict(flow.request.headers)
    
    return {
        "session_ticket": session_ticket,
        "user_agent": headers.get("User-Agent", ""),
        "blaze_id": headers.get("X-BLAZE-ID", ""),
        "Cookie": headers.get("Cookie", ""),
    }


def load_latest_flow_from_file(flow_path: Path) -> dict[str, Any] | None:
    """Load the most recent Mobile_SearchAuctions flow from a mitm file.
    
    Args:
        flow_path: Path to .mitm flow file
        
    Returns:
        Session context dict or None if no valid flows found
    """
    if not flow_path.exists():
        return None
    
    try:
        with open(flow_path, "rb") as f:
            reader = mitmio.FlowReader(f)
            
            # Read all flows and find the newest Mobile_SearchAuctions
            latest_context = None
            latest_timestamp = 0
            flow_count = 0
            search_auction_count = 0
            
            for flow_data in reader.stream():
                flow_count += 1
                if isinstance(flow_data, HTTPFlow):
                    # Debug: Check if this is a SearchAuctions request (check body content)
                    if flow_data.request.content:
                        try:
                            body_text = flow_data.request.content.decode("utf-8", errors="ignore")
                            if "SearchAuction" in body_text or "Mobile_SearchAuctions" in body_text:
                                search_auction_count += 1
                                logger.debug("found_search_auction", url=flow_data.request.pretty_url)
                        except Exception:
                            pass
                    
                    context = extract_session_ticket_from_flow(flow_data)
                    if context and flow_data.request.timestamp_start > latest_timestamp:
                        latest_context = context
                        latest_timestamp = flow_data.request.timestamp_start
            
            logger.info(
                "flow_scan_complete",
                total_flows=flow_count,
                search_auctions_found=search_auction_count,
                valid_context_found=latest_context is not None,
            )
            
            return latest_context
            
    except Exception as e:
        logger.error("flow_read_error", error=str(e), path=str(flow_path))
        return None


def extract_tokens_from_flow(flow: HTTPFlow) -> Optional[Tuple[float, Dict[str, Any]]]:
    """Capture OAuth token exchanges from a mitm flow."""

    if not flow.request or not flow.response:
        return None

    if flow.request.method != "POST":
        return None

    if "accounts.ea.com/connect/token" not in flow.request.pretty_url:
        return None

    if flow.response.status_code != 200:
        return None

    try:
        payload = json.loads(flow.response.content)
    except json.JSONDecodeError:
        return None

    if {"access_token", "refresh_token"}.issubset(payload):
        return flow.response.timestamp_end, payload

    return None


def load_latest_tokens_from_file(flow_path: Path) -> Optional[Dict[str, Any]]:
    """Scan for the most recent OAuth token payload in a mitm capture."""

    if not flow_path.exists():
        return None

    latest: Optional[Tuple[float, Dict[str, Any]]] = None

    try:
        with open(flow_path, "rb") as fh:
            reader = mitmio.FlowReader(fh)
            for flow_data in reader.stream():
                if isinstance(flow_data, HTTPFlow):
                    token_payload = extract_tokens_from_flow(flow_data)
                    if token_payload:
                        if latest is None or token_payload[0] > latest[0]:
                            latest = token_payload
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("token_scan_failed", error=str(exc), path=str(flow_path))
        return None

    if latest:
        return latest[1]

    return None


def save_session_context(context: dict[str, Any], output_path: Path) -> None:
    """Save session context to JSON file.
    
    Args:
        context: Session context dict
        output_path: Path to save JSON file
    """
    # Also add ak_bmsc_cookie alias for compatibility
    context_with_alias = dict(context)
    context_with_alias["ak_bmsc_cookie"] = context["Cookie"]
    
    with open(output_path, "w") as f:
        json.dump(context_with_alias, f, indent=2)
    
    logger.info(
        "session_context_saved",
        path=str(output_path),
        session_ticket=context["session_ticket"][:30] + "...",
    )


def save_tokens(tokens: Dict[str, Any], output_path: Path) -> None:
    """Persist OAuth tokens with metadata for TokenManager compatibility."""

    issued_at = datetime.now(timezone.utc)
    expires_in = int(tokens.get("expires_in", 900))
    expires_at = issued_at + timedelta(seconds=expires_in)

    payload = {
        "jwt_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "expires_at": expires_at.isoformat(),
        "issued_at": issued_at.isoformat(),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

    logger.info(
        "tokens_saved",
        path=str(output_path),
        expires_at=payload["expires_at"],
    )


def watch_and_refresh(
    flow_path: Path,
    output_path: Path,
    tokens_output: Path,
    check_interval: float = 0.5,
) -> None:
    """Watch flow file for changes and auto-update session context.
    
    Args:
        flow_path: Path to watch for new flows
        output_path: Path to save updated session context
        check_interval: Seconds between file checks
    """
    logger.info(
    "watcher_started",
    flow_path=str(flow_path),
    output_path=str(output_path),
    tokens_output=str(tokens_output),
    check_interval=check_interval,
    )
    
    print("\n" + "=" * 80)
    print("🔄 SESSION TICKET AUTO-REFRESH")
    print("=" * 80)
    print(f"Watching: {flow_path}")
    print(f"Session output: {output_path}")
    print(f"Tokens output:  {tokens_output}")
    print(f"Check interval: {check_interval}s")
    print("=" * 80)
    print("\n📱 Open the EA app and search auctions to capture a fresh session ticket...")
    print("Press Ctrl+C to stop\n")
    
    last_mtime = 0
    if flow_path.exists():
        last_mtime = flow_path.stat().st_mtime
    
    last_session_ticket: Optional[str] = None
    last_refresh_token: Optional[str] = None
    
    try:
        while True:
            time.sleep(check_interval)
            
            if not flow_path.exists():
                continue
            
            current_mtime = flow_path.stat().st_mtime
            
            # File was modified
            if current_mtime > last_mtime:
                last_mtime = current_mtime
                
                print(f"\n🔍 File modified, scanning flows... (this may take a moment for large files)")
                
                # Extract latest flow
                context = load_latest_flow_from_file(flow_path)
                
                if context:
                    if context["session_ticket"] != last_session_ticket:
                        last_session_ticket = context["session_ticket"]
                        
                        # Save updated context
                        save_session_context(context, output_path)
                        
                        print(f"\n✅ NEW SESSION TICKET CAPTURED!")
                        print(f"   Session: {context['session_ticket'][:40]}...")
                        print(f"   Saved to: {output_path}")
                        print(f"   Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
                        print(f"\n   Your streaming script will now use this fresh session! 🎉\n")
                    else:
                        print(f"   ℹ️  Same session ticket found (still valid): {context['session_ticket'][:20]}...")
                        print(f"   Last updated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
                else:
                    print(f"   ⚠️  No Mobile_SearchAuctions found in this update")

                tokens = load_latest_tokens_from_file(flow_path)
                if tokens and tokens.get("refresh_token"):
                    if tokens["refresh_token"] != last_refresh_token:
                        last_refresh_token = tokens["refresh_token"]
                        save_tokens(tokens, tokens_output)
                        print(f"   🔐 OAuth tokens updated ({tokens_output})")
                    else:
                        print("   ℹ️  Latest OAuth tokens unchanged")
                    
    except KeyboardInterrupt:
        print("\n\n⚠️  Watcher stopped by user.\n")


def refresh_once(flow_path: Path, output_path: Path, tokens_output: Path) -> bool:
    """Extract session ticket once without watching.
    
    Args:
        flow_path: Path to flow file
        output_path: Path to save session context
        
    Returns:
        True if successful, False otherwise
    """
    logger.info("one_time_refresh", flow_path=str(flow_path))
    
    context = load_latest_flow_from_file(flow_path)
    if context:
        save_session_context(context, output_path)
        print("\n✅ Session ticket extracted successfully!")
        print(f"   Session: {context['session_ticket'][:40]}...")
        print(f"   Saved to: {output_path}")
    else:
        logger.error("no_valid_flows", flow_path=str(flow_path))
        print(f"\n❌ No valid Mobile_SearchAuctions flows found in {flow_path}\n")
    
    tokens = load_latest_tokens_from_file(flow_path)
    if tokens:
        save_tokens(tokens, tokens_output)
        print(f"   🔐 OAuth tokens saved to: {tokens_output}\n")
    else:
        print("   ⚠️  No OAuth tokens found during one-time extraction\n")

    return True


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Auto-refresh session ticket from mitmproxy captures",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Watch default fresh_capture.mitm file
  python scripts/refresh_session_ticket.py
  
  # Watch a specific flow file
  python scripts/refresh_session_ticket.py --flow-file research/captures/my_capture.mitm
  
  # Extract once without watching
  python scripts/refresh_session_ticket.py --once
  
  # Custom output path
  python scripts/refresh_session_ticket.py --output my_session.json

Workflow:
  Terminal 1: mitmdump -p 8888 -w companion_collect/savedFlows/fresh_capture.mitm
  Terminal 2: python scripts/refresh_session_ticket.py
  Terminal 3: python scripts/run_live_stream.py (after session refreshed)
        """,
    )
    
    parser.add_argument(
        "--flow-file",
        type=Path,
        default=Path.cwd() / "companion_collect" / "savedFlows" / "fresh_capture.mitm",
        help="Path to mitmproxy flow file to watch (default: companion_collect/savedFlows/fresh_capture.mitm)",
    )
    
    parser.add_argument(
        "--output",
        type=Path,
        default=Path.cwd() / "research" / "captures" / "current_session_context.json",
        help="Output path for session context (default: research/captures/current_session_context.json)",
    )
    
    parser.add_argument(
        "--once",
        action="store_true",
        help="Extract once and exit (don't watch for changes)",
    )
    
    parser.add_argument(
        "--tokens-output",
        type=Path,
        default=Path.cwd() / "tokens.json",
        help="Output path for OAuth tokens (default: tokens.json)",
    )
    
    parser.add_argument(
        "--check-interval",
        type=float,
        default=0.5,
        help="Seconds between file checks when watching (default: 0.5)",
    )
    
    return parser.parse_args()


def main() -> None:
    """Main entry point."""
    args = parse_args()
    
    # Ensure output directory exists
    args.output.parent.mkdir(parents=True, exist_ok=True)
    
    if args.once:
        # One-time extraction
        success = refresh_once(args.flow_file, args.output, args.tokens_output)
        exit(0 if success else 1)
    else:
        # Watch mode
        watch_and_refresh(args.flow_file, args.output, args.tokens_output, args.check_interval)


if __name__ == "__main__":
    main()
