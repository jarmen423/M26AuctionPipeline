from mitmproxy import http
from mitmproxy import ctx

relevant_domains = [
    "accounts.ea.com",
    "eaaccounts.akamaized.net",
    "gateway.ea.com",
    "wal2.tools.gos.bio-iad.ea.com",
    "wal.tools.gos.bio-iad.ea.com",
    "blaze.ea.com",
    "login.ea.com"
]

def request(flow: http.HTTPFlow) -> None:
    host = flow.request.pretty_host.lower()
    if any(domain in host for domain in relevant_domains):
        ctx.log.info(f"Captured request: {flow.request.method} {flow.request.pretty_url}")
    else:
        # Optionally drop unrelated flows to keep the file small
        flow.response = None
        flow.request.content = b""
        flow.response = http.Response.make(204)  # No content

def response(flow: http.HTTPFlow) -> None:
    host = flow.request.pretty_host.lower()
    if any(domain in host for domain in relevant_domains):
        ctx.log.info(f"Captured response: {flow.response.status_code} {flow.request.pretty_url}")