#!/usr/bin/env python3
"""Generate a fresh session ticket from auth pool and test it."""

import asyncio
import json
from pathlib import Path

from companion_collect.auth.session_manager import SessionManager
from companion_collect.auth.token_manager import TokenManager
from companion_collect.config import get_settings


async def main():
    """Generate fresh session ticket."""
    print("=" * 80)
    print("GENERATING FRESH SESSION TICKET FROM AUTH POOL")
    print("=" * 80)
    
    settings = get_settings()
    
    # Ensure tokens are fresh
    tokens_path = Path(settings.tokens_path)
    if not tokens_path.exists():
        print("Tokens file not found: {}".format(tokens_path))
        return 1
    
    token_manager = TokenManager.from_file(tokens_path)
    print("\nEnsuring valid JWT token...")
    jwt = await token_manager.get_valid_jwt()
    print("JWT ready: {}...".format(jwt[:20]))
    
    # Load auth pool
    auth_pool_path = Path("research/captures/auth_pool.json")
    with open(auth_pool_path) as f:
        auth_pool = json.load(f)
    
    print("\nLoaded auth pool with {} bundles".format(len(auth_pool)))
    
    if not auth_pool:
        print("Auth pool is empty!")
        return 1
    
    # Get fresh auth
    fresh_auth = auth_pool[0]
    print("\nUsing auth bundle:")
    print("   Auth code: {}...".format(fresh_auth['auth_code'][:20]))
    print("   Auth type: {}".format(fresh_auth['auth_type']))
    
    # Generate session ticket
    print("\nGenerating session ticket...")
    
    session_manager = SessionManager(token_manager)
    
    try:
        session_ticket = await session_manager.get_session_ticket()
        
        print("\nGenerated session ticket:")
        print("   {}".format(session_ticket))
        
        # Update context file
        context_path = Path(settings.session_context_path)
        
        if context_path.exists():
            with open(context_path) as f:
                context = json.load(f)
        else:
            context = {}
        
        # Update session ticket
        context['session_ticket'] = session_ticket
        
        # Write back
        with open(context_path, 'w') as f:
            json.dump(context, f, indent=2)
        
        print("\nUpdated {}".format(context_path))
        print("\nReady for testing!")
        return 0
        
    except Exception as e:
        print("\nError: {}".format(e))
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
