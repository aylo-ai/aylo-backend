"""Dashboard views, split by domain.

Every public name is re-exported here so `from apps.dashboard.views import X`
and `views.X` in `urls.py` keep resolving exactly as they did when this package
was a single module.
"""
from apps.dashboard.views.assistants import (
    DashboardAssistantDetail,
    DashboardAssistantFileUploadDetail,
    DashboardAssistantFileUploadList,
    DashboardAssistantList,
    DashboardAssistantToggleActive,
    DashboardPromptTemplateDetail,
    DashboardPromptTemplateList,
)
from apps.dashboard.views.audit import DashboardAuditLogList
from apps.dashboard.views.auth import (
    DashboardSendOtpLoginView,
    DashboardVerifyOtpLoginView,
)
from apps.dashboard.views.base import get_client_ip, subscription_repr
from apps.dashboard.views.catalog import (
    DashboardBalanceList,
    DashboardCardList,
    DashboardFeatureDetail,
    DashboardFeatureList,
    DashboardPricingPackageDetail,
    DashboardPricingPackageList,
)
from apps.dashboard.views.conversations import (
    DashboardConversationClose,
    DashboardConversationDetail,
    DashboardConversationEscalate,
    DashboardConversationList,
    DashboardMessageList,
)
from apps.dashboard.views.integrations import (
    DashboardIntegrationDetail,
    DashboardIntegrationList,
)
from apps.dashboard.views.leads import (
    DashboardLeadDetail,
    DashboardLeadExport,
    DashboardLeadList,
    DashboardLeadStats,
)
from apps.dashboard.views.notifications import (
    DashboardNotificationList,
    DashboardNotificationSend,
)
from apps.dashboard.views.overview import (
    DashboardAICostBreakdownView,
    DashboardEnhancedStatsView,
    DashboardGlobalSearch,
    DashboardStatisticsView,
    DashboardView,
)
from apps.dashboard.views.subscriptions import (
    DashboardSubscriptionCancel,
    DashboardSubscriptionDetail,
    DashboardSubscriptionExtend,
    DashboardSubscriptionList,
)
from apps.dashboard.views.system import DashboardSystemHealthView
from apps.dashboard.views.transactions import (
    DashboardTransactionBulkAction,
    DashboardTransactionDetail,
    DashboardTransactionExport,
    DashboardTransactionList,
    DashboardTransactionRefund,
)
from apps.dashboard.views.users import (
    DashboardUserBulkAction,
    DashboardUserChangeRole,
    DashboardUserDetail,
    DashboardUserExport,
    DashboardUserList,
    DashboardUserToggleActive,
)

__all__ = [
    "DashboardAICostBreakdownView",
    "DashboardAssistantDetail",
    "DashboardAssistantFileUploadDetail",
    "DashboardAssistantFileUploadList",
    "DashboardAssistantList",
    "DashboardAssistantToggleActive",
    "DashboardAuditLogList",
    "DashboardBalanceList",
    "DashboardCardList",
    "DashboardConversationClose",
    "DashboardConversationDetail",
    "DashboardConversationEscalate",
    "DashboardConversationList",
    "DashboardEnhancedStatsView",
    "DashboardFeatureDetail",
    "DashboardFeatureList",
    "DashboardGlobalSearch",
    "DashboardIntegrationDetail",
    "DashboardIntegrationList",
    "DashboardLeadDetail",
    "DashboardLeadExport",
    "DashboardLeadList",
    "DashboardLeadStats",
    "DashboardMessageList",
    "DashboardNotificationList",
    "DashboardNotificationSend",
    "DashboardPricingPackageDetail",
    "DashboardPricingPackageList",
    "DashboardPromptTemplateDetail",
    "DashboardPromptTemplateList",
    "DashboardSendOtpLoginView",
    "DashboardStatisticsView",
    "DashboardSubscriptionCancel",
    "DashboardSubscriptionDetail",
    "DashboardSubscriptionExtend",
    "DashboardSubscriptionList",
    "DashboardSystemHealthView",
    "DashboardTransactionBulkAction",
    "DashboardTransactionDetail",
    "DashboardTransactionExport",
    "DashboardTransactionList",
    "DashboardTransactionRefund",
    "DashboardUserBulkAction",
    "DashboardUserChangeRole",
    "DashboardUserDetail",
    "DashboardUserExport",
    "DashboardUserList",
    "DashboardUserToggleActive",
    "DashboardVerifyOtpLoginView",
    "DashboardView",
    "get_client_ip",
    "subscription_repr",
]
