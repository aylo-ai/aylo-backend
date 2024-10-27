from django.urls import path, include

urlpatterns = [
    path("user/", include(("user.urls", "user"), namespace="user")),
    path("payment/", include(("payment.urls", "payment"), namespace="payment")),
    path("company/", include(("company.urls", "company"), namespace="company")),
    path("integration/", include(("integration.urls", "integration"), namespace="integration")),
    path("assistant/", include(("assistant.urls", "assistant"), namespace="assistant")),

]
