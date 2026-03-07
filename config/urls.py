from django.contrib import admin
from django.urls import path, include
from django.conf.urls.static import static
from django.http import JsonResponse
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from config import settings

urlpatterns = [
    path("acer-laptop/samsung-g10/", admin.site.urls),
    path("api/v1/", include("apps.urls")),
    path("", lambda _: JsonResponse({"message": "ok"})),
    path("health/", lambda _: JsonResponse({"status": "healthy"})),
]

urlpatterns += [
    path("G7@qz3!KwfX2//schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "G7@qz3!KwfX2/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += (
        path(
            "error_trigger/",
            lambda _: JsonResponse("Ok, you found it."),
        ),
    )
