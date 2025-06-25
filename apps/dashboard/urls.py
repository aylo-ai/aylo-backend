from django.urls import path
from apps.dashboard import views

urlpatterns = [
    path("users/", views.DashboardUserList.as_view()),
    path("users/<uuid:pk>/assistants/", views.DashboardAssistantList.as_view()),
    path("assistant/<uuid:pk>/conversations/", views.DashboardConversationList.as_view()),
    path("conversation/<uuid:pk>/messages/", views.DashboardMessageList.as_view()),
    path("integration/<uuid:pk>/comment-responses/", views.DashboardCommentResponseList.as_view()),
    path("assistant/<uuid:pk>/integrations/", views.DashboardIntegrationList.as_view()),
    path("user/<uuid:pk>/notifications/", views.DashboardNotificationList.as_view()),
    path("conversation/<uuid:pk>/", views.DashboardConversationDetail.as_view()),
    path("message/<uuid:pk>/", views.DashboardMessageDetail.as_view()),
    path("user/<uuid:pk>/transactions/", views.DashboardTransactionList.as_view()),
    path("transaction/<uuid:pk>/", views.DashboardTransactionDetail.as_view()),
    path("subscriptions/", views.DashboardSubscriptionList.as_view()),
    path("subscription/<uuid:pk>/", views.DashboardSubscriptionDetail.as_view()),
    path("user/<uuid:pk>/balance/", views.DashboardBalanceList.as_view()),
    path("subscription/<uuid:pk>/retry-payments/", views.DashboardRetryPaymentList.as_view()),
    path("assistant/<uuid:pk>/file-uploads/", views.DashboardAssistantFileUploadList.as_view()),
    path("user/<uuid:pk>/cards/", views.DashboardCardList.as_view()),
]
