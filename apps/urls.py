from django.urls import include, path

urlpatterns = [
    path("user/", include(("apps.user.urls", "user"), namespace="user")),
    path("payment/", include(("apps.payment.urls", "payment"), namespace="payment")),
    path("integration/", include(("apps.integration.urls", "integration"), namespace="integration")),
    path("chat/", include(("apps.assistant.urls", "assistant"), namespace="assistant")),
    path("dashboard/", include(("apps.dashboard.urls", 'dashboard'), namespace="dashboard")),
    path("blog/", include(("apps.blog.urls", "blog"), namespace="blog")),
    path("landing/", include(("apps.landing.urls", "landing"), namespace="landing")),
]
