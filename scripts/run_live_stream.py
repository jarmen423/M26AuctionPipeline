"""High-speed live auction streaming with auth pool rotation.

This script continuously polls the EA Companion API for auction data as fast
as possible while using auth pool rotation to avoid rate limiting.

Features:
- Minimal latency between requests
- Automatic auth pool rotation (259 bundles)
- Error handling with exponential backoff
- Live statistics and progress reporting
- Optional output to JSON files
- Graceful shutdown on Ctrl+C

Usage:
    python scripts/run_live_stream.py
    python scripts/run_live_stream.py --interval 2.0
    python scripts/run_live_stream.py --output-dir ./auction_data
    python scripts/run_live_stream.py --max-iterations 100
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any

from companion_collect.auth.auth_pool_manager import AuthPoolManager
from companion_collect.collectors.auctions import AuctionCollector
from companion_collect.config import get_settings
from companion_collect.logging import get_logger

logger = get_logger(__name__)


def load_session_context() -> dict[str, Any]:
    """Load session context from current session context file.
    
    Returns:
        Dict with session_ticket, user_agent, blaze_id, ak_bmsc_cookie
    """
    # Try current_session_context.json first (fresher), fallback to working bundle
    session_paths = [
        Path.cwd() / "research" / "captures" / "current_session_context.json",
        Path.cwd() / "research" / "captures" / "working_request_bundle.json",
    ]
    
    for bundle_path in session_paths:
        if bundle_path.exists():
            with open(bundle_path) as f:
                data = json.load(f)
            
            # Handle both formats
            if "headers" in data:
                # working_request_bundle.json format
                return {
                    "session_ticket": data["session_ticket"],
                    "user_agent": data["headers"]["User-Agent"],
                    "blaze_id": data["headers"]["X-BLAZE-ID"],
                    "ak_bmsc_cookie": data["headers"]["Cookie"],
                }
            else:
                # current_session_context.json format (already flat)
                # Normalize cookie key name
                result = dict(data)
                if "Cookie" in result and "ak_bmsc_cookie" not in result:
                    result["ak_bmsc_cookie"] = result["Cookie"]
                return result
    
    raise FileNotFoundError(
        "No session context file found. Tried:\n" +
        "\n".join(f"  - {p}" for p in session_paths) +
        "\nThese files contain the session ticket and other context needed for API requests."
    )


class StreamStats:
    """Track streaming statistics."""

    def __init__(self) -> None:
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.total_auctions = 0
        self.start_time = monotonic()
        self.last_success_time: float | None = None

    def record_success(self, auction_count: int) -> None:
        """Record successful request."""
        self.total_requests += 1
        self.successful_requests += 1
        self.total_auctions += auction_count
        self.last_success_time = monotonic()

    def record_failure(self) -> None:
        """Record failed request."""
        self.total_requests += 1
        self.failed_requests += 1

    def get_uptime(self) -> float:
        """Get uptime in seconds."""
        return monotonic() - self.start_time

    def get_success_rate(self) -> float:
        """Get success rate as percentage."""
        if self.total_requests == 0:
            return 0.0
        return (self.successful_requests / self.total_requests) * 100

    def get_avg_auctions_per_request(self) -> float:
        """Get average auctions per successful request."""
        if self.successful_requests == 0:
            return 0.0
        return self.total_auctions / self.successful_requests

    def get_requests_per_second(self) -> float:
        """Get requests per second."""
        uptime = self.get_uptime()
        if uptime == 0:
            return 0.0
        return self.total_requests / uptime


class AuctionStreamer:
    """High-speed auction streaming with auth pool rotation."""

    def __init__(
        self,
        *,
        interval: float = 0.5,
        output_dir: Path | None = None,
        max_iterations: int | None = None,
    ) -> None:
        """Initialize streamer.

        Args:
            interval: Minimum seconds between requests (default: 0.5 for high speed)
            output_dir: Optional directory to save auction data JSON files
            max_iterations: Optional maximum number of requests before stopping
        """
        self.interval = interval
        self.output_dir = output_dir
        self.max_iterations = max_iterations
        self.stats = StreamStats()
        self._logger = logger.bind(component="auction_streamer")
        self._shutdown = asyncio.Event()
        self._all_responses = []  # Store all responses for single file output

        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            self._logger.info("output_dir_created", path=str(output_dir))

    def _extract_auctions(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract auction list from API response."""
        try:
            return response.get("responseInfo", {}).get("value", {}).get("details", [])
        except (KeyError, AttributeError, TypeError):
            return []

    def _save_response(self, response: dict[str, Any], iteration: int) -> None:
        """Save response to accumulated list for batch output."""
        if not self.output_dir:
            return

        # Add to accumulated responses with metadata
        self._all_responses.append({
            "iteration": iteration,
            "timestamp": datetime.now().isoformat(),
            "response": response
        })
        
        self._logger.debug("response_accumulated", iteration=iteration, total=len(self._all_responses))

    def _save_all_responses(self) -> None:
        """Save all accumulated responses to a single JSON file."""
        if not self.output_dir or not self._all_responses:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"all_auctions_{timestamp}.json"
        filepath = self.output_dir / filename

        try:
            with open(filepath, "w") as f:
                json.dump(self._all_responses, f, indent=2)
            self._logger.info("all_responses_saved", file=str(filepath), count=len(self._all_responses))
            print(f"\n💾 Saved {len(self._all_responses)} responses to: {filepath}")
        except Exception as e:
            self._logger.error("save_failed", error=str(e), file=str(filepath))

    def _print_stats(self) -> None:
        """Print current statistics to console."""
        uptime = self.stats.get_uptime()
        print(
            f"\r[{uptime:>7.1f}s] "
            f"Requests: {self.stats.total_requests} "
            f"({self.stats.successful_requests} ✓ / {self.stats.failed_requests} ✗) | "
            f"Success Rate: {self.stats.get_success_rate():.1f}% | "
            f"Auctions: {self.stats.total_auctions} "
            f"(avg: {self.stats.get_avg_auctions_per_request():.1f}/req) | "
            f"Speed: {self.stats.get_requests_per_second():.2f} req/s",
            end="",
            flush=True,
        )

    async def stream(self) -> None:
        """Run continuous streaming loop."""
        settings = get_settings()
        auth_pool = AuthPoolManager.from_default_path()
        
        # Load session context (session_ticket, user_agent, etc.)
        try:
            session_context = load_session_context()
            self._logger.info(
                "session_context_loaded",
                session_ticket=session_context["session_ticket"][:20] + "...",
            )
        except FileNotFoundError as e:
            self._logger.error("session_context_load_failed", error=str(e))
            print(f"\n❌ ERROR: {e}\n")
            return

        self._logger.info(
            "streamer_starting",
            interval=self.interval,
            auth_pool_size=auth_pool.pool_size(),
            max_iterations=self.max_iterations,
            output_dir=str(self.output_dir) if self.output_dir else None,
        )

        print("\n" + "=" * 80)
        print("🚀 HIGH-SPEED AUCTION STREAMER")
        print("=" * 80)
        print(f"Poll interval: {self.interval}s")
        print(f"Auth pool size: {auth_pool.pool_size()} bundles")
        print(f"Max iterations: {self.max_iterations or 'unlimited'}")
        print(f"Output directory: {self.output_dir or 'none (no file saving)'}")
        print("=" * 80)
        print("Press Ctrl+C to stop gracefully\n")

        collector = AuctionCollector(settings=settings, auth_pool=auth_pool)

        consecutive_failures = 0
        max_consecutive_failures = 5
        backoff_delay = self.interval

        async with collector.lifecycle():
            iteration = 0

            try:
                while not self._shutdown.is_set():
                    # Check max iterations
                    if self.max_iterations and iteration >= self.max_iterations:
                        self._logger.info("max_iterations_reached", iterations=iteration)
                        break

                    iteration += 1
                    request_start = monotonic()

                    try:
                        # Fetch auction data with session context
                        response = await collector.fetch_once(context=session_context)
                        auctions = self._extract_auctions(response)
                        auction_count = len(auctions)

                        # Record success
                        self.stats.record_success(auction_count)
                        consecutive_failures = 0
                        backoff_delay = self.interval

                        # Save response if configured
                        self._save_response(response, iteration)

                        # Log success
                        self._logger.info(
                            "fetch_success",
                            iteration=iteration,
                            auction_count=auction_count,
                            auth_pool_index=auth_pool._index,
                        )
                    except Exception as e:
                        # Record failure
                        self.stats.record_failure()
                        consecutive_failures += 1

                        self._logger.error(
                            "fetch_failed",
                            iteration=iteration,
                            error=str(e),
                            consecutive_failures=consecutive_failures,
                        )

                        # Check if we should stop due to repeated failures
                        if consecutive_failures >= max_consecutive_failures:
                            self._logger.error(
                                "max_failures_reached",
                                consecutive_failures=consecutive_failures,
                                stopping=True,
                            )
                            print(
                                f"\n\n❌ Too many consecutive failures ({consecutive_failures}). Stopping.\n"
                            )
                            break

                        # Exponential backoff
                        backoff_delay = min(backoff_delay * 2, 60.0)
                        self._logger.warning("applying_backoff", delay=backoff_delay)

                    # Print stats
                    self._print_stats()

                    # Calculate sleep time to maintain interval
                    request_duration = monotonic() - request_start
                    sleep_time = max(0, backoff_delay - request_duration)

                    if sleep_time > 0:
                        try:
                            await asyncio.wait_for(
                                self._shutdown.wait(), timeout=sleep_time
                            )
                            # If we get here, shutdown was triggered
                            break
                        except asyncio.TimeoutError:
                            # Normal case - sleep time elapsed
                            pass
            finally:
                # Always save responses even if interrupted
                self._save_all_responses()

        # Final stats
        print("\n\n" + "=" * 80)
        print("📊 FINAL STATISTICS")
        print("=" * 80)
        print(f"Total uptime: {self.stats.get_uptime():.1f} seconds")
        print(f"Total requests: {self.stats.total_requests}")
        print(f"Successful: {self.stats.successful_requests}")
        print(f"Failed: {self.stats.failed_requests}")
        print(f"Success rate: {self.stats.get_success_rate():.1f}%")
        print(f"Total auctions collected: {self.stats.total_auctions}")
        print(f"Average auctions/request: {self.stats.get_avg_auctions_per_request():.1f}")
        print(f"Average speed: {self.stats.get_requests_per_second():.2f} requests/second")
        print("=" * 80 + "\n")

        self._logger.info(
            "streamer_stopped",
            uptime=self.stats.get_uptime(),
            total_requests=self.stats.total_requests,
            success_rate=self.stats.get_success_rate(),
            total_auctions=self.stats.total_auctions,
        )

    def shutdown(self) -> None:
        """Signal graceful shutdown."""
        self._shutdown.set()


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="High-speed auction streaming with auth pool rotation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Maximum speed (0.5 second interval)
  python scripts/run_live_stream.py

  # Slower polling (2 seconds)
  python scripts/run_live_stream.py --interval 2.0

  # Save responses to files
  python scripts/run_live_stream.py --output-dir ./auction_data

  # Run for 100 iterations then stop
  python scripts/run_live_stream.py --max-iterations 100

  # Combine options
  python scripts/run_live_stream.py --interval 1.0 --output-dir ./data --max-iterations 50
        """,
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=0.5,
        help="Minimum seconds between requests (default: 0.5 for high speed)",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to save auction JSON files (default: no file saving)",
    )

    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Maximum number of requests before stopping (default: unlimited)",
    )

    return parser.parse_args()


async def main() -> None:
    """Main entry point."""
    args = parse_args()

    streamer = AuctionStreamer(
        interval=args.interval,
        output_dir=args.output_dir,
        max_iterations=args.max_iterations,
    )

    # Setup signal handlers for graceful shutdown
    def signal_handler() -> None:
        print("\n\n⚠️  Shutdown signal received. Stopping gracefully...\n")
        streamer.shutdown()

    # Register signal handlers
    try:
        import signal

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)
    except (ImportError, NotImplementedError):
        # Windows doesn't support add_signal_handler
        # Ctrl+C will still work through KeyboardInterrupt
        pass

    try:
        await streamer.stream()
    except KeyboardInterrupt:
        print("\n\n⚠️  Keyboard interrupt received. Stopping gracefully...\n")
        streamer.shutdown()
        await asyncio.sleep(0.5)  # Give time for cleanup


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!\n")
        sys.exit(0)
        sys.exit(0)
