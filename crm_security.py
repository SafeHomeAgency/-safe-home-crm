"""
PHASE 1.5 — უსაფრთხოების დამხმარე ფუნქციები (Flask-ისა და მონაცემთა
ბაზისგან დამოუკიდებელი, ამიტომ ცალკე ტესტირებადი):

  * validate_init_data   — Telegram Mini App initData: HMAC + auth_date ვადა
  * sanitize_metadata    — audit metadata-დან სენსიტიური გასაღებების ამოღება
  * RateLimiter          — მარტივი sliding-window (პროცესის შიდა!)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import urllib.parse
from collections import defaultdict, deque


# ------------------------------------------------------------ initData

def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int,
                       future_skew_seconds: int = 60, now: float | None = None):
    """აბრუნებს (user_dict | None, reason).

    ვალიდაციის რიგი (უსაფრთხო): 1) მონაცემები არსებობს; 2) hash არსებობს;
    3) HMAC ემთხვევა (constant-time) — **მხოლოდ ამის შემდეგ** ვენდობით
    დანარჩენ ველებს; 4) auth_date არსებობს და მთელი რიცხვია; 5) არც ძალიან
    ძველია (> max_age), არც მომავალშია (> future_skew). `reason` მხოლოდ
    მოკლე კოდია ("expired", "bad_hmac"...) — initData ან hash ლოგში არასდროს
    იწერება."""
    if not init_data or not bot_token:
        return None, "missing"
    try:
        pairs = urllib.parse.parse_qsl(init_data, keep_blank_values=True)
        data = dict(pairs)
        received_hash = data.pop("hash", None)
        if not received_hash:
            return None, "no_hash"
        check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        computed = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed, received_hash):
            return None, "bad_hmac"
        raw_auth = data.get("auth_date")
        if raw_auth is None or str(raw_auth).strip() == "":
            return None, "no_auth_date"
        try:
            auth_date = int(str(raw_auth).strip())
        except (TypeError, ValueError):
            return None, "bad_auth_date"
        if auth_date <= 0:
            return None, "bad_auth_date"
        current = time.time() if now is None else now
        if current - auth_date > max_age_seconds:
            return None, "expired"
        if auth_date - current > future_skew_seconds:
            return None, "from_future"
        user = json.loads(data.get("user", "{}"))
        if not isinstance(user, dict):
            return None, "bad_user"
        return {"user": user, "auth_date": auth_date}, "ok"
    except Exception:
        return None, "error"


# ------------------------------------------------------------ audit metadata

_SENSITIVE_PARTS = ("password", "passwd", "token", "secret", "api_key", "apikey",
                    "authorization", "initdata", "init_data", "credential", "cookie")


def _is_sensitive_key(key) -> bool:
    k = str(key).lower().replace("-", "_")
    return any(p in k for p in _SENSITIVE_PARTS)


def sanitize_metadata(value, _depth: int = 0):
    """მეტამონაცემებიდან სენსიტიური გასაღებების მნიშვნელობა იცვლება
    "[redacted]"-ით; სიღრმე და სიგრძე შეზღუდულია."""
    if _depth > 4:
        return "[truncated]"
    if isinstance(value, dict):
        return {str(k): ("[redacted]" if _is_sensitive_key(k) else sanitize_metadata(v, _depth + 1))
                for k, v in list(value.items())[:40]}
    if isinstance(value, (list, tuple, set)):
        return [sanitize_metadata(v, _depth + 1) for v in list(value)[:40]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    s = str(value)
    return s if len(s) <= 300 else s[:300] + "…"


# ------------------------------------------------------------ rate limiter

class RateLimiter:
    """Sliding-window limiter. **პროცესის შიდაა**: მრავალ-ინსტანსიან
    გარემოში (ან restart-ზე) ლიმიტი ინსტანსზეა და არა გლობალური — ეს
    production-grade განაწილებული limiter არ არის."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._hits: dict[tuple, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: tuple, limit: int, window_seconds: int) -> tuple[bool, int]:
        """აბრუნებს (allowed, retry_after_seconds). `check` თავადვე ითვლის
        მოთხოვნას, თუ დაშვებულია."""
        now = self._clock()
        with self._lock:
            dq = self._hits[key]
            while dq and now - dq[0] >= window_seconds:
                dq.popleft()
            if len(dq) >= limit:
                return False, max(1, int(window_seconds - (now - dq[0])) + 1)
            dq.append(now)
            # მეხსიერების დაცვა: ცარიელ გასაღებებს ხანდახან ვასუფთავებთ
            if len(self._hits) > 5000:
                for k in [k for k, v in self._hits.items() if not v]:
                    self._hits.pop(k, None)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
