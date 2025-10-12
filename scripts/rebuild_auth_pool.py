"""Rebuild auth_pool.json from fresh mitmproxy captures.

This script scans mitmproxy flow files for Mobile_SearchAuctions requests
and extracts all unique auth bundles to create a fresh auth pool.

Usage:
    python scripts/rebuild_auth_pool.py
    python scripts/rebuild_auth_pool.py --flow-file path/to/capture.mitm
    python scripts/rebuild_auth_pool.py --min-bundles 50
    python scripts/rebuild_auth_pool.py --watch  # Keep retrying

Workflow:
    1. Capture multiple auction searches in mitmproxy
    2. Run this script to extract all auth bundles
    3. Your auth pool is now refreshed with valid auth codes!
    
Watch mode will keep the script running and retry every 30 seconds if
insufficient auth bundles are found.
"""

import argparse
import json
import time
from pathlib import Path
from typing import Any

from mitmproxy import io as mitmio
from mitmproxy.http import HTTPFlow

from companion_collect.logging import get_logger
from companion_collect.utils import get_active_capture, get_file_info, read_recent_flows

logger = get_logger(__name__)


def extract_auth_from_flow(flow: HTTPFlow) -> dict[str, Any] | None:
    """Extract auth bundle from a Mobile_SearchAuctions flow.
    
    Returns:
        Dict with auth_code, auth_data, auth_type, source_timestamp or None
    """
    # Check if this is a Process request
    if "wal/mca/Process" not in flow.request.pretty_url:
        return None
    
    try:
        # Parse request body
        request_body = json.loads(flow.request.content.decode("utf-8"))
        
        # Check if this is Mobile_SearchAuctions
        if "requestInfo" not in request_body:
            return None
            
        request_info = json.loads(request_body["requestInfo"])
        
        if request_info.get("commandName") != "Mobile_SearchAuctions":
            return None
        
        # Extract auth
        message_auth = request_info.get("messageAuthData", {})
        
        if not message_auth.get("authCode") or not message_auth.get("authData"):
            return None
        
        return {
            "auth_code": message_auth["authCode"],
            "auth_data": message_auth["authData"],
            "auth_type": message_auth["authType"],
            "source_timestamp": flow.request.timestamp_start,
        }
        
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.debug("flow_parse_failed", error=str(e))
        return None


def rebuild_auth_pool(
    flow_file: Path,
    output_file: Path,
    min_bundles: int = 10,
    max_flows: int = 5000,
) -> int:
    """Rebuild auth pool from mitmproxy flow file.
    
    For large files, only reads the most recent flows for efficiency.
    
    Args:
        flow_file: Path to mitmproxy flow file
        output_file: Path to write auth_pool.json
        min_bundles: Minimum number of bundles required
        max_flows: Maximum number of recent flows to scan (default: 5000)
        
    Returns:
        Number of bundles extracted
    """
    logger.info("scanning_flows", flow_path=str(flow_file), max_flows=max_flows)
    
    auth_bundles = []
    seen_auth_codes = set()
    total_flows = 0
    search_auction_flows = 0
    
    # Use read_recent_flows for efficient scanning of large files
    for flow_data in read_recent_flows(flow_file, max_flows=max_flows):
        total_flows += 1
        
        if not isinstance(flow_data, HTTPFlow):
            continue
            
        if "wal/mca/Process" not in flow_data.request.pretty_url:
            continue
            
        search_auction_flows += 1
        auth_bundle = extract_auth_from_flow(flow_data)
        
        if auth_bundle:
            # Only add unique bundles (by auth_code)
                if auth_bundle["auth_code"] not in seen_auth_codes:
                    auth_bundles.append(auth_bundle)
                    seen_auth_codes.add(auth_bundle["auth_code"])
    
    logger.info(
        "flow_scan_complete",
        total_flows=total_flows,
        search_auction_flows=search_auction_flows,
        unique_bundles=len(auth_bundles),
    )
    
    if len(auth_bundles) < min_bundles:
        logger.warning(
            "insufficient_bundles",
            found=len(auth_bundles),
            required=min_bundles,
        )
        print(f"\n⚠️  WARNING: Only found {len(auth_bundles)} unique auth bundles.")
        print(f"   Recommended: at least {min_bundles} for good rotation.")
        print(f"\n   To get more bundles:")
        print(f"   1. Keep mitmproxy running and capture more auction searches")
        print(f"   2. Rerun this script")
        return 0
    
    # Sort by timestamp (newest first)
    auth_bundles.sort(key=lambda x: x["source_timestamp"], reverse=True)
    
    # Write to file
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(auth_bundles, f, indent=2)
    
    logger.info(
        "auth_pool_saved",
        path=str(output_file),
        bundle_count=len(auth_bundles),
    )
    
    print(f"\n✅ Auth pool rebuilt successfully!")
    print(f"   Bundles: {len(auth_bundles)}")
    print(f"   Saved to: {output_file}")
    print(f"\n   Your auth pool is now fresh! 🎉")
    
    return len(auth_bundles)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Rebuild auth_pool.json from mitmproxy captures",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Use default flow file (fresh_capture.mitm)
  python scripts/rebuild_auth_pool.py

  # Use specific flow file
  python scripts/rebuild_auth_pool.py --flow-file path/to/capture.mitm

  # Require at least 50 bundles
  python scripts/rebuild_auth_pool.py --min-bundles 50
        """,
    )

    parser.add_argument(
        "--flow-file",
        type=Path,
        default=None,  # Will auto-detect most recent capture
        help="Path to mitmproxy flow file (default: auto-detect most recent)",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=Path("research/captures/auth_pool.json"),
        help="Output path for auth_pool.json (default: research/captures/auth_pool.json)",
    )

    parser.add_argument(
        "--min-bundles",
        type=int,
        default=10,
        help="Minimum number of bundles required (default: 10)",
    )
    
    parser.add_argument(
        "--max-flows",
        type=int,
        default=5000,
        help="Max number of recent flows to scan from large files (default: 5000)",
    )
    
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Keep retrying every 30 seconds if insufficient bundles (useful with mitmproxy running)",
    )
    
    parser.add_argument(
        "--retry-interval",
        type=int,
        default=30,
        help="Seconds between retries in watch mode (default: 30)",
    )

    return parser.parse_args()


def main() -> None:
    """Main entry point."""
    args = parse_args()
    
    attempt = 0
    max_attempts = 999999 if args.watch else 1
    
    while attempt < max_attempts:
        attempt += 1
        
        if attempt > 1:
            print(f"\n{'='*80}")
            print(f"Retry attempt {attempt} (waiting {args.retry_interval}s for new traffic...)")
            time.sleep(args.retry_interval)

        # Auto-detect flow file if not specified
        flow_file = args.flow_file
        if flow_file is None:
            if attempt == 1:
                print("\n🔍 Auto-detecting most recent capture file...")
            flow_file = get_active_capture()
            
            if flow_file is None:
                print("\n❌ ERROR: No capture files found in companion_collect/savedFlows/")
                print("\n   Start mitmproxy to capture traffic:")
                print("   mitmdump -w companion_collect/savedFlows/capture_$(date +%Y%m%d_%H%M%S).mitm")
                
                if not args.watch:
                    return
                continue
            
            info = get_file_info(flow_file)
            if attempt == 1:
                print(f"✅ Using: {flow_file.name} ({info['size_mb']} MB, modified {info['age_hours']:.1f}h ago)")
                
                if info['size_mb'] > 100:
                    print(f"   📌 Large file detected - scanning only last {args.max_flows} flows for efficiency")

        if not flow_file.exists():
            logger.error("flow_file_not_found", path=str(flow_file))
            print(f"\n❌ ERROR: Flow file not found: {flow_file}")
            print(f"\n   Make sure mitmproxy is running and capturing traffic:")
            print(f"   mitmdump -p 8888 -w {flow_file}")
            
            if not args.watch:
                return
            continue

        bundle_count = rebuild_auth_pool(
            flow_file=flow_file,
            output_file=args.output,
            min_bundles=args.min_bundles,
            max_flows=args.max_flows,
        )

        if bundle_count == 0 or bundle_count < args.min_bundles:
            if attempt == 1:
                print(f"\n❌ Insufficient auth bundles (found {bundle_count}, need {args.min_bundles})")
                
                if args.watch:
                    print(f"\n⏳ Watch mode enabled - will retry every {args.retry_interval}s")
                    print("   Browse the auction house in the companion app to generate more traffic...")
                    print("   Press Ctrl+C to stop")
                else:
                    print(f"\n   Use --watch to keep retrying automatically:")
                    print("   python scripts/rebuild_auth_pool.py --watch")
                    exit(1)
            
            # Reset flow_file to None so we re-detect on next iteration
            if args.flow_file is None:
                flow_file = None
            continue
        
        # Success!
        if args.watch:
            print(f"\n✨ Will continue watching for new auth bundles every {args.retry_interval}s...")
            print("   Press Ctrl+C to stop")
            
            # Reset flow_file to None so we re-detect on next iteration
            if args.flow_file is None:
                flow_file = None
        else:
            return  # Exit on success if not watching


if __name__ == "__main__":
    main()
