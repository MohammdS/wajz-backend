"""SSRF-resistant fetching for admin-supplied article URLs."""

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.services.cleaning import clean_text

MAX_REDIRECTS = 4
MAX_RESPONSE_BYTES = 2_000_000
BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
    "instance-data",
}


def validate_public_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only public http and https URLs are allowed")
    hostname = parsed.hostname.rstrip(".").lower()
    if (
        hostname in BLOCKED_HOSTS
        or hostname.endswith(".local")
        or hostname.endswith(".internal")
        or hostname.endswith(".localhost")
    ):
        raise ValueError("Local and internal hosts are blocked")
    try:
        addresses = {
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(hostname, parsed.port or 443)
        }
    except socket.gaierror as exc:
        raise ValueError("Host could not be resolved") from exc
    for address in addresses:
        if not address.is_global:
            raise ValueError("Private, loopback, link-local, and reserved IPs are blocked")
    return parsed.geturl()


def fetch_article_url(url: str) -> dict:
    current = validate_public_url(url)
    headers = {
        "User-Agent": "WajzAdminFetcher/1.0 (+source-grounded news studio)",
        "Accept": "text/html,application/xhtml+xml",
    }
    with httpx.Client(timeout=20.0, follow_redirects=False, headers=headers) as client:
        for _ in range(MAX_REDIRECTS + 1):
            response = client.get(current)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise ValueError("Redirect response did not include a location")
                current = validate_public_url(urljoin(current, location))
                continue
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if "text/html" not in content_type:
                raise ValueError("URL must return an HTML article")
            if len(response.content) > MAX_RESPONSE_BYTES:
                raise ValueError("Article response is too large")
            soup = BeautifulSoup(response.text, "html.parser")
            title = (
                (soup.find("meta", property="og:title") or {}).get("content")
                or (soup.title.string if soup.title and soup.title.string else "")
            ).strip()
            article_node = soup.find("article") or soup.body
            raw = str(article_node or "")
            cleaned = clean_text(raw)
            if not title or len(cleaned) < 80:
                raise ValueError("Could not extract enough article content")
            return {
                "url": current,
                "title": title[:1000],
                "raw_text": raw,
                "cleaned_text": cleaned[:100_000],
                "hostname": urlparse(current).hostname or "External source",
            }
    raise ValueError("Too many redirects")
