"""Rate limits for the integration app's unauthenticated surfaces.

The rates are declared on the classes rather than in
`REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]`: `SimpleRateThrottle` only consults
settings when `rate` is unset, so an app-local limit needs no settings change
and cannot be silently dropped by one.

Webhook receivers (Instagram/Telegram) are deliberately *not* throttled — they
authenticate every delivery (HMAC signature / secret path token) and Meta
disables a subscription that starts collecting 429s.
"""
from rest_framework.throttling import SimpleRateThrottle


class _ClientRateThrottle(SimpleRateThrottle):
    """Throttle by client address — these endpoints have no authenticated user."""

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class OAuthCallbackThrottle(_ClientRateThrottle):
    """OAuth redirect targets.

    Each call spends unauthenticated server time on two outbound HTTPS requests
    to a host taken from the query string, so an unthrottled callback is a free
    outbound-request amplifier.
    """

    scope = "integration_oauth_callback"
    rate = "30/minute"


class MetaDataRequestThrottle(_ClientRateThrottle):
    """Meta's deauthorize / data-deletion callbacks.

    Signature-verified, but the deauthorize handler *deletes* an integration
    and everything hanging off it, so failed attempts must not be free.
    """

    scope = "integration_meta_data_request"
    rate = "30/minute"
