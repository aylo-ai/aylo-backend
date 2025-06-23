from django.urls import path
import apps.integration.views as views

urlpatterns = [
    path("assistant/<uuid:pk>/integration/", views.IntegrationListCreateView.as_view()),
    path("integration/<uuid:pk>/", views.IntegrationRetrieveUpdateDestroyView.as_view()),
    path("integration/<uuid:pk>/telegram-group/", views.TelegramGroupListView.as_view()),
    path('telegram/webhook/<str:bot_token>/', views.TelegramWebhookView.as_view()),
    
    path("instagram/webhook/", views.InstagramWebhookView.as_view()),
    path("instagram/callback/", views.InstagramCallbackView.as_view()),
    path('instagram/deauthorize/', views.InstagramDeauthorizeView.as_view()),
    path('instagram/data-deletion/', views.InstagramDataDeletionView.as_view()),

    path("integration/<uuid:pk>/instagram/posts/", views.InstagramPostListView.as_view()),
    
    # Trigger words endpoints
    path("trigger-words/", views.CommentTriggerWordListCreateView.as_view()),
    path("trigger-words/<uuid:pk>/", views.CommentTriggerWordRetrieveView.as_view()),
    
    # Comment responses endpoints
    path("integration/<uuid:pk>/instagram/comment-responses/", views.InstagramCommentResponseListCreateView.as_view()),
    path("instagram/comment-responses/<uuid:pk>/", views.InstagramCommentResponseRetrieveView.as_view()),

    path("send-telegram-message/", views.SendUserMessageView.as_view()),
]