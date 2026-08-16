from django.urls import path

from apps.landing.views import LandingLeadCreateView, LeadBotWebhookView

urlpatterns = [
    path("lead/", LandingLeadCreateView.as_view(), name="landing-lead-create"),
    path("lead-bot/webhook/", LeadBotWebhookView.as_view(), name="lead-bot-webhook"),
]
