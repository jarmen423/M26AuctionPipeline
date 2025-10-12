"""JWT Token lifecycle management with automatic refresh capability.

This module manages the OAuth JWT access tokens used to generate session tickets.
It handles token expiration, automatic refresh using refresh tokens, and provides
a simple interface for getting valid tokens on demand.

Key Features:
- Automatic JWT refresh before expiration
- Thread-safe token storage and refresh
- Configurable refresh timing (default: 5 minutes before expiry)
- Persistent token storage for restarts

Architecture:
    TokenManager
        ├── get_valid_jwt() → Returns valid JWT (refreshes if needed)
        ├── refresh_jwt() → Explicitly refresh the JWT
        └── is_jwt_expired() → Check if current JWT is expired

Usage:
    ```python
    manager = TokenManager.from_file("tokens.json")
    jwt = await manager.get_valid_jwt()  # Always returns valid JWT
    ```
"""

from __future__ import annotations

import asyncio
import json
import httpx
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
import jwt as jwt_lib  # PyJWT for decoding


# OAuth constants for EA Companion App
CLIENT_ID = "MCA_25_COMP_APP"
CLIENT_SECRET = "wfGAWnrxLroZOwwELYA2ZrAuaycuF2WDb00zOLv48Sb79viJDGlyD6OyK8pM5eIiv_20240731135155"
TOKEN_ENDPOINT = "https://accounts.ea.com/connect/token"
REFRESH_SAFETY_MARGIN_SECONDS = 300  # Refresh 5 minutes before expiry


@dataclass
class TokenData:
    """Container for JWT and refresh token data."""
    
    jwt_token: str
    refresh_token: str
    expires_at: str  # ISO 8601 timestamp
    issued_at: str  # ISO 8601 timestamp
    
    @property
    def expires_at_dt(self) -> datetime:
        """Get expiration as datetime object."""
        return datetime.fromisoformat(self.expires_at)
    
    @property
    def issued_at_dt(self) -> datetime:
        """Get issued time as datetime object."""
        return datetime.fromisoformat(self.issued_at)
    
    def is_expired(self, safety_margin_seconds: int = REFRESH_SAFETY_MARGIN_SECONDS) -> bool:
        """Check if JWT is expired or within safety margin of expiring."""
        now = datetime.now(timezone.utc)
        expiry_with_margin = self.expires_at_dt - timedelta(seconds=safety_margin_seconds)
        return now >= expiry_with_margin
    
    def time_until_expiry(self) -> timedelta:
        """Get time remaining until expiration."""
        now = datetime.now(timezone.utc)
        return self.expires_at_dt - now


class TokenManager:
    """Manages JWT token lifecycle with automatic refresh."""
    
    def __init__(self, token_data: TokenData, storage_path: Optional[Path] = None):
        """Initialize with existing token data.
        
        Args:
            token_data: Initial token data (JWT + refresh token)
            storage_path: Optional path to persist tokens
        """
        self._token_data = token_data
        self._storage_path = storage_path
        self._refresh_lock = asyncio.Lock()
    
    @classmethod
    def from_file(cls, path: Path | str) -> TokenManager:
        """Load TokenManager from a JSON file.
        
        Args:
            path: Path to JSON file containing token data
            
        Returns:
            Initialized TokenManager
            
        Raises:
            FileNotFoundError: If token file doesn't exist
            ValueError: If token file is invalid
        """
        path = Path(path)
        
        if not path.exists():
            raise FileNotFoundError(f"Token file not found: {path}")
        
        with open(path) as f:
            data = json.load(f)
        
        # Handle raw OAuth response format
        if 'access_token' in data:
            jwt_token = data['access_token']
            refresh_token = data.get('refresh_token', '')
            expires_in = data.get('expires_in', 3600)
            
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=expires_in)
            
            token_data = TokenData(
                jwt_token=jwt_token,
                refresh_token=refresh_token,
                expires_at=expires_at.isoformat(),
                issued_at=now.isoformat()
            )
        else:
            # Assume already in TokenData format
            token_data = TokenData(**data)
        
        return cls(token_data, storage_path=path)
    
    @classmethod
    def from_login_response(
        cls, 
        jwt_token: str, 
        refresh_token: str, 
        expires_in: int,
        storage_path: Optional[Path] = None
    ) -> TokenManager:
        """Create TokenManager from OAuth login response.
        
        Args:
            jwt_token: The JWT access token
            refresh_token: The refresh token for getting new JWTs
            expires_in: Token lifetime in seconds
            storage_path: Optional path to persist tokens
            
        Returns:
            Initialized TokenManager
        """
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=expires_in)
        
        token_data = TokenData(
            jwt_token=jwt_token,
            refresh_token=refresh_token,
            expires_at=expires_at.isoformat(),
            issued_at=now.isoformat()
        )
        
        manager = cls(token_data, storage_path=storage_path)
        
        # Persist immediately if storage path provided
        if storage_path:
            manager._save_to_storage()
        
        return manager
    
    async def get_valid_jwt(self) -> str:
        """Get a valid JWT token, refreshing if necessary.
        
        This is the main method you should use. It ensures you always
        get a valid JWT, automatically refreshing if the current one
        is expired or about to expire.
        
        Returns:
            A valid JWT access token
            
        Raises:
            httpx.HTTPError: If refresh fails
        """
        if self._token_data.is_expired():
            await self.refresh_jwt()
        
        return self._token_data.jwt_token
    
    async def refresh_jwt(self) -> str:
        """Refresh the JWT using the refresh token.
        
        Uses the refresh token to obtain a new JWT access token and
        refresh token from EA's OAuth server. Updates internal state
        and persists to storage if configured.
        
        Returns:
            The new JWT access token
            
        Raises:
            httpx.HTTPError: If refresh request fails
        """
        async with self._refresh_lock:
            # Double-check after acquiring lock (another task may have refreshed)
            if not self._token_data.is_expired():
                return self._token_data.jwt_token
            
            print(f"🔄 Refreshing JWT token (expired at {self._token_data.expires_at})...")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    TOKEN_ENDPOINT,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": self._token_data.refresh_token,
                        "client_id": CLIENT_ID,
                        "client_secret": CLIENT_SECRET,
                    },
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 13; Android SDK built for x86_64 Build/TE1A.220922.034)",
                    }
                )
                
                response.raise_for_status()
                data = response.json()
            
            # Decode JWT to get actual expiration time
            # Note: We don't verify signature since we trust EA's server
            jwt_payload = jwt_lib.decode(
                data["access_token"],
                options={"verify_signature": False}
            )
            
            # Update token data
            now = datetime.now(timezone.utc)
            expires_at = datetime.fromtimestamp(jwt_payload["exp"], tz=timezone.utc)
            
            self._token_data = TokenData(
                jwt_token=data["access_token"],
                refresh_token=data.get("refresh_token", self._token_data.refresh_token),
                expires_at=expires_at.isoformat(),
                issued_at=now.isoformat()
            )
            
            # Persist to storage
            if self._storage_path:
                self._save_to_storage()
            
            time_until_expiry = self._token_data.time_until_expiry()
            print(f"✅ JWT refreshed successfully (expires in {time_until_expiry})")
            
            return self._token_data.jwt_token
    
    def _save_to_storage(self) -> None:
        """Persist current token data to storage file."""
        if not self._storage_path:
            return
        
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(self._storage_path, 'w') as f:
            json.dump(asdict(self._token_data), f, indent=2)
    
    def get_status(self) -> dict:
        """Get current token status information.
        
        Returns:
            Dict with token status including expiration info
        """
        time_remaining = self._token_data.time_until_expiry()
        
        return {
            "is_expired": self._token_data.is_expired(),
            "expires_at": self._token_data.expires_at,
            "issued_at": self._token_data.issued_at,
            "time_remaining": str(time_remaining),
            "time_remaining_seconds": time_remaining.total_seconds(),
            "needs_refresh_soon": self._token_data.is_expired(safety_margin_seconds=0),
        }
