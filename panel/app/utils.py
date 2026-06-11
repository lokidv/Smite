"""Utility functions for address parsing and validation"""
import ipaddress
import re
import secrets
import string
from typing import Tuple, Optional


def parse_address_port(address_str: str) -> Tuple[str, Optional[int], bool]:
    """
    Parse an address:port string, handling both IPv4 and IPv6 addresses.
    
    Supports formats:
    - IPv4: "127.0.0.1:8080" -> ("127.0.0.1", 8080, False)
    - IPv6: "[2001:db8::1]:8080" -> ("2001:db8::1", 8080, True)
    - IPv6: "2001:db8::1" -> ("2001:db8::1", None, True)
    - Hostname: "example.com:8080" -> ("example.com", 8080, False)
    
    Args:
        address_str: Address string in format "host:port" or "[ipv6]:port"
        
    Returns:
        Tuple of (host, port, is_ipv6) where port is None if not specified
    """
    if not address_str:
        return ("", None, False)
    
    address_str = address_str.strip()
    
    ipv6_bracket_match = re.match(r'^\[([^\]]+)\](?::(\d+))?$', address_str)
    if ipv6_bracket_match:
        host = ipv6_bracket_match.group(1)
        port_str = ipv6_bracket_match.group(2)
        port = int(port_str) if port_str else None
        return (host, port, True)
    
    try:
        ipaddress.IPv6Address(address_str)
        return (address_str, None, True)
    except (ValueError, ipaddress.AddressValueError):
        pass
    
    if ":" in address_str:
        parts = address_str.rsplit(":", 1)
        if len(parts) == 2:
            host_part = parts[0]
            port_str = parts[1]
            
            try:
                ipaddress.IPv6Address(host_part)
                return (host_part, int(port_str), True)
            except (ValueError, ipaddress.AddressValueError):
                try:
                    port = int(port_str)
                    return (host_part, port, False)
                except ValueError:
                    return (address_str, None, False)
    
    return (address_str, None, False)


def format_address_port(host: str, port: Optional[int] = None) -> str:
    """
    Format host and port into address:port string, handling IPv6 addresses.
    
    Args:
        host: Host address (IPv4, IPv6, or hostname)
        port: Port number (optional)
        
    Returns:
        Formatted string: "host:port" or "[ipv6]:port" or "host"
    """
    if not host:
        return ""
    
    try:
        ipaddress.IPv6Address(host)
        if port is not None:
            return f"[{host}]:{port}"
        return host
    except (ValueError, ipaddress.AddressValueError):
        if port is not None:
            return f"{host}:{port}"
        return host


def is_valid_ip_address(address: str) -> bool:
    """
    Check if a string is a valid IP address (IPv4 or IPv6).
    
    Args:
        address: String to validate
        
    Returns:
        True if valid IP address, False otherwise
    """
    try:
        ipaddress.ip_address(address)
        return True
    except (ValueError, ipaddress.AddressValueError):
        return False


def is_valid_ipv6_address(address: str) -> bool:
    """
    Check if a string is a valid IPv6 address.
    
    Args:
        address: String to validate
        
    Returns:
        True if valid IPv6 address, False otherwise
    """
    try:
        ipaddress.IPv6Address(address)
        return True
    except (ValueError, ipaddress.AddressValueError):
        return False


def generate_token(length: int = 16) -> str:
    """
    Generate a random secure token.
    
    Args:
        length: Length of the token (default: 16)
        
    Returns:
        Random token string
    """
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


# Port used by the FRP communication channel (the frps that runs on the panel
# so foreign nodes can reach back through a node-initiated tunnel). FRP tunnel
# cores must never reuse it: on a co-located panel+node host the tunnel's frps
# would fail to bind ("address already in use") and the foreign frpc would end
# up talking to the comm server instead, producing "token doesn't match".
FRP_COMM_RESERVED_PORT = 7000


def frp_safe_bind_port(tunnel_id: str, requested=None) -> int:
    """Pick an FRP tunnel control (bind) port that won't collide with the
    FRP communication channel.

    - If ``requested`` is a valid port other than the reserved comm port, keep it.
    - Otherwise derive a deterministic port in the 7100-7899 range from the
      tunnel id so the server (frps) and client (frpc) always agree.
    """
    import hashlib
    try:
        port = int(requested) if requested else 0
    except (ValueError, TypeError):
        port = 0
    if port and port != FRP_COMM_RESERVED_PORT:
        return port
    port_hash = int(hashlib.md5(tunnel_id.encode()).hexdigest()[:8], 16)
    return 7100 + (port_hash % 800)

