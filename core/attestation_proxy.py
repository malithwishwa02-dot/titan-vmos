"""
Remote Attestation Proxy — Play Integrity Bypass Architecture
=============================================================
Implements the attestation delegation pattern for bypassing hardware-backed
key attestation in virtualized environments.

The RKP (Remote Key Provisioning) era has made static keybox injection
obsolete. This module provides two approaches:

1. TEE Simulation (TEESimulator-style)
   - Hooks Binder IPC calls to keystore daemon
   - Manages virtual self-consistent cryptographic keys
   - Simulates hardware-backed attestation responses

2. Remote Attestation Delegation
   - Intercepts attestation requests from applications
   - Forwards to physical "host" device with genuine TEE
   - Returns authentic hardware-backed certificate chains

Based on: "Bypassing Key Attestation API with Remote Devices" (Guardsquare)
and TEESimulator (JingMatrix/TEESimulator)
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import secrets
import struct
import time
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, Callable, Dict, List, Optional, Tuple
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography import x509
from cryptography.x509.oid import NameOID
from datetime import datetime, timedelta

logger = logging.getLogger("titan.attestation-proxy")


class SecurityLevel(IntEnum):
    """Android KeyMint security levels."""
    SOFTWARE = 0
    TRUSTED_ENVIRONMENT = 1      # TEE (TrustZone)
    STRONGBOX = 2                # Secure Element


class AttestationResult(Enum):
    """Play Integrity API verdict types."""
    MEETS_BASIC_INTEGRITY = "MEETS_BASIC_INTEGRITY"
    MEETS_DEVICE_INTEGRITY = "MEETS_DEVICE_INTEGRITY"
    MEETS_STRONG_INTEGRITY = "MEETS_STRONG_INTEGRITY"


@dataclass
class KeyAttestationRequest:
    """Represents a key attestation request from an application."""
    package_name: str
    challenge: bytes              # Server-provided nonce
    key_alias: str
    key_purposes: List[int] = field(default_factory=list)
    attestation_type: str = "key"  # "key" or "id"
    include_props: bool = True
    timestamp: float = field(default_factory=time.time)


@dataclass
class AttestationResponse:
    """Response containing certificate chain and attestation data."""
    success: bool
    certificate_chain: List[bytes] = field(default_factory=list)
    attestation_extension: bytes = b""
    security_level: SecurityLevel = SecurityLevel.TRUSTED_ENVIRONMENT
    error: str = ""
    source: str = "simulated"    # "simulated", "delegated", "cached"


class VirtualKeyStore:
    """
    Simulates Android hardware-backed keystore operations.
    
    Manages virtual cryptographic keys that produce self-consistent
    attestation responses without actual hardware TEE.
    """

    # ASN.1 OID for Android Key Attestation Extension
    ATTESTATION_EXTENSION_OID = "1.3.6.1.4.1.11129.2.1.17"
    
    # Google's attestation root certificate (public)
    GOOGLE_ROOT_CERT_PEM = """-----BEGIN CERTIFICATE-----
MIICizCCAjKgAwIBAgIJAKIFntEOQ1tXMAoGCCqGSM49BAMCMIGiMQswCQYDVQQG
EwJVUzETMBEGA1UECAwKQ2FsaWZvcm5pYTEWMBQGA1UEBwwNTW91bnRhaW4gVmll
dzEQMA4GA1UECgwHQW5kcm9pZDEQMA4GA1UECwwHQW5kcm9pZDEiMCAGA1UEAwwZ
QW5kcm9pZCBLZXlzdG9yZSBTb2Z0d2FyZTEeMBwGCSqGSIb3DQEJARYPYXZiQGdv
b2dsZS5jb20wHhcNMTYwMTExMDA0MzUwWhcNMzYwMTA2MDA0MzUwWjCBojELMAkG
A1UEBhMCVVMxEzARBgNVBAgMCkNhbGlmb3JuaWExFjAUBgNVBAcMDU1vdW50YWlu
IFZpZXcxEDAOBgNVBAoMB0FuZHJvaWQxEDAOBgNVBAsMB0FuZHJvaWQxIjAgBgNV
BAMMGUFuZHJvaWQgS2V5c3RvcmUgU29mdHdhcmUxHjAcBgkqhkiG9w0BCQEWD2F2
YkBnb29nbGUuY29tMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE7l1ex+HA220D
pfhVm7bwF+z+u7HEn8n3p4bvMj90YjcMPJKwDQ6z8q0xCyL1UrKHzO1OKNKpAiE9
7BZp0Fq7hqNjMGEwHQYDVR0OBBYEFMit6XdMRcOjzw0WEOR5QzohWjDPMB8GA1Ud
IwQYMBaAFMit6XdMRcOjzw0WEOR5QzohWjDPMA8GA1UdEwEB/wQFMAMBAf8wDgYD
VR0PAQH/BAQDAgKEMAoGCCqGSM49BAMCA0cAMEQCIDUho++LNEYenNVg8x1YiSBq
3KNlQfYNns6KGYxmSGB7AiBNC/NR2TB8fVvaNTQdqEcbY6WFZTytTySn502vQX3x
vw==
-----END CERTIFICATE-----"""

    def __init__(self, device_info: Dict[str, Any] = None):
        """
        Initialize virtual keystore.
        
        Args:
            device_info: Device properties for attestation extension
        """
        self.device_info = device_info or self._default_device_info()
        self._keys: Dict[str, Tuple[ec.EllipticCurvePrivateKey, bytes]] = {}
        self._attestation_cache: Dict[str, AttestationResponse] = {}
        
        # Generate root and intermediate CA keys
        self._root_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
        self._intermediate_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
        
        # Generate self-signed root certificate
        self._root_cert = self._generate_root_cert()
        self._intermediate_cert = self._generate_intermediate_cert()

    def _default_device_info(self) -> Dict[str, Any]:
        """Default device info for Samsung Galaxy S24."""
        return {
            "brand": "samsung",
            "device": "e3q",
            "product": "e3qxxx",
            "model": "SM-S928B",
            "manufacturer": "samsung",
            "os_version": "14",
            "os_patch_level": "2024-03-01",
            "vendor_patch_level": "2024-03-01",
            "boot_patch_level": "2024-03-01",
            "verified_boot_state": "green",
            "device_locked": True,
            "fingerprint": "samsung/e3qxxx/e3q:14/UP1A.231005.007/S928BXXU1AXCA:user/release-keys",
        }

    def _generate_root_cert(self) -> x509.Certificate:
        """Generate simulated attestation root certificate."""
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "California"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "Mountain View"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Google LLC"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Android Keystore Software Attestation Root"),
        ])
        
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(self._root_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.utcnow() - timedelta(days=365))
            .not_valid_after(datetime.utcnow() + timedelta(days=3650))
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=1),
                critical=True,
            )
            .add_extension(
                x509.KeyUsage(
                    key_cert_sign=True,
                    crl_sign=True,
                    digital_signature=False,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .sign(self._root_key, hashes.SHA256(), default_backend())
        )
        
        return cert

    def _generate_intermediate_cert(self) -> x509.Certificate:
        """Generate intermediate CA certificate."""
        subject = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "California"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Google LLC"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Android Keystore Software Attestation Intermediate"),
        ])
        
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(self._root_cert.subject)
            .public_key(self._intermediate_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.utcnow() - timedelta(days=180))
            .not_valid_after(datetime.utcnow() + timedelta(days=1825))
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=0),
                critical=True,
            )
            .sign(self._root_key, hashes.SHA256(), default_backend())
        )
        
        return cert

    def generate_key(self, alias: str, algorithm: str = "EC") -> bytes:
        """
        Generate a new key pair in the virtual keystore.
        
        Args:
            alias: Key alias
            algorithm: "EC" (ECDSA P-256) or "RSA"
        
        Returns:
            Public key bytes
        """
        if algorithm == "EC":
            private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
        else:
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend()
            )
        
        public_key_bytes = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        
        self._keys[alias] = (private_key, public_key_bytes)
        return public_key_bytes

    def _build_attestation_extension(self, 
                                      challenge: bytes,
                                      key_purposes: List[int],
                                      security_level: SecurityLevel) -> bytes:
        """
        Build Android Key Attestation Extension (ASN.1 DER encoded).
        
        This extension contains device information that apps use to verify
        the key was generated in a secure environment.
        """
        # Simplified attestation extension structure
        # In production, this would be full ASN.1 encoding
        
        extension_data = {
            "attestationVersion": 200,  # Version 200 = Android 14
            "attestationSecurityLevel": security_level.value,
            "keymasterVersion": 200,
            "keymasterSecurityLevel": security_level.value,
            "attestationChallenge": base64.b64encode(challenge).decode(),
            "uniqueId": "",
            "softwareEnforced": {
                "creationDateTime": int(time.time() * 1000),
            },
            "teeEnforced": {
                "purpose": key_purposes,
                "algorithm": 3,  # EC
                "keySize": 256,
                "digest": [4],  # SHA-256
                "ecCurve": 1,  # P-256
                "noAuthRequired": True,
                "origin": 0,  # Generated
                "rootOfTrust": {
                    "verifiedBootKey": hashlib.sha256(
                        self.device_info["fingerprint"].encode()
                    ).hexdigest()[:64],
                    "deviceLocked": self.device_info.get("device_locked", True),
                    "verifiedBootState": 0,  # Verified (green)
                    "verifiedBootHash": secrets.token_hex(32),
                },
                "osVersion": int(self.device_info["os_version"]) * 10000,
                "osPatchLevel": int(self.device_info["os_patch_level"].replace("-", "")[:6]),
                "vendorPatchLevel": int(self.device_info["vendor_patch_level"].replace("-", "")[:6]),
                "bootPatchLevel": int(self.device_info["boot_patch_level"].replace("-", "")[:6]),
                "attestationIdBrand": self.device_info["brand"],
                "attestationIdDevice": self.device_info["device"],
                "attestationIdProduct": self.device_info["product"],
                "attestationIdManufacturer": self.device_info["manufacturer"],
                "attestationIdModel": self.device_info["model"],
            }
        }
        
        # Encode as JSON for simplicity (real implementation uses ASN.1)
        return json.dumps(extension_data).encode()

    def attest_key(self, request: KeyAttestationRequest) -> AttestationResponse:
        """
        Generate attestation certificate chain for a key.
        
        Args:
            request: Attestation request details
        
        Returns:
            AttestationResponse with certificate chain
        """
        alias = request.key_alias
        
        # Generate key if not exists
        if alias not in self._keys:
            self.generate_key(alias)
        
        private_key, public_key_bytes = self._keys[alias]
        
        # Determine security level based on request
        security_level = SecurityLevel.TRUSTED_ENVIRONMENT
        
        # Build attestation extension
        attestation_ext = self._build_attestation_extension(
            challenge=request.challenge,
            key_purposes=request.key_purposes or [2, 3],  # Sign, Verify
            security_level=security_level
        )
        
        # Generate leaf certificate with attestation extension
        subject = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, f"Android Keystore Key ({alias})"),
        ])
        
        leaf_cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(self._intermediate_cert.subject)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.utcnow() - timedelta(hours=1))
            .not_valid_after(datetime.utcnow() + timedelta(days=365))
            .add_extension(
                x509.UnrecognizedExtension(
                    x509.ObjectIdentifier(self.ATTESTATION_EXTENSION_OID),
                    attestation_ext
                ),
                critical=False,
            )
            .sign(self._intermediate_key, hashes.SHA256(), default_backend())
        )
        
        # Build certificate chain: [leaf, intermediate, root]
        cert_chain = [
            leaf_cert.public_bytes(serialization.Encoding.DER),
            self._intermediate_cert.public_bytes(serialization.Encoding.DER),
            self._root_cert.public_bytes(serialization.Encoding.DER),
        ]
        
        return AttestationResponse(
            success=True,
            certificate_chain=cert_chain,
            attestation_extension=attestation_ext,
            security_level=security_level,
            source="simulated"
        )


class RemoteAttestationProxy:
    """
    Delegates attestation requests to physical devices with genuine TEE.
    
    Architecture:
    1. Intercept attestation request in virtual container
    2. Forward challenge + metadata to remote attestation server
    3. Physical device generates genuine hardware-backed attestation
    4. Return authentic certificate chain to virtual container
    
    This completely bypasses RKP rotation and CRL revocation since
    attestations are genuinely generated by compliant hardware.
    """

    def __init__(self, 
                 relay_endpoint: str = None,
                 api_key: str = None,
                 timeout: float = 30.0):
        """
        Initialize remote attestation proxy.
        
        Args:
            relay_endpoint: URL of attestation relay server
            api_key: Authentication key for relay server
            timeout: Request timeout in seconds
        """
        self.relay_endpoint = relay_endpoint
        self.api_key = api_key
        self.timeout = timeout
        self._session = None
        
        # Fallback to local simulation if no relay configured
        self._local_keystore = VirtualKeyStore()

    async def _get_session(self):
        """Get or create HTTP session."""
        if self._session is None:
            import httpx
            self._session = httpx.AsyncClient(timeout=self.timeout)
        return self._session

    async def request_attestation(self, 
                                   request: KeyAttestationRequest) -> AttestationResponse:
        """
        Request attestation from remote physical device.
        
        Args:
            request: Attestation request details
        
        Returns:
            AttestationResponse with genuine certificate chain
        """
        # If no relay endpoint, use local simulation
        if not self.relay_endpoint:
            logger.info("No relay endpoint configured, using local TEE simulation")
            return self._local_keystore.attest_key(request)
        
        try:
            session = await self._get_session()
            
            # Prepare relay request
            payload = {
                "package_name": request.package_name,
                "challenge": base64.b64encode(request.challenge).decode(),
                "key_alias": request.key_alias,
                "key_purposes": request.key_purposes,
                "attestation_type": request.attestation_type,
                "timestamp": request.timestamp,
            }
            
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            
            response = await session.post(
                f"{self.relay_endpoint}/attest",
                json=payload,
                headers=headers
            )
            
            if response.status_code != 200:
                logger.warning(f"Remote attestation failed: {response.status_code}")
                return self._local_keystore.attest_key(request)
            
            data = response.json()
            
            # Decode certificate chain
            cert_chain = [
                base64.b64decode(cert) 
                for cert in data.get("certificate_chain", [])
            ]
            
            return AttestationResponse(
                success=True,
                certificate_chain=cert_chain,
                attestation_extension=base64.b64decode(
                    data.get("attestation_extension", "")
                ),
                security_level=SecurityLevel(data.get("security_level", 1)),
                source="delegated"
            )
            
        except Exception as e:
            logger.error(f"Remote attestation error: {e}")
            # Fallback to local simulation
            return self._local_keystore.attest_key(request)

    async def close(self):
        """Close HTTP session."""
        if self._session:
            await self._session.aclose()
            self._session = None


class PlayIntegritySimulator:
    """
    Simulates Play Integrity API responses.
    
    Generates integrity verdicts that satisfy app-level checks
    without requiring actual Play Integrity API calls.
    """

    def __init__(self, 
                 keystore: VirtualKeyStore = None,
                 device_info: Dict[str, Any] = None):
        self.keystore = keystore or VirtualKeyStore(device_info)
        self.device_info = device_info or self.keystore.device_info

    def generate_integrity_token(self,
                                  nonce: str,
                                  package_name: str) -> Dict[str, Any]:
        """
        Generate Play Integrity API token response.
        
        Args:
            nonce: Server-provided nonce (base64)
            package_name: Requesting app package name
        
        Returns:
            Integrity token response structure
        """
        # Decode and validate nonce
        try:
            nonce_bytes = base64.b64decode(nonce)
        except:
            nonce_bytes = nonce.encode()
        
        timestamp_ms = int(time.time() * 1000)
        
        # Build integrity payload
        payload = {
            "requestDetails": {
                "requestPackageName": package_name,
                "timestampMillis": timestamp_ms,
                "nonce": base64.b64encode(nonce_bytes).decode(),
            },
            "appIntegrity": {
                "appRecognitionVerdict": "PLAY_RECOGNIZED",
                "packageName": package_name,
                "certificateSha256Digest": [
                    hashlib.sha256(secrets.token_bytes(32)).hexdigest().upper()
                ],
                "versionCode": "1",
            },
            "deviceIntegrity": {
                "deviceRecognitionVerdict": [
                    "MEETS_DEVICE_INTEGRITY",
                    "MEETS_BASIC_INTEGRITY",
                ]
            },
            "accountDetails": {
                "appLicensingVerdict": "LICENSED"
            },
            "environmentDetails": {
                "playProtectVerdict": "NO_ISSUES",
                "appAccessRiskVerdict": {
                    "appsDetected": []
                }
            }
        }
        
        # Sign payload (simplified - real implementation uses JWS)
        payload_json = json.dumps(payload)
        payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode()
        
        # Generate signature
        key_alias = f"play_integrity_{secrets.token_hex(4)}"
        self.keystore.generate_key(key_alias)
        private_key, _ = self.keystore._keys[key_alias]
        
        signature = private_key.sign(
            payload_json.encode(),
            ec.ECDSA(hashes.SHA256())
        )
        signature_b64 = base64.urlsafe_b64encode(signature).decode()
        
        # Build JWT-like token
        header = {"alg": "ES256", "typ": "JWT"}
        header_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).decode()
        
        token = f"{header_b64}.{payload_b64}.{signature_b64}"
        
        return {
            "token": token,
            "payload": payload,
            "timestamp": timestamp_ms,
        }

    def verify_verdict(self, 
                       required_level: str = "MEETS_DEVICE_INTEGRITY") -> bool:
        """
        Check if simulated device meets required integrity level.
        
        Args:
            required_level: Required verdict level
        
        Returns:
            True if device meets requirement
        """
        levels = {
            "MEETS_BASIC_INTEGRITY": 1,
            "MEETS_DEVICE_INTEGRITY": 2,
            "MEETS_STRONG_INTEGRITY": 3,
        }
        
        # Simulated device can achieve DEVICE but not STRONG
        # (STRONG requires genuine hardware TEE attestation)
        simulated_level = 2  # MEETS_DEVICE_INTEGRITY
        
        required = levels.get(required_level, 2)
        return simulated_level >= required


# Convenience functions
def create_virtual_keystore(device_profile: str = "samsung_s24") -> VirtualKeyStore:
    """Create virtual keystore with device profile."""
    profiles = {
        "samsung_s24": {
            "brand": "samsung",
            "device": "e3q",
            "product": "e3qxxx",
            "model": "SM-S928B",
            "manufacturer": "samsung",
            "os_version": "14",
            "os_patch_level": "2024-03-01",
            "vendor_patch_level": "2024-03-01",
            "boot_patch_level": "2024-03-01",
            "verified_boot_state": "green",
            "device_locked": True,
            "fingerprint": "samsung/e3qxxx/e3q:14/UP1A.231005.007/S928BXXU1AXCA:user/release-keys",
        },
        "pixel_9": {
            "brand": "google",
            "device": "komodo",
            "product": "komodo",
            "model": "Pixel 9 Pro",
            "manufacturer": "Google",
            "os_version": "15",
            "os_patch_level": "2024-10-05",
            "vendor_patch_level": "2024-10-05",
            "boot_patch_level": "2024-10-05",
            "verified_boot_state": "green",
            "device_locked": True,
            "fingerprint": "google/komodo/komodo:15/AP31.240617.009/12094726:user/release-keys",
        },
    }
    
    device_info = profiles.get(device_profile, profiles["samsung_s24"])
    return VirtualKeyStore(device_info)


def create_attestation_proxy(relay_endpoint: str = None) -> RemoteAttestationProxy:
    """Create attestation proxy with optional remote relay."""
    return RemoteAttestationProxy(relay_endpoint=relay_endpoint)


if __name__ == "__main__":
    import asyncio
    
    print("Attestation Proxy - Test Output")
    print("=" * 50)
    
    # Test virtual keystore
    keystore = create_virtual_keystore("samsung_s24")
    
    print("\n1. Testing key generation...")
    pub_key = keystore.generate_key("test_key")
    print(f"   Generated key: {len(pub_key)} bytes")
    
    print("\n2. Testing key attestation...")
    request = KeyAttestationRequest(
        package_name="com.example.app",
        challenge=secrets.token_bytes(32),
        key_alias="test_key",
        key_purposes=[2, 3],
    )
    
    response = keystore.attest_key(request)
    print(f"   Success: {response.success}")
    print(f"   Certificate chain: {len(response.certificate_chain)} certs")
    print(f"   Security level: {response.security_level.name}")
    print(f"   Source: {response.source}")
    
    print("\n3. Testing Play Integrity simulation...")
    integrity = PlayIntegritySimulator(keystore)
    token_response = integrity.generate_integrity_token(
        nonce=base64.b64encode(secrets.token_bytes(16)).decode(),
        package_name="com.example.app"
    )
    print(f"   Token length: {len(token_response['token'])} chars")
    print(f"   Verdict: {token_response['payload']['deviceIntegrity']['deviceRecognitionVerdict']}")
    
    print("\n✓ Attestation proxy demonstrates TEE simulation capabilities")
