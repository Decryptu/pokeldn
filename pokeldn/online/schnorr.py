"""BIP-340 Schnorr signatures over secp256k1, the signature every Nostr event carries (NIP-01).
Pure Python in Jacobian coordinates; a launcher signs about one event a second."""
import hashlib
import os

P = 2 ** 256 - 2 ** 32 - 977
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
     0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)


def tagged_hash(tag: str, data: bytes) -> bytes:
    t = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(t + t + data).digest()


def _double(p):
    x, y, z = p
    if y == 0:
        return (0, 1, 0)
    s = 4 * x * y * y % P
    m = 3 * x * x % P
    nx = (m * m - 2 * s) % P
    return (nx, (m * (s - nx) - 8 * y ** 4) % P, 2 * y * z % P)


def _add(p, q):
    if p[2] == 0:
        return q
    if q[2] == 0:
        return p
    z1z1, z2z2 = p[2] * p[2] % P, q[2] * q[2] % P
    u1, u2 = p[0] * z2z2 % P, q[0] * z1z1 % P
    s1, s2 = p[1] * q[2] * z2z2 % P, q[1] * p[2] * z1z1 % P
    if u1 == u2:
        return _double(p) if s1 == s2 else (0, 1, 0)
    h, r = u2 - u1, s2 - s1
    hh = h * h % P
    hhh = h * hh % P
    v = u1 * hh % P
    nx = (r * r - hhh - 2 * v) % P
    return (nx, (r * (v - nx) - s1 * hhh) % P, h * p[2] * q[2] % P)


def _mul(k, point=G):
    result, addend = (0, 1, 0), (point[0], point[1], 1)
    while k:
        if k & 1:
            result = _add(result, addend)
        addend = _double(addend)
        k >>= 1
    if result[2] == 0:
        return None
    zi = pow(result[2], -1, P)
    return (result[0] * zi * zi % P, result[1] * zi * zi * zi % P)


def _lift_x(x: int):
    if x >= P:
        return None
    y = pow((pow(x, 3, P) + 7) % P, (P + 1) // 4, P)
    if y * y % P != (pow(x, 3, P) + 7) % P:
        return None
    return (x, y if y % 2 == 0 else P - y)


def public_key(secret: bytes) -> bytes:
    """-> the 32-byte x-only public key of a 32-byte secret."""
    d = int.from_bytes(secret, "big")
    if not 1 <= d < N:
        raise ValueError("secret key out of range")
    return _mul(d)[0].to_bytes(32, "big")


def sign(secret: bytes, message: bytes, aux: bytes | None = None) -> bytes:
    d0 = int.from_bytes(secret, "big")
    if not 1 <= d0 < N:
        raise ValueError("secret key out of range")
    pub = _mul(d0)
    d = d0 if pub[1] % 2 == 0 else N - d0
    aux = os.urandom(32) if aux is None else aux
    t = (d ^ int.from_bytes(tagged_hash("BIP0340/aux", aux), "big")).to_bytes(32, "big")
    px = pub[0].to_bytes(32, "big")
    k0 = int.from_bytes(tagged_hash("BIP0340/nonce", t + px + message), "big") % N
    if k0 == 0:
        raise ValueError("nonce is zero")
    r = _mul(k0)
    k = k0 if r[1] % 2 == 0 else N - k0
    rx = r[0].to_bytes(32, "big")
    e = int.from_bytes(tagged_hash("BIP0340/challenge", rx + px + message), "big") % N
    return rx + ((k + e * d) % N).to_bytes(32, "big")


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    pub = _lift_x(int.from_bytes(public, "big"))
    r, s = int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
    if pub is None or r >= P or s >= N:
        return False
    e = int.from_bytes(tagged_hash("BIP0340/challenge", signature[:32] + public + message), "big") % N
    a, b = _mul(s), _mul(N - e, pub)
    if a is None or b is None:
        point = a or b
    else:
        sum_ = _add((a[0], a[1], 1), (b[0], b[1], 1))
        if sum_[2] == 0:
            return False
        zi = pow(sum_[2], -1, P)
        point = (sum_[0] * zi * zi % P, sum_[1] * zi * zi * zi % P)
    return point is not None and point[1] % 2 == 0 and point[0] == r
