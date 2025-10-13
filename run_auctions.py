import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from companion_collect.auth.session_manager import SessionManager
from companion_collect.auth.token_manager import TokenManager
from companion_collect.collectors.auctions import AuctionCollector
from companion_collect.config import get_settings
from companion_collect.logging import get_logger
from companion_collect.pipelines.auction_pipeline import AuctionRecord, normalize_auction


logger = get_logger(__name__)


def build_context(
    search: str,
    offset: int,
    max_results: int,
    settings: Any,
) -> Dict[str, Any]:
    """Build request context for auction fetch."""
    context: Dict[str, Any] = {
        "page": offset // max_results,
        "page_size": max_results,
        "count": max_results,
        "start": offset,
        "page_offset": offset,
        "api_version": "2",
        "client_device": "3",
        "command_name": settings.m26_command_name,
        "component_id": settings.m26_component_id,
        "command_id": settings.m26_command_id,
        "component_name": "mut",
        "ip_address": "127.0.0.1",
        "blaze_id": settings.m26_blaze_id,
        "device_id": settings.device_id or "dev",
        "message_expiration_time": int(datetime.now().timestamp()) + 3600,
        "auth_type": 17039361,
        "user_agent": "MutDashboard-Collector/1.0",
        "ak_bmsc_cookie": "",
    }

    # Add filters for search
    if search:
        filters: List[Dict[str, Any]] = [
            {
                "type": "contains",
                "value": search,
                "field": "itemName",  # Assuming search is for item name
            }
        ]
        payload_dict = {"filters": filters, "itemName": ""}
        payload_json = json.dumps(payload_dict)
        escaped_payload = payload_json.replace("\\", "\\\\").replace('"', '\\"')
        context["request_payload"] = escaped_payload
    else:
        context["request_payload"] = '{"filters":[],"itemName":""}'

    # Merge settings overrides
    context.update(settings.request_context_overrides)
    return context


async def fetch_and_save_auctions(
    collector: AuctionCollector,
    context: Dict[str, Any],
    output_path: Path,
) -> None:
    """Fetch auctions and save to JSON."""
    try:
        response = await collector.fetch_once(context=context)
        logger.info("Fetched auctions successfully")

        # Parse auctions from response
        auction_details = (
            response.get("responseInfo", {})
            .get("value", {})
            .get("details", [])
        )

        # Normalize auctions
        normalized_auctions: List[AuctionRecord] = []
        for raw in auction_details:
            try:
                normalized_auctions.append(normalize_auction(raw))
            except KeyError as e:
                logger.warning("Failed to normalize auction", error=str(e), raw=raw)

        # Build output context
        output_context = {
            "timestamp": datetime.now().isoformat(),
            "search_query": context.get("request_payload", ""),
            "offset": context.get("start", 0),
            "max_results": len(normalized_auctions),
            "total_fetched": len(normalized_auctions),
            "auctions": [auction.__dict__ for auction in normalized_auctions],
            "raw_response": response,  # Include raw for debugging
        }

        # Ensure output directory
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            json.dump(output_context, f, indent=2)

        logger.info(
            "Auctions saved successfully",
            count=len(normalized_auctions),
            path=str(output_path),
        )

    except httpx.HTTPStatusError as e:
        logger.error("HTTP error during fetch", status=e.response.status_code, detail=e.response.text)
        raise
    except KeyError as e:
        logger.error("Parsing error in response", error=str(e), response=response)
        raise
    except Exception as e:
        logger.error("Unexpected error during fetch and save", error=str(e))
        raise


async def main() -> None:
    parser = argparse.ArgumentParser(description="Collect Madden 26 auction data via EA API")
    parser.add_argument(
        "--search", type=str, default="", help="Search query for auctions (e.g., player name)"
    )
    parser.add_argument("--max", type=int, default=100, help="Maximum number of results to fetch")
    parser.add_argument("--offset", type=int, default=0, help="Starting offset for pagination")
    parser.add_argument(
        "--output",
        type=str,
        default="auction_data/auctions.json",
        help="Output JSON file path",
    )
    args = parser.parse_args()

    # Validate args
    if args.max <= 0:
        logger.error("Invalid max value", value=args.max)
        sys.exit(1)
    if args.offset < 0:
        logger.error("Invalid offset value", value=args.offset)
        sys.exit(1)

    # Setup project path
    project_root = os.path.dirname(os.path.abspath(__file__))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    settings = get_settings()
    logger.info("Starting auction collection", search=args.search, max=args.max, offset=args.offset)

    try:
        # Initialize components
        token_path = Path(settings.tokens_path)
        if not token_path.is_absolute():
            token_path = Path(project_root) / token_path
        token_manager = TokenManager.from_file(token_path)
        session_manager = SessionManager(token_manager)
        await session_manager.ensure_backups()  # Ensure session tickets are ready

        collector = AuctionCollector()
        output_path = Path(args.output)

        context = build_context(args.search, args.offset, args.max, settings)
        await fetch_and_save_auctions(collector, context, output_path)

    except FileNotFoundError as e:
        logger.error("Missing required file", file=str(e))
        sys.exit(1)
    except httpx.RequestError as e:
        logger.error("Network error", error=str(e))
        sys.exit(1)
    except Exception as e:
        logger.error("Pipeline failed", error=str(e))
        sys.exit(1)

    logger.info("Auction collection completed")


if __name__ == "__main__":
    asyncio.run(main())