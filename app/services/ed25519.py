"""Vérification de signatures Ed25519 en Python pur (RFC 8032), sans dépendance : sert à contrôler les mises à jour et les licences hors ligne.
Seule la VÉRIFICATION est fournie ; les clés privées ne quittent jamais la machine de publication. Lent mais suffisant (quelques dizaines de ms).
"""

import hashlib

P = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493


def _inv(x):
    """inverse modulaire dans le corps de la courbe."""
    return pow(x, P - 2, P)


D = -121665 * _inv(121666) % P
I = pow(2, (P - 1) // 4, P)


def _xrecover(y):
    """retrouve la coordonnée x d'un point à partir de y."""
    xx = (y * y - 1) * _inv(D * y * y + 1) % P
    x = pow(xx, (P + 3) // 8, P)
    if (x * x - xx) % P != 0:
        x = x * I % P
    if x % 2 != 0:
        x = P - x
    return x


BY = 4 * _inv(5) % P
B = (_xrecover(BY) % P, BY)


def _add(a, b):
    """addition de deux points de la courbe (coordonnées étendues)."""
    x1, y1 = a
    x2, y2 = b
    t = D * x1 * x2 * y1 * y2 % P
    return ((x1 * y2 + x2 * y1) * _inv(1 + t) % P, (y1 * y2 + x1 * x2) * _inv(1 - t) % P)


def _mul(pt, e):
    """multiplication d'un point par un entier (doublements et additions)."""
    r = (0, 1)
    while e:
        if e & 1:
            r = _add(r, pt)
        pt = _add(pt, pt)
        e >>= 1
    return r


def _enc(pt):
    """encode un point sur 32 octets."""
    x, y = pt
    return (y | ((x & 1) << 255)).to_bytes(32, 'little')


def _dec(s):
    """décode et valide un point de 32 octets ; lève ValueError s'il n'est pas sur la courbe."""
    if len(s) != 32:
        raise ValueError('point')
    y = int.from_bytes(s, 'little')
    sign = y >> 255
    y &= (1 << 255) - 1
    if y >= P:
        raise ValueError('point')
    x = _xrecover(y)
    if x & 1 != sign:
        x = P - x
    pt = (x, y)
    if (-x * x + y * y - 1 - D * x * x * y * y) % P != 0:
        raise ValueError('point')
    return pt


_CACHE = {}


def verify(public_key, message, signature):
    """True si la signature (64 octets) de message est valide pour la clé publique (32 octets) ; jamais d'exception.
    Le calcul en Python pur coûte ~130 ms : le résultat est mémorisé (même clé, même message, même signature = même réponse), sinon chaque page affichée refaisait la vérification de la licence et ralentissait chaque clic."""
    try:
        key = (bytes(public_key), bytes(message), bytes(signature))
    except Exception:
        return False
    r = _CACHE.get(key)
    if r is None:
        r = _verify(*key)
        if len(_CACHE) > 256:
            _CACHE.clear()
        _CACHE[key] = r
    return r


def _verify(public_key, message, signature):
    """vérification sans mémoire."""
    try:
        if len(public_key) != 32 or len(signature) != 64:
            return False
        A = _dec(public_key)
        R = _dec(signature[:32])
        S = int.from_bytes(signature[32:], 'little')
        if _mul(A, 8) == (0, 1) or _mul(R, 8) == (0, 1):
            return False  # points d'ordre faible refusés
        if S >= L:
            return False
        h = int.from_bytes(hashlib.sha512(signature[:32] + public_key + message).digest(), 'little') % L
        return _mul(B, S) == _add(R, _mul(A, h))
    except Exception:
        return False
