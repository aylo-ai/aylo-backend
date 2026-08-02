# Endpoint Test Checklist

Auto-generated from the live URL resolver on 2026-08-01 by walking `django.urls.get_resolver()` the same way `api-doctor` does. This is the working checklist for the **[test-writer](../../.claude/agents/test-writer.md)** agent and for your own manual review — regenerate the table (not the `Reviewed` column) with the **endpoint-test-checklist** skill whenever routes change.

## How to use this file

- **Coverage** is a heuristic: it means the view class name or the endpoint's static path
  prefix appears in *some* test file. It is **not** a claim that the behavior is correct or
  complete — a route can show `heuristic` and still be undertested.
- **Reviewed** is the column that matters and the only one you should hand-edit. Leave it `[ ]`
  until *you* have exercised that endpoint (via the test suite or a live probe) and are satisfied
  the test(s) actually assert the right thing. Flip it to `[x]` once you're sure, or leave a note
  like `[x] 2026-08-01 — happy path only, no perm test` if coverage is partial.
- When `test-writer` adds tests for a route, it sets **Coverage** to `written`, links the test
  file, and leaves **Reviewed** untouched — review is always a human step, never something an
  agent marks off on its own.
- Do not hand-edit the Method/Path/View columns; they're regenerated from the resolver.


## `assistant` — assistant — assistants, conversations, messages, leads, follow-ups

| Method | Path | View | Coverage | Reviewed |
|---|---|---|---|---|
| GET,PUT,PATCH,DELETE | `api/v1/chat/assistant-files/<uuid:pk>/` | `AssistantFileUploadRetrieveView` | none | [ ] |
| GET,POST | `api/v1/chat/assistant/` | `AssistantListCreateView` | heuristic (apps/assistant/tests.py) | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/chat/assistant/<uuid:pk>/` | `AssistantRetrieveView` | heuristic (apps/assistant/tests.py) | [ ] |
| GET,POST | `api/v1/chat/assistant/<uuid:pk>/conversation/` | `ConversationListCreateView` | heuristic (apps/assistant/tests.py) | [ ] |
| GET | `api/v1/chat/assistant/<uuid:pk>/export-leads/` | `ExportLeadsView` | heuristic (apps/assistant/tests.py) | [ ] |
| GET,PUT,PATCH | `api/v1/chat/assistant/<uuid:pk>/follow-up/` | `FollowUpConfigView` | heuristic (apps/assistant/tests.py) | [ ] |
| GET | `api/v1/chat/assistant/<uuid:pk>/follow-up/logs/` | `FollowUpLogListView` | heuristic (apps/assistant/tests.py) | [ ] |
| GET,POST | `api/v1/chat/assistant/<uuid:pk>/follow-up/stages/` | `FollowUpStageListCreateView` | heuristic (apps/assistant/tests.py) | [ ] |
| GET,POST | `api/v1/chat/assistant/<uuid:pk>/leads/` | `LeadListCreateView` | heuristic (apps/assistant/tests.py) | [ ] |
| POST | `api/v1/chat/assistant/<uuid:pk>/update-file/` | `AssistantFileUploadUpdateView` | heuristic (apps/assistant/tests.py) | [ ] |
| GET,POST | `api/v1/chat/assistant/<uuid:pk>/upload-file/` | `AssistantFileUploadListCreateView` | heuristic (apps/assistant/tests.py) | [ ] |
| GET | `api/v1/chat/assistant/token-stats/` | `AssistantTokenStatsView` | none | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/chat/conversation/<uuid:pk>/` | `ConversationRetrieveView` | heuristic (apps/assistant/tests.py) | [ ] |
| GET,POST | `api/v1/chat/conversation/<uuid:pk>/message/` | `MessageListCreateView` | heuristic (apps/assistant/tests.py) | [ ] |
| GET | `api/v1/chat/conversation/<uuid:pk>/messages/` | `ConversationMessagesListView` | heuristic (apps/assistant/tests.py) | [ ] |
| PUT,PATCH | `api/v1/chat/conversation/<uuid:pk>/messages/bulk-read/` | `MessageBulkReadView` | heuristic (apps/assistant/tests.py) | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/chat/follow-up/stage/<uuid:pk>/` | `FollowUpStageDetailView` | none | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/chat/lead/<uuid:pk>/` | `LeadRetrieveView` | none | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/chat/message/<uuid:pk>/` | `MessageRetrieveView` | heuristic (apps/assistant/tests.py) | [ ] |
| GET | `api/v1/chat/prompt-templates/` | `PromptTemplateListView` | none | [ ] |

_assistant: 15/20 have some coverage; 5 have none._


## `blog` — blog — marketing content

| Method | Path | View | Coverage | Reviewed |
|---|---|---|---|---|
| GET | `api/v1/blog/posts/` | `BlogPostListView` | none | [ ] |
| GET | `api/v1/blog/posts/<slug:slug>/` | `BlogPostDetailView` | none | [ ] |

_blog: 0/2 have some coverage; 2 have none._


## `dashboard` — dashboard — admin/staff console

| Method | Path | View | Coverage | Reviewed |
|---|---|---|---|---|
| GET,POST | `api/v1/dashboard/assistantfiles/` | `DashboardAssistantFileUploadList` | none | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/dashboard/assistantfiles/<uuid:pk>/` | `DashboardAssistantFileUploadDetail` | none | [ ] |
| GET,POST | `api/v1/dashboard/assistants/` | `DashboardAssistantList` | none | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/dashboard/assistants/<uuid:pk>/` | `DashboardAssistantDetail` | none | [ ] |
| POST | `api/v1/dashboard/assistants/<uuid:pk>/toggle-active/` | `DashboardAssistantToggleActive` | none | [ ] |
| GET | `api/v1/dashboard/audit-logs/` | `DashboardAuditLogList` | none | [ ] |
| GET | `api/v1/dashboard/balances/` | `DashboardBalanceList` | none | [ ] |
| GET | `api/v1/dashboard/cards/` | `DashboardCardList` | none | [ ] |
| GET | `api/v1/dashboard/conversations/` | `DashboardConversationList` | none | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/dashboard/conversations/<uuid:pk>/` | `DashboardConversationDetail` | none | [ ] |
| POST | `api/v1/dashboard/conversations/<uuid:pk>/close/` | `DashboardConversationClose` | none | [ ] |
| POST | `api/v1/dashboard/conversations/<uuid:pk>/escalate/` | `DashboardConversationEscalate` | none | [ ] |
| GET | `api/v1/dashboard/dashboard/` | `DashboardView` | none | [ ] |
| GET | `api/v1/dashboard/dashboard/enhanced/` | `DashboardEnhancedStatsView` | none | [ ] |
| GET,POST | `api/v1/dashboard/features/` | `DashboardFeatureList` | none | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/dashboard/features/<uuid:pk>/` | `DashboardFeatureDetail` | none | [ ] |
| GET | `api/v1/dashboard/integrations/` | `DashboardIntegrationList` | none | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/dashboard/integrations/<uuid:pk>/` | `DashboardIntegrationDetail` | none | [ ] |
| GET | `api/v1/dashboard/leads/` | `DashboardLeadList` | none | [ ] |
| GET,PUT,PATCH | `api/v1/dashboard/leads/<uuid:pk>/` | `DashboardLeadDetail` | none | [ ] |
| GET | `api/v1/dashboard/leads/export/` | `DashboardLeadExport` | none | [ ] |
| GET | `api/v1/dashboard/leads/stats/` | `DashboardLeadStats` | none | [ ] |
| GET | `api/v1/dashboard/messages/` | `DashboardMessageList` | none | [ ] |
| GET | `api/v1/dashboard/notifications/` | `DashboardNotificationList` | none | [ ] |
| POST | `api/v1/dashboard/notifications/send/` | `DashboardNotificationSend` | none | [ ] |
| GET,POST | `api/v1/dashboard/pricingpackages/` | `DashboardPricingPackageList` | none | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/dashboard/pricingpackages/<uuid:pk>/` | `DashboardPricingPackageDetail` | none | [ ] |
| GET,POST | `api/v1/dashboard/prompts/` | `DashboardPromptTemplateList` | none | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/dashboard/prompts/<uuid:pk>/` | `DashboardPromptTemplateDetail` | none | [ ] |
| GET | `api/v1/dashboard/search/` | `DashboardGlobalSearch` | none | [ ] |
| POST | `api/v1/dashboard/send-otp/login/` | `DashboardSendOtpLoginView` | none | [ ] |
| GET | `api/v1/dashboard/statistics/` | `DashboardStatisticsView` | none | [ ] |
| GET | `api/v1/dashboard/statistics/ai-costs/` | `DashboardAICostBreakdownView` | none | [ ] |
| GET | `api/v1/dashboard/subscriptions/` | `DashboardSubscriptionList` | heuristic (apps/dashboard/tests.py) | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/dashboard/subscriptions/<uuid:pk>/` | `DashboardSubscriptionDetail` | written (apps/dashboard/tests.py — DashboardSubscriptionDetailPermissionTests) | [ ] |
| POST | `api/v1/dashboard/subscriptions/<uuid:pk>/cancel/` | `DashboardSubscriptionCancel` | heuristic (apps/payment/tests.py) | [ ] |
| POST | `api/v1/dashboard/subscriptions/<uuid:pk>/extend/` | `DashboardSubscriptionExtend` | heuristic (apps/dashboard/tests.py) | [ ] |
| GET | `api/v1/dashboard/system-health/` | `DashboardSystemHealthView` | none | [ ] |
| GET | `api/v1/dashboard/transactions/` | `DashboardTransactionList` | heuristic (apps/dashboard/tests.py) | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/dashboard/transactions/<uuid:pk>/` | `DashboardTransactionDetail` | written (apps/dashboard/tests.py — DashboardTransactionDetailPermissionTests) | [ ] |
| POST | `api/v1/dashboard/transactions/<uuid:pk>/refund/` | `DashboardTransactionRefund` | heuristic (apps/dashboard/tests.py) | [ ] |
| POST | `api/v1/dashboard/transactions/bulk-action/` | `DashboardTransactionBulkAction` | none | [ ] |
| GET | `api/v1/dashboard/transactions/export/` | `DashboardTransactionExport` | none | [ ] |
| GET | `api/v1/dashboard/users/` | `DashboardUserList` | heuristic (apps/dashboard/tests.py) | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/dashboard/users/<uuid:pk>/` | `DashboardUserDetail` | written (apps/dashboard/tests.py — DashboardUserDetailPermissionTests) | [ ] |
| POST | `api/v1/dashboard/users/<uuid:pk>/change-role/` | `DashboardUserChangeRole` | heuristic (apps/dashboard/tests.py) | [ ] |
| POST | `api/v1/dashboard/users/<uuid:pk>/toggle-active/` | `DashboardUserToggleActive` | heuristic (apps/dashboard/tests.py) | [ ] |
| POST | `api/v1/dashboard/users/bulk-action/` | `DashboardUserBulkAction` | none | [ ] |
| GET | `api/v1/dashboard/users/export/` | `DashboardUserExport` | none | [ ] |
| POST | `api/v1/dashboard/verify-otp/login/` | `DashboardVerifyOtpLoginView` | none | [ ] |

_dashboard: 11/50 have some coverage; 39 have none._


## `integration` — integration — Telegram, Instagram, amoCRM, Billz, broadcasts

| Method | Path | View | Coverage | Reviewed |
|---|---|---|---|---|
| GET,POST | `api/v1/integration/<uuid:integration_id>/instagram/comment-responses/` | `InstagramCommentResponseListCreateView` | heuristic (apps/integration/tests.py) | [ ] |
| GET | `api/v1/integration/amocrm/` | `AmoCRMOAuthHandlerView` | none | [ ] |
| GET | `api/v1/integration/amocrm/install/` | `AmoCRMOAuthInstallView` | none | [ ] |
| POST | `api/v1/integration/amocrm/refresh/` | `AmoCRMTokenRefreshView` | none | [ ] |
| POST | `api/v1/integration/amocrm/set-pipeline/` | `AmoCRMSetPipelineView` | none | [ ] |
| POST | `api/v1/integration/assistant/<uuid:pk>/billz/` | `BillzSecretTokenHandlerView` | heuristic (apps/integration/tests.py) | [ ] |
| GET,POST | `api/v1/integration/assistant/<uuid:pk>/integration/` | `IntegrationListCreateView` | heuristic (apps/integration/tests.py) | [ ] |
| GET,POST | `api/v1/integration/broadcast/` | `BroadcastListCreateView` | heuristic (apps/integration/tests.py) | [ ] |
| GET | `api/v1/integration/broadcast/recipients-count/<uuid:integration_id>/` | `BroadcastRecipientsCountView` | none | [ ] |
| GET | `api/v1/integration/broadcast/recipients/<uuid:integration_id>/` | `BroadcastRecipientsListView` | none | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/integration/buttons/<uuid:pk>/` | `CommentResponseButtonRetrieveUpdateDestroyView` | heuristic (apps/integration/tests.py) | [ ] |
| GET,POST | `api/v1/integration/comment-response/flow/<uuid:pk>/transition/` | `InstagramFlowTransitionListCreateView` | none | [ ] |
| GET,POST | `api/v1/integration/comment-responses/<uuid:pk>/flow/` | `InstagramCommentResponseFlowListCreateView` | none | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/integration/flow/<uuid:pk>/` | `FlowRetrieveUpdateDestroyView` | heuristic (apps/integration/tests.py) | [ ] |
| GET | `api/v1/integration/instagram/callback/` | `InstagramCallbackView` | heuristic (apps/integration/tests.py) | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/integration/instagram/comment-responses/<uuid:pk>/` | `InstagramCommentResponseRetrieveView` | heuristic (apps/integration/tests.py) | [ ] |
| POST | `api/v1/integration/instagram/data-deletion/` | `InstagramDataDeletionView` | none | [ ] |
| POST | `api/v1/integration/instagram/deauthorize/` | `InstagramDeauthorizeView` | none | [ ] |
| GET,POST | `api/v1/integration/instagram/webhook/` | `InstagramWebhookView` | heuristic (apps/integration/tests.py) | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/integration/intagram-media/<uuid:pk>/` | `InstagramMediaRetrieveView` | none | [ ] |
| GET | `api/v1/integration/integration-list/` | `IntegrationListView` | none | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/integration/integration/<uuid:pk>/` | `IntegrationRetrieveUpdateDestroyView` | heuristic (apps/integration/tests.py) | [ ] |
| GET | `api/v1/integration/integration/<uuid:pk>/instagram/posts/` | `InstagramPostListView` | heuristic (apps/integration/tests.py) | [ ] |
| GET | `api/v1/integration/integration/<uuid:pk>/telegram-group/` | `TelegramGroupListView` | heuristic (apps/integration/tests.py) | [ ] |
| POST | `api/v1/integration/send-telegram-message/` | `SendUserMessageView` | none | [ ] |
| POST | `api/v1/integration/send/integration/<uuid:pk>/` | `SendIntegrationMessageView` | none | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/integration/steps/<uuid:pk>/` | `StepRetrieveUpdateDestroyView` | heuristic (apps/integration/tests.py) | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/integration/telegram-group/<uuid:pk>/` | `TelegramGroupUpdateDestroyView` | none | [ ] |
| POST | `api/v1/integration/telegram/webhook/<str:bot_token>/` | `TelegramWebhookView` | heuristic (apps/shared/tests/test_telegram_webhook_logging.py) | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/integration/transition/<uuid:pk>/` | `TransitionRetrieveUpdateDestroyView` | heuristic (apps/integration/tests.py) | [ ] |
| POST | `api/v1/integration/trigger-words/` | `CommentTriggerWordListCreateView` | none | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/integration/trigger-words/<uuid:pk>/` | `CommentTriggerWordRetrieveView` | none | [ ] |

_integration: 15/32 have some coverage; 17 have none._


## `landing` — landing — public marketing site leads

| Method | Path | View | Coverage | Reviewed |
|---|---|---|---|---|
| POST | `api/v1/landing/lead-bot/webhook/` | `LeadBotWebhookView` | none | [ ] |
| POST | `api/v1/landing/lead/` | `LandingLeadCreateView` | none | [ ] |

_landing: 0/2 have some coverage; 2 have none._


## `payment` — payment — subscriptions, cards, transactions

| Method | Path | View | Coverage | Reviewed |
|---|---|---|---|---|
| GET | `api/v1/payment/cards/` | `CardListView` | heuristic (apps/payment/tests.py) | [ ] |
| GET,PUT,PATCH | `api/v1/payment/cards/<uuid:pk>/` | `CardDetailView` | heuristic (apps/payment/tests.py) | [ ] |
| DELETE | `api/v1/payment/cards/<uuid:pk>/remove/` | `CardRemoveView` | heuristic (apps/payment/tests.py) | [ ] |
| POST | `api/v1/payment/cards/<uuid:pk>/set-default/` | `SetDefaultCard` | heuristic (apps/payment/tests.py) | [ ] |
| GET,POST | `api/v1/payment/features/` | `FeatureListCreateView` | none | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/payment/features/<uuid:pk>/` | `FeatureRetrieveView` | none | [ ] |
| POST | `api/v1/payment/manual-payment/` | `ManualSubscriptionPaymentView` | none | [ ] |
| POST | `api/v1/payment/payme/card/add/` | `CardCreateWithPaymeView` | none | [ ] |
| POST | `api/v1/payment/payme/card/pay-subscription/` | `PayWithCard` | none | [ ] |
| POST | `api/v1/payment/payme/card/update-subscription/` | `SubscriptionUpdateView` | none | [ ] |
| POST | `api/v1/payment/payme/get-verify-token/` | `PaymeGetVerifyCodeView` | none | [ ] |
| POST | `api/v1/payment/payme/verify-code/` | `PaymeVerifyCodeView` | none | [ ] |
| GET,POST | `api/v1/payment/pricing-packages/` | `PricingPackageListCreateView` | heuristic (apps/payment/tests.py) | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/payment/pricing-packages/<uuid:pk>/` | `PricingPackageRetrieveView` | heuristic (apps/payment/tests.py) | [ ] |
| GET | `api/v1/payment/retry-payments/subscription/<uuid:pk>/` | `RetryPaymentListView` | heuristic (apps/payment/tests.py) | [ ] |
| PUT,PATCH | `api/v1/payment/subscriptions/<uuid:pk>/` | `SubscriptionUpdateAutoRenewView` | heuristic (apps/payment/tests.py) | [ ] |
| POST | `api/v1/payment/subscriptions/cancel/` | `SubscriptionCancellationView` | heuristic (apps/payment/tests.py) | [ ] |
| POST | `api/v1/payment/subscriptions/create/` | `SubscriptionCreateView` | heuristic (apps/payment/tests.py) | [ ] |
| GET | `api/v1/payment/transactions/` | `TransactionListView` | none | [ ] |

_payment: 10/19 have some coverage; 9 have none._


## `user` — user — auth, accounts, staff, notifications

| Method | Path | View | Coverage | Reviewed |
|---|---|---|---|---|
| GET | `api/v1/user/accounts/google/login/` | `GoogleLoginView` | heuristic (apps/user/tests.py) | [ ] |
| GET | `api/v1/user/accounts/google/login/callback/` | `GoogleAuthCallbackView` | heuristic (apps/user/tests.py) | [ ] |
| POST | `api/v1/user/add-staff/` | `AddStaffView` | none | [ ] |
| POST | `api/v1/user/auth/login/refresh/` | `LoginRefreshView` | none | [ ] |
| POST | `api/v1/user/auth/logout/` | `LogoutView` | none | [ ] |
| GET | `api/v1/user/auth/profile/` | `UserProfileGetView` | heuristic (apps/user/tests.py) | [ ] |
| POST | `api/v1/user/auth/register/` | `UserRegisterView` | heuristic (apps/user/tests.py) | [ ] |
| POST | `api/v1/user/auth/send-otp/` | `SendCodeView` | heuristic (apps/user/tests.py) | [ ] |
| PUT,PATCH | `api/v1/user/auth/update-user/` | `UpdateProfileView` | none | [ ] |
| POST | `api/v1/user/auth/verify-otp/` | `VerifyCodeView` | heuristic (apps/user/tests.py) | [ ] |
| PUT,PATCH | `api/v1/user/notification/<uuid:pk>/` | `NotificationUpdateView` | heuristic (apps/user/tests.py) | [ ] |
| GET | `api/v1/user/notifications/` | `NotificationListView` | none | [ ] |
| GET,POST | `api/v1/user/privacy-policy/` | `PrivacyPolicyListCreateView` | none | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/user/privacy-policy/<uuid:pk>/` | `PrivacyPolicyRetrieveView` | none | [ ] |
| GET | `api/v1/user/staff/` | `StaffListView` | none | [ ] |
| DELETE | `api/v1/user/staff/<uuid:pk>/` | `StaffDeleteView` | none | [ ] |
| GET,POST | `api/v1/user/user-agreement/` | `UserAgreementListCreateView` | none | [ ] |
| GET,PUT,PATCH,DELETE | `api/v1/user/user-agreement/<uuid:pk>/` | `UserAgreementRetrieveView` | none | [ ] |

_user: 7/18 have some coverage; 11 have none._


## Totals

- 143 endpoints across 7 apps.
- 58 have some coverage; **85 have none** — start `test-writer` there.
- 0 carried over as `Reviewed` from the previous version of this file.
