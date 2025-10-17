# Endpoint Recon Test Plan

## Scope and Objectives
- Validate DNS, TLS, and HTTPS reachability for Madden/MUT and GOS/Blaze endpoints that are relevant to console services.
- Exclude endpoints explicitly related to mobile (e.g., anything containing `maddenmobile`).
- Provide a throttled, non-destructive probe that can run without credentials but optionally accepts a bearer token for future scenarios.
- Capture results in machine-readable artifacts suitable for longitudinal tracking and comparisons.

## Safety Constraints
- Use only DNS queries, TLS handshakes, and HTTPS requests to listed hosts.
- Default timeouts (6 seconds) and concurrency (20) keep load minimal; each request includes a 0–200 ms random delay to avoid bursts.
- Respect retries (default 1) with exponential backoff and jitter; avoid hammering the same host unless `--keep-dupes` is provided.
- Treat HTTP `401` and `403` responses as success (reachable but restricted) and avoid credentialed or state-changing operations.

## Test Execution

### Prerequisites
- Python 3.11 or newer on macOS or Linux.
- Create a virtual environment (`uv venv` or `python -m venv .venv`) and install requirements (`pip install -r requirements.txt` or equivalent).
- Ensure `aiohttp` and `dnspython` are installed.

### Running the Harness
```bash
python tools/check_endpoints.py \
  --sources lists/master_madden_gos_list.txt lists/gos_subdomains_full.txt \
  --concurrency 20 --timeout 6 --retries 1
```
Optional flags:
- `--dns-only`, `--tls-only`, `--http-only` to restrict phases.
- `--keep-dupes` to process duplicate hosts exactly as listed.
- `--bearer <token>` to include an `Authorization: Bearer` header for future authenticated checks (still no credential requirement by default).
- `--proxy https://proxy.example:8443` to route HTTPS traffic through a proxy.
- `--output-dir /custom/path` to write artifacts elsewhere.

### Expected Outcomes
- `dns.status` reflects `OK`, `NXDOMAIN`, or timeout/error, with resolved IPs and a `is_private` boolean.
- `tls.status` reports `OK` when the handshake completes, including certificate subject/issuer, SANs, validity window, ALPN, and TLS version.
- `http.status` reports `OK` for any completed request (including `401/403/503` codes), with latency (ms) and key headers. `TIMEOUT` or `ERROR` indicate failure to reach the service.
- Summary markdown (`/out/summary.md`) aggregates counts for resolved/unresolved hosts, HTTP reachability, and response codes by family.

### Data Model
Each record in `results.json` adheres to:
```json
{
  "input": "madden.easports.com",
  "host": "madden.easports.com",
  "dns": {"status": "OK", "ips": ["159.153.226.34"], "is_private": false, "ptr": "origin.example.com"},
  "tls": {"status": "OK", "alpn": "h2", "version": "TLSv1.3", "cert": {"cn": "madden.easports.com", "sans": ["madden.easports.com"], "issuer": "DigiCert Inc", "not_before": "2024-03-01T00:00:00Z", "not_after": "2025-03-01T23:59:59Z", "chain_depth": 2}},
  "http": {"status": "OK", "code": 200, "server": "nginx", "via": null, "time_ms": 212, "akamai": false},
  "timestamp": "2024-05-12T18:22:33Z"
}
```

The flattened CSV (`results.csv`) contains one row per unique host with representative values:
```csv
host,dns_status,first_ip,is_private,tls_status,tls_version,http_status,http_code,time_ms
madden.easports.com,OK,159.153.226.34,false,OK,TLSv1.3,OK,200,212
```

### Interpreting HTTP Results
- `2xx/3xx`: Service is reachable and responding normally.
- `401/403`: Host reached but access is restricted; this is expected for secure services.
- `5xx`: Service is reachable but experiencing server-side issues; still classified as reachable.
- `TIMEOUT`/`ERROR`: Host could not be contacted (network failure, refused connection, or other fatal issue).

## Maintenance Notes
- Add or update source lists under `/lists/`. The harness accepts multiple files via `--sources`; by default it looks for `lists/master_madden_gos_list.txt` and `lists/gos_subdomains_full.txt`.
- If the default files are absent, the tool falls back to an embedded seed list covering core Madden and GOS hosts.
- Keep Python dependencies pinned in `requirements.txt` / `pyproject.toml` to ensure reproducibility. Update them when adding new capabilities (e.g., newer `aiohttp` releases).
- Review summary output regularly to detect regressions in endpoint reachability and certificate freshness.
- CI can invoke the script with conservative settings (e.g., `--dns-only`) on a schedule to monitor DNS reachability without stressing the services.

