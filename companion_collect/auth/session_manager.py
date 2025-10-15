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
import ssl
import asyncio
import httpx
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Any
from pathlib import Path

from .token_manager import TokenManager
from companion_collect.config import get_settings
from companion_collect.logging import get_logger

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
        self._logger = get_logger(__name__).bind(component="session_manager")
    
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
            self._logger.warning(
                "primary_ticket_failed",
                failed_count=self._primary_ticket.failed_count,
            )
            
            if not self._primary_ticket.is_healthy:
                self._logger.warning("primary_ticket_unhealthy")
                await self._promote_or_generate_primary()
        
        # Also check backups
        backup_list = list(self._backup_tickets)
        for backup in backup_list:
            if backup.ticket == ticket:
                backup.failed_count += 1
                if not backup.is_healthy:
                    self._logger.warning("backup_removed", reason="unhealthy")
                    self._backup_tickets.remove(backup)
                break
    
    async def ensure_backups(self) -> None:
        """Ensure backup ticket pool is full."""
        needed = self.max_backups - len(self._backup_tickets)
        
        if needed <= 0:
            return
        
        self._logger.info("ensure_backups_start", count=needed)
        
        for i in range(needed):
            try:
                # Respect rate limits with cooldown
                await self._wait_for_generation_cooldown()
                
                ticket_data = await self._generate_ticket()
                self._backup_tickets.append(ticket_data)
                self._logger.info(
                    "backup_generated",
                    index=i + 1,
                    total=needed,
                )
                
            except Exception as e:
                self._logger.warning(
                    "backup_generation_failed",
                    index=i + 1,
                    error=str(e),
                )
                break  # Stop trying if we hit errors
    
    async def _promote_or_generate_primary(self) -> None:
        """Promote a backup to primary or generate new primary."""
        async with self._generation_lock:
            # Try to promote a healthy backup
            while self._backup_tickets:
                backup = self._backup_tickets.pop(0)
                if backup.is_healthy:
                    self._primary_ticket = backup
                    self._logger.info("promoted_backup_to_primary")
                    return
            
            # No healthy backups, generate new primary
            self._logger.info("generating_new_primary")
            await self._wait_for_generation_cooldown()
            
            try:
                self._primary_ticket = await self._generate_ticket()
                self._logger.info("primary_ticket_generated")
            except Exception as e:
                raise RuntimeError("Failed to generate primary session ticket: {}".format(e))
    
    async def _generate_ticket(self) -> SessionTicket:
        """Generate a fresh session ticket from JWT.
        """
        from companion_collect.madden import get_identifiers
        # Get valid JWT from token manager
        jwt_token = await self.token_manager.get_valid_jwt()

        # Load settings for dynamic product channel header and product name
        settings = get_settings()

        # Determine which year to use for WAL (allow override)
        madden_year = settings.wal_madden_year or settings.madden_year

        # Get WAL identifiers (skip intermediate varialbes)
        identifiers = get_identifiers(madden_year, settings.madden_platform)
        wal_blaze_header = settings.wal_blaze_id or identifiers.blaze_header
        wal_product_name = settings.wal_product_name or identifiers.product_name

        # If were overriding from entitlement-derived year, log that shit
        if settings.wal_madden_year and settings.wal_madden_year != settings.madden_year:
            self._logger.info(
                "wal_year_override",
                wal_year=settings.wal_madden_year,
                default_year=settings.madden_year,
            )

        # Read optional cookie from session context (skip entitlement validation)
        session_cookie: Optional[str] = None
        try:
            ctx_path = Path(settings.session_context_path)
            if ctx_path.exists():
                with ctx_path.open("r", encoding="utf-8") as f:
                    ctx = json.load(f)
                cookie_val = ctx.get("Cookie") or ctx.get("ak_bmsc_cookie")
                if isinstance(cookie_val, str) and cookie_val.strip():
                    session_cookie = cookie_val.strip()
        except Exception as e:
            self._logger.warning("session_cookie_read_failed", error=str(e))
        
        # Match snallabot's permissive TLS configuartion
        ssl_context = ssl.create_default_context()
        # allow legacy renegotiation (like undici's SSL_OP_LEGACY_SERVER_CONNECT)
        ssl_context.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
        # Mirror rejectUnauthorized:false
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        # Prepare WAL payload
        payload: dict[str, Any] = {
            "accessToken": jwt_token,
            "productName": wal_product_name,
        }
        self._logger.info(
            "wal_login_start",
            blaze_id=wal_blaze_header,
            product=wal_product_name,
        )
        # Call WAL login endpoint to generate session ticket
        async with httpx.AsyncClient(timeout=30.0, verify=ssl_context) as client:
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
            try:
                response = await client.post(
                    WAL_LOGIN_ENDPOINT,
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                self._logger.error(
                    "wal_login_failed",
                    status=e.response.status_code,
                    response=e.response.text[:1000],
                )
                raise
            data = response.json()

            # Validate response structure
            if "userLoginInfo" not in data:
                snippet = json.dumps(data, indent=2)[:500]
                self._logger.error("wal_login_missing_user_info", snippet=snippet)
                raise RuntimeError(f"WAL login missing userLoginInfo: {snippet}")
            user_login_info = data["userLoginInfo"]
            self._last_generation_time = datetime.now(timezone.utc)
            self._logger.info(
                "wal_login_success",
                blaze_id=user_login_info.get("blazeId"),
            )

            context_path = Path(settings.session_context_path)
            context_path.parent.mkdir(parents=True, exist_ok=True)

            existing_context: dict[str, Any] = {}
            if context_path.exists():
                try:
                    with context_path.open(encoding="utf-8") as handle:
                        existing_context = json.load(handle)
                except Exception as exc:  # pragma: no cover - best effort
                    self._logger.warning(
                        "session_context_preserve_failed",
                        error=str(exc),
                    )
                    existing_context = {}

            persona_details = user_login_info.get("personaDetails", {})
            updated_context = dict(existing_context)
            updated_context.update(
                {
                    "session_ticket": user_login_info["sessionKey"],
                    "persona_id": str(user_login_info["blazeId"]),
                    "personaId": str(user_login_info["blazeId"]),
                    "persona_display_name": persona_details.get("displayName", ""),
                }
            )
            if session_cookie:
                updated_context.setdefault("ak_bmsc_cookie", session_cookie)

            with context_path.open("w", encoding="utf-8") as handle:
                json.dump(updated_context, handle, indent=2)
        
        return SessionTicket(
            ticket=user_login_info["sessionKey"],
            blaze_id=user_login_info["blazeId"],
            display_name=user_login_info.get("personaDetails", {}).get("displayName", ""),
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
