from django.urls import path
import apps.assistant.views as views


urlpatterns = [
    path("assistant/", views.AssistantListCreateView.as_view()),
    path('assistant/token-stats/', views.AssistantTokenStatsView.as_view(), name='assistant-token-stats'),
    path("assistant/<uuid:pk>/", views.AssistantRetrieveView.as_view()),
    path("assistant/<uuid:pk>/conversation/", views.ConversationListCreateView.as_view()),
    path("conversation/<uuid:pk>/", views.ConversationRetrieveView.as_view()),
    path("conversation/<uuid:pk>/message/", views.MessageListCreateView.as_view()),
    path("message/<uuid:pk>/", views.MessageRetrieveView.as_view()),
    path("conversation/<uuid:pk>/messages/", views.ConversationMessagesListView.as_view()),
    path("assistant/<uuid:pk>/leads/", views.LeadListCreateView.as_view()),
    path("lead/<uuid:pk>/", views.LeadRetrieveView.as_view()),
    path("assistant/<uuid:pk>/export-leads/", views.ExportLeadsView.as_view()),

    # file upload for assistant
    path("assistant/<uuid:pk>/upload-file/", views.AssistantFileUploadListCreateView.as_view()),
    path("assistant/<uuid:pk>/update-file/", views.AssistantFileUploadUpdateView.as_view()),
    path("assistant-files/<uuid:pk>/", views.AssistantFileUploadRetrieveView.as_view()),

    path('conversation/<uuid:pk>/messages/bulk-read/', views.MessageBulkReadView.as_view(), name='message-bulk-read'),
    path('prompt-templates/', views.PromptTemplateListView.as_view(), name='prompt-template-list'),

    # Follow-up configuration
    path("assistant/<uuid:pk>/follow-up/", views.FollowUpConfigView.as_view(), name='follow-up-config'),
    path("assistant/<uuid:pk>/follow-up/stages/", views.FollowUpStageListCreateView.as_view(), name='follow-up-stages'),
    path("follow-up/stage/<uuid:pk>/", views.FollowUpStageDetailView.as_view(), name='follow-up-stage-detail'),
    path("assistant/<uuid:pk>/follow-up/logs/", views.FollowUpLogListView.as_view(), name='follow-up-logs'),
]