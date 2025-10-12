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
from typing import Optional

from .token_manager import TokenManager


# WAL authentication endpoint for generating session tickets
WAL_LOGIN_ENDPOINT = "https://wal2.tools.gos.bio-iad.ea.com/wal/authentication/login"
PRODUCT_NAME = "madden-2025-xbsx-mca"

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
        
        return self._primary_ticket.ticket
    
    async def mark_failed(self, ticket: str) -> None:
        """Mark a session ticket as failed.
        
        Increments the failure count and promotes a backup ticket if the
        primary ticket has failed. Generates new primary if no backups available.
        
        Args:
            ticket: The session ticket that failed
        """
        # Find and mark the failed ticket
        if self._primary_ticket and self._primary_ticket.ticket == ticket:
            self._primary_ticket.failed_count += 1
            print(f"⚠️  Primary ticket failed (count: {self._primary_ticket.failed_count})")
            
            if not self._primary_ticket.is_healthy:
                print("❌ Primary ticket unhealthy, promoting backup...")
                await self._promote_or_generate_primary()
        
        # Also check backups
        for backup in self._backup_tickets:
            if backup.ticket == ticket:
                backup.failed_count += 1
                if not backup.is_healthy:
                    print(f"❌ Removing unhealthy backup ticket")
                    self._backup_tickets.remove(backup)
                break
    
    async def ensure_backups(self) -> None:
        """Ensure backup ticket pool is full.
        
        Generates backup tickets up to max_backups limit. Respects rate
        limiting by adding cooldown delays between generations.
        
        This should be called periodically (not per-request) to maintain
        a healthy backup pool.
        """
        needed = self.max_backups - len(self._backup_tickets)
        
        if needed <= 0:
            return
        
        print(f"🔄 Generating {needed} backup session ticket(s)...")
        
        for i in range(needed):
            try:
                # Respect rate limits with cooldown
                await self._wait_for_generation_cooldown()
                
                ticket_data = await self._generate_ticket()
                self._backup_tickets.append(ticket_data)
                
                print(f"   ✅ Backup {i+1}/{needed} generated: {ticket_data.ticket[:50]}...")
                
            except Exception as e:
                print(f"   ❌ Failed to generate backup {i+1}: {e}")
                break  # Stop trying if we hit errors
    
    async def _promote_or_generate_primary(self) -> None:
        """Promote a backup to primary or generate new primary."""
        async with self._generation_lock:
            # Try to promote a healthy backup
            while self._backup_tickets:
                backup = self._backup_tickets.pop(0)
                if backup.is_healthy:
                    self._primary_ticket = backup
                    print(f"✅ Promoted backup to primary: {backup.ticket[:50]}...")
                    return
            
            # No healthy backups, generate new primary
            print("🔄 No healthy backups, generating new primary ticket...")
            await self._wait_for_generation_cooldown()
            
            try:
                self._primary_ticket = await self._generate_ticket()
                print(f"✅ New primary ticket generated: {self._primary_ticket.ticket[:50]}...")
            except Exception as e:
                raise RuntimeError(f"Failed to generate primary session ticket: {e}")
    
    async def _generate_ticket(self) -> SessionTicket:
        """Generate a fresh session ticket from JWT.
        
        Returns:
            SessionTicket data
            
        Raises:
            httpx.HTTPError: If generation fails
        """
        # Get valid JWT from token manager
        jwt_token = await self.token_manager.get_valid_jwt()
        
        # Call WAL login endpoint to generate session ticket
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                WAL_LOGIN_ENDPOINT,
                json={
                    "accessToken": jwt_token,
                    "productName": PRODUCT_NAME,
                },
                headers={
                    "Accept-Charset": "UTF-8",
                    "Accept": "application/json",
                    "X-BLAZE-ID": "madden-2025-xbsx-gen5",
                    "X-BLAZE-VOID-RESP": "XML",
                    "X-Application-Key": "MADDEN-MCA",
                    "Content-Type": "application/json",
                    "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 13; Android SDK built for x86_64 Build/TE1A.220922.034)",
                }
            )
            
            response.raise_for_status()
            data = response.json()
        
        # Check for userLoginInfo
        if "userLoginInfo" not in data:
            raise RuntimeError(f"Session generation failed. Response: {json.dumps(data, indent=2)[:500]}")
        
        # Extract session ticket info
        user_login_info = data["userLoginInfo"]
        
        # Update last generation time for rate limiting
        self._last_generation_time = datetime.now(timezone.utc)
        
        return SessionTicket(
            ticket=user_login_info["sessionKey"],
            blaze_id=user_login_info["blazeId"],
            display_name=user_login_info["personaDetails"]["displayName"],
            generated_at=self._last_generation_time,
        )
    
    async def _wait_for_generation_cooldown(self) -> None:
        """Wait if we're in generation cooldown period.
        
        Respects EA's rate limits by enforcing a cooldown between
        session ticket generations (~3 tickets per short period allowed).
        """
        if self._last_generation_time is None:
            return
        
        now = datetime.now(timezone.utc)
        time_since_last = (now - self._last_generation_time).total_seconds()
        
        if time_since_last < GENERATION_COOLDOWN_SECONDS:
            wait_time = GENERATION_COOLDOWN_SECONDS - time_since_last
            print(f"⏳ Waiting {wait_time:.1f}s for generation cooldown...")
            await asyncio.sleep(wait_time)
    
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
