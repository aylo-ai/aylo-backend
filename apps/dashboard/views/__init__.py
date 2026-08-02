"""Dashboard views, split by domain.

Every public name is re-exported here so `from apps.dashboard.views import X`
and `views.X` in `urls.py` keep resolving exactly as they did when this package
was a single module.
"""
from apps.dashboard.views.base import get_client_ip, subscription_repr
from apps.dashboard.views.auth import (
    DashboardSendOtpLoginView,
    DashboardVerifyOtpLoginView,
)
from apps.dashboard.views.overview import (
    DashboardView,
    DashboardEnhancedStatsView,
    DashboardStatisticsView,
    DashboardAICostBreakdownView,
    DashboardGlobalSearch,
)
from apps.dashboard.views.system import DashboardSystemHealthView
from apps.dashboard.views.users import (
    DashboardUserList,
    DashboardUserDetail,
    DashboardUserToggleActive,
    DashboardUserChangeRole,
    DashboardUserExport,
    DashboardUserBulkAction,
)
from apps.dashboard.views.assistants import (
    DashboardAssistantList,
    DashboardAssistantDetail,
    DashboardAssistantToggleActive,
    DashboardAssistantFileUploadList,
    DashboardAssistantFileUploadDetail,
    DashboardPromptTemplateList,
    DashboardPromptTemplateDetail,
)
from apps.dashboard.views.conversations import (
    DashboardConversationList,
    DashboardConversationDetail,
    DashboardConversationClose,
    DashboardConversationEscalate,
    DashboardMessageList,
)
from apps.dashboard.views.transactions import (
    DashboardTransactionList,
    DashboardTransactionDetail,
    DashboardTransactionRefund,
    DashboardTransactionExport,
    DashboardTransactionBulkAction,
)
from apps.dashboard.views.subscriptions import (
    DashboardSubscriptionList,
    DashboardSubscriptionDetail,
    DashboardSubscriptionCancel,
    DashboardSubscriptionExtend,
)
from apps.dashboard.views.integrations import (
    DashboardIntegrationList,
    DashboardIntegrationDetail,
)
from apps.dashboard.views.leads import (
    DashboardLeadList,
    DashboardLeadDetail,
    DashboardLeadStats,
    DashboardLeadExport,
)
from apps.dashboard.views.audit import DashboardAuditLogList
from apps.dashboard.views.notifications import (
    DashboardNotificationList,
    DashboardNotificationSend,
)
from apps.dashboard.views.catalog import (
    DashboardBalanceList,
    DashboardCardList,
    DashboardFeatureList,
    DashboardFeatureDetail,
    DashboardPricingPackageList,
    DashboardPricingPackageDetail,
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
