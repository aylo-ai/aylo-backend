from django.urls import path
import assistant.views as views


urlpatterns = [
    path("assistant/", views.AssistantListCreateView.as_view()),
    path("assistant/<uuid:pk>/", views.AssistantRetrieveView.as_view()),
    path("assistant/<uuid:pk>/conversation/", views.ConversationListCreateView.as_view()),
    path("conversation/<uuid:pk>/", views.ConversationRetrieveView.as_view()),
    path("conversation/<uuid:pk>/message/", views.MessageListCreateView.as_view()),
    path("message/<uuid:pk>/", views.MessageRetrieveView.as_view()),
    path("conversation/<uuid:pk>/messages/", views.ConversationMessagesListView.as_view()),

    # file upload for assistant
    path("assistant/<uuid:pk>/upload-file/", views.AssistantFileUploadListCreateView.as_view()),
    path("assistant/<uuid:pk>/update-file/", views.AssistantFileUploadUpdateView.as_view()),
    path("assistant-files/<uuid:pk>/", views.AssistantFileUploadRetrieveView.as_view()),
]
