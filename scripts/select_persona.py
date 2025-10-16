#!/usr/bin/env python3
"""Interactive helper to pick the Madden persona/console for WAL logins.

This script mirrors the Binder/Snallabot flow: it uses the Companion JWT to query
EA's entitlements + personas, lets you choose the correct console persona, and
persists the resulting WAL identifiers to disk so that SessionManager can reuse
them when minting tickets.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

import httpx

import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from companion_collect.auth.token_manager import TokenManager
from companion_collect.config import get_settings


USER_AGENT = "Dalvik/2.1.0 (Linux; U; Android 13; Android SDK built for x86_64 Build/TE1A.220922.034)"
CLIENT_ID = "MCA_25_COMP_APP"
CLIENT_SECRET = "wfGAWnrxLroZOwwELYA2ZrAuaycuF2WDb00zOLv48Sb79viJDGlyD6OyK8pM5eIiv_20240731135155"
AUTH_SOURCE = "317239"
MACHINE_KEY = "444d362e8e067fe2"
REDIRECT_URL = "http://127.0.0.1/success"


ENTITLEMENT_SUFFIX_MAP = {
    "XBSX": ("xbsx", "xbox"),
    "XONE": ("xone", "xbox"),
    "PS5": ("ps5", "ps3"),
    "PS4": ("ps4", "ps3"),
    "PC": ("pc", "cem_ea_id"),
    "SDA": ("stadia", "stadia"),
}


@dataclass
class PersonaCandidate:
    """Representation of a single persona returned by EA."""

    display_name: str
    persona_id: int
    namespace: str
    entitlement: str
    console: str
    entitlement_year: int | None = None


def _parse_entitlement(entitlement: dict[str, Any]) -> tuple[str, str, int | None] | None:
    """
    Return (console, namespace, year) for a Madden entitlement record.
    Accepts legacy years (e.g., MADDEN_25_XBSX).
    """

    group_name = entitlement.get("groupName")
    if not isinstance(group_name, str) or not group_name.startswith("MADDEN_"):
        return None

    remainder = group_name[len("MADDEN_") :]
    if not remainder:
        return None

    year_chars = []
    suffix_chars = []
    for ch in remainder:
        if ch.isdigit() and not suffix_chars:
            year_chars.append(ch)
        else:
            suffix_chars.append(ch)

    if not year_chars or not suffix_chars:
        return None

    year_token = "".join(year_chars)
    suffix = "".join(suffix_chars).upper()
    suffix = suffix.upper()
    mapping = ENTITLEMENT_SUFFIX_MAP.get(suffix)
    if not mapping:
        return None

    console, namespace = mapping
    try:
        year_val = int(year_token)
        entitlement_year = 2000 + year_val if year_val < 100 else year_val
    except ValueError:
        entitlement_year = None

    return console, namespace, entitlement_year


def _build_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    base = {
        "Accept-Charset": "UTF-8",
        "Accept-Encoding": "gzip, deflate",
        "User-Agent": USER_AGENT,
    }
    if extra:
        base.update(extra)
    return base


async def _fetch_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
) -> Any:
    response = await client.request(method, url, headers=headers)
    response.raise_for_status()
    return response.json()


def _render_personas(personas: Iterable[PersonaCandidate]) -> None:
    print("\nDiscovered Madden personas:")
    print("-" * 72)
    for idx, persona in enumerate(personas):
        print(
            f"[{idx}] personaId={persona.persona_id:<12} "
            f"console={persona.console:<5} namespace={persona.namespace:<12} "
            f"display='{persona.display_name}' entitlement={persona.entitlement} "
            f"year={persona.entitlement_year or 'n/a'}"
        )
    print("-" * 72)


def _derive_wal_identifiers(year: int, console: str) -> tuple[str, str]:
    """Return the WAL blaze + product names a la Snallabot (no gen suffix)."""
    year_token = str(year)
    blaze = f"madden-{year_token}-{console}"
    product = f"{blaze}-mca"
    return blaze, product


async def _mint_persona_tokens(
    access_token: str,
    persona: PersonaCandidate,
) -> dict[str, Any]:
    """Perform persona-scoped OAuth exchange and return new token payload."""

    auth_headers = {
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (Linux; Android 13; sdk_gphone_x86_64 Build/TE1A.220922.031; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/103.0.5060.71 Mobile Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.9",
        "X-Requested-With": "com.ea.gp.madden19companionapp",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "en-US,en;q=0.9",
    }

    params = {
        "hide_create": "true",
        "release_type": "prod",
        "response_type": "code",
        "redirect_uri": REDIRECT_URL,
        "client_id": CLIENT_ID,
        "machineProfileKey": MACHINE_KEY,
        "authentication_source": AUTH_SOURCE,
        "access_token": access_token,
        "persona_id": str(persona.persona_id),
        "persona_namespace": persona.namespace,
    }

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
        location_response = await client.get(
            "https://accounts.ea.com/connect/auth",
            params=params,
            headers=auth_headers,
        )
        if location_response.status_code not in (301, 302):
            raise RuntimeError(
                f"Persona auth redirect failed with status {location_response.status_code}: "
                f"{location_response.text[:200]}"
            )

        location = location_response.headers.get("Location")
        if not location:
            raise RuntimeError("Persona auth response missing Location header")

        parsed = urlparse(location)
        code = parse_qs(parsed.query).get("code", [None])[0]
        if not code:
            raise RuntimeError("Failed to extract code from persona auth redirect")

        token_headers = {
            "Accept-Charset": "UTF-8",
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept-Encoding": "gzip, deflate",
        }
        token_payload = {
            "authentication_source": AUTH_SOURCE,
            "code": code,
            "grant_type": "authorization_code",
            "token_format": "JWS",
            "release_type": "prod",
            "client_secret": CLIENT_SECRET,
            "redirect_uri": REDIRECT_URL,
            "client_id": CLIENT_ID,
        }

        token_response = await client.post(
            "https://accounts.ea.com/connect/token",
            headers=token_headers,
            data=token_payload,
        )
        token_response.raise_for_status()
        return token_response.json()


async def main() -> int:
    parser = argparse.ArgumentParser(description="Select Madden persona for WAL access")
    parser.add_argument(
        "--tokens-path",
        default=None,
        help="Path to tokens.json (defaults to COMPANION_tokens_path)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Persona metadata output path (defaults to persona_context_path)",
    )
    parser.add_argument(
        "--select",
        type=int,
        default=None,
        help="Automatically select persona by index (omit for interactive prompt)",
    )
    parser.add_argument(
        "--update-tokens",
        action="store_true",
        help="After selecting persona, mint persona-scoped tokens and persist to tokens.json",
    )
    args = parser.parse_args()

    settings = get_settings()
    tokens_path = Path(args.tokens_path or settings.tokens_path)
    if not tokens_path.exists():
        print(f"Token file not found: {tokens_path}")
        return 1

    persona_path = Path(args.output or getattr(settings, "persona_context_path", "auction_data/persona_context.json"))
    persona_path.parent.mkdir(parents=True, exist_ok=True)

    token_mgr = TokenManager.from_file(tokens_path)
    access_token = await token_mgr.get_valid_jwt()

    wal_year = getattr(settings, "wal_madden_year", None) or settings.madden_year

    print("Fetching persona list from EA...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        tokeninfo = await _fetch_json(
            client,
            f"https://accounts.ea.com/connect/tokeninfo?access_token={access_token}",
            headers=_build_headers({"X-Include-Deviceid": "true"}),
        )
        pid = tokeninfo.get("pid_id")
        if not pid:
            print("Unable to determine pid_id from tokeninfo response.")
            return 1

        entitlements_payload = await _fetch_json(
            client,
            f"https://gateway.ea.com/proxy/identity/pids/{pid}/entitlements/?status=ACTIVE",
            headers=_build_headers(
                {
                    "Authorization": f"Bearer {access_token}",
                    "X-Expand-Results": "true",
                }
            ),
        )

        entitlement_list = (
            entitlements_payload.get("entitlements", {}).get("entitlement", [])
            if isinstance(entitlements_payload, dict)
            else []
        )
        parsed_entitlements: list[tuple[dict[str, Any], str, str, int | None]] = []
        for ent in entitlement_list:
            if ent.get("entitlementTag") != "ONLINE_ACCESS":
                continue
            parsed = _parse_entitlement(ent)
            if not parsed:
                continue
            console, namespace, ent_year = parsed
            parsed_entitlements.append((ent, console, namespace, ent_year))

        if not parsed_entitlements:
            sample = [
                {
                    "groupName": ent.get("groupName"),
                    "entitlementTag": ent.get("entitlementTag"),
                    "status": ent.get("status"),
                }
                for ent in entitlement_list[:5]
            ]
            print("No Madden entitlements found for this account.")
            if sample:
                print("Sample entitlements returned:")
                for item in sample:
                    print(f"  - groupName={item['groupName']} tag={item['entitlementTag']} status={item['status']}")
            else:
                print("Entitlement list was empty.")
            return 1

        personas: list[PersonaCandidate] = []
        for entitlement, console, expected_namespace, ent_year in parsed_entitlements:
            pid_uri = entitlement.get("pidUri")
            entitlement_name = entitlement.get("groupName")
            if not pid_uri or not entitlement_name:
                continue
            response = await _fetch_json(
                client,
                f"https://gateway.ea.com/proxy/identity{pid_uri}/personas?status=ACTIVE&access_token={access_token}",
                headers=_build_headers({"X-Expand-Results": "true"}),
            )
            raw_personas = response.get("personas", {}).get("persona", []) if isinstance(response, dict) else []

            for raw_persona in raw_personas:
                persona_namespace = raw_persona.get("namespaceName") or ""
                if persona_namespace != expected_namespace:
                    continue
                try:
                    persona_id = int(raw_persona.get("personaId"))
                except (TypeError, ValueError):
                    continue
                personas.append(
                    PersonaCandidate(
                        display_name=raw_persona.get("displayName", ""),
                        persona_id=persona_id,
                        namespace=persona_namespace,
                        entitlement=entitlement_name,
                        console=console,
                        entitlement_year=ent_year,
                    )
                )

    if not personas:
        print("No active Madden personas were returned for this account.")
        return 1

    personas.sort(key=lambda p: (p.console, p.display_name.lower()))
    _render_personas(personas)

    selection = args.select
    if selection is None:
        try:
            selection = int(input("Select persona index: ").strip())
        except ValueError:
            print("Invalid input; expected an integer index.")
            return 1

    if selection < 0 or selection >= len(personas):
        print(f"Selection {selection} is out of range.")
        return 1

    chosen = personas[selection]
    wal_blaze_id, wal_product_name = _derive_wal_identifiers(wal_year, chosen.console)

    new_token_payload: dict[str, Any] | None = None
    if args.update_tokens:
        print("\nMinting persona-scoped tokens...")
        try:
            new_token_payload = await _mint_persona_tokens(access_token, chosen)
        except Exception as exc:
            print(f"Failed to mint persona-scoped tokens: {exc}")
            return 1

    persona_context = {
        "console": chosen.console,
        "persona_id": chosen.persona_id,
        "persona_display_name": chosen.display_name,
        "persona_namespace": chosen.namespace,
        "madden_entitlement": chosen.entitlement,
        "entitlement_year": chosen.entitlement_year,
        "wal_blaze_id": wal_blaze_id,
        "wal_product_name": wal_product_name,
        "wal_madden_year": wal_year,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    persona_path.write_text(json.dumps(persona_context, indent=2))
    print(f"\nSaved persona context to {persona_path}")
    print(f" - console: {chosen.console}")
    print(f" - persona_id: {chosen.persona_id}")
    print(f" - WAL blaze/product: {wal_blaze_id}, {wal_product_name}")

    if new_token_payload is not None:
        tokens_path.write_text(json.dumps(new_token_payload, indent=2))
        refreshed_mgr = TokenManager.from_file(tokens_path)
        status = refreshed_mgr.get_status()
        print(f"\nUpdated {tokens_path} with persona-scoped tokens.")
        print(f" - expires_at: {status.get('expires_at')}")
        print(f" - time_remaining: {status.get('time_remaining')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
