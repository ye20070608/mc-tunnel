"""Self-signed SSL certificate generation.

Generates a persistent self-signed X.509 certificate + RSA key pair
on first run.  Subsequent runs reuse the stored files.

Uses the ``cryptography`` library for X.509 construction.
"""

from __future__ import annotations

import ipaddress
import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


def ensure_ssl_cert(
    cert_path: str | Path,
    key_path: str | Path,
    logger=None,
) -> tuple[Path, Path]:
    """Ensure SSL certificate and key files exist, generating them if missing.

    If both files already exist and are valid PEM, returns immediately.
    If one exists and the other does not, raises FileNotFoundError
    (mismatch — never overwrite a lone file).

    The generated certificate is self-signed with:
      - RSA 2048-bit key
      - SHA-256 signature hash
      - 10-year validity
      - SAN entries: 127.0.0.1, localhost

    Args:
        cert_path: Path to the PEM certificate file.
        key_path: Path to the PEM private key file.
        logger: Optional logger instance.

    Returns:
        Tuple of ``(cert_path, key_path)`` resolved to absolute Paths.

    Raises:
        FileNotFoundError: If one file exists but the other is missing.
        ValueError: If existing files contain invalid PEM data.
    """
    cert = Path(cert_path)
    key = Path(key_path)

    cert_exists = cert.exists()
    key_exists = key.exists()

    # Case 1: Both exist — validate and return
    if cert_exists and key_exists:
        _validate_pem(cert, "CERTIFICATE")
        _validate_pem(key, "PRIVATE KEY")
        if logger:
            logger.info("SSL certificate and key found at: {} / {}", cert, key)
        return (cert.resolve(), key.resolve())

    # Case 2: One exists but not the other — error (never overwrite)
    if cert_exists != key_exists:
        missing = "key" if cert_exists else "certificate"
        existing = cert if cert_exists else key
        raise FileNotFoundError(
            f"SSL {missing} file missing while {existing.name} exists; "
            f"cannot generate a matching pair. "
            f"Either provide both files or remove the existing one to regenerate."
        )

    # Case 3: Neither exists — generate
    if logger:
        logger.info("Generating self-signed SSL certificate...")

    cert.parent.mkdir(parents=True, exist_ok=True)

    # Import here to avoid hard dependency at module level
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    # Generate RSA key pair
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Build certificate
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "MC Tunnel Controller Self-Signed"),
    ])

    now = datetime.now(timezone.utc)
    cert_obj = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=3650))  # 10 years
        .add_extension(
            x509.SubjectAlternativeName([
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                x509.DNSName("localhost"),
            ]),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                key_cert_sign=False,
                key_agreement=False,
                content_commitment=False,
                data_encipherment=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )

    # Write private key (PEM, unencrypted)
    key_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key.write_bytes(key_bytes)
    # Restrict permissions on POSIX systems
    if os.name != "nt":
        key.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0o600

    # Write certificate (PEM)
    cert_bytes = cert_obj.public_bytes(serialization.Encoding.PEM)
    cert.write_bytes(cert_bytes)

    if logger:
        logger.info("Self-signed certificate generated:")
        logger.info("  Certificate: {}", cert.resolve())
        logger.info("  Private key:  {}", key.resolve())
        logger.info(
            "  Validity: {} to {}",
            now.strftime("%Y-%m-%d"),
            (now + timedelta(days=3650)).strftime("%Y-%m-%d"),
        )
        logger.warning(
            "Self-signed certificate will show a browser warning. "
            "This is normal for local management tools."
        )
        logger.warning(
            "To suppress the warning, replace config/certs/ with a trusted certificate."
        )

    return (cert.resolve(), key.resolve())


def _validate_pem(path: Path, expected_label: str) -> None:
    """Quick sanity check that *path* contains valid PEM with *expected_label*.

    For private keys, accepts both ``PRIVATE KEY`` and ``RSA PRIVATE KEY``.
    """
    try:
        text = path.read_text(encoding="ascii")
    except Exception as exc:
        raise ValueError(f"File is not valid PEM (not ASCII): {path}") from exc

    if f"-----BEGIN {expected_label}-----" in text:
        return  # exact match
    # For private keys, also accept RSA/EC/etc. variants
    if expected_label == "PRIVATE KEY" and "-----BEGIN " in text and "PRIVATE KEY-----" in text:
        return
    raise ValueError(
        f"File {path} does not contain a {expected_label} PEM block; "
        f"remove it to regenerate, or provide valid PEM files."
    )
