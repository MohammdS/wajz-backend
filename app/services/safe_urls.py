import ipaddress
import socket
from urllib.parse import urlparse

import httpx

MAX_RESPONSE_BYTES = 2_000_000
MAX_REDIRECTS = 3


def validate_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only public HTTP and HTTPS URLs are allowed")
    if parsed.username or parsed.password:
        raise ValueError("Credentials in URLs are not allowed")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443)
    except socket.gaierror as exc:
        raise ValueError("URL hostname could not be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("Private or reserved network targets are not allowed")
    return url


def fetch_public_url(url: str, *, timeout: float = 15.0) -> httpx.Response:
    current = validate_public_url(url)
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            response = client.get(current, headers={"User-Agent": "WajzBot/0.1"})
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise ValueError("Redirect target is missing")
                current = validate_public_url(str(response.url.join(location)))
                continue
            response.raise_for_status()
            if len(response.content) > MAX_RESPONSE_BYTES:
                raise ValueError("Response is too large")
            return response
    raise ValueError("Too many redirects")
