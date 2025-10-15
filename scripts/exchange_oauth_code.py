#!/usr/bin/env python3
"""Exchange OAuth authorization code for tokens."""
import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import httpx

from companion_collect.config import get_settings


CLIENT_ID = "MCA_25_COMP_APP"
CLIENT_SECRET = "wfGAWnrxLroZOwwELYA2ZrAuaycuF2WDb00zOLv48Sb79viJDGlyD6OyK8pM5eIiv_20240731135155"
TOKEN_ENDPOINT = "https://accounts.ea.com/connect/token"
TOKENINFO_ENDPOINT = "https://accounts.ea.com/connect/tokeninfo"
IDENTITY_BASE_URL = "https://gateway.ea.com/proxy/identity"
AUTHENTICATION_SOURCE = "317239"
RELEASE_TYPE = "prod"
TOKEN_FORMAT = "JWS"

MOBILE_USER_AGENT = "Dalvik/2.1.0 (Linux; U; Android 13; Android SDK built for x86_64 Build/TE1A.220922.034)"


async def exchange_code_for_tokens(
    client: httpx.AsyncClient,
    *,
    auth_code: str,
    redirect_uri: str,
    code_verifier: Optional[str] = None,
) -> Dict[str, Any]:
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
    if code_verifier:
        data["code_verifier"] = code_verifier

    response = await client.post(
        TOKEN_ENDPOINT,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    response.raise_for_status()
    return response.json()


async def fetch_pid(client: httpx.AsyncClient, access_token: str) -> str:
    response = await client.get(
        TOKENINFO_ENDPOINT,
        params={"access_token": access_token},
        headers={
            "Accept-Charset": "UTF-8",
            "X-Include-Deviceid": "true",
            "User-Agent": MOBILE_USER_AGENT,
            "Accept-Encoding": "gzip",
        },
    )
    response.raise_for_status()
    data = response.json()
    pid = data.get("pid_id")
    if not pid:
        raise RuntimeError("EA tokeninfo response did not include pid_id")
    return pid


async def fetch_personas(
    client: httpx.AsyncClient,
    *,
    pid: str,
    access_token: str,
) -> List[Dict[str, Any]]:
    url = f"{IDENTITY_BASE_URL}/pids/{pid}/personas"
    response = await client.get(
        url,
        params={"status": "ACTIVE", "access_token": access_token},
        headers={
            "Accept-Charset": "UTF-8",
            "User-Agent": MOBILE_USER_AGENT,
            "Accept-Encoding": "gzip",
            "X-Expand-Results": "true",
        },
    )
    response.raise_for_status()
    payload = response.json()
    personas_container = payload.get("personas", {})
    persona_list = personas_container.get("persona", [])
    if not isinstance(persona_list, list):
        return []
    return persona_list


def select_persona(
    personas: List[Dict[str, Any]],
    *,
    expected_namespace: Optional[str],
) -> tuple[Optional[Dict[str, Any]], str]:
    if expected_namespace:
        matches = [p for p in personas if p.get("namespaceName") == expected_namespace]
        if matches:
            selected = max(matches, key=lambda p: p.get("lastAuthenticated", ""))
            return selected, f"matched expected namespace '{expected_namespace}'"

    account_personas = [p for p in personas if p.get("namespaceName") == "cem_ea_id"]
    if account_personas:
        selected = max(account_personas, key=lambda p: p.get("lastAuthenticated", ""))
        return selected, "fell back to cem_ea_id account persona"

    if personas:
        selected = max(personas, key=lambda p: p.get("lastAuthenticated", ""))
        return selected, "fell back to most recently authenticated persona"

    return None, "no personas available"


def update_session_context(
    *,
    context_path: Path,
    persona: Dict[str, Any],
    pid: str,
    selection_reason: str,
    session_ticket: Optional[str] = None,
) -> Dict[str, Any]:
    context: Dict[str, Any] = {}
    if context_path.exists():
        with open(context_path, "r", encoding="utf-8") as fh:
            try:
                context = json.load(fh)
            except json.JSONDecodeError:
                context = {}

    preserved_fields: Dict[str, Any] = {}
    if context.get("session_ticket"):
        preserved_fields["session_ticket"] = context["session_ticket"]
    if context.get("ak_bmsc_cookie"):
        preserved_fields["ak_bmsc_cookie"] = context["ak_bmsc_cookie"]

    new_context: Dict[str, Any] = {**preserved_fields}
    if session_ticket:
        new_context["session_ticket"] = session_ticket
    new_context["persona_id"] = str(persona.get("personaId")) if persona.get("personaId") else None
    if persona.get("namespaceName"):
        new_context["persona_namespace"] = persona["namespaceName"]
    new_context["persona_display_name"] = persona.get("displayName")
    new_context["pid_id"] = pid

    # Drop any None values to keep the context minimal.
    new_context = {k: v for k, v in new_context.items() if v is not None}

    context_path.parent.mkdir(parents=True, exist_ok=True)
    with open(context_path, "w", encoding="utf-8") as fh:
        json.dump(new_context, fh, indent=2)

    return new_context


async def enrich_with_persona(
    client: httpx.AsyncClient,
    *,
    access_token: str,
    session_ticket: Optional[str],
) -> None:
    settings = get_settings()
    pid = await fetch_pid(client, access_token)
    namespace_preferences = {
        "xbsx": "xbox",
        "xone": "xbox",
        "ps5": "ps3",
        "ps4": "ps3",
        "pc": "cem_ea_id",
        "steam": "cem_ea_id",
        "origin": "cem_ea_id",
    }
    platform = (settings.madden_platform or "").lower()
    expected_namespace = namespace_preferences.get(platform)

    personas = await fetch_personas(client, pid=pid, access_token=access_token)
    if not personas:
        print("WARNING: No personas returned by EA for the supplied account.")
        return

    persona, selection_reason = select_persona(personas, expected_namespace=expected_namespace)
    if persona is None:
        print("WARNING: Unable to select a Madden persona from EA response.")
        return

    context_path = Path(settings.session_context_path)
    new_context = update_session_context(
        context_path=context_path,
        persona=persona,
        pid=pid,
        selection_reason=selection_reason,
        session_ticket=session_ticket,
    )

    print("Persona context updated:")
    print(json.dumps(new_context, indent=2))
    if selection_reason:
        print(f"Selection reason: {selection_reason}")


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exchange OAuth authorization code for tokens and hydrate persona context.",
    )
    parser.add_argument(
        "callback_url",
        help="The full callback URL from the authentication flow (or just /success?code=...)",
    )
    parser.add_argument(
        "--redirect-uri",
        dest="redirect_uri",
        default=None,
        help="Redirect URI used during auth (defaults to parsed callback base or EA success endpoint)",
    )
    parser.add_argument(
        "--code-verifier",
        dest="code_verifier",
        default=None,
        help="PKCE code_verifier if the auth flow used PKCE",
    )
    parser.add_argument(
        "--session-ticket",
        dest="session_ticket",
        default=None,
        help="Optional session ticket to seed into current_session_context.json",
    )
    args = parser.parse_args()

    parsed = urlparse(args.callback_url)
    query = parse_qs(parsed.query)
    auth_code = query.get("code", [None])[0]

    if not auth_code:
        print("No auth code found in callback URL")
        return 1

    redirect_uri = args.redirect_uri
    if not redirect_uri:
        if parsed.scheme and parsed.netloc:
            redirect_uri = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        else:
            redirect_uri = "https://accounts.ea.com/connect/auth/success"

    print(f"Exchanging code: {auth_code[:20]}...")
    print(f"Requesting token from: {TOKEN_ENDPOINT}")
    print(f"Using redirect_uri: {redirect_uri}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        tokens = await exchange_code_for_tokens(
            client,
            auth_code=auth_code,
            redirect_uri=redirect_uri,
            code_verifier=args.code_verifier,
        )

        tokens_path = Path("tokens.json")
        with open(tokens_path, "w", encoding="utf-8") as fh:
            json.dump(tokens, fh, indent=2)

        print(f"Saved tokens to {tokens_path}")
        print(f"Access token: {tokens.get('access_token', 'N/A')[:20]}...")
        print(f"Expires in: {tokens.get('expires_in', 'N/A')} seconds")

        access_token = tokens.get("access_token")
        if access_token:
            await enrich_with_persona(
                client,
                access_token=access_token,
                session_ticket=args.session_ticket,
            )
        else:
            print("WARNING: Token exchange response did not contain an access_token. Skipping persona lookup.")

    print("Ready for session generation and pipeline run!")
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)