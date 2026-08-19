"""Integration views, split by domain.

Every view class is re-exported here so `from apps.integration.views import X`
and `views.X` in `urls.py` keep resolving exactly as they did when this package
was a single module. URL paths are unchanged — the Instagram/Telegram webhooks
and the amoCRM OAuth handler are registered with external systems.
"""
from apps.integration.views.amocrm import (
    AmoCRMOAuthHandlerView,
    AmoCRMOAuthInstallView,
    AmoCRMSetPipelineView,
    AmoCRMTokenRefreshView,
)
from apps.integration.views.billz import (
    BillzSecretTokenHandlerView,
    BillzSyncView,
)
from apps.integration.views.broadcasts import (
    BroadcastListCreateView,
    BroadcastRecipientsCountView,
    BroadcastRecipientsListView,
)
from apps.integration.views.comment_automation import (
    CommentTriggerWordListCreateView,
    CommentTriggerWordRetrieveView,
    InstagramCommentResponseListCreateView,
    InstagramCommentResponseRetrieveView,
)
from apps.integration.views.flows import (
    CommentResponseButtonListCreateView,
    CommentResponseButtonRetrieveUpdateDestroyView,
    FlowRetrieveUpdateDestroyView,
    InstagramCommentResponseFlowListCreateView,
    InstagramFlowTransitionListCreateView,
    StepRetrieveUpdateDestroyView,
    TransitionRetrieveUpdateDestroyView,
)
from apps.integration.views.instagram_media import (
    InstagramMediaRetrieveView,
    InstagramPostListView,
)
from apps.integration.views.instagram_oauth import (
    InstagramCallbackView,
    InstagramDataDeletionView,
    InstagramDeauthorizeView,
)
from apps.integration.views.instagram_webhook import InstagramWebhookView
from apps.integration.views.integrations import (
    IntegrationListCreateView,
    IntegrationListView,
    IntegrationRetrieveUpdateDestroyView,
    SendIntegrationMessageView,
    SendUserMessageView,
)
from apps.integration.views.telegram import (
    TelegramGroupListView,
    TelegramGroupUpdateDestroyView,
    TelegramWebhookView,
)

__all__ = [
    "AmoCRMOAuthHandlerView",
    "AmoCRMOAuthInstallView",
    "AmoCRMSetPipelineView",
    "AmoCRMTokenRefreshView",
    "BillzSecretTokenHandlerView",
    "BillzSyncView",
    "BroadcastListCreateView",
    "BroadcastRecipientsCountView",
    "BroadcastRecipientsListView",
    "CommentResponseButtonListCreateView",
    "CommentResponseButtonRetrieveUpdateDestroyView",
    "CommentTriggerWordListCreateView",
    "CommentTriggerWordRetrieveView",
    "FlowRetrieveUpdateDestroyView",
    "InstagramCallbackView",
    "InstagramCommentResponseFlowListCreateView",
    "InstagramCommentResponseListCreateView",
    "InstagramCommentResponseRetrieveView",
    "InstagramDataDeletionView",
    "InstagramDeauthorizeView",
    "InstagramFlowTransitionListCreateView",
    "InstagramMediaRetrieveView",
    "InstagramPostListView",
    "InstagramWebhookView",
    "IntegrationListCreateView",
    "IntegrationListView",
    "IntegrationRetrieveUpdateDestroyView",
    "SendIntegrationMessageView",
    "SendUserMessageView",
    "StepRetrieveUpdateDestroyView",
    "TelegramGroupListView",
    "TelegramGroupUpdateDestroyView",
    "TelegramWebhookView",
    "TransitionRetrieveUpdateDestroyView",
]
