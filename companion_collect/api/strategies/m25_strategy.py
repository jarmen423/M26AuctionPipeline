"""
Madden 25 API Strategy
======================

Version-specific configuration for Madden 25 Companion API.

Based on known working configurations from our captures and testing.
"""

from . import VersionStrategy


class M25Strategy(VersionStrategy):
    """
    Madden 25 API strategy.
    
    Confirmed working configuration from captures dated October 9-10, 2025.
    """
    
    def __init__(self):
        super().__init__(
            version=25,
            blaze_id="madden-2025-xbsx-gen5",
            app_key="MADDEN-MCA",
            component_id=2050,
            command_ids={
                # Hub/Navigation
                "get_hub_entry_data": 9114,
                "get_binder_page": 9121,
                
                # Auction Commands (confirmed working)
                "search_auctions": 9153,
                "refresh_auction_details": 9154,
                "get_auction_bids": 9157,
                
                # Potential auction commands (to be tested)
                # Speculation based on sequential IDs:
                # 9155: PlaceBid?
                # 9156: BuyNow?
                # 9158: CancelAuction?
                # 9159: ListAuction?
            }
        )
    
    def parse_auction_response(self, response: dict) -> list:
        """
        Parse M25 auction response.
        
        Args:
            response: Raw API response
            
        Returns:
            List of auction dictionaries
        """
        # M25 uses 'responseInfo' format
        if "responseInfo" in response:
            value = response["responseInfo"].get("value", {})
            return value.get("details", [])
        
        # Fallback to parent implementation
        return super().parse_auction_response(response)


__all__ = ['M25Strategy']
