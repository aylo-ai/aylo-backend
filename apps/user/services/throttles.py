"""Per-identifier throttles for the OTP endpoints.

DRF's `ScopedRateThrottle` buckets anonymous traffic by client IP. That is the
wrong key for an OTP flow in two directions:

* an attacker who rotates IPs (any botnet, or a phone on mobile data) gets a
  fresh budget per address, so a per-IP limit does not bound the guesses made
  against *one* phone number or email; and
* every subscriber behind one NAT — a whole office, or a carrier CGNAT range —
  shares a single bucket, so one user's sign-up attempt locks out everybody
  else on that address.

These throttles key on the identifier in the request body instead, so the limit
follows the account being attacked rather than the network it is attacked from.
They are additional to the per-IP scope, not a replacement: DRF requires *every*
throttle in `throttle_classes` to allow the request.
"""
import hashlib

from rest_framework.throttling import SimpleRateThrottle


def _identifier(request):
    """The phone number or email a request is about, or None."""
    data = getattr(request, "data", None)
    if not isinstance(data, dict):
        return None
    value = data.get("phone_number") or data.get("email")
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value or None


class BaseOtpIdentifierThrottle(SimpleRateThrottle):
    """Rate-limit by the identifier an OTP request targets."""

    def get_cache_key(self, request, view):
        identifier = _identifier(request)
        if identifier is None:
            # Nothing to key on — the serializer will reject the request anyway,
            # and the per-IP scope still applies.
            return None
        # Hashed so a phone number or email address never lands in a cache key
        # (and so an over-long address cannot break the backend's key limits).
        digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": digest}


class OtpSendIdentifierThrottle(BaseOtpIdentifierThrottle):
    """Caps how often a code can be sent *to* one phone number or email."""

    scope = "otp_send_identifier"


class OtpVerifyIdentifierThrottle(BaseOtpIdentifierThrottle):
    """Caps how many codes can be tried *against* one phone number or email."""

    scope = "otp_verify_identifier"
