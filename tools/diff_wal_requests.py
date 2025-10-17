"""Utility to diff Madden 25 vs Madden 26 WAL payloads.

This script defines two request payloads that mirror the POST bodies, headers,
and endpoint metadata that the Madden Companion App sends to the Blaze Web App
Layer (WAL).  It performs a recursive comparison so we can quickly identify
every structural or value difference between the working Madden 25 request and
the failing Madden 26 request.

The goal is to surface differences in areas such as:

* HTTP headers (e.g., Authorization, X-BLAZE-ID, productName)
* URL paths or hosts
* componentId / commandId / commandName
* messageAuthData formatting
* Persona / routing metadata attached to headers

Only visible fields are compared—the script treats messageAuthData blobs as
opaque and simply reports whether the raw values differ.

Optionally, callers can supply JSON files for the Madden 25 and Madden 26
payloads so real capture data can be diffed without editing this file.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, List, Tuple


Request = dict[str, Any]


def _default_requests() -> Tuple[Request, Request]:
    """Return the baked-in Madden 25 and Madden 26 request payloads."""

    m25_request: Request = {
        "url": "https://wal2.tools.gos.ea.com/wal/mca/Process/{M25_ticket}",
        "headers": {
            "Authorization": "Bearer REDACTED_M25",
            "Content-Type": "application/json",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 13; Pixel 6 Build/TQ3A.230901.001)",
            "X-Application-Key": "MADDEN-MCA",
            "X-BLAZE-ID": "madden-2025-xbsx-gen5",
            "X-BLAZE-PERSONA-ID": "2813100605",
            "X-BLAZE-ROUTE": "routingPersona=2813100605;region=FRA;shard=mut-companion",
            "productName": "madden-2025-xbsx-mca",
        },
        "json": {
            "componentId": 2050,
            "componentName": "mut",
            "commandId": 9153,
            "commandName": "Mobile_SearchAuctions",
            "messageAuthData": {
                "authCode": "REDACTED_M25_AUTH_CODE",
                "authData": "REDACTED_M25_AUTH_DATA",
                "authType": 17039361,
            },
            "requestPayload": {
                "filters": [
                    {"type": "team", "value": "DAL"},
                    {"type": "program", "value": "Core Gold"},
                ],
                "itemName": "",
                "pageSize": 20,
            },
        },
    }

    m26_request: Request = {
        "url": "https://wal2.tools.gos.ea.com/wal/mca/Process/{M26_ticket}",
        "headers": {
            "Authorization": "Bearer REDACTED_M26",
            "Content-Type": "application/json",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 14; Pixel 8 Build/UPB1.230309.017)",
            "X-Application-Key": "MADDEN-MCA",
            "X-BLAZE-ID": "madden-2026-xbsx-gen5",
            "X-BLAZE-PERSONA-ID": "2813100605",
            "productName": "madden-2026-xbsx-mca",
        },
        "json": {
            "componentId": 2050,
            "componentName": "mut",
            "commandId": 9153,
            "commandName": "Mobile_SearchAuctions",
            "messageAuthData": "REDACTED_M26_BLOB",
            "requestPayload": {
                "filters": [
                    {"type": "team", "value": "DAL"},
                ],
                "itemName": "",
                "pageSize": 20,
            },
        },
    }

    return m25_request, m26_request


def _extend_path(base: str, addition: str) -> str:
    """Helper to append a segment to a dotted key path."""

    if not base:
        return addition
    return f"{base}.{addition}"


def diff(value_a: Any, value_b: Any, path: str = "") -> List[Tuple[str, Any, Any]]:
    """Recursively diff two Python objects.

    Returns a list of tuples describing every difference.  Each tuple contains:

    * path: Dotted key/index path identifying where the mismatch occurred.
    * value_a: Value from the Madden 25 request (left-hand side).
    * value_b: Value from the Madden 26 request (right-hand side).
    """

    differences: List[Tuple[str, Any, Any]] = []

    if isinstance(value_a, dict) and isinstance(value_b, dict):
        all_keys = sorted(set(value_a) | set(value_b))
        for key in all_keys:
            next_path = _extend_path(path, key)
            if key not in value_a:
                differences.append((next_path, "<missing>", value_b[key]))
                continue
            if key not in value_b:
                differences.append((next_path, value_a[key], "<missing>"))
                continue
            differences.extend(diff(value_a[key], value_b[key], next_path))
        return differences

    if isinstance(value_a, list) and isinstance(value_b, list):
        max_len = max(len(value_a), len(value_b))
        for index in range(max_len):
            next_path = _extend_path(path, f"[{index}]")
            try:
                left = value_a[index]
            except IndexError:
                differences.append((next_path, "<missing>", value_b[index]))
                continue
            try:
                right = value_b[index]
            except IndexError:
                differences.append((next_path, left, "<missing>"))
                continue
            differences.extend(diff(left, right, next_path))
        return differences

    if value_a != value_b:
        differences.append((path, value_a, value_b))

    return differences


def print_diff(diff_results: Iterable[Tuple[str, Any, Any]]) -> None:
    """Pretty-print diff results to stdout."""

    for key_path, left, right in diff_results:
        print(f"✗ {key_path}")
        print(f"    Madden 25: {left}")
        print(f"    Madden 26: {right}\n")


def summarize(diff_results: Iterable[Tuple[str, Any, Any]]) -> None:
    """Print a short summary of the mismatches that were found."""

    diff_list = list(diff_results)
    print("Summary")
    print("-------")
    if not diff_list:
        print("No differences detected.")
        return
    print(f"Total mismatches: {len(diff_list)}")

    header_diffs = [d for d in diff_list if d[0].startswith("headers.")]
    json_diffs = [d for d in diff_list if d[0].startswith("json.")]
    url_diffs = [d for d in diff_list if d[0] == "url"]

    if header_diffs:
        print(f"- Header differences: {len(header_diffs)}")
    if json_diffs:
        print(f"- Body differences: {len(json_diffs)}")
    if url_diffs:
        print(f"- URL differences: {len(url_diffs)}")


def _load_request_from_file(path: Path) -> Request:
    """Load a WAL request payload from a JSON file."""

    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:  # pragma: no cover - thin convenience wrapper
        raise FileNotFoundError(f"Request file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"File '{path}' is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Request file '{path}' must decode to a JSON object.")

    return data


def _parse_args() -> argparse.Namespace:
    """Parse command line arguments for optional request overrides."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--left",
        type=Path,
        help="Path to a JSON file that should replace the Madden 25 request payload.",
    )
    parser.add_argument(
        "--right",
        type=Path,
        help="Path to a JSON file that should replace the Madden 26 request payload.",
    )
    return parser.parse_args()


def main() -> None:
    """Run the diff and display results."""

    args = _parse_args()

    m25_request, m26_request = _default_requests()
    if args.left is not None:
        m25_request = _load_request_from_file(args.left)
    if args.right is not None:
        m26_request = _load_request_from_file(args.right)

    diff_results = diff(m25_request, m26_request)
    print_diff(diff_results)
    summarize(diff_results)


if __name__ == "__main__":
    main()

