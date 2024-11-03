from django.urls import path
import apps.integration.views as views

urlpatterns = [
    path("integration/", views.IntegrationListCreateView.as_view()),
    path("integration/<uuid:pk>/", views.IntegrationRetrieveUpdateDestroyView.as_view()),
]