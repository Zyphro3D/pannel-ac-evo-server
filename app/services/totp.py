"""Authentification à deux facteurs (TOTP, RFC 6238) sans dépendance externe.

Compatible Google Authenticator, Aegis, 2FAS, Bitwarden, etc. : SHA-1, 6 chiffres, pas de 30 s.
Les codes de secours sont à usage unique et stockés hachés (HMAC-SHA256 avec SECRET_KEY)."""
import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
from urllib.parse import quote

PERIOD = 30
DIGITS = 6
WINDOW = 1            # tolère un pas de 30 s avant / après (dérive d'horloge)
RECOVERY_COUNT = 10


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret_b32: str, counter: int) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
    return str(code).zfill(DIGITS)


def code_at(secret_b32: str, at: float | None = None) -> str:
    return _hotp(secret_b32, int((at if at is not None else time.time()) // PERIOD))


def verify(secret_b32: str, code: str, last_step: int = 0, at: float | None = None) -> int | None:
    """Retourne le pas (counter) accepté, ou None. Un pas déjà utilisé (<= last_step) est refusé : un code
    espionné ne peut pas être rejoué pendant sa fenêtre de validité."""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != DIGITS:
        return None
    now_step = int((at if at is not None else time.time()) // PERIOD)
    for step in range(now_step - WINDOW, now_step + WINDOW + 1):
        if step > (last_step or 0) and hmac.compare_digest(_hotp(secret_b32, step), code):
            return step
    return None


def otpauth_uri(secret_b32: str, account: str, issuer: str) -> str:
    return (f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret_b32}"
            f"&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={PERIOD}")


# ── Codes de secours ─────────────────────────────────────────────────────────

def _hash_recovery(code: str, pepper: str) -> str:
    norm = "".join(ch for ch in code.lower() if ch.isalnum())
    return hmac.new(pepper.encode(), norm.encode(), hashlib.sha256).hexdigest()


def new_recovery_codes(pepper: str) -> tuple[list[str], str]:
    """(codes en clair à montrer une seule fois, JSON des hachés à stocker)."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    plain = ["".join(secrets.choice(alphabet) for _ in range(8)) for _ in range(RECOVERY_COUNT)]
    shown = [f"{c[:4]}-{c[4:]}" for c in plain]
    return shown, json.dumps([_hash_recovery(c, pepper) for c in plain])


def consume_recovery(stored_json: str, code: str, pepper: str) -> str | None:
    """Si ``code`` est un code de secours valide, retourne le nouveau JSON (sans lui) ; sinon None."""
    try:
        hashes = json.loads(stored_json or "[]")
    except ValueError:
        return None
    h = _hash_recovery(code, pepper)
    for known in hashes:
        if hmac.compare_digest(known, h):
            hashes.remove(known)
            return json.dumps(hashes)
    return None


def recovery_left(stored_json: str) -> int:
    try:
        return len(json.loads(stored_json or "[]"))
    except ValueError:
        return 0
