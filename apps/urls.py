from django.urls import path, include

urlpatterns = [
    path("user/", include(("user.urls", "user"), namespace="user")),
    path("payment/", include(("payment.urls", "payment"), namespace="payment")),
    path("integration/", include(("integration.urls", "integration"), namespace="integration")),
    path("chat/", include(("assistant.urls", "assistant"), namespace="assistant")),
    path("dashboard/", include(("dashboard.urls", 'dashboard'), namespace="dashboard")),
    path("mcp-database/", include(("mcpdatabase.urls", "mcpdatabase"), namespace="mcpdatabase")),
]
