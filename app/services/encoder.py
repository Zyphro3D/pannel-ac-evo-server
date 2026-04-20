"""
Encode/decode the -serverconfig and -seasondefinition args used by
AssettoCorsaEVOServer.exe.

Format: 4-byte big-endian uint32 (uncompressed payload length) + zlib-compressed JSON.
The "type" visible in AAAD/AAAC prefixes is actually just the high bytes of the length.
"""
import struct
import zlib
import base64
import json


def _decode(b64: str) -> bytes:
    return base64.b64decode(b64)


def _encode(payload: bytes) -> str:
    header = struct.pack(">I", len(payload))   # 4-byte big-endian length
    compressed = zlib.compress(payload, level=6)
    return base64.b64encode(header + compressed).decode("ascii")


def decode_config(b64: str) -> dict:
    raw = _decode(b64)
    return json.loads(zlib.decompress(raw[4:]))


def encode_serverconfig(data: dict) -> str:
    payload = json.dumps(data, separators=(",", ":")).encode("utf-8")
    return _encode(payload)


def encode_seasondefinition(data: dict) -> str:
    payload = json.dumps(data, separators=(",", ":")).encode("utf-8")
    return _encode(payload)
