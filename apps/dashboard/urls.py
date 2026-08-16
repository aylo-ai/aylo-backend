from django.urls import path

from apps.dashboard import views

urlpatterns = [
    # Auth
    path("send-otp/login/", views.DashboardSendOtpLoginView.as_view()),
    path("verify-otp/login/", views.DashboardVerifyOtpLoginView.as_view()),

    # Dashboard & statistics
    path("dashboard/", views.DashboardView.as_view()),
    path("dashboard/enhanced/", views.DashboardEnhancedStatsView.as_view()),
    path("statistics/", views.DashboardStatisticsView.as_view()),
    path("statistics/ai-costs/", views.DashboardAICostBreakdownView.as_view()),

    # System health
    path("system-health/", views.DashboardSystemHealthView.as_view()),

    # Global search
    path("search/", views.DashboardGlobalSearch.as_view()),

    # Users
    path("users/", views.DashboardUserList.as_view()),
    path("users/export/", views.DashboardUserExport.as_view()),
    path("users/bulk-action/", views.DashboardUserBulkAction.as_view()),
    path("users/<uuid:pk>/", views.DashboardUserDetail.as_view()),
    path("users/<uuid:pk>/toggle-active/", views.DashboardUserToggleActive.as_view()),
    path("users/<uuid:pk>/change-role/", views.DashboardUserChangeRole.as_view()),

    # Assistants
    path("assistants/", views.DashboardAssistantList.as_view()),
    path("assistants/<uuid:pk>/", views.DashboardAssistantDetail.as_view()),
    path("assistants/<uuid:pk>/toggle-active/", views.DashboardAssistantToggleActive.as_view()),

    # Conversations
    path("conversations/", views.DashboardConversationList.as_view()),
    path("conversations/<uuid:pk>/", views.DashboardConversationDetail.as_view()),
    path("conversations/<uuid:pk>/close/", views.DashboardConversationClose.as_view()),
    path("conversations/<uuid:pk>/escalate/", views.DashboardConversationEscalate.as_view()),

    # Transactions
    path("transactions/", views.DashboardTransactionList.as_view()),
    path("transactions/export/", views.DashboardTransactionExport.as_view()),
    path("transactions/bulk-action/", views.DashboardTransactionBulkAction.as_view()),
    path("transactions/<uuid:pk>/", views.DashboardTransactionDetail.as_view()),
    path("transactions/<uuid:pk>/refund/", views.DashboardTransactionRefund.as_view()),

    # Subscriptions
    path("subscriptions/", views.DashboardSubscriptionList.as_view()),
    path("subscriptions/<uuid:pk>/", views.DashboardSubscriptionDetail.as_view()),
    path("subscriptions/<uuid:pk>/cancel/", views.DashboardSubscriptionCancel.as_view()),
    path("subscriptions/<uuid:pk>/extend/", views.DashboardSubscriptionExtend.as_view()),

    # Integrations
    path("integrations/", views.DashboardIntegrationList.as_view()),
    path("integrations/<uuid:pk>/", views.DashboardIntegrationDetail.as_view()),

    # Leads
    path("leads/", views.DashboardLeadList.as_view()),
    path("leads/stats/", views.DashboardLeadStats.as_view()),
    path("leads/export/", views.DashboardLeadExport.as_view()),
    path("leads/<uuid:pk>/", views.DashboardLeadDetail.as_view()),

    # Audit Logs
    path("audit-logs/", views.DashboardAuditLogList.as_view()),

    # Messages
    path("messages/", views.DashboardMessageList.as_view()),

    # Prompts
    path("prompts/", views.DashboardPromptTemplateList.as_view()),
    path("prompts/<uuid:pk>/", views.DashboardPromptTemplateDetail.as_view()),

    # Notifications
    path("notifications/", views.DashboardNotificationList.as_view()),
    path("notifications/send/", views.DashboardNotificationSend.as_view()),
    path("features/", views.DashboardFeatureList.as_view()),
    path("features/<uuid:pk>/", views.DashboardFeatureDetail.as_view()),
    path("pricingpackages/", views.DashboardPricingPackageList.as_view()),
    path("pricingpackages/<uuid:pk>/", views.DashboardPricingPackageDetail.as_view()),
    path("assistantfiles/", views.DashboardAssistantFileUploadList.as_view()),
    path("assistantfiles/<uuid:pk>/", views.DashboardAssistantFileUploadDetail.as_view()),
    path("balances/", views.DashboardBalanceList.as_view()),
    path("cards/", views.DashboardCardList.as_view()),
]
