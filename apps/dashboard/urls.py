from django.urls import path
from apps.dashboard import views

urlpatterns = [
    path("dashboard/", views.DashboardView.as_view()),
    #list of models
    path("users/", views.DashboardUserList.as_view()),
    path("assistants/", views.DashboardAssistantList.as_view()),
    path("conversations/", views.DashboardConversationList.as_view()),
    path("integrations/", views.DashboardIntegrationList.as_view()),
    path("transactions/", views.DashboardTransactionList.as_view()),
    path("subscriptions/", views.DashboardSubscriptionList.as_view()),
    path("assistantfiles/", views.DashboardAssistantFileUploadList.as_view()),
    path("features/", views.DashboardFeatureList.as_view()),
    path("pricingpackages/", views.DashboardPricingPackageList.as_view()),
    path("notifications/", views.DashboardNotificationList.as_view()),
    
    #detail of models
    path("users/<uuid:pk>/", views.DashboardUserDetail.as_view()),
    path("assistants/<uuid:pk>/", views.DashboardAssistantDetail.as_view()),
    path("conversations/<uuid:pk>/", views.DashboardConversationDetail.as_view()),
    path("integrations/<uuid:pk>/", views.DashboardIntegrationDetail.as_view()),
    path("transactions/<uuid:pk>/", views.DashboardTransactionDetail.as_view()),
    path("subscriptions/<uuid:pk>/", views.DashboardSubscriptionDetail.as_view()),
    path("assistantfiles/<uuid:pk>/", views.DashboardAssistantFileUploadDetail.as_view()),
    path("features/<uuid:pk>/", views.DashboardFeatureDetail.as_view()),
    path("pricingpackages/<uuid:pk>/", views.DashboardPricingPackageDetail.as_view()),

    #user login dashboard
    path("send-otp/login/", views.DashboardSendOtpLoginView.as_view()),
    path("verify-otp/login/", views.DashboardVerifyOtpLoginView.as_view()),

    #dashboard statistics
    path("statistics/", views.DashboardStatisticsView.as_view()),

    #prompt templates
    path("prompts/", views.DashboardPromptTemplateList.as_view()),
    path("prompts/<uuid:pk>/", views.DashboardPromptTemplateDetail.as_view()),
]
