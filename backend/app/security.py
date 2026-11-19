import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURL(ValueError):
    pass


# RFC 6052 well-known NAT64 prefix. IPv6-only ISPs (DNS64) return addresses in it
# that wrap a site's IPv4 address, e.g. 64:ff9b::7712:3692 = 119.18.54.146.
NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")


def _effective_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address):
    """Unwrap IPv6 forms that carry an IPv4 address, so the real target is checked.

    Python marks all of 64:ff9b::/96 as reserved, which would refuse every public
    site on a NAT64 network; checking the embedded IPv4 keeps 64:ff9b::7f00:1
    (127.0.0.1) refused while allowing public sites.
    """
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            return ip.ipv4_mapped
        if ip in NAT64_PREFIX:
            return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip


def _assert_safe_host(host: str, port: int | None = None) -> None:
    if not host or host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise UnsafeURL("Local hosts are not allowed")
    try:
        addresses = socket.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise UnsafeURL("Host could not be resolved") from exc
    for address in addresses:
        ip = _effective_ip(ipaddress.ip_address(address[4][0]))
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise UnsafeURL("Private or reserved network targets are not allowed")


def validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise UnsafeURL("Only HTTP(S) URLs are allowed")
    host = parsed.hostname.rstrip(".").lower()
    if len(url) > 2048:
        raise UnsafeURL("URL is too long")
    _assert_safe_host(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    return parsed.geturl()


def validate_redirect(url: str, allowed_host: str) -> str:
    safe_url = validate_url(url)
    if urlparse(safe_url).netloc.lower() != allowed_host.lower():
        raise UnsafeURL("Redirect leaves the audited domain")
    return safe_url
