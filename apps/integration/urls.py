from django.urls import path
import apps.integration.views as views

urlpatterns = [
    path("assistant/<uuid:pk>/integration/", views.IntegrationListCreateView.as_view()),
    path("integration/<uuid:pk>/", views.IntegrationRetrieveUpdateDestroyView.as_view()),
    path('telegram/webhook/<str:bot_token>/', views.TelegramWebhookView.as_view(), name='telegram_webhook'),

]