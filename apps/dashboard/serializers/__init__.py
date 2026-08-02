"""Dashboard serializers, split by domain.

Every public name is re-exported here so `from apps.dashboard.serializers
import X` keeps resolving exactly as it did when this package was a single
module.
"""
from apps.dashboard.serializers.common import (
    StrictCharField,
    serialize_pricing_package,
    serialize_subscription,
)
from apps.dashboard.serializers.auth import (
    DashboardSendOtpLoginSerializer,
    DashboardVerifyOtpLoginSerializer,
)
from apps.dashboard.serializers.overview import (
    DashboardSerializer,
    DashboardEnhancedStatsSerializer,
    DashboardStatisticsSerializer,
)
from apps.dashboard.serializers.users import (
    DashboardUserSerializer,
    DashboardUserListSerializer,
    ChangeRoleSerializer,
    UserBulkActionSerializer,
)
from apps.dashboard.serializers.assistants import (
    DashboardPromptTemplateSerializer,
    DashboardAssistantListSerializer,
    DashboardAssistantFileUploadSerializer,
    DashboardAssistantCreateSerializer,
    DashboardAssistantCreateUserSerializer,
    AssistantFileFilterSerializer,
)
from apps.dashboard.serializers.conversations import (
    DashboardConversationSerializer,
    DashboardConversationListSerializer,
)
from apps.dashboard.serializers.transactions import (
    DashboardTransactionSerializer,
    RefundSerializer,
    TransactionBulkActionSerializer,
)
from apps.dashboard.serializers.subscriptions import (
    DashboardSubscriptionSerializer,
    SubscriptionExtendSerializer,
    DashboardSubscriptionUpdateSerializer,
)
from apps.dashboard.serializers.integrations import (
    DashboardIntegrationListSerializer,
)
from apps.dashboard.serializers.leads import DashboardLeadSerializer
from apps.dashboard.serializers.audit import AuditLogSerializer
from apps.dashboard.serializers.catalog import (
    DashboardPricingPackageDetailSerializer,
    DashboardFeatureSerializer,
)
from apps.dashboard.serializers.notifications import NotificationSendSerializer

__all__ = [
    "AssistantFileFilterSerializer",
    "AuditLogSerializer",
    "ChangeRoleSerializer",
    "DashboardAssistantCreateSerializer",
    "DashboardAssistantCreateUserSerializer",
    "DashboardAssistantFileUploadSerializer",
    "DashboardAssistantListSerializer",
    "DashboardConversationListSerializer",
    "DashboardConversationSerializer",
    "DashboardEnhancedStatsSerializer",
    "DashboardFeatureSerializer",
    "DashboardIntegrationListSerializer",
    "DashboardLeadSerializer",
    "DashboardPricingPackageDetailSerializer",
    "DashboardPromptTemplateSerializer",
    "DashboardSendOtpLoginSerializer",
    "DashboardSerializer",
    "DashboardStatisticsSerializer",
    "DashboardSubscriptionSerializer",
    "DashboardSubscriptionUpdateSerializer",
    "DashboardTransactionSerializer",
    "DashboardUserListSerializer",
    "DashboardUserSerializer",
    "DashboardVerifyOtpLoginSerializer",
    "NotificationSendSerializer",
    "RefundSerializer",
    "StrictCharField",
    "SubscriptionExtendSerializer",
    "TransactionBulkActionSerializer",
    "UserBulkActionSerializer",
    "serialize_pricing_package",
    "serialize_subscription",
]
