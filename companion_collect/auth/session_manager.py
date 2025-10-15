"""Session ticket management with automatic generation and failover.

This module manages the pool of session tickets used for API calls. Session tickets
are generated from JWT tokens and are REUSABLE (not single-use as initially thought).

Key Features:
- Maintains 2-3 reusable session tickets
- Automatic generation with rate limit respect
- Failover to backup tickets on errors
- Integration with TokenManager for JWT lifecycle

Architecture:
    SessionManager
        ├── get_session_ticket() → Returns active session ticket
        ├── mark_failed() → Handle failed ticket, switch to backup
        ├── ensure_backups() → Maintain backup ticket pool
        └── generate_ticket() → Create new session ticket from JWT

Discovery: Session tickets are REUSABLE!
- Can use same ticket for multiple API calls
- Not consumed after first use (contrary to initial assumption)
- Rate limited generation: ~3 tickets per short time period
- Simple architecture: 2-3 tickets is plenty

Usage:
    ```python
    token_mgr = TokenManager.from_file("tokens.json")
    session_mgr = SessionManager(token_mgr)
    
    # Get ticket for API call (reusable!)
    ticket = await session_mgr.get_session_ticket()
    
    # If API call fails, mark it and get backup
    if api_failed:
        await session_mgr.mark_failed(ticket)
        ticket = await session_mgr.get_session_ticket()
    ```
"""

from __future__ import annotations

import asyncio
import httpx
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Any
from pathlib import Path

from .token_manager import TokenManager
from companion_collect.config import get_settings
from ea_constants import ENTITLEMENT_TO_VALID_NAMESPACE, VALID_ENTITLEMENTS


# WAL authentication endpoint for generating session tickets
WAL_LOGIN_ENDPOINT = "https://wal2.tools.gos.bio-iad.ea.com/wal/authentication/login"

# Rate limiting configuration
GENERATION_COOLDOWN_SECONDS = 10  # Wait between generations to respect rate limits
MAX_BACKUP_TICKETS = 2  # Keep 2 backup tickets (3 total with primary)


@dataclass
class SessionTicket:
    """Container for session ticket data."""
    
    ticket: str
    blaze_id: int
    display_name: str
    generated_at: datetime
    failed_count: int = 0
    
    @property
    def is_healthy(self) -> bool:
        """Check if ticket has not failed too many times."""
        return self.failed_count < 3


class SessionManager:
    """Manages session ticket pool with automatic generation and failover."""
    
    def __init__(
        self,
        token_manager: TokenManager,
        max_backups: int = MAX_BACKUP_TICKETS
    ):
        """Initialize session manager.
        
        Args:
            token_manager: TokenManager for getting valid JWTs
            max_backups: Maximum number of backup tickets to maintain
        """
        self.token_manager = token_manager
        self.max_backups = max_backups
        self._primary_ticket: Optional[SessionTicket] = None
        self._backup_tickets: list[SessionTicket] = []
        self._generation_lock = asyncio.Lock()
        self._last_generation_time: Optional[datetime] = None
    
    async def get_session_ticket(self) -> str:
        """Get current active session ticket.
        
        Returns the primary ticket, generating one if needed. Since tickets
        are reusable, this ticket can be used for multiple API calls.
        
        Returns:
            Session ticket string for API calls
            
        Raises:
            RuntimeError: If unable to generate any tickets
        """
        if self._primary_ticket is None or not self._primary_ticket.is_healthy:
            await self._promote_or_generate_primary()
        
        if self._primary_ticket is None:
            raise RuntimeError("Failed to acquire session ticket")

        return self._primary_ticket.ticket
    
    async def mark_failed(self, ticket: str) -> None:
        """Mark a session ticket as failed."""
        # Find and mark the failed ticket
        if self._primary_ticket and self._primary_ticket.ticket == ticket:
            self._primary_ticket.failed_count += 1
            print("Primary ticket failed (count: {})".format(self._primary_ticket.failed_count))
            
            if not self._primary_ticket.is_healthy:
                print("Primary ticket unhealthy, promoting backup...")
                await self._promote_or_generate_primary()
        
        # Also check backups
        backup_list = list(self._backup_tickets)
        for backup in backup_list:
            if backup.ticket == ticket:
                backup.failed_count += 1
                if not backup.is_healthy:
                    print("Removing unhealthy backup ticket")
                    self._backup_tickets.remove(backup)
                break
    
    async def ensure_backups(self) -> None:
        """Ensure backup ticket pool is full."""
        needed = self.max_backups - len(self._backup_tickets)
        
        if needed <= 0:
            return
        
        print("Generating {} backup session ticket(s)...".format(needed))
        
        for i in range(needed):
            try:
                # Respect rate limits with cooldown
                await self._wait_for_generation_cooldown()
                
                ticket_data = await self._generate_ticket()
                self._backup_tickets.append(ticket_data)
                
                print("   Backup {}/{} generated: {}...".format(i+1, needed, ticket_data.ticket[:50]))
                
            except Exception as e:
                print("   Failed to generate backup {}: {}".format(i+1, e))
                break  # Stop trying if we hit errors
    
    async def _promote_or_generate_primary(self) -> None:
        """Promote a backup to primary or generate new primary."""
        async with self._generation_lock:
            # Try to promote a healthy backup
            while self._backup_tickets:
                backup = self._backup_tickets.pop(0)
                if backup.is_healthy:
                    self._primary_ticket = backup
                    print("Promoted backup to primary: {}...".format(backup.ticket[:50]))
                    return
            
            # No healthy backups, generate new primary
            print("No healthy backups, generating new primary ticket...")
            await self._wait_for_generation_cooldown()
            
            try:
                self._primary_ticket = await self._generate_ticket()
                print("New primary ticket generated: {}...".format(self._primary_ticket.ticket[:50]))
            except Exception as e:
                raise RuntimeError("Failed to generate primary session ticket: {}".format(e))
    
    async def _generate_ticket(self) -> SessionTicket:
        """Generate a fresh session ticket from JWT.
        
        Returns:
            SessionTicket data
            
        Raises:
            httpx.HTTPError: If generation fails
        """
        from companion_collect.madden import get_identifiers
        # Get valid JWT from token manager
        jwt_token = await self.token_manager.get_valid_jwt()

        # Load settings for dynamic product channel header and product name
        settings = get_settings()

        # Determine which year to use for WAL (allow override)
        madden_year = settings.wal_madden_year or settings.madden_year

        identifiers = get_identifiers(madden_year, settings.madden_platform)
        blaze_header = identifiers.blaze_header
        product_name = identifiers.product_name

        # If were overriding from entitlement-derived year, log that shit
        if settings.wal_madden_year and settings.wal_madden_year != settings.madden_year:
            print(f"WAL year override active: using {settings.wal_madden_year} instead of {settings.madden_year}")
        wal_blaze_header = settings.wal_blaze_id or blaze_header
        wal_product_name = settings.wal_product_name or product_name

        # Read numeric persona ID from session context (prefers persona_id key, falls back to blaze_id)
        persona_id: Optional[int] = None
        session_cookie: Optional[str] = None
        try:
            ctx_path = Path(settings.session_context_path)
            if ctx_path.exists():
                with ctx_path.open("r", encoding="utf-8") as f:
                    ctx = json.load(f)

                platform_key = str(settings.madden_platform or "").lower()
                expected_entitlement = VALID_ENTITLEMENTS.get(platform_key)
                if expected_entitlement:
                    ctx_entitlement = ctx.get("madden_entitlement")
                    if ctx_entitlement and ctx_entitlement != expected_entitlement:
                        raise RuntimeError(
                            "Session context Madden entitlement does not match configured platform. "
                            f"Expected '{expected_entitlement}', found '{ctx_entitlement}'."
                        )
                    expected_namespace = ENTITLEMENT_TO_VALID_NAMESPACE.get(expected_entitlement)
                    ctx_namespace = ctx.get("persona_namespace")
                    if expected_namespace and ctx_namespace and ctx_namespace != expected_namespace:
                        selection_reason = ctx.get("persona_selection_reason") or "unspecified"
                        print(
                            "Warning: session context persona namespace does not match Madden entitlement namespace. "
                            f"Expected '{expected_namespace}', found '{ctx_namespace}'. "
                            f"Continuing with stored persona (reason: {selection_reason})."
                        )

                cookie_val = ctx.get("Cookie") or ctx.get("ak_bmsc_cookie")
                if isinstance(cookie_val, str) and cookie_val.strip():
                    session_cookie = cookie_val.strip()

                for key in ("persona_id", "personaId", "blaze_persona_id"):
                    raw_val = ctx.get(key)
                    if raw_val is None:
                        continue
                    raw_str = str(raw_val).strip()
                    if raw_str.isdigit():
                        persona_id = int(raw_str)
                        break

                if persona_id is None:
                    raw_blaze = str(ctx.get("blaze_id", "")).strip()
                    if raw_blaze.isdigit():
                        persona_id = int(raw_blaze)
        except Exception as e:
            print(f"Warning: failed reading session context persona id: {e}")

        # Prepare WAL login URL and payload; keep X-BLAZE-ID header as product channel string
        login_url = WAL_LOGIN_ENDPOINT

        # Log both identifiers just before calling WAL
        print(
            "WAL login using X-BLAZE-ID header: {} (product: {}), numeric persona/blaze ID: {}".format(
                wal_blaze_header,
                wal_product_name,
                persona_id,
            )
        )

        payload: dict[str, Any] = {
            "accessToken": jwt_token,
            "productName": wal_product_name,
        }
        import ssl
        import httpx
        ssl_context = ssl.create_default_context()
        # Match snallabot's permissive TLS configuartion
        # allow legacy renegotiation (like undici's SSL_OP_LEGACY_SERVER_CONNECT)
        ssl_context.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)

        # Mirror rejectUnauthorized: false        
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        # Python doesn't have SSL_OP_LEGACY_SERVER_CONNECT equivalent,
        # but disabling verification should be enough
    
        # Call WAL login endpoint to generate session ticket
        async with httpx.AsyncClient(timeout=30.0, verify=ssl_context) as client:
            try:
                headers = {
                    "Accept-Charset": "UTF-8",
                    "Accept": "application/json",
                    "X-BLAZE-ID": wal_blaze_header,
                    "X-BLAZE-VOID-RESP": "XML",
                    "X-Application-Key": "MADDEN-MCA",
                    "Content-Type": "application/json",
                    "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 13; Android SDK built for x86_64 Build/TE1A.220922.034)",
                    "Accept-Encoding": "gzip, deflate, br, zstd",
                    "Connection": "keep-alive",
                }
                if session_cookie:
                    headers["Cookie"] = session_cookie

                response = await client.post(
                    login_url,
                    json=payload,
                    headers=headers,
                )
                print("WAL login request sent:")
                print("URL:", response.request.url)
                print("Headers:", dict(response.request.headers))
                print("Payload:", payload)
                try:
                    Path("auction_data").mkdir(parents=True, exist_ok=True)
                    with Path("auction_data/wal_login_request.json").open("w", encoding="utf-8") as f:
                        json.dump(
                            {
                                "url": str(response.request.url),
                                "headers": dict(response.request.headers),
                                "payload": payload,
                            },
                            f,
                            indent=2,
                        )
                except Exception:
                    pass
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                # Print request/response details for diagnosis (e.g., 404)
                req = e.request
                resp = e.response
                try:
                    print("WAL login request:", req.method, str(req.url))
                    try:
                        # Cast Headers to dict for printing; may include bytes/strings
                        print("Request headers:", dict(req.headers))
                    except Exception:
                        pass
                    try:
                        print("Request body:", (req.content.decode("utf-8", "ignore") if req.content else "")[:2000])
                    except Exception:
                        pass
                except Exception:
                    pass
                try:
                    print("WAL login response status:", resp.status_code if resp else "N/A")
                    print("WAL login response body:", (resp.text if resp is not None else "")[:4000])
                except Exception:
                    pass
                # Re-raise to preserve original behavior
                raise

            data = response.json()
        
        # Check for userLoginInfo
        if "userLoginInfo" not in data:
            print("WAL login returned error payload:")
            try:
                print(json.dumps(data, indent=2))
            except Exception:
                print(str(data))
            try:
                Path("auction_data").mkdir(parents=True, exist_ok=True)
                with Path("auction_data/wal_login_response.json").open("w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            except Exception:
                pass
            raise RuntimeError(f"Session generation failed. Response: {json.dumps(data, indent=2)[:500]}")
        
        # Extract session ticket info
        user_login_info = data["userLoginInfo"]
        
        # Update last generation time for rate limiting
        self._last_generation_time = datetime.now(timezone.utc)

        session_key_preview = user_login_info["sessionKey"][:6]
        print(
            "WAL login succeeded: blazeHeader={}, sessionKeyPrefix={}..., blazeId={}".format(
                wal_blaze_header,
                session_key_preview,
                user_login_info["blazeId"],
            )
        )
        
        return SessionTicket(
            ticket=user_login_info["sessionKey"],
            blaze_id=user_login_info["blazeId"],
            display_name=user_login_info["personaDetails"]["displayName"],
            generated_at=self._last_generation_time,
        )
    
    async def _wait_for_generation_cooldown(self) -> None:
        """Wait if we're in generation cooldown period."""
        if self._last_generation_time is None:
            return
        
        now = datetime.now(timezone.utc)
        time_since_last = (now - self._last_generation_time).total_seconds()
        
        if time_since_last < GENERATION_COOLDOWN_SECONDS:
            wait_time = GENERATION_COOLDOWN_SECONDS - time_since_last
            print("Waiting {:.1f}s for generation cooldown...".format(wait_time))
            await asyncio.sleep(wait_time)
    
    async def create_session_ticket(
        self,
        *,
        auth_code: Optional[str] = None,
        auth_data: Optional[str] = None,
        auth_type: Optional[int] = None,
        promote_primary: bool = True,
    ) -> str:
        """Generate a fresh session ticket on demand.

        The ``auth_*`` parameters are accepted for forward compatibility with
        call sites that pass through auth bundle metadata from the pool. The
        WAL login flow does not currently require these fields, so they are
        ignored for now.

        Args:
            auth_code: Optional message auth code (unused).
            auth_data: Optional message auth payload (unused).
            auth_type: Optional auth type (unused).
            promote_primary: When true, replace the current primary ticket with
                the newly created one. When false, append the ticket to the
                backup pool (respecting the configured maximum).

        Returns:
            Newly created session ticket string.
        """

        async with self._generation_lock:
            await self._wait_for_generation_cooldown()
            ticket_data = await self._generate_ticket()

            if promote_primary:
                self._primary_ticket = ticket_data
            else:
                self._backup_tickets.append(ticket_data)
                if len(self._backup_tickets) > self.max_backups:
                    self._backup_tickets = self._backup_tickets[-self.max_backups :]

        return ticket_data.ticket

    def get_status(self) -> dict:
        """Get current session manager status.
        
        Returns:
            Dict with pool status and health information
        """
        return {
            "primary_ticket": {
                "ticket": self._primary_ticket.ticket[:50] + "..." if self._primary_ticket else None,
                "blaze_id": self._primary_ticket.blaze_id if self._primary_ticket else None,
                "display_name": self._primary_ticket.display_name if self._primary_ticket else None,
                "failed_count": self._primary_ticket.failed_count if self._primary_ticket else 0,
                "is_healthy": self._primary_ticket.is_healthy if self._primary_ticket else False,
            } if self._primary_ticket else None,
            "backup_count": len(self._backup_tickets),
            "backup_tickets": [
                {
                    "ticket": b.ticket[:50] + "...",
                    "failed_count": b.failed_count,
                    "is_healthy": b.is_healthy,
                }
                for b in self._backup_tickets
            ],
            "last_generation": self._last_generation_time.isoformat() if self._last_generation_time else None,
        }
