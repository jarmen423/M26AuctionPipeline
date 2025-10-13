#!/usr/bin/env python3
"""Exchange OAuth authorization code for tokens."""
import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import httpx
import argparse

CLIENT_ID = "MCA_25_COMP_APP"
CLIENT_SECRET = "wfGAWnrxLroZOwwELYA2ZrAuaycuF2WDb00zOLv48Sb79viJDGlyD6OyK8pM5eIiv_20240731135155"
TOKEN_ENDPOINT = "https://accounts.ea.com/connect/token"
AUTHENTICATION_SOURCE = "317239"
RELEASE_TYPE = "prod"
TOKEN_FORMAT = "JWS"

async def main():
    parser = argparse.ArgumentParser(description="Exchange OAuth authorization code for tokens.")
    parser.add_argument("callback_url", help="The full callback URL from the authentication flow (or just /success?code=...)")
    parser.add_argument("--redirect-uri", dest="redirect_uri", default=None, help="Redirect URI used during auth (defaults to parsed callback base or EA success endpoint)")
    parser.add_argument("--code-verifier", dest="code_verifier", default=None, help="PKCE code_verifier if the auth flow used PKCE")
    args = parser.parse_args()

    parsed = urlparse(args.callback_url)
    query = parse_qs(parsed.query)
    auth_code = query.get("code", [None])[0]
    
    if not auth_code:
        print("No auth code found in callback URL")
        return 1

    # Determine redirect_uri
    redirect_uri = args.redirect_uri
    if not redirect_uri:
        if parsed.scheme and parsed.netloc:
            redirect_uri = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        else:
            # Fallback to EA's connect success endpoint commonly used by Companion flows
            redirect_uri = "https://accounts.ea.com/connect/auth/success"
    
    print(f"Exchanging code: {auth_code[:20]}...")
    print(f"Requesting token from: {TOKEN_ENDPOINT}")
    print(f"Using redirect_uri: {redirect_uri}")

    data = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "authentication_source": AUTHENTICATION_SOURCE,
        "release_type": RELEASE_TYPE,
        "token_format": TOKEN_FORMAT,
    }
    if args.code_verifier:
        data["code_verifier"] = args.code_verifier
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            TOKEN_ENDPOINT,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        tokens = response.json()
    
    # Save to tokens.json
    tokens_path = Path("tokens.json")
    with open(tokens_path, "w") as f:
        json.dump(tokens, f, indent=2)
    
    print(f"Saved tokens to {tokens_path}")
    print(f"Access token: {tokens.get('access_token', 'N/A')[:20]}...")
    print(f"Expires in: {tokens.get('expires_in', 'N/A')} seconds")
    print("Ready for session generation and pipeline run!")
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)