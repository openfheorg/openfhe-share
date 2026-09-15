"""
Post-quantum secure routing manager for hiding aggregated results from the server.

Uses ML-KEM-1024 (NIST Level 5) for key encapsulation, HKDF-SHA256 for key
derivation, and AES-256-GCM for symmetric encryption of session keys and payloads.
Supports two roles: coordinator (lead client that fuses partial decryptions and
encrypts results per client) and standard client (generates KEM keypair, receives
session key, decrypts payloads).
"""

import logging
import os
import pickle
from typing import Any, Collection, Dict, Optional, Set, Tuple

import oqs
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
KEM_ALG = "ML-KEM-1024"
HKDF_INFO = b"pqc handshake data"
AES_KEY_LEN = 32
GCM_NONCE_LEN = 12


def _derive_kek(shared_secret: bytes) -> bytes:
    """Derive Key Encryption Key from PQC shared secret using HKDF-SHA256."""
    return HKDF(
        algorithm=hashes.SHA256(),
        length=AES_KEY_LEN,
        salt=None,
        info=HKDF_INFO,
    ).derive(shared_secret)


# -----------------------------------------------------------------------------
# PQC Routing Manager (coordinator and standard client roles)
# -----------------------------------------------------------------------------
class PQCRoutingManager:
    """
    Manager for post-quantum key exchange and symmetric-key payload routing.

    Use as coordinator (e.g. lead_client) to register client public keys,
    generate and distribute AES session keys, and build encrypted payload
    vectors. Use as standard client to generate a KEM keypair, receive a key
    package, and decrypt routed payloads.
    """

    def __init__(
        self,
        client_name: str,
        is_coordinator: bool = False,
        kem_alg: str = KEM_ALG,
    ):
        """
        Args:
            client_name: Identifier for this participant (e.g. site name).
            is_coordinator: If True, this instance acts as the coordinator that
                performs encapsulation and encrypts payloads for other clients.
                If False, acts as a standard client that generates a keypair and
                receives a session key.
            kem_alg: Key encapsulation algorithm (default ML-KEM-1024).
        """
        self.client_name = client_name
        self.is_coordinator = is_coordinator
        self.kem_alg = kem_alg
        self.custom_logger = logging.getLogger("custom.audit_log")

        if is_coordinator:
            self.received_pubs: Dict[str, bytes] = {}
            self.aes_session_keys: Dict[str, bytes] = {}
            self._kem = None
            self._public_key_bytes: Optional[bytes] = None
            self._aes_session_key: Optional[bytes] = None
        else:
            self.received_pubs = {}
            self.aes_session_keys = {}
            self._kem = oqs.KeyEncapsulation(kem_alg)
            self._public_key_bytes = self._kem.generate_keypair()
            self._aes_session_key: Optional[bytes] = None
            self.custom_logger.info("ML-KEM keypair generated.")

    # -------------------------------------------------------------------------
    # Standard client: export public key
    # -------------------------------------------------------------------------
    def get_public_key(self) -> bytes:
        """
        Export public key bytes to be sent to the coordinator (via server).

        Only valid when is_coordinator is False. Call after __init__.
        """
        if self.is_coordinator:
            raise RuntimeError("get_public_key is for standard clients only")
        if self._public_key_bytes is None:
            raise RuntimeError("KEM keypair not generated")
        return self._public_key_bytes

    # -------------------------------------------------------------------------
    # Coordinator: register client public keys
    # -------------------------------------------------------------------------
    def register_pubkey(self, client_name: str, pubkey_bytes: bytes) -> None:
        """
        Register a client's ML-KEM public key (called by coordinator).

        Keys are typically routed from clients via the server. After all
        client public keys are registered, call generate_and_distribute_keys().
        """
        if not self.is_coordinator:
            raise RuntimeError("register_pubkey is for coordinator only")
        self.received_pubs[client_name] = pubkey_bytes
        self.custom_logger.info(f"Registered ML-KEM public key for client {client_name}.")

    # -------------------------------------------------------------------------
    # Coordinator: encapsulate and produce key packages
    # -------------------------------------------------------------------------
    def generate_and_distribute_keys(
        self,
        exclude_clients: Optional[Collection[str]] = None,
    ) -> Dict[str, Tuple[bytes, bytes, bytes]]:
        """
        Perform KEM encapsulation for every registered client (except names in
        ``exclude_clients``) and build key packages.

        For each client: encapsulate a secret, derive KEK, generate a random
        AES session key, encrypt it with KEK. Returns a dict suitable for the
        server to route to each client: client_name -> (kem_ciphertext, nonce,
        encrypted_session_key).

        Args:
            exclude_clients: Optional set of client names to skip (no key package).

        Returns:
            Dict mapping client_name to (kem_ciphertext, nonce, enc_session_key).
        """
        if not self.is_coordinator:
            raise RuntimeError("generate_and_distribute_keys is for coordinator only")

        messages: Dict[str, Tuple[bytes, bytes, bytes]] = {}
        skip: Set[str] = set(exclude_clients) if exclude_clients else set()

        for client_name, peer_pub_bytes in self.received_pubs.items():
            if client_name in skip:
                continue
            with oqs.KeyEncapsulation(self.kem_alg) as kem:
                ciphertext, shared_secret = kem.encap_secret(peer_pub_bytes)
                kek = _derive_kek(shared_secret)
                session_key = os.urandom(AES_KEY_LEN)
                self.aes_session_keys[client_name] = session_key
                aesgcm = AESGCM(kek)
                nonce = os.urandom(GCM_NONCE_LEN)
                encrypted_session_key = aesgcm.encrypt(nonce, session_key, None)
                messages[client_name] = (ciphertext, nonce, encrypted_session_key)
        self.custom_logger.info(f"Generated AES session keys for {len(messages)} clients and encrypted them with KEM.")

        return messages

    # -------------------------------------------------------------------------
    # Standard client: receive key package and store AES session key
    # -------------------------------------------------------------------------
    def receive_key_package(
        self,
        kem_ciphertext: bytes,
        nonce: bytes,
        enc_session_key: bytes,
    ) -> None:
        """
        Process key package from coordinator: decapsulate, derive KEK, decrypt
        and store the AES session key. Call after receiving the package routed
        by the server.

        After this, the KEM context is freed; decrypt_payload() can be used
        for Phase 2.
        """
        if self.is_coordinator:
            raise RuntimeError("receive_key_package is for standard clients only")
        if self._kem is None:
            raise RuntimeError("KEM context already freed or not initialized")

        shared_secret = self._kem.decap_secret(kem_ciphertext)
        kek = _derive_kek(shared_secret)
        aesgcm = AESGCM(kek)
        self._aes_session_key = aesgcm.decrypt(nonce, enc_session_key, None)

        self._kem.free()
        self._kem = None
        self.custom_logger.info(f"AES session key established.")

    # -------------------------------------------------------------------------
    # Standard client: decrypt a routed payload
    # -------------------------------------------------------------------------
    def decrypt_payload(self, nonce: bytes, ciphertext: bytes) -> Any:
        """
        Decrypt a payload encrypted for this client (Phase 2 secure routing).

        Expects the payload to have been serialized with pickle before
        encryption. Returns the deserialized object.
        """
        if self.is_coordinator:
            raise RuntimeError("decrypt_payload is for standard clients only")
        if self._aes_session_key is None:
            raise ValueError("AES session key not established; receive_key_package first")
        aesgcm = AESGCM(self._aes_session_key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        self.custom_logger.info(f"Decrypted payload using AES session key.")
        return pickle.loads(plaintext)

    # -------------------------------------------------------------------------
    # Coordinator: encrypt payload for each client (Phase 2)
    # -------------------------------------------------------------------------
    def build_payload_vector(
        self,
        payload: Any,
    ) -> Dict[str, Tuple[bytes, bytes]]:
        """
        Encrypt the aggregated result for each registered client.

        Serializes the payload with pickle, then encrypts it with each client's
        AES session key. The server can route the resulting (nonce, ciphertext)
        per client without seeing plaintext.

        Args:
            payload: Arbitrary serializable object (e.g. fused decryption result).

        Returns:
            Dict mapping client_name to (nonce, ciphertext).
        """
        if not self.is_coordinator:
            raise RuntimeError("build_payload_vector is for coordinator only")

        raw_payload = pickle.dumps(payload)
        encrypted_vector: Dict[str, Tuple[bytes, bytes]] = {}

        for client_name, session_key in self.aes_session_keys.items():
            aesgcm = AESGCM(session_key)
            nonce = os.urandom(GCM_NONCE_LEN)
            ciphertext = aesgcm.encrypt(nonce, raw_payload, None)
            encrypted_vector[client_name] = (nonce, ciphertext)
        self.custom_logger.info(f"Built encrypted payload vector for {len(encrypted_vector)} clients using AES session key.")

        return encrypted_vector
