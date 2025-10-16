# Complete MUT Mobile Commands Discovery

**Date**: October 10, 2025  
**Source**: Live capture analysis (freshFlows/freshFlow1)  
**Total Commands**: 7 unique Mobile commands discovered

## Complete Command Set

| ID | Command Name | Category | Purpose | Status |
|----|--------------|----------|---------|--------|
| 9114 | `GetHubEntryData` | UI/Navigation | Hub/menu entry data | Known (not auction-related) |
| 9121 | `GetBinderPage` | Collection | Binder/collection page data | Known (not auction-related) |
| **9153** | **`Mobile_SearchAuctions`** | **Auction Core** | **Initial auction search** | **✅ IMPLEMENTED** |
| **9154** | **`Mobile_RefreshAuctionDetails`** | **Auction Streaming** | **Refresh specific auctions** | **🆕 NEW DISCOVERY** |
| **9157** | **`Mobile_GetAuctionBids`** | **Auction Tracking** | **Get bid history/tracking** | **🆕 NEW DISCOVERY** |

## NEW Commands Detail

### 1. Mobile_RefreshAuctionDetails (9154)

**Purpose**: Refresh auction details for specific auction IDs

**Request**:
```json
{
  "commandId": 9154,
  "commandName": "Mobile_RefreshAuctionDetails",
  "requestPayload": {
    "auctionIdList": []  // Array of auction IDs to refresh
  }
}
```

**Response**:
```json
{
  "details": [],  // Array of updated auction objects
  "responseData": { ... }
}
```

**Use Case**: Live auction monitoring - efficient polling for updates

---

### 2. Mobile_GetAuctionBids (9157)

**Purpose**: Get bid history or auction bid tracking information

**Request**:
```json
{
  "commandId": 9157,
  "commandName": "Mobile_GetAuctionBids",
  "requestPayload": {
    "offset": 0,      // Pagination offset
    "count": 100      // Number of bids to retrieve
  }
}
```

**Response**:
```json
{
  "details": [],  // Array of bid objects
  "responseData": { ... }
}
```

**Use Case**: 
- Track your own bids across auctions
- Monitor bid history for specific auctions
- Implement bid tracking/notifications

---

## Streaming Architecture Pattern

The discovered commands reveal EA's auction architecture:

```
┌─────────────────────────────────────────────────────────────┐
│                    AUCTION WORKFLOW                          │
└─────────────────────────────────────────────────────────────┘

1. SEARCH Phase
   ├── Mobile_SearchAuctions (9153)
   │   └── Get initial auction results with filters
   │
2. MONITORING Phase
   ├── Mobile_RefreshAuctionDetails (9154)
   │   └── Poll specific auctions for updates
   │
3. TRACKING Phase
   └── Mobile_GetAuctionBids (9157)
       └── Monitor your bids and bid history
```

## Implementation Strategy

### For companion_collect Pipeline

**Current State**: Only uses SearchAuctions repeatedly
**New Efficient Pattern**:

```python
# Phase 1: Initial Search
auctions = mobile_search_auctions(filters)
auction_ids = [a['auctionId'] for a in auctions]

# Phase 2: Live Monitoring
while streaming:
    # Efficient refresh (only changed auctions)
    updates = mobile_refresh_auction_details(auction_ids)
    changes = detect_changes(previous_state, updates)
    
    # Track bids
    bid_updates = mobile_get_auction_bids(offset=0, count=100)
    
    # Broadcast changes
    broadcast_to_clients(changes, bid_updates)
    
    sleep(poll_interval)
```

### Benefits

1. **Lower API Load**: Targeted refreshes vs full searches
2. **Faster Updates**: Smaller payloads, quicker responses  
3. **Better Tracking**: Dedicated bid monitoring
4. **More Scalable**: Can monitor more auctions simultaneously

## Command Comparison

### SearchAuctions vs RefreshAuctionDetails

| Aspect | SearchAuctions (9153) | RefreshAuctionDetails (9154) |
|--------|----------------------|------------------------------|
| Input | Search filters (cardId, teamId, etc) | Auction ID list |
| Output | Matching auctions | Updated auction details |
| Use Case | Initial discovery | Live monitoring |
| Load | Higher (full search) | Lower (targeted) |
| Frequency | Once per search | Repeated polling |

### RefreshAuctionDetails vs GetAuctionBids

| Aspect | RefreshAuctionDetails (9154) | GetAuctionBids (9157) |
|--------|----------------------------|----------------------|
| Focus | Auction details (price, time left) | Bid history/tracking |
| Input | Auction IDs | Pagination (offset/count) |
| Use Case | Price/status updates | Your bids across all auctions |
| Scope | Specific auctions | All your bid activity |

## M26 Testing Priority

Now that we have 3 auction commands, test M26 versions:

**High Priority Tests**:
1. RefreshAuctionDetails (9154) with M26 Blaze ID
2. GetAuctionBids (9157) with M26 Blaze ID
3. Check for M26-specific command IDs (9254? 9257?)

**Testing Matrix**:
```
Command         | M25 ID | M26 ID? | Blaze ID Variant?
----------------|--------|---------|------------------
SearchAuctions  | 9153   | ???     | madden-2026?
RefreshDetails  | 9154   | ???     | madden-2026?
GetAuctionBids  | 9157   | ???     | madden-2026?
```

## Gap Analysis

### Known Commands (Working)
- ✅ Mobile_SearchAuctions (9153) - Fully documented, implemented

### Newly Discovered (Need Testing)
- 🆕 Mobile_RefreshAuctionDetails (9154) - Documented, need real auction ID test
- 🆕 Mobile_GetAuctionBids (9157) - Documented, need real bid test

### Potential Commands (Speculation)
Based on command ID gaps and auction operations:

- 9155: Mobile_PlaceBid? (place auction bid)
- 9156: Mobile_BuyNow? (buy now purchase)
- 9158: Mobile_CancelAuction? (cancel your auction)
- 9159: Mobile_ListAuction? (create new auction)
- 9160: Mobile_GetAuctionStats? (auction statistics)

**TODO**: Fuzz 9155-9160 range in live capture

## Next Steps

### Immediate (Today)
1. ✅ Document all discovered commands
2. ⏸️ Test RefreshAuctionDetails with real auction IDs
3. ⏸️ Test GetAuctionBids to understand bid tracking

### Short-term (This Week)
4. ⏸️ Search captures for command IDs 9155-9160
5. ⏸️ Test M26 variants of all auction commands
6. ⏸️ Integrate RefreshDetails into companion_collect

### Long-term (This Month)
7. ⏸️ Build streaming pipeline using RefreshDetails
8. ⏸️ Implement bid tracking with GetAuctionBids
9. ⏸️ Replace periodic searches with efficient refresh pattern

## References

- RefreshAuctionDetails docs: `docs/MOBILE_REFRESH_AUCTION_DETAILS.md`
- Memory file: `.serena/memories/CURRENT - RefreshAuctionDetails discovery.md`
- Analysis script: `scripts/analyze_commands.py`
- Live capture: `freshFlows/freshFlow1`
- Discovery timestamp: 2025-10-10 13:21:04

## Impact Assessment

**Critical**: This discovery fundamentally changes our auction monitoring approach

- **Before**: Inefficient repeated full searches
- **After**: Efficient targeted polling with dedicated refresh/bid commands

This puts us on par with mut.exchange's streaming capabilities! 🎉
