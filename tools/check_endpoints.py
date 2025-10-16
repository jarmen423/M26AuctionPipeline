#!/usr/bin/env python3
"""Endpoint reachability harness for Madden/MUT and GOS/Blaze services."""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import random
import ssl
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from ipaddress import ip_address
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, TypedDict
from urllib.parse import urlparse

import aiohttp
import dns.asyncresolver
import dns.exception
import dns.reversename
import dns.resolver

SEED_ENDPOINTS = [
    "madden.easports.com",
    "www.madden.easports.com",
    "maddennfl.easports.com",
    "maddennfl.alpha.easports.com",
    "maddennfl.beta.easports.com",
    "madden.api.easports.com",
    "madden.cert.api.easports.com",
    "madden.test.api.easports.com",
    "madden.load.api.easports.com",
    "madden.cert.ondemand.easports.com",
    "569856-maddenlb3.ea.com",
    "ldrun50.abn-iad.ea.com",
    "ldrun51.abn-iad.ea.com",
    "ldrun52.abn-iad.ea.com",
    "ldrun53.abn-iad.ea.com",
    "ldrun54.abn-iad.ea.com",
    "ldrun55.abn-iad.ea.com",
    "ldrun56.abn-iad.ea.com",
    "ldrun57.abn-iad.ea.com",
    "ldrun58.abn-iad.ea.com",
    "ldrun60.abn-iad.ea.com",
    "ldrun61.abn-iad.ea.com",
    "ldrun62.abn-iad.ea.com",
    "ldrun63.abn-iad.ea.com",
    "ldrun64.abn-iad.ea.com",
    "ldrun66.abn-iad.ea.com",
    "ldrun67.abn-iad.ea.com",
    "ldrun68.abn-iad.ea.com",
    "ldrun69.abn-iad.ea.com",
    "ldrun70.abn-iad.ea.com",
    "ldrun71.abn-iad.ea.com",
    "ldrun73.abn-iad.ea.com",
    "ldrun74.abn-iad.ea.com",
    "ldrun75.abn-iad.ea.com",
    "ldrun76.abn-iad.ea.com",
    "ldrun77.abn-iad.ea.com",
    "ldrun78.abn-iad.ea.com",
    "ldrun79.abn-iad.ea.com",
    "ldrun80.abn-iad.ea.com",
    "ldrun81.abn-iad.ea.com",
    "ldrun82.abn-iad.ea.com",
    "ldrun83.abn-iad.ea.com",
    "ldrun84.abn-iad.ea.com",
    "ldrun85.abn-iad.ea.com",
    "ldrun86.abn-iad.ea.com",
    "ldrun87.abn-iad.ea.com",
    "ldrun88.abn-iad.ea.com",
    "ldrun89.abn-iad.ea.com",
    "ldrun90.abn-iad.ea.com",
    "chef.abn-iad.ea.com",
    "uxdepot.abn-iad.ea.com",
    "eaogameweb06.eao.abn.ea.com",
    "eaogameweb07.eao.abn.ea.com",
    "eaogameweb08.eao.abn.ea.com",
    "eaogameweb09.eao.abn.ea.com",
    "betacsrapp01.beta.eao.abn-iad.ea.com",
    "418450-gosprapp546.ea.com",
    "472199-gosltapp353.ea.com",
    "560010-gosprmdb0824.ea.com",
    "647522-gosltmdb767.ea.com",
]

DEFAULT_SOURCE_FILES = [
    Path("lists/master_madden_gos_list.txt"),
    Path("lists/gos_subdomains_full.txt"),
]


class CertificateInfo(TypedDict, total=False):
    """Subset of certificate metadata to expose in results."""

    cn: Optional[str]
    sans: List[str]
    issuer: Optional[str]
    not_before: Optional[str]
    not_after: Optional[str]
    chain_depth: Optional[int]


class DNSResult(TypedDict, total=False):
    status: str
    ips: List[str]
    is_private: bool
    ptr: Optional[str]
    error: Optional[str]


class TLSResult(TypedDict, total=False):
    status: str
    alpn: Optional[str]
    version: Optional[str]
    cert: CertificateInfo
    error: Optional[str]


class HTTPResult(TypedDict, total=False):
    status: str
    code: Optional[int]
    server: Optional[str]
    via: Optional[str]
    time_ms: Optional[int]
    akamai: Optional[bool]
    error: Optional[str]


class EndpointResult(TypedDict, total=False):
    input: str
    host: str
    dns: DNSResult
    tls: TLSResult
    http: HTTPResult
    timestamp: str


@dataclass
class EndpointTask:
    original: str
    host: str


async def load_endpoints(sources: Sequence[Path], keep_dupes: bool) -> List[EndpointTask]:
    """Load endpoint hostnames from the provided sources or fallback to defaults."""

    endpoints: List[EndpointTask] = []
    seen: set[str] = set()
    logger = logging.getLogger(__name__)

    def normalize(line: str) -> Optional[str]:
        line = line.strip()
        if not line or line.startswith("#"):
            return None
        parsed = urlparse(line if "://" in line else f"//{line}")
        host = parsed.hostname
        if not host:
            return None
        if "maddenmobile" in host.lower():
            return None
        return host.lower()

    files_used = False
    for path in sources:
        if path.is_file():
            files_used = True
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError as exc:
                logger.warning("Failed to read %s: %s", path, exc)
                continue
            for raw in lines:
                host = normalize(raw)
                if not host:
                    continue
                if not keep_dupes and host in seen:
                    continue
                seen.add(host)
                endpoints.append(EndpointTask(original=raw.strip(), host=host))
    if not files_used:
        for raw in SEED_ENDPOINTS:
            host = normalize(raw)
            if not host:
                continue
            if not keep_dupes and host in seen:
                continue
            seen.add(host)
            endpoints.append(EndpointTask(original=raw, host=host))
    return endpoints


async def resolve(host: str, timeout: float) -> DNSResult:
    resolver = dns.asyncresolver.Resolver()
    resolver.lifetime = timeout
    result: DNSResult = {"status": "SKIPPED", "ips": [], "is_private": False}
    ips: List[str] = []
    try:
        gathered = []
        for rtype in ("A", "AAAA"):
            try:
                answers = await resolver.resolve(host, rtype, lifetime=timeout)
                gathered.append(answers)
            except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
                continue
        for answers in gathered:
            ips.extend([str(rdata) for rdata in answers])
        if not ips:
            result.update({"status": "NXDOMAIN", "ips": [], "is_private": False})
            return result
        is_private = any(ip_address(ip).is_private for ip in ips)
        result.update({"status": "OK", "ips": ips, "is_private": is_private})
        # PTR lookup for first IP only (best effort)
        try:
            ptr_name = dns.reversename.from_address(ips[0])
            ptr_answer = await resolver.resolve(ptr_name, "PTR", lifetime=timeout / 2)
            result["ptr"] = str(ptr_answer[0]).rstrip(".")
        except Exception:  # pragma: no cover - best effort only
            pass
    except dns.resolver.NXDOMAIN:
        result.update({"status": "NXDOMAIN", "ips": [], "is_private": False})
    except dns.exception.Timeout:
        result.update({"status": "TIMEOUT", "error": "DNS timeout"})
    except Exception as exc:  # pragma: no cover
        result.update({"status": "ERROR", "error": str(exc)})
    return result


async def tls_probe(host: str, timeout: float) -> TLSResult:
    result: TLSResult = {"status": "SKIPPED"}
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_REQUIRED
    writer: Optional[asyncio.StreamWriter] = None
    try:
        async with asyncio.timeout(timeout):
            reader, writer = await asyncio.open_connection(
                host=host,
                port=443,
                ssl=ssl_context,
                server_hostname=host,
            )
        ssl_object = writer.get_extra_info("ssl_object") if writer else None
        if not ssl_object:
            raise RuntimeError("Missing SSL object")
        cert = ssl_object.getpeercert()
        chain = ssl_object.get_peer_cert_chain()
        info: CertificateInfo = {
            "cn": cert.get("subject", [[("commonName", None)]])[0][0][1] if cert else None,
            "sans": [item[1] for item in cert.get("subjectAltName", [])] if cert else [],
            "issuer": cert.get("issuer", [[("commonName", None)]])[0][0][1] if cert else None,
            "not_before": cert.get("notBefore"),
            "not_after": cert.get("notAfter"),
            "chain_depth": len(chain) if chain else None,
        }
        result.update(
            {
                "status": "OK",
                "alpn": ssl_object.selected_alpn_protocol(),
                "version": ssl_object.version(),
                "cert": info,
            }
        )
    except asyncio.TimeoutError:
        result.update({"status": "TIMEOUT", "error": "TLS timeout"})
    except Exception as exc:  # pragma: no cover
        result.update({"status": "ERROR", "error": str(exc)})
    finally:
        if writer is not None:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:  # pragma: no cover
                pass
    return result


async def http_probe(
    host: str,
    session: aiohttp.ClientSession,
    bearer: Optional[str],
    user_agent: str,
    proxy: Optional[str],
) -> HTTPResult:
    result: HTTPResult = {"status": "SKIPPED"}
    headers = {
        "Accept": "*/*",
        "User-Agent": user_agent,
    }
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    url = f"https://{host}/"
    loop = asyncio.get_running_loop()
    start = loop.time()
    try:
        request_kwargs: Dict[str, Any] = {"headers": headers, "allow_redirects": True}
        if proxy:
            request_kwargs["proxy"] = proxy
        async with session.request("HEAD", url, **request_kwargs) as resp:
            time_ms = int((loop.time() - start) * 1000)
            result = {
                "status": "OK",
                "code": resp.status,
                "server": resp.headers.get("Server"),
                "via": resp.headers.get("Via"),
                "time_ms": time_ms,
                "akamai": _looks_akamai(resp.headers),
            }
            if resp.status == 405:
                # Retry with GET bytes=0-0
                get_headers = {**headers, "Range": "bytes=0-0"}
                get_kwargs: Dict[str, Any] = {
                    "headers": get_headers,
                    "allow_redirects": True,
                }
                if proxy:
                    get_kwargs["proxy"] = proxy
                async with session.get(url, **get_kwargs) as get_resp:
                    time_ms = int((loop.time() - start) * 1000)
                    result.update(
                        {
                            "status": "OK",
                            "code": get_resp.status,
                            "server": get_resp.headers.get("Server"),
                            "via": get_resp.headers.get("Via"),
                            "time_ms": time_ms,
                            "akamai": _looks_akamai(get_resp.headers),
                        }
                    )
    except asyncio.TimeoutError:
        result.update({"status": "TIMEOUT", "error": "HTTP timeout"})
    except aiohttp.ClientError as exc:
        result.update({"status": "ERROR", "error": str(exc)})
    return result


def _looks_akamai(headers: aiohttp.typedefs.LooseHeaders) -> bool:
    header_keys = {key.lower() for key in headers.keys()}
    if any("akamai" in key for key in header_keys):
        return True
    for value in headers.values():
        if isinstance(value, str) and "akamai" in value.lower():
            return True
    return False


async def run_with_retries(
    func: Callable[[], Awaitable[Any]],
    retries: int,
    base_delay: float = 0.5,
) -> Any:
    attempt = 0
    while True:
        try:
            return await func()
        except Exception:
            if attempt >= retries:
                raise
            delay = base_delay * (2 ** attempt)
            delay += random.uniform(0, 0.3)
            await asyncio.sleep(delay)
            attempt += 1


async def worker(
    name: str,
    queue: "asyncio.Queue[EndpointTask]",
    semaphore: asyncio.Semaphore,
    args: argparse.Namespace,
    session: aiohttp.ClientSession,
    results: List[EndpointResult],
    per_host_result: Dict[str, EndpointResult],
) -> None:
    logger = logging.getLogger(__name__)
    run_dns = not args.tls_only and not args.http_only
    run_tls = not args.dns_only and not args.http_only
    run_http = not args.dns_only and not args.tls_only
    while True:
        try:
            task = queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        try:
            await asyncio.sleep(random.uniform(0, 0.2))
            async with semaphore:
                logger.debug("[%s] processing %s", name, task.host)
                record: EndpointResult = {
                    "input": task.original,
                    "host": task.host,
                    "dns": {"status": "SKIPPED"},
                    "tls": {"status": "SKIPPED"},
                    "http": {"status": "SKIPPED"},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                # DNS
                if run_dns:
                    try:
                        dns_result = await run_with_retries(
                            lambda: resolve(task.host, args.timeout), args.retries
                        )
                    except Exception as exc:
                        dns_result = {"status": "ERROR", "error": str(exc)}
                    record["dns"] = dns_result
                # TLS
                if run_tls and dns_ok(record["dns"]):
                    try:
                        tls_result = await run_with_retries(
                            lambda: tls_probe(task.host, args.timeout), args.retries
                        )
                    except Exception as exc:
                        tls_result = {"status": "ERROR", "error": str(exc)}
                    record["tls"] = tls_result
                # HTTP
                if run_http and dns_ok(record["dns"]):
                    try:
                        http_result = await run_with_retries(
                            lambda: http_probe(
                                task.host,
                                session,
                                args.bearer,
                                args.user_agent,
                                args.proxy or None,
                            ),
                            args.retries,
                        )
                    except Exception as exc:
                        http_result = {"status": "ERROR", "error": str(exc)}
                    record["http"] = http_result
                results.append(record)
                per_host_result.setdefault(task.host, record)
        finally:
            queue.task_done()


def dns_ok(dns_result: DNSResult) -> bool:
    return dns_result.get("status") in {"OK", "SKIPPED"}


def write_outputs(
    results: Sequence[EndpointResult],
    per_host: Dict[str, EndpointResult],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "results.json"
    csv_path = output_dir / "results.csv"
    summary_path = output_dir / "summary.md"

    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump(results, json_file, indent=2)

    csv_headers = [
        "host",
        "dns_status",
        "first_ip",
        "is_private",
        "tls_status",
        "tls_version",
        "http_status",
        "http_code",
        "time_ms",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=csv_headers)
        writer.writeheader()
        for host, record in per_host.items():
            dns_info = record.get("dns", {})
            http_info = record.get("http", {})
            tls_info = record.get("tls", {})
            ips = dns_info.get("ips", [])
            writer.writerow(
                {
                    "host": host,
                    "dns_status": dns_info.get("status"),
                    "first_ip": ips[0] if ips else None,
                    "is_private": dns_info.get("is_private"),
                    "tls_status": tls_info.get("status"),
                    "tls_version": tls_info.get("version"),
                    "http_status": http_info.get("status"),
                    "http_code": http_info.get("code"),
                    "time_ms": http_info.get("time_ms"),
                }
            )

    summary_counts = compute_summary(per_host)
    with summary_path.open("w", encoding="utf-8") as summary_file:
        summary_file.write("# Endpoint Check Summary\n\n")
        summary_file.write(f"Total unique hosts: {summary_counts['total']}\n\n")
        summary_file.write("## DNS\n")
        summary_file.write(f"- Resolved: {summary_counts['dns_resolved']}\n")
        summary_file.write(f"- Unresolved: {summary_counts['dns_unresolved']}\n\n")
        summary_file.write("## HTTP\n")
        summary_file.write(f"- Reachable: {summary_counts['http_reachable']}\n")
        summary_file.write(f"- Unreachable: {summary_counts['http_unreachable']}\n\n")
        summary_file.write("### HTTP Codes\n")
        for family, count in summary_counts["http_codes"].items():
            summary_file.write(f"- {family}: {count}\n")


def compute_summary(per_host: Dict[str, EndpointResult]) -> Dict[str, Any]:
    dns_resolved = 0
    dns_unresolved = 0
    http_reachable = 0
    http_unreachable = 0
    http_codes: Dict[str, int] = defaultdict(int)

    for record in per_host.values():
        dns_status = record.get("dns", {}).get("status")
        if dns_status == "OK":
            dns_resolved += 1
        elif dns_status not in (None, "SKIPPED"):
            dns_unresolved += 1
        http_info = record.get("http", {})
        status = http_info.get("status")
        code = http_info.get("code")
        if status == "OK" and code is not None:
            http_reachable += 1
            family = f"{code // 100}xx"
            http_codes[family] += 1
        elif status == "OK":
            http_reachable += 1
            http_codes["unknown"] += 1
        elif status not in (None, "SKIPPED"):
            http_unreachable += 1
            http_codes[status or "unknown"] += 1

    return {
        "total": len(per_host),
        "dns_resolved": dns_resolved,
        "dns_unresolved": dns_unresolved,
        "http_reachable": http_reachable,
        "http_unreachable": http_unreachable,
        "http_codes": dict(http_codes),
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check endpoint reachability.")
    parser.add_argument(
        "--sources",
        nargs="*",
        type=Path,
        default=DEFAULT_SOURCE_FILES,
        help="Files containing endpoint hostnames",
    )
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=6.0)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--dns-only", action="store_true")
    parser.add_argument("--http-only", action="store_true")
    parser.add_argument("--tls-only", action="store_true")
    parser.add_argument("--keep-dupes", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("/tools/results.json"))
    parser.add_argument(
        "--user-agent",
        default="EA Endpoint Recon/1.0 (+https://ea.com)",
        help="User-Agent header value",
    )
    parser.add_argument("--proxy", default=None, help="HTTPS proxy URL")
    parser.add_argument("--bearer", default=None, help="Optional bearer token")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    return parser.parse_args(argv)


async def run(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    logger = logging.getLogger(__name__)

    if sum(1 for flag in (args.dns_only, args.tls_only, args.http_only) if flag) > 1:
        logger.error("Select at most one of --dns-only, --tls-only, or --http-only")
        return 1

    endpoints = await load_endpoints(args.sources, args.keep_dupes)
    if not endpoints:
        logger.error("No endpoints loaded; aborting")
        return 1
    logger.info("Loaded %d endpoints", len(endpoints))

    connector = aiohttp.TCPConnector(limit=args.concurrency)
    timeout = aiohttp.ClientTimeout(total=args.timeout)
    session_kwargs: Dict[str, Any] = {"connector": connector, "timeout": timeout}
    if args.proxy:
        session_kwargs["trust_env"] = True
    results: List[EndpointResult] = []
    per_host: Dict[str, EndpointResult] = {}

    queue: "asyncio.Queue[EndpointTask]" = asyncio.Queue()
    for task in endpoints:
        queue.put_nowait(task)

    semaphore = asyncio.Semaphore(args.concurrency)

    async with aiohttp.ClientSession(**session_kwargs) as session:
        tasks = [
            asyncio.create_task(
                worker(f"worker-{i}", queue, semaphore, args, session, results, per_host)
            )
            for i in range(args.concurrency)
        ]
        await asyncio.gather(*tasks)

    write_outputs(results, per_host, args.output_dir)
    logger.info("Wrote results to %s", args.output_dir)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
