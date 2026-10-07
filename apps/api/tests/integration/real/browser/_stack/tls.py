"""A throwaway CA and a localhost certificate it signs, for the fixture site's https origin.

A secret is typed only on an https page of its site, so origin A is served over
TLS. The hosts trust the CA through BROWSER_HOST_TEST_CA_FILE; nothing else does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

#: Long enough for any one test session.
_VALID_FOR = timedelta(days=2)


@dataclass(frozen=True)
class FixtureTls:
    """Where the CA certificate, the server's chain and its key were written."""

    ca_file: Path
    chain_file: Path
    key_file: Path


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def issue(directory: Path) -> FixtureTls:
    """Write a CA and a certificate for localhost and 127.0.0.1 it signs; the chain file carries both."""
    now = datetime.now(UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca = (
        x509.CertificateBuilder()
        .subject_name(_name("browser stack test CA"))
        .issuer_name(_name("browser stack test CA"))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + _VALID_FOR)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        x509.CertificateBuilder()
        .subject_name(_name("localhost"))
        .issuer_name(ca.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + _VALID_FOR)
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([x509.OID_SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    tls = FixtureTls(
        ca_file=directory / "fixture-ca.pem",
        chain_file=directory / "fixture-chain.pem",
        key_file=directory / "fixture-key.pem",
    )
    ca_pem = ca.public_bytes(serialization.Encoding.PEM)
    tls.ca_file.write_bytes(ca_pem)
    tls.chain_file.write_bytes(leaf.public_bytes(serialization.Encoding.PEM) + ca_pem)
    tls.key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return tls
