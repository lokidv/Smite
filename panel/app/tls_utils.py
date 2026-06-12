"""TLS material generation for the WireGuard Stealth (rathole over TLS) carrier.

The reverse rathole tunnel uses rathole's native ``tls`` transport so the
foreign->iran control connection looks like an ordinary HTTPS/TLS session to a
real-looking host (fake SNI, e.g. ``www.digikala.com``). rathole's TLS server
loads a PKCS#12 identity; its TLS client trusts a CA PEM and sends the SNI as
``hostname``. We generate a single self-signed cert (CN + SAN = the fake SNI),
package it as PKCS#12 for the iran (server) side, and hand the same cert (PEM)
to the foreign (client) side as the trusted root.

Everything is generated on the panel once per tunnel and stored in the tunnel
spec so re-applies/benchmarks stay consistent without any node round-trip.
"""
from __future__ import annotations

import base64
import datetime
from typing import Dict

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from app.utils import generate_token

DEFAULT_STEALTH_SNI = "www.digikala.com"


def generate_wg_stealth_cert(sni: str | None = None, password: str | None = None) -> Dict[str, str]:
    """Generate a self-signed cert for the stealth carrier.

    Returns a dict with base64-encoded PKCS#12 (server identity), the PKCS#12
    password, the base64-encoded CA/cert PEM (client trusted_root), and the SNI
    the client must present (must match the cert SAN for verification to pass).
    """
    sni = (sni or DEFAULT_STEALTH_SNI).strip() or DEFAULT_STEALTH_SNI
    password = password or generate_token(16)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, sni)])
    now = datetime.datetime.utcnow()
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        # rustls/native-tls verify against the SAN, not the CN.
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(sni)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    ca_pem = cert.public_bytes(serialization.Encoding.PEM)
    p12 = pkcs12.serialize_key_and_certificates(
        name=b"smite-wg-stealth",
        key=key,
        cert=cert,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(password.encode()),
    )

    return {
        "pkcs12_b64": base64.b64encode(p12).decode("ascii"),
        "pkcs12_password": password,
        "ca_pem_b64": base64.b64encode(ca_pem).decode("ascii"),
        "sni": sni,
    }


def ensure_wg_stealth_materials(spec: dict, default_sni: str | None = None) -> bool:
    """Ensure a rathole-TLS spec carries cert material. Returns True if it added it.

    Idempotent: if a PKCS#12 is already present we leave it untouched so the
    server (iran) and client (foreign) always agree on the same identity across
    re-applies and benchmarks.
    """
    if spec.get("tls_pkcs12_b64") and spec.get("tls_ca_pem_b64"):
        return False
    sni = spec.get("sni") or default_sni or DEFAULT_STEALTH_SNI
    material = generate_wg_stealth_cert(sni, spec.get("tls_pkcs12_password"))
    spec["tls_pkcs12_b64"] = material["pkcs12_b64"]
    spec["tls_pkcs12_password"] = material["pkcs12_password"]
    spec["tls_ca_pem_b64"] = material["ca_pem_b64"]
    spec["sni"] = material["sni"]
    return True
