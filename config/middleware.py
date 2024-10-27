from django.utils.translation import activate, deactivate

from config import settings


class LanguageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        language = request.META.get("Accept-Language")
        if language:
            language = language.split(";")[0]
            if language in dict(settings.LANGUAGES):
                activate(language)
        # Deactivate after the request has been processed to avoid leakage
        deactivate()

        return self.get_response(request)