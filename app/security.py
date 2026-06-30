"""Password hashing and stateless session cookies (stdlib only — no deps).

- Passwords: PBKDF2-SHA256 with a per-user random salt, 600k iterations.
  Stored as the string "pbkdf2_sha256$<iters>$<salt_b64>$<hash_b64>".
- Sessions: a signed cookie "b64(username).b64(exp).b64(hmac)" verified with a
  constant-time compare. Carries the username; the DB is the source of truth
  for is_admin / existence, checked on each request.
"""
import base64
import hashlib
import hmac
import os
import time

PBKDF2_ITERATIONS = 600_000
DIGEST = "sha256"
SALT_BYTES = 16
HASH_BYTES = 32

SESSION_COOKIE = "meme_gen_auth"
SESSION_TTL = 60 * 60 * 24 * 30  # 30 days, in seconds


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #

def hash_password(password: str) -> str:
    salt = os.urandom(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(DIGEST, password.encode("utf-8"), salt, PBKDF2_ITERATIONS, HASH_BYTES)
    return f"pbkdf2_{DIGEST}${PBKDF2_ITERATIONS}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check against a stored hash. False on malformed stored value."""
    try:
        scheme, rest = stored.split("$", 1)
        expected_scheme = f"pbkdf2_{DIGEST}"
        if scheme != expected_scheme:
            return False
        iters_s, salt_b64, hash_b64 = rest.split("$", 2)
        iters = int(iters_s)
        salt = _unb64(salt_b64)
        expected = _unb64(hash_b64)
    except (ValueError, AttributeError):
        return False
    dk = hashlib.pbkdf2_hmac(DIGEST, password.encode("utf-8"), salt, iters, len(expected))
    return hmac.compare_digest(dk, expected)


# --------------------------------------------------------------------------- #
# Signed session cookie
# --------------------------------------------------------------------------- #

def create_session_cookie(username: str, secret: str, *, ttl: int = SESSION_TTL) -> str:
    """Return the cookie value: 'b64(user).b64(exp).b64(hmac)'."""
    exp = int(time.time()) + ttl
    payload = f"{_b64(username.encode())}.{_b64(str(exp).encode())}"
    sig = _sign(payload, secret)
    return f"{payload}.{sig}"


def parse_session_cookie(value: str | None, secret: str) -> str | None:
    """Return the username if the cookie is well-formed, unexpired, and signed
    with the same secret; otherwise None (treat the caller as anonymous)."""
    if not value or value.count(".") != 2:
        return None
    payload, sig = value.rsplit(".", 1)
    expected_sig = _sign(payload, secret)
    if not hmac.compare_digest(sig, expected_sig):
        return None
    user_b64, exp_b64 = payload.split(".", 1)
    try:
        username = _unb64(user_b64).decode("utf-8")
        exp = int(_unb64(exp_b64).decode("ascii"))
    except (ValueError, UnicodeDecodeError):
        return None
    if exp < time.time():
        return None
    return username


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign(payload: str, secret: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256)
    return _b64(mac.digest())
