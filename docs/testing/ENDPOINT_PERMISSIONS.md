# Endpoint Permission Matrix

Auto-generated from the live URL resolver on 2026-08-01 — every view's actual `permission_classes` (or, where `get_permissions()` is overridden, a hand-maintained note on the real per-method split). Regenerate with:

```bash
.venv/bin/python .claude/skills/endpoint-test-checklist/scripts/permissions_matrix.py
```

If a view's `get_permissions()` changes, update `OVERRIDE_NOTES` in that script — the generator can't infer per-method logic by introspection, only the fallback class list.

## Access levels, from broadest to narrowest

1. **Public** — no auth. Must still degrade to a clean 4xx on bad input, never 500.
2. **Any authenticated user** — gate is role-agnostic; correctness depends entirely on the view's `get_queryset`/`get_object` scoping the row to `request.user`. A permission class alone never proves tenancy — check the view body.
3. **Dashboard staff** (`IsDashboardUser`) — any of staff/support_agent/manager/admin/super_admin. Appropriate for read/list and low-stakes actions only.
4. **Function-scoped admin** (`CanManageUsers`, `CanManageFinance`, `CanModerateConversations`) — admin/super_admin (plus support_agent for moderation), scoped to one domain. Prefer these over `IsAdmin` when the action is squarely in their domain — they self-document *why* it's gated.
5. **`IsAdmin`** — admin/super_admin, for anything not covered by a function-scoped class (exports, audit logs, system health).
6. **`IsSuperAdmin`** — narrowest; use sparingly, only for the handful of super-admin-only actions.

## Known-fixed issue (2026-07-31)

`DashboardUserDetail`, `DashboardSubscriptionDetail`, `DashboardTransactionDetail` used to gate **every** method — including PUT/PATCH/DELETE — with plain `IsDashboardUser`, so any support_agent could PATCH a user's `user_role` to `super_admin` or delete a user/subscription/transaction outright, bypassing the narrower `CanManageUsers`/`CanManageFinance` endpoints built for exactly those actions. Fixed via `get_permissions()` overrides — see `docs/reports/2026-07-31-dashboard-permission-escalation.md`. **When adding a new `RetrieveUpdateDestroyAPIView` over a sensitive model (money, identity/role), default to a per-method `get_permissions()` split rather than one class for all methods — GET can be broader than the rest.**


## `assistant` — assistant — assistants, conversations, messages, leads, follow-ups

| Method | Path | View | Effective access |
|---|---|---|---|
| GET,PUT,PATCH,DELETE | `api/v1/chat/assistant-files/<uuid:pk>/` | `AssistantFileUploadRetrieveView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET,POST | `api/v1/chat/assistant/` | `AssistantListCreateView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET,PUT,PATCH,DELETE | `api/v1/chat/assistant/<uuid:pk>/` | `AssistantRetrieveView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET,POST | `api/v1/chat/assistant/<uuid:pk>/conversation/` | `ConversationListCreateView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET | `api/v1/chat/assistant/<uuid:pk>/export-leads/` | `ExportLeadsView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET,PUT,PATCH | `api/v1/chat/assistant/<uuid:pk>/follow-up/` | `FollowUpConfigView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET | `api/v1/chat/assistant/<uuid:pk>/follow-up/logs/` | `FollowUpLogListView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET,POST | `api/v1/chat/assistant/<uuid:pk>/follow-up/stages/` | `FollowUpStageListCreateView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET,POST | `api/v1/chat/assistant/<uuid:pk>/leads/` | `LeadListCreateView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| POST | `api/v1/chat/assistant/<uuid:pk>/update-file/` | `AssistantFileUploadUpdateView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET,POST | `api/v1/chat/assistant/<uuid:pk>/upload-file/` | `AssistantFileUploadListCreateView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET | `api/v1/chat/assistant/token-stats/` | `AssistantTokenStatsView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET,PUT,PATCH,DELETE | `api/v1/chat/conversation/<uuid:pk>/` | `ConversationRetrieveView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET,POST | `api/v1/chat/conversation/<uuid:pk>/message/` | `MessageListCreateView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET | `api/v1/chat/conversation/<uuid:pk>/messages/` | `ConversationMessagesListView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| PUT,PATCH | `api/v1/chat/conversation/<uuid:pk>/messages/bulk-read/` | `MessageBulkReadView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET,PUT,PATCH,DELETE | `api/v1/chat/follow-up/stage/<uuid:pk>/` | `FollowUpStageDetailView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET,PUT,PATCH,DELETE | `api/v1/chat/lead/<uuid:pk>/` | `LeadRetrieveView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET,PUT,PATCH,DELETE | `api/v1/chat/message/<uuid:pk>/` | `MessageRetrieveView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET | `api/v1/chat/prompt-templates/` | `PromptTemplateListView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |

## `blog` — blog — marketing content

| Method | Path | View | Effective access |
|---|---|---|---|
| GET | `api/v1/blog/posts/` | `BlogPostListView` | Public — no auth required |
| GET | `api/v1/blog/posts/<slug:slug>/` | `BlogPostDetailView` | Public — no auth required |

## `dashboard` — dashboard — admin/staff console

| Method | Path | View | Effective access |
|---|---|---|---|
| GET,POST | `api/v1/dashboard/assistantfiles/` | `DashboardAssistantFileUploadList` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| GET,PUT,PATCH,DELETE | `api/v1/dashboard/assistantfiles/<uuid:pk>/` | `DashboardAssistantFileUploadDetail` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| GET,POST | `api/v1/dashboard/assistants/` | `DashboardAssistantList` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| GET,PUT,PATCH,DELETE | `api/v1/dashboard/assistants/<uuid:pk>/` | `DashboardAssistantDetail` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| POST | `api/v1/dashboard/assistants/<uuid:pk>/toggle-active/` | `DashboardAssistantToggleActive` | Admin or super_admin only |
| GET | `api/v1/dashboard/audit-logs/` | `DashboardAuditLogList` | Admin or super_admin only |
| GET | `api/v1/dashboard/balances/` | `DashboardBalanceList` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| GET | `api/v1/dashboard/cards/` | `DashboardCardList` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| GET | `api/v1/dashboard/conversations/` | `DashboardConversationList` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| GET,PUT,PATCH,DELETE | `api/v1/dashboard/conversations/<uuid:pk>/` | `DashboardConversationDetail` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| POST | `api/v1/dashboard/conversations/<uuid:pk>/close/` | `DashboardConversationClose` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| POST | `api/v1/dashboard/conversations/<uuid:pk>/escalate/` | `DashboardConversationEscalate` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| GET | `api/v1/dashboard/dashboard/` | `DashboardView` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| GET | `api/v1/dashboard/dashboard/enhanced/` | `DashboardEnhancedStatsView` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| GET,POST | `api/v1/dashboard/features/` | `DashboardFeatureList` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| GET,PUT,PATCH,DELETE | `api/v1/dashboard/features/<uuid:pk>/` | `DashboardFeatureDetail` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| GET | `api/v1/dashboard/integrations/` | `DashboardIntegrationList` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| GET,PUT,PATCH,DELETE | `api/v1/dashboard/integrations/<uuid:pk>/` | `DashboardIntegrationDetail` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| GET | `api/v1/dashboard/leads/` | `DashboardLeadList` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| GET,PUT,PATCH | `api/v1/dashboard/leads/<uuid:pk>/` | `DashboardLeadDetail` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| GET | `api/v1/dashboard/leads/export/` | `DashboardLeadExport` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| GET | `api/v1/dashboard/leads/stats/` | `DashboardLeadStats` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| GET | `api/v1/dashboard/messages/` | `DashboardMessageList` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| GET | `api/v1/dashboard/notifications/` | `DashboardNotificationList` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| POST | `api/v1/dashboard/notifications/send/` | `DashboardNotificationSend` | Admin or super_admin only |
| GET,POST | `api/v1/dashboard/pricingpackages/` | `DashboardPricingPackageList` | Admin or super_admin only |
| GET,PUT,PATCH,DELETE | `api/v1/dashboard/pricingpackages/<uuid:pk>/` | `DashboardPricingPackageDetail` | Admin or super_admin only |
| GET,POST | `api/v1/dashboard/prompts/` | `DashboardPromptTemplateList` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| GET,PUT,PATCH,DELETE | `api/v1/dashboard/prompts/<uuid:pk>/` | `DashboardPromptTemplateDetail` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| GET | `api/v1/dashboard/search/` | `DashboardGlobalSearch` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| POST | `api/v1/dashboard/send-otp/login/` | `DashboardSendOtpLoginView` | Public — no auth required |
| GET | `api/v1/dashboard/statistics/` | `DashboardStatisticsView` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| GET | `api/v1/dashboard/statistics/ai-costs/` | `DashboardAICostBreakdownView` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| GET | `api/v1/dashboard/subscriptions/` | `DashboardSubscriptionList` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| GET,PUT,PATCH,DELETE | `api/v1/dashboard/subscriptions/<uuid:pk>/` | `DashboardSubscriptionDetail` | GET → Dashboard staff (IsDashboardUser); PUT/PATCH/DELETE → Admin/super_admin only (CanManageFinance) — fixed 2026-07-31, was IsDashboardUser on all methods |
| POST | `api/v1/dashboard/subscriptions/<uuid:pk>/cancel/` | `DashboardSubscriptionCancel` | Admin or super_admin — billing/subscription/transaction management |
| POST | `api/v1/dashboard/subscriptions/<uuid:pk>/extend/` | `DashboardSubscriptionExtend` | Admin or super_admin — billing/subscription/transaction management |
| GET | `api/v1/dashboard/system-health/` | `DashboardSystemHealthView` | Admin or super_admin only |
| GET | `api/v1/dashboard/transactions/` | `DashboardTransactionList` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| GET,PUT,PATCH,DELETE | `api/v1/dashboard/transactions/<uuid:pk>/` | `DashboardTransactionDetail` | GET → Dashboard staff (IsDashboardUser); PUT/PATCH/DELETE → Admin/super_admin only (CanManageFinance) — fixed 2026-07-31, was IsDashboardUser on all methods |
| POST | `api/v1/dashboard/transactions/<uuid:pk>/refund/` | `DashboardTransactionRefund` | Admin or super_admin — billing/subscription/transaction management |
| POST | `api/v1/dashboard/transactions/bulk-action/` | `DashboardTransactionBulkAction` | Admin or super_admin — billing/subscription/transaction management |
| GET | `api/v1/dashboard/transactions/export/` | `DashboardTransactionExport` | Admin or super_admin only |
| GET | `api/v1/dashboard/users/` | `DashboardUserList` | Dashboard staff (any of: staff, support_agent, manager, admin, super_admin) |
| GET,PUT,PATCH,DELETE | `api/v1/dashboard/users/<uuid:pk>/` | `DashboardUserDetail` | GET → Dashboard staff (IsDashboardUser); PUT/PATCH/DELETE → Admin/super_admin only (CanManageUsers) — fixed 2026-07-31, was IsDashboardUser on all methods |
| POST | `api/v1/dashboard/users/<uuid:pk>/change-role/` | `DashboardUserChangeRole` | Admin or super_admin — user identity/role/active-state management |
| POST | `api/v1/dashboard/users/<uuid:pk>/toggle-active/` | `DashboardUserToggleActive` | Admin or super_admin — user identity/role/active-state management |
| POST | `api/v1/dashboard/users/bulk-action/` | `DashboardUserBulkAction` | Admin or super_admin — user identity/role/active-state management |
| GET | `api/v1/dashboard/users/export/` | `DashboardUserExport` | Admin or super_admin only |
| POST | `api/v1/dashboard/verify-otp/login/` | `DashboardVerifyOtpLoginView` | Public — no auth required |

## `integration` — integration — Telegram, Instagram, amoCRM, Billz, broadcasts

| Method | Path | View | Effective access |
|---|---|---|---|
| GET,POST | `api/v1/integration/<uuid:integration_id>/instagram/comment-responses/` | `InstagramCommentResponseListCreateView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET | `api/v1/integration/amocrm/` | `AmoCRMOAuthHandlerView` | Public — no auth required |
| GET | `api/v1/integration/amocrm/install/` | `AmoCRMOAuthInstallView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| POST | `api/v1/integration/amocrm/refresh/` | `AmoCRMTokenRefreshView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| POST | `api/v1/integration/amocrm/set-pipeline/` | `AmoCRMSetPipelineView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| POST | `api/v1/integration/assistant/<uuid:pk>/billz/` | `BillzSecretTokenHandlerView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET,POST | `api/v1/integration/assistant/<uuid:pk>/integration/` | `IntegrationListCreateView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET,POST | `api/v1/integration/broadcast/` | `BroadcastListCreateView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET | `api/v1/integration/broadcast/recipients-count/<uuid:integration_id>/` | `BroadcastRecipientsCountView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET | `api/v1/integration/broadcast/recipients/<uuid:integration_id>/` | `BroadcastRecipientsListView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET,PUT,PATCH,DELETE | `api/v1/integration/buttons/<uuid:pk>/` | `CommentResponseButtonRetrieveUpdateDestroyView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET,POST | `api/v1/integration/comment-response/flow/<uuid:pk>/transition/` | `InstagramFlowTransitionListCreateView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET,POST | `api/v1/integration/comment-responses/<uuid:pk>/flow/` | `InstagramCommentResponseFlowListCreateView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET,PUT,PATCH,DELETE | `api/v1/integration/flow/<uuid:pk>/` | `FlowRetrieveUpdateDestroyView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET | `api/v1/integration/instagram/callback/` | `InstagramCallbackView` | Public — no auth required |
| GET,PUT,PATCH,DELETE | `api/v1/integration/instagram/comment-responses/<uuid:pk>/` | `InstagramCommentResponseRetrieveView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| POST | `api/v1/integration/instagram/data-deletion/` | `InstagramDataDeletionView` | Public — no auth required |
| POST | `api/v1/integration/instagram/deauthorize/` | `InstagramDeauthorizeView` | Public — no auth required |
| GET,POST | `api/v1/integration/instagram/webhook/` | `InstagramWebhookView` | Public — no auth required |
| GET,PUT,PATCH,DELETE | `api/v1/integration/intagram-media/<uuid:pk>/` | `InstagramMediaRetrieveView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET | `api/v1/integration/integration-list/` | `IntegrationListView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET,PUT,PATCH,DELETE | `api/v1/integration/integration/<uuid:pk>/` | `IntegrationRetrieveUpdateDestroyView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET | `api/v1/integration/integration/<uuid:pk>/instagram/posts/` | `InstagramPostListView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET | `api/v1/integration/integration/<uuid:pk>/telegram-group/` | `TelegramGroupListView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| POST | `api/v1/integration/send-telegram-message/` | `SendUserMessageView` | Customer role only |
| POST | `api/v1/integration/send/integration/<uuid:pk>/` | `SendIntegrationMessageView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET,PUT,PATCH,DELETE | `api/v1/integration/steps/<uuid:pk>/` | `StepRetrieveUpdateDestroyView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET,PUT,PATCH,DELETE | `api/v1/integration/telegram-group/<uuid:pk>/` | `TelegramGroupUpdateDestroyView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| POST | `api/v1/integration/telegram/webhook/<str:bot_token>/` | `TelegramWebhookView` | Public — no auth required |
| GET,PUT,PATCH,DELETE | `api/v1/integration/transition/<uuid:pk>/` | `TransitionRetrieveUpdateDestroyView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| POST | `api/v1/integration/trigger-words/` | `CommentTriggerWordListCreateView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET,PUT,PATCH,DELETE | `api/v1/integration/trigger-words/<uuid:pk>/` | `CommentTriggerWordRetrieveView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |

## `landing` — landing — public marketing site leads

| Method | Path | View | Effective access |
|---|---|---|---|
| POST | `api/v1/landing/lead-bot/webhook/` | `LeadBotWebhookView` | Public — no auth required |
| POST | `api/v1/landing/lead/` | `LandingLeadCreateView` | Public — no auth required |

## `payment` — payment — subscriptions, cards, transactions

| Method | Path | View | Effective access |
|---|---|---|---|
| GET | `api/v1/payment/cards/` | `CardListView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET,PUT,PATCH | `api/v1/payment/cards/<uuid:pk>/` | `CardDetailView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| DELETE | `api/v1/payment/cards/<uuid:pk>/remove/` | `CardRemoveView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| POST | `api/v1/payment/cards/<uuid:pk>/set-default/` | `SetDefaultCard` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET,POST | `api/v1/payment/features/` | `FeatureListCreateView` | GET → Public (AllowAny); POST → Admin/super_admin only (IsAdmin) |
| GET,PUT,PATCH,DELETE | `api/v1/payment/features/<uuid:pk>/` | `FeatureRetrieveView` | Method-dependent (get_permissions overridden — base: IsAdmin). Read the view. |
| POST | `api/v1/payment/manual-payment/` | `ManualSubscriptionPaymentView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| POST | `api/v1/payment/payme/card/add/` | `CardCreateWithPaymeView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| POST | `api/v1/payment/payme/card/pay-subscription/` | `PayWithCard` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| POST | `api/v1/payment/payme/card/update-subscription/` | `SubscriptionUpdateView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| POST | `api/v1/payment/payme/get-verify-token/` | `PaymeGetVerifyCodeView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| POST | `api/v1/payment/payme/verify-code/` | `PaymeVerifyCodeView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET,POST | `api/v1/payment/pricing-packages/` | `PricingPackageListCreateView` | GET → Public (AllowAny); POST → Admin/super_admin only (IsAdmin) |
| GET,PUT,PATCH,DELETE | `api/v1/payment/pricing-packages/<uuid:pk>/` | `PricingPackageRetrieveView` | Method-dependent (get_permissions overridden — base: IsAdmin). Read the view. |
| GET | `api/v1/payment/retry-payments/subscription/<uuid:pk>/` | `RetryPaymentListView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| PUT,PATCH | `api/v1/payment/subscriptions/<uuid:pk>/` | `SubscriptionUpdateAutoRenewView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| POST | `api/v1/payment/subscriptions/cancel/` | `SubscriptionCancellationView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| POST | `api/v1/payment/subscriptions/create/` | `SubscriptionCreateView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET | `api/v1/payment/transactions/` | `TransactionListView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |

## `user` — user — auth, accounts, staff, notifications

| Method | Path | View | Effective access |
|---|---|---|---|
| GET | `api/v1/user/accounts/google/login/` | `GoogleLoginView` | Public — no auth required |
| GET | `api/v1/user/accounts/google/login/callback/` | `GoogleAuthCallbackView` | Public — no auth required |
| POST | `api/v1/user/add-staff/` | `AddStaffView` | Admin or customer — must be owner-scoped (created_by) in get_queryset |
| POST | `api/v1/user/auth/login/refresh/` | `LoginRefreshView` | Public — no auth required |
| POST | `api/v1/user/auth/logout/` | `LogoutView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET | `api/v1/user/auth/profile/` | `UserProfileGetView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| POST | `api/v1/user/auth/register/` | `UserRegisterView` | Public — no auth required |
| POST | `api/v1/user/auth/send-otp/` | `SendCodeView` | Public — no auth required |
| PUT,PATCH | `api/v1/user/auth/update-user/` | `UpdateProfileView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| POST | `api/v1/user/auth/verify-otp/` | `VerifyCodeView` | Public — no auth required |
| PUT,PATCH | `api/v1/user/notification/<uuid:pk>/` | `NotificationUpdateView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET | `api/v1/user/notifications/` | `NotificationListView` | Any authenticated user — must be owner-scoped in get_queryset/get_object |
| GET,POST | `api/v1/user/privacy-policy/` | `PrivacyPolicyListCreateView` | GET → Public (AllowAny); POST → Admin/super_admin only (IsAdmin) |
| GET,PUT,PATCH,DELETE | `api/v1/user/privacy-policy/<uuid:pk>/` | `PrivacyPolicyRetrieveView` | Method-dependent (get_permissions overridden — base: IsAdmin). Read the view. |
| GET | `api/v1/user/staff/` | `StaffListView` | Admin or customer — must be owner-scoped (created_by) in get_queryset |
| DELETE | `api/v1/user/staff/<uuid:pk>/` | `StaffDeleteView` | Admin or customer — must be owner-scoped (created_by) in get_queryset |
| GET,POST | `api/v1/user/user-agreement/` | `UserAgreementListCreateView` | GET → Public (AllowAny); POST → Admin/super_admin only (IsAdmin) |
| GET,PUT,PATCH,DELETE | `api/v1/user/user-agreement/<uuid:pk>/` | `UserAgreementRetrieveView` | Method-dependent (get_permissions overridden — base: IsAdmin). Read the view. |