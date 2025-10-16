#!/usr/bin/env python3
"""Send Mobile_GetBinderPage via WAL using the existing collector stack."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from companion_collect.adapters.request_template import RequestTemplate
from companion_collect.collectors.auctions import AuctionCollector
from companion_collect.config import Settings, get_settings
from ea_constants import AuctionSearchResponse


BINDER_COMMANDS = {
    "binder": {"command_id": 9121, "command_name": "GetBinderPage"},
    "hub": {"command_id": 9114, "command_name": "GetHubEntryData"},
}


def _parse_payload(source: str) -> Any:
    text = source.strip()
    if not text:
        raise ValueError("Payload content is empty")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


async def _run(args: argparse.Namespace, settings: Settings) -> AuctionSearchResponse:
    template_path = Path(args.template or settings.request_template_path)
    template = RequestTemplate.from_path(template_path)
    collector = AuctionCollector(settings=settings, request_template=template)

    payload_value: Any
    if args.payload and args.payload_file:
        raise ValueError("--payload and --payload-file are mutually exclusive")
    if args.payload_file:
        payload_value = _parse_payload(Path(args.payload_file).read_text(encoding="utf-8"))
    elif args.payload:
        payload_value = _parse_payload(args.payload)
    else:
        raise ValueError("One of --payload or --payload-file is required")

    context: dict[str, Any] = {
        "command_name": args.command_name,
        "command_id": args.command_id,
        "component_id": args.component_id,
        "component_name": args.component_name,
        "request_payload_json": payload_value,
    }

    if args.page is not None:
        context["page"] = args.page
    if args.count is not None:
        context["count"] = args.count
    if args.start is not None:
        context["start"] = args.start

    async with collector.lifecycle() as active:
        return await active.fetch_once(context=context)


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch binder data via WAL Process using Mobile_GetBinderPage")
    ap.add_argument("--payload", help="Inline JSON payload inserted into requestPayload")
    ap.add_argument("--payload-file", help="Path to JSON payload inserted into requestPayload")
    ap.add_argument("--binder-command", choices=sorted(BINDER_COMMANDS.keys()), help="Shortcut for known binder commands (binder=GetBinderPage, hub=GetHubEntryData)")
    ap.add_argument("--command-id", type=int, default=None, help="Override commandId (defaults to binder/hub selection)")
    ap.add_argument("--command-name", default=None, help="Override commandName (defaults to binder/hub selection)")
    ap.add_argument("--component-id", type=int, default=2050, help="ComponentId value")
    ap.add_argument("--component-name", default="mut", help="ComponentName value")
    ap.add_argument("--template", help="Override request template path")
    ap.add_argument("--page", type=int, help="Optional page override for template context")
    ap.add_argument("--count", type=int, help="Optional count override for template context")
    ap.add_argument("--start", type=int, help="Optional start override for template context")
    ap.add_argument("--output", help="Optional path to write response JSON")
    args = ap.parse_args()

    settings = get_settings()

    if args.binder_command:
        defaults = BINDER_COMMANDS[args.binder_command]
        if args.command_id is None:
            args.command_id = defaults["command_id"]
        if args.command_name is None:
            args.command_name = defaults["command_name"]

    if args.command_id is None or args.command_name is None:
        raise SystemExit("Command id and name must be provided (set --binder-command or explicit overrides)")

    try:
        result = asyncio.run(_run(args, settings))
    except Exception as exc:  # pragma: no cover - CLI surface
        raise SystemExit(f"Binder fetch failed: {exc}")

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"Binder response written to {output_path}")
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
