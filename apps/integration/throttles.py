from rest_framework.throttling import SimpleRateThrottle


class _ClientRateThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class OAuthCallbackThrottle(_ClientRateThrottle):
    scope = "integration_oauth_callback"
    rate = "30/minute"


class MetaDataRequestThrottle(_ClientRateThrottle):
    scope = "integration_meta_data_request"
    rate = "30/minute"
