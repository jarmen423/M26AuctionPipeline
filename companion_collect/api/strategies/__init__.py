"""
Version Strategy Pattern for Madden API
========================================

Provides clean abstraction for version-specific API configuration (M25, M26, future versions).

Pattern inspired by madden-franchise repository's StrategyPicker.

Usage:
    from companion_collect.api.strategies import StrategyPicker
    
    # Get M25 strategy
    m25 = StrategyPicker.pick(25)
    print(m25.blaze_id)  # "madden-2025-xbsx-gen5"
    
    # Get M26 strategy
    m26 = StrategyPicker.pick(26)
    print(m26.blaze_id)  # "madden-2026-xbsx-gen5"
"""

from dataclasses import dataclass
from typing import Dict


@dataclass
class VersionStrategy:
    """
    Base strategy for version-specific API configuration.
    
    Attributes:
        version: Game year (25, 26, etc.)
        blaze_id: X-BLAZE-ID header value
        app_key: X-Application-Key header value
        component_id: Default component ID for requests
        command_ids: Mapping of command names to command IDs
    """
    version: int
    blaze_id: str
    app_key: str
    component_id: int
    command_ids: Dict[str, int]
    
    def get_command_id(self, command_name: str) -> int:
        """
        Get command ID by name.
        
        Args:
            command_name: Command name (e.g., 'search_auctions')
            
        Returns:
            Command ID integer
            
        Raises:
            ValueError: If command name not found
        """
        if command_name not in self.command_ids:
            raise ValueError(
                f"Unknown command '{command_name}' for version {self.version}. "
                f"Available commands: {', '.join(self.command_ids.keys())}"
            )
        return self.command_ids[command_name]
    
    def parse_auction_response(self, response: dict) -> list:
        """
        Parse auction search response.
        
        Args:
            response: Raw API response dictionary
            
        Returns:
            List of auction dictionaries
        """
        # Default implementation - can be overridden by subclasses
        if "responseInfo" in response:
            value = response["responseInfo"].get("value", {})
            return value.get("details", [])
        
        if "result" in response:
            return response["result"].get("Data", {}).get("details", [])
        
        return []
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(version={self.version}, blaze_id='{self.blaze_id}')"


__all__ = ['VersionStrategy']
