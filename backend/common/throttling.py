"""Throttles for authentication endpoints.

DRF's `ScopedRateThrottle` keys on the client address, which is the right
primary control but has one failure mode worth defending against: if the proxy
count is ever misconfigured, every user collapses into a single bucket (one
person locks out everyone) or each request gets its own (no limit at all).

`TargetedAccountThrottle` keys on the account being attacked instead, so a
credential-stuffing run against one user is capped regardless of how the
address resolves.

Deliberately a rate limit and not a lockout: an attacker hammering someone
else's email slows that account's login attempts but never disables it, so this
cannot be turned into a denial-of-service against a specific user.
"""

from __future__ import annotations

import hashlib

from rest_framework.throttling import SimpleRateThrottle


class TargetedAccountThrottle(SimpleRateThrottle):
    scope = "login_email"

    def get_cache_key(self, request, view):
        email = ""
        if isinstance(request.data, dict):
            email = str(request.data.get("email") or "").strip().lower()
        if not email:
            return None  # nothing to key on; the IP throttle still applies

        # Hashed so the cache never holds a list of the instance's addresses.
        digest = hashlib.sha256(email.encode()).hexdigest()[:32]
        return f"throttle_{self.scope}_{digest}"
