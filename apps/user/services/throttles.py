import hashlib

from rest_framework.throttling import SimpleRateThrottle


def _identifier(request):
    data = getattr(request, "data", None)
    if not isinstance(data, dict):
        return None
    value = data.get("phone_number") or data.get("email")
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value or None


class BaseOtpIdentifierThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        identifier = _identifier(request)
        if identifier is None:
            return None
        digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": digest}


class OtpSendIdentifierThrottle(BaseOtpIdentifierThrottle):
    scope = "otp_send_identifier"


class OtpVerifyIdentifierThrottle(BaseOtpIdentifierThrottle):
    scope = "otp_verify_identifier"
