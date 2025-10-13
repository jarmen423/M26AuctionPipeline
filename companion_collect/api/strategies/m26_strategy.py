"""
Madden 26 API Strategy
======================

Version-specific configuration for Madden 26 Companion API.

M26 inherits most configuration from M25 with minimal overrides.
"""

from .m25_strategy import M25Strategy


class M26Strategy(M25Strategy):
    """
    Madden 26 API strategy - inherits from M25.
    
    Based on testing October 9, 2025:
    - Same command IDs as M25 (confirmed working with 9153)
    - Same component ID (2050)
    - Same app key (MADDEN-MCA)
    - Only difference: blaze_id header
    
    This minimal difference aligns with madden-franchise repository findings:
    M26 file format is 95%+ identical to M25 (only compression changed).
    """
    
    def __init__(self, platform: str = "ps5"):
        super().__init__()
        # Override only what's different
        self.version = 26
        self.platform = platform
        self.blaze_id = M26_BLAZE_IDS.get(platform, M26_BLAZE_IDS["default"])
        
        # command_ids inherited from M25 (confirmed working)
        # If M26-specific command IDs discovered, override here:
        # self.command_ids["search_auctions"] = 9200  # Example
    
    def parse_auction_response(self, response: dict) -> list:
        """
        Parse M26 auction response.
        
        M26 response format is identical to M25 (confirmed October 9, 2025).
        Uses parent's implementation.
        """
        return super().parse_auction_response(response)


# Platform-specific blaze IDs (all confirmed working October 9, 2025)
M26_BLAZE_IDS = {
    # Xbox variants
    "xbox": "madden-2026-xbox",
    "xbox-series": "madden-2026-xbox-series", 
    "xbsx": "madden-2026-xbsx",
    
    # PlayStation variants
    "playstation": "madden-2026-playstation",
    "playstation5": "madden-2026-playstation5",
    "ps5": "madden-2026-ps5",
    
    # PC variants
    "pc": "madden-2026-pc",
    "steam": "madden-2026-steam",
    "origin": "madden-2026-origin",
    "windows": "madden-2026-windows",
    
    # Generic
    "default": "madden-2026",
    
    # Non-working (404 errors)
    # "xbsx-gen5": "madden-2026-xbsx-gen5",  # 404
    # "gen5": "madden-2026-gen5",  # 404
}


__all__ = ['M26Strategy', 'M26_BLAZE_IDS']
