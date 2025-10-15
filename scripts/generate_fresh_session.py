#!/usr/bin/env python3
"""Generate a fresh session ticket via WAL login."""
import asyncio
import json
from pathlib import Path

from companion_collect.auth.session_manager import SessionManager
from companion_collect.auth.token_manager import TokenManager
from companion_collect.config import get_settings

async def main():
    """Generate fresh session ticket from WAL."""
    print("=" * 80)
    print("GENERATING FRESH SESSION TICKET FROM WAL")
    print("=" * 80)
    
    settings = get_settings()

    #Ensure tokens are fresh
    tokens_path = Path(settings.tokens_path)
    if not tokens_path.exists():
        print(f"Tokens file not found: {tokens_path}")
        return 1
    
    token_manager = TokenManager.from_file(tokens_path)
    print("\nEnsuring valid JWT token...")
    jwt = await token_manager.get_valid_jwt()
    print(f"JWT ready: {jwt[:20]}...")

    # Generate session ticket via WAL
    print("\nGenerating session ticket from WAL...")

    session_manager = SessionManager(token_manager)
    try:
        session_ticket = await session_manager.get_session_ticket()

        print(f"\nGenerated session ticket:")
        print(f"   {session_ticket}")

        # Update context file 
        context_path = Path(settings.session_context_path)

        if context_path.exists():
            with open(context_path) as f:
                context = json.load(f)
        else:
            context = {}
        # Update session ticket (keep persona infor if present)
        context['session_ticket'] = session_ticket

        # Write back
        with open(context_path, 'w') as f:
            json.dump(context, f, indent=2)
        print(f"\nUpdated {context_path}")
        print("\nReady for testing!")
        return 0
    
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        return 1
if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
    