"""Canonical JSON serialization and SHA-256 fingerprints (contract §6.1/§6.3, frozen).

- canonical_json keeps its parameters exactly: sort_keys / ensure_ascii=False / compact separators / allow_nan=False;
- fingerprints are always full SHA-256 (64 lowercase hex, CR-2); [:8] truncation is forbidden;
- float is banned on the trials fingerprint path (all Trial fields are int/str/empty dict).
"""

from __future__ import annotations

import hashlib
import json


def canonical_json(obj: object) -> str:
    """Canonical JSON: sorted keys, no whitespace, UTF-8, NaN/Inf forbidden (serialization raises)."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def sha256_hex(text: str) -> str:
    """Full SHA-256 hex fingerprint (64 lowercase hex)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_hex_bytes(data: bytes) -> str:
    """Full SHA-256 hex fingerprint (bytes input)."""
    return hashlib.sha256(data).hexdigest()
