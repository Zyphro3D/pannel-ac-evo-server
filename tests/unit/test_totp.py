from app.services import totp


def test_rfc6238_vector():
    # Vecteur de test RFC 6238 (secret ASCII « 12345678901234567890 », SHA-1, 8 chiffres → on compare les 6 derniers)
    import base64
    secret = base64.b32encode(b"12345678901234567890").decode()
    assert totp.code_at(secret, at=59) == "287082"                 # 94287082 tronqué à 6 chiffres
    assert totp.code_at(secret, at=1111111109) == "081804"
    assert totp.code_at(secret, at=2000000000) == "279037"


def test_verify_window_and_replay():
    s = totp.new_secret()
    t = 1_700_000_000
    code = totp.code_at(s, at=t)
    step = totp.verify(s, code, at=t)
    assert step == t // 30
    assert totp.verify(s, code, last_step=step, at=t) is None             # rejeu refusé
    assert totp.verify(s, totp.code_at(s, at=t - 30), at=t) is not None   # un pas de tolérance
    assert totp.verify(s, totp.code_at(s, at=t - 120), at=t) is None      # trop ancien
    assert totp.verify(s, "12345", at=t) is None and totp.verify(s, "abcdef", at=t) is None


def test_recovery_codes_are_single_use():
    shown, stored = totp.new_recovery_codes("pepper")
    assert len(shown) == totp.RECOVERY_COUNT and totp.recovery_left(stored) == totp.RECOVERY_COUNT
    after = totp.consume_recovery(stored, shown[0].upper(), "pepper")      # insensible à la casse / au tiret
    assert after is not None and totp.recovery_left(after) == totp.RECOVERY_COUNT - 1
    assert totp.consume_recovery(after, shown[0], "pepper") is None        # déjà utilisé
    assert totp.consume_recovery(stored, shown[1], "autre") is None        # mauvais secret serveur


def test_otpauth_uri():
    uri = totp.otpauth_uri("ABCDEF", "flo@x", "EVO Panel")
    assert uri.startswith("otpauth://totp/EVO%20Panel:flo%40x?secret=ABCDEF") and "digits=6" in uri
