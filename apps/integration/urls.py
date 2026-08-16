from django.urls import path

import apps.integration.views as views

urlpatterns = [
    path("assistant/<uuid:pk>/integration/", views.IntegrationListCreateView.as_view()),
    path("integration-list/", views.IntegrationListView.as_view()),
    path(
        "integration/<uuid:pk>/", views.IntegrationRetrieveUpdateDestroyView.as_view()
    ),
    path(
        "integration/<uuid:pk>/telegram-group/", views.TelegramGroupListView.as_view()
    ),
    path("telegram-group/<uuid:pk>/", views.TelegramGroupUpdateDestroyView.as_view()),
    path("telegram/webhook/<str:bot_token>/", views.TelegramWebhookView.as_view()),
    path("instagram/webhook/", views.InstagramWebhookView.as_view()),
    path("instagram/callback/", views.InstagramCallbackView.as_view()),
    path("instagram/deauthorize/", views.InstagramDeauthorizeView.as_view()),
    path("instagram/data-deletion/", views.InstagramDataDeletionView.as_view()),
    path(
        "integration/<uuid:pk>/instagram/posts/", views.InstagramPostListView.as_view()
    ),
    path("send/integration/<uuid:pk>/", views.SendIntegrationMessageView.as_view()),
    path("send-telegram-message/", views.SendUserMessageView.as_view()),
    # Trigger words endpoints
    path("trigger-words/", views.CommentTriggerWordListCreateView.as_view()),
    path("trigger-words/<uuid:pk>/", views.CommentTriggerWordRetrieveView.as_view()),
    path("intagram-media/<uuid:pk>/", views.InstagramMediaRetrieveView.as_view()),
    # Comment responses endpoints

    path(
        "<uuid:integration_id>/instagram/comment-responses/",
        views.InstagramCommentResponseListCreateView.as_view(),
    ),
    path(
        "comment-responses/<uuid:pk>/flow/",
        views.InstagramCommentResponseFlowListCreateView.as_view(),
    ),
    path(
        "comment-response/flow/<uuid:pk>/transition/",
        views.InstagramFlowTransitionListCreateView.as_view(),
    ),
    path(
        "instagram/comment-responses/<uuid:pk>/",
        views.InstagramCommentResponseRetrieveView.as_view(),
    ),
    # Flow, Step, Transition, Button, UserState endpoints
    path("flow/<uuid:pk>/", views.FlowRetrieveUpdateDestroyView.as_view()),
    path("steps/<uuid:pk>/", views.StepRetrieveUpdateDestroyView.as_view()),
    path("transition/<uuid:pk>/", views.TransitionRetrieveUpdateDestroyView.as_view()),
    path("buttons/<uuid:pk>/", views.CommentResponseButtonRetrieveUpdateDestroyView.as_view()),
    # Broadcast endpoints
    path("broadcast/", views.BroadcastListCreateView.as_view()),
    path("broadcast/recipients-count/<uuid:integration_id>/", views.BroadcastRecipientsCountView.as_view()),
    path("broadcast/recipients/<uuid:integration_id>/", views.BroadcastRecipientsListView.as_view()),
    # amoCRM OAuth integration endpoints
    path("amocrm/", views.AmoCRMOAuthHandlerView.as_view()),
    path("amocrm/install/", views.AmoCRMOAuthInstallView.as_view()),
    path("amocrm/refresh/", views.AmoCRMTokenRefreshView.as_view()),
    path("amocrm/set-pipeline/", views.AmoCRMSetPipelineView.as_view()),
    # billz integration
    path("assistant/<uuid:pk>/billz/", views.BillzSecretTokenHandlerView.as_view()),
]
